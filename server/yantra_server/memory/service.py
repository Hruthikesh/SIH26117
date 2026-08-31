"""MemoryService (SPEC §13): episodic/semantic memory, skills, project file.

Similarity uses the gateway embedder (cached); facts without provenance are refused; every
write is audited. Skills are proposed after verified runs and approved in the TUI.
"""

from __future__ import annotations

import logging
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from yantra_server.db.base import Database, utcnow
from yantra_server.db.models import MemoryRow, SkillRow

if TYPE_CHECKING:
    from yantra_server.gateway.service import Gateway

log = logging.getLogger(__name__)


class MemoryError(Exception):
    pass


@dataclass
class SkillMatch:
    name: str
    description: str
    body: str
    score: float


class MemoryService:
    def __init__(self, db: Database, gateway: Gateway, skills_dir: Path) -> None:
        self.db = db
        self.gateway = gateway
        self.skills_dir = skills_dir
        self._load_skill_files()

    # ------------------------------------------------------------- semantic facts

    async def remember_fact(
        self, text: str, provenance: list[str], *, user: str = "local", confidence: float = 1.0
    ) -> str:
        if not provenance:
            raise MemoryError("facts require provenance (chunk ids or artifact locators)")
        embedding = await self._embed(text)
        with self.db.session() as s:
            row = MemoryRow(
                user=user,
                kind="fact",
                text=text,
                provenance=provenance,
                confidence=confidence,
                embedding_ref=_pack(embedding),
            )
            s.add(row)
            s.flush()
            return row.id

    async def remember_preference(self, text: str, *, user: str = "local") -> str:
        embedding = await self._embed(text)
        with self.db.session() as s:
            row = MemoryRow(user=user, kind="preference", text=text, embedding_ref=_pack(embedding))
            s.add(row)
            s.flush()
            return row.id

    async def recall(
        self, query: str, *, kind: str | None = None, top: int = 5
    ) -> list[dict[str, Any]]:
        query_vec = await self._embed(query)
        with self.db.session() as s:
            stmt = select(MemoryRow).where(MemoryRow.approved.is_(True))
            if kind:
                stmt = stmt.where(MemoryRow.kind == kind)
            rows = list(s.execute(stmt).scalars())
        scored = []
        for row in rows:
            if not row.embedding_ref:
                continue
            score = _cosine(query_vec, _unpack(row.embedding_ref))
            scored.append((score, row))
        scored.sort(key=lambda x: -x[0])
        return [
            {
                "id": row.id,
                "kind": row.kind,
                "text": row.text,
                "provenance": row.provenance,
                "confidence": row.confidence,
                "score": round(score, 3),
            }
            for score, row in scored[:top]
        ]

    def list_memories(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            stmt = select(MemoryRow).order_by(MemoryRow.created_at.desc())
            if kind:
                stmt = stmt.where(MemoryRow.kind == kind)
            return [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "text": r.text,
                    "provenance": r.provenance,
                    "approved": r.approved,
                    "confidence": r.confidence,
                }
                for r in s.execute(stmt).scalars()
            ]

    def review_memory(self, memory_id: str, action: str) -> bool:
        with self.db.session() as s:
            row = s.get(MemoryRow, memory_id)
            if row is None:
                return False
            if action == "purge":
                s.delete(row)
            elif action == "approve":
                row.approved = True
            return True

    # ------------------------------------------------------------- episodic

    async def record_episode(self, run_id: str, goal: str, summary: str) -> str:
        text = f"Goal: {goal}\nOutcome: {summary}"
        embedding = await self._embed(text)
        with self.db.session() as s:
            row = MemoryRow(
                kind="episode",
                text=text,
                provenance=[f"run:{run_id}"],
                embedding_ref=_pack(embedding),
            )
            s.add(row)
            s.flush()
            return row.id

    async def similar_episodes(self, goal: str, top: int = 3) -> list[dict[str, Any]]:
        return await self.recall(goal, kind="episode", top=top)

    # ------------------------------------------------------------- procedural (skills)

    def _load_skill_files(self) -> None:
        """Load SKILL.md files from skills/<name>/ into the DB (idempotent upsert)."""
        if not self.skills_dir.is_dir():
            return
        for skill_md in self.skills_dir.glob("*/SKILL.md"):
            try:
                meta, body = _parse_skill_md(skill_md.read_text(encoding="utf-8"))
            except ValueError:
                continue
            name = meta.get("name") or skill_md.parent.name
            with self.db.session() as s:
                existing = s.execute(
                    select(SkillRow).where(SkillRow.name == name)
                ).scalar_one_or_none()
                if existing:
                    existing.description = meta.get("description", existing.description)
                    existing.body = body
                    existing.triggers = meta.get("triggers", existing.triggers)
                    existing.tools = meta.get("tools", existing.tools)
                else:
                    s.add(
                        SkillRow(
                            name=name,
                            description=meta.get("description", ""),
                            triggers=meta.get("triggers", []),
                            tools=meta.get("tools", []),
                            body=body,
                            status="active",
                        )
                    )

    def list_skills(self) -> list[dict[str, Any]]:
        with self.db.session() as s:
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "status": r.status,
                    "success_count": r.success_count,
                }
                for r in s.execute(
                    select(SkillRow).order_by(SkillRow.success_count.desc())
                ).scalars()
            ]

    def matching_skills(self, goal: str, top: int = 2) -> list[SkillMatch]:
        """Cheap trigger/keyword match (no embedding needed at intake time)."""
        goal_low = goal.lower()
        goal_words = set(goal_low.split())
        matches: list[SkillMatch] = []
        with self.db.session() as s:
            for row in s.execute(select(SkillRow).where(SkillRow.status == "active")).scalars():
                score = float(sum(1 for trig in row.triggers if str(trig).lower() in goal_low))
                score += len(goal_words & set(row.description.lower().split())) * 0.2
                if score > 0:
                    matches.append(SkillMatch(row.name, row.description, row.body, score))
        matches.sort(key=lambda m: -m.score)
        return matches[:top]

    def matching_skills_text(self, goal: str, top: int = 2) -> str:
        matches = self.matching_skills(goal, top)
        if not matches:
            return ""
        return "\n\n".join(f"# Skill: {m.name}\n{m.body[:800]}" for m in matches)

    async def propose_skill(
        self, run_id: str, goal: str, plan_outline: list[str], tools: list[str]
    ) -> str:
        """Propose a skill from a verified run; stored as 'proposed' pending /skills review."""
        name = _slug(goal)[:60] or f"skill-{run_id[:8]}"
        body = (
            f"# {goal}\n\n## Plan outline\n"
            + "\n".join(f"{i + 1}. {step}" for i, step in enumerate(plan_outline))
            + f"\n\n## Tools\n{', '.join(tools)}\n"
        )
        with self.db.session() as s:
            existing = s.execute(select(SkillRow).where(SkillRow.name == name)).scalar_one_or_none()
            if existing:
                existing.success_count += 1
                existing.last_used = utcnow()
                return existing.id
            row = SkillRow(
                name=name,
                description=goal[:200],
                triggers=_keywords(goal),
                tools=tools,
                body=body,
                status="proposed",
            )
            s.add(row)
            s.flush()
            return row.id

    def approve_skill(self, skill_id: str, action: str) -> bool:
        with self.db.session() as s:
            row = s.get(SkillRow, skill_id)
            if row is None:
                return False
            if action == "reject":
                s.delete(row)
            elif action == "approve":
                row.status = "active"
                self._write_skill_file(row)
            return True

    def _write_skill_file(self, row: SkillRow) -> None:
        skill_dir = self.skills_dir / row.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = (
            "---\n"
            f"name: {row.name}\n"
            f"description: {row.description}\n"
            f"triggers: {list(row.triggers)}\n"
            f"tools: {list(row.tools)}\n"
            "---\n\n"
        )
        (skill_dir / "SKILL.md").write_text(frontmatter + row.body, encoding="utf-8")

    # ------------------------------------------------------------- helpers

    async def _embed(self, text: str) -> list[float]:
        vectors = await self.gateway.embed([text], role="embed")
        return vectors[0] if vectors else []


def _pack(vector: list[float]) -> str:
    return struct.pack(f"<{len(vector)}f", *vector).hex()


def _unpack(hexstr: str) -> list[float]:
    data = bytes.fromhex(hexstr)
    return list(struct.unpack(f"<{len(data) // 4}f", data))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _slug(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _keywords(text: str) -> list[str]:
    import re

    stop = {"the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with", "from"}
    words = [w for w in re.findall(r"[a-z0-9\-]+", text.lower()) if w not in stop and len(w) > 3]
    return list(dict.fromkeys(words))[:10]


def _parse_skill_md(text: str) -> tuple[dict[str, Any], str]:
    import yaml

    if not text.startswith("---"):
        return {}, text
    _, _, rest = text.partition("---\n")
    front, _, body = rest.partition("\n---")
    meta = yaml.safe_load(front) or {}
    return dict(meta), body.strip()
