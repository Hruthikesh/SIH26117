"""Agent definitions load from agents/*.yaml and hot-reload on file change."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)


class AgentVerification(BaseModel):
    rubric: str = "rubrics/default.md"
    threshold: int = 80


class AgentDecoding(BaseModel):
    temperature: float = 0.0
    reasoning_effort: str | None = None


class AgentDef(BaseModel):
    name: str
    description: str = ""
    model_role: str = "executor"
    tools: list[str] = Field(default_factory=list)
    system_prompt: str = ""  # path relative to agents/, resolved to text by the roster
    fewshots: list[str] = Field(default_factory=list)
    verification: AgentVerification = Field(default_factory=AgentVerification)
    decoding: AgentDecoding = Field(default_factory=AgentDecoding)

    persona_text: str = ""  # filled by the loader
    rubric_text: str = ""


class AgentRoster:
    def __init__(self, agents_dir: Path) -> None:
        self.agents_dir = agents_dir
        self._agents: dict[str, AgentDef] = {}
        self._mtimes: dict[Path, float] = {}
        self.reload()

    def _stale(self) -> bool:
        if not self.agents_dir.is_dir():
            return False
        current = {p: p.stat().st_mtime for p in self.agents_dir.glob("*.yaml")}
        return current != self._mtimes

    def reload(self) -> None:
        agents: dict[str, AgentDef] = {}
        mtimes: dict[Path, float] = {}
        if not self.agents_dir.is_dir():
            self._agents, self._mtimes = agents, mtimes
            return
        for path in sorted(self.agents_dir.glob("*.yaml")):
            mtimes[path] = path.stat().st_mtime
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                agent = AgentDef.model_validate(raw)
            except (yaml.YAMLError, ValidationError) as exc:
                log.warning("skipping invalid agent file %s: %s", path.name, exc)
                continue
            agent.persona_text = self._read_rel(agent.system_prompt)
            agent.rubric_text = self._read_rel(agent.verification.rubric)
            agents[agent.name] = agent
        self._agents, self._mtimes = agents, mtimes

    def _read_rel(self, rel: str) -> str:
        if not rel:
            return ""
        path = self.agents_dir / rel
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return ""

    def maybe_reload(self) -> None:
        if self._stale():
            log.info("agent roster changed on disk; reloading")
            self.reload()

    def get(self, name: str) -> AgentDef | None:
        self.maybe_reload()
        return self._agents.get(name)

    def all(self) -> list[AgentDef]:
        self.maybe_reload()
        return list(self._agents.values())

    def names(self) -> list[str]:
        return [a.name for a in self.all()]

    def roster_text(self, exclude: tuple[str, ...] = ("planner", "reviewer", "router")) -> str:
        """One line per assignable agent, for the planner prompt."""
        lines = [
            f"- {agent.name}: {agent.description}"
            for agent in self.all()
            if agent.name not in exclude
        ]
        return "\n".join(lines)

    def validate_all(self) -> list[str]:
        """Problems for `yantra agents validate` (missing personas, empty tools…)."""
        problems: list[str] = []
        # planner/reviewer/router steer the model with a persona but call no tools directly.
        toolless_by_design = {"planner", "router", "reviewer"}
        for agent in self.all():
            if not agent.persona_text:
                problems.append(f"{agent.name}: system_prompt file missing ({agent.system_prompt})")
            if not agent.tools and agent.name not in toolless_by_design:
                problems.append(f"{agent.name}: no tools declared")
        return problems
