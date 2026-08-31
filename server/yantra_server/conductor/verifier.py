"""Verifier (SPEC §8.6): all programmatic checks, then the reviewer persona.

Checks never short-circuit — the model needs the complete failure list to fix things.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yantra_server.agents import AgentRoster
from yantra_server.db.models import VerificationRow
from yantra_server.gateway.engines.base import ChatMessage, Constraint, Decoding
from yantra_server.gateway.service import ModelRequest
from yantra_server.observe.tracing import span
from yantra_server.sandbox import Sandbox
from yantra_server.sandbox.local import shell_argv

from .types import (
    CheckResult,
    FinishArgs,
    PlanTask,
    ReviewerReport,
    VerificationOutcome,
)

if TYPE_CHECKING:
    from yantra_server.state import AppState

REVIEW_ARTIFACT_BYTES = 12_000  # per artifact excerpt shown to the reviewer

CheckFn = Callable[["Verifier", dict[str, Any], PlanTask, FinishArgs], Awaitable[CheckResult]]

# Extensible checker registry; vision (M7) and operators (custom plugins) add entries.
EXTRA_CHECKERS: dict[str, CheckFn] = {}


@dataclass
class Verifier:
    state: AppState
    roster: AgentRoster
    workspace: Path
    run_id: str
    sandbox: Sandbox

    # ------------------------------------------------------------- entry

    async def verify(
        self, plan_task: PlanTask, finish: FinishArgs, attempt: int
    ) -> VerificationOutcome:
        with span("verify", kind="verify", task_id=plan_task.id, attempt=attempt) as sp:
            results: list[CheckResult] = []
            rubric_checks: list[dict[str, Any]] = []
            for check in plan_task.acceptance:
                payload = check.model_dump()
                if payload["kind"] == "rubric":
                    rubric_checks.append(payload)
                    continue
                results.append(await self._run_check(payload, plan_task, finish))

            # Domain-safety hard gate (SPEC §16.3): never accept a recommendation to defeat a
            # safety function — applies to every task regardless of its acceptance checks.
            results.append(self._check_domain_safety(finish))

            reviewer = await self._review(plan_task, finish, results)
            threshold = self._threshold(plan_task, rubric_checks)
            for rubric in rubric_checks:
                passed = reviewer.score >= int(rubric.get("min_score", threshold))
                results.append(
                    CheckResult(
                        check=rubric,
                        passed=passed,
                        detail=f"reviewer score {reviewer.score} vs min {rubric.get('min_score')}",
                    )
                )

            hard_pass = all(r.passed for r in results)
            verdict = (
                "pass"
                if hard_pass and reviewer.verdict == "pass" and reviewer.score >= threshold
                else "fail"
            )
            outcome = VerificationOutcome(
                task_id=plan_task.id,
                attempt=attempt,
                checks=results,
                reviewer=reviewer,
                verdict=verdict,
            )
            sp.set("verdict", verdict)
            sp.set("reviewer_score", reviewer.score)
            sp.set("checks", [{"kind": r.check.get("kind"), "passed": r.passed} for r in results])
            with self.state.db.session() as s:
                s.add(
                    VerificationRow(
                        task_id=plan_task.id,
                        run_id=self.run_id,
                        attempt=attempt,
                        checks=[r.model_dump(mode="json") for r in results],
                        reviewer=reviewer.model_dump(mode="json"),
                        verdict=verdict,
                    )
                )
            return outcome

    def _check_domain_safety(self, finish: FinishArgs) -> CheckResult:
        from yantra_server.guard.domain_safety import check_domain_safety

        text = finish.summary + "\n" + "\n".join(c.text for c in finish.claims)
        violations = check_domain_safety(text)
        if violations:
            return CheckResult(
                check={"kind": "domain_safety"},
                passed=False,
                detail="; ".join(v.sentence for v in violations[:3]),
            )
        return CheckResult(
            check={"kind": "domain_safety"}, passed=True, detail="no unsafe recommendations"
        )

    def _threshold(self, plan_task: PlanTask, rubric_checks: list[dict[str, Any]]) -> int:
        agent = self.roster.get(plan_task.role)
        base = agent.verification.threshold if agent else 80
        if plan_task.outputs and any(o.schema_id for o in plan_task.outputs):
            base = max(base, 85)  # deliverable tasks (SPEC §8.6)
        return base

    # ------------------------------------------------------------- checks

    async def _run_check(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        kind = str(check.get("kind"))
        runner = getattr(self, f"_check_{kind}", None)
        if runner is None:
            extra = EXTRA_CHECKERS.get(kind) or EXTRA_CHECKERS.get(str(check.get("plugin", "")))
            if extra is not None:
                return await extra(self, check, plan_task, finish)
            return CheckResult(check=check, passed=False, detail=f"no checker for kind {kind!r}")
        try:
            result = await runner(check, plan_task, finish)
            assert isinstance(result, CheckResult)
            return result
        except Exception as exc:
            return CheckResult(check=check, passed=False, detail=f"checker error: {exc}")

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else self.workspace / p

    async def _check_file_exists(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        path = self._resolve(str(check["path"]))
        if path.is_file() and path.stat().st_size > 0:
            return CheckResult(
                check=check, passed=True, detail=f"{path.name}: {path.stat().st_size} B"
            )
        return CheckResult(check=check, passed=False, detail=f"missing or empty: {check['path']}")

    async def _check_schema_valid(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        import jsonschema

        path = self._resolve(str(check["path"]))
        if not path.is_file():
            return CheckResult(check=check, passed=False, detail=f"file missing: {check['path']}")
        schema_file = (
            self.state.loaded.assets_dir / "templates" / "schemas" / f"{check['schema_id']}.json"
        )
        if not schema_file.is_file():
            return CheckResult(
                check=check, passed=False, detail=f"unknown schema_id {check['schema_id']!r}"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.validate(data, json.loads(schema_file.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            return CheckResult(check=check, passed=False, detail=f"not valid JSON: {exc}")
        except jsonschema.ValidationError as exc:
            return CheckResult(check=check, passed=False, detail=f"schema violation: {exc.message}")
        return CheckResult(check=check, passed=True, detail="validates")

    async def _check_tests_pass(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        import sys

        cmd = str(check.get("cmd", "auto"))
        cwd = self._resolve(str(check.get("cwd", ".")))
        if cmd == "auto":
            cmd = f'"{sys.executable}" -m pytest -q'
        result = await self.sandbox.run(shell_argv(cmd), cwd=cwd, timeout_s=300)
        tail = result.combined_output()[-800:]
        if result.exit_code == 0:
            return CheckResult(check=check, passed=True, detail=f"exit 0; {tail[-200:]}")
        return CheckResult(check=check, passed=False, detail=f"exit {result.exit_code}; {tail}")

    async def _check_command_succeeds(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        result = await self.sandbox.run(
            shell_argv(str(check["cmd"])), cwd=self.workspace, timeout_s=180
        )
        if result.exit_code == 0:
            return CheckResult(check=check, passed=True, detail="exit 0")
        return CheckResult(
            check=check,
            passed=False,
            detail=f"exit {result.exit_code}: {result.combined_output()[-400:]}",
        )

    async def _check_citation_coverage(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        facts = [c for c in finish.claims if c.kind == "fact"]
        if not facts:
            return CheckResult(check=check, passed=True, detail="no fact claims")
        cited = sum(1 for c in facts if c.citations)
        ratio = cited / len(facts)
        ok = ratio >= float(check.get("min_ratio", 0.9))
        return CheckResult(
            check=check, passed=ok, detail=f"{cited}/{len(facts)} fact claims cited ({ratio:.0%})"
        )

    async def _check_claims_entailed(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        cited_claims = [c for c in finish.claims if c.citations and c.kind == "fact"]
        if not cited_claims:
            return CheckResult(check=check, passed=True, detail="no cited fact claims")
        total = 0.0
        judged = 0
        for claim in cited_claims[:20]:
            passage = self._resolve_citation_text(claim.citations[0])
            if passage is None:
                judged += 1  # unresolvable citation counts as unsupported
                continue
            verdict = await self.state.gateway.chat(
                ModelRequest(
                    role="utility",
                    messages=[
                        ChatMessage(
                            role="system",
                            content="Does the passage support the claim? Answer yes, no or partial.",
                        ),
                        ChatMessage(
                            role="user",
                            content=f"Claim: {claim.text}\n\nPassage:\n{passage[:3000]}",
                        ),
                    ],
                    constraint=Constraint(kind="choice", choices=["yes", "no", "partial"]),
                    decoding=Decoding(temperature=0.0, max_tokens=8),
                    priority=1,
                )
            )
            judged += 1
            if verdict.parsed == "yes":
                total += 1.0
            elif verdict.parsed == "partial":
                total += 0.5
        ratio = total / judged if judged else 0.0
        ok = ratio >= float(check.get("min_ratio", 0.85))
        return CheckResult(
            check=check, passed=ok, detail=f"entailment {ratio:.0%} over {judged} claims"
        )

    def _resolve_citation_text(self, citation: str) -> str | None:
        if citation.startswith("c:"):
            citation = citation[2:]
        if ":" in citation:  # artifact_id:locator
            artifact_id = citation.split(":", 1)[0]
            try:
                return self.state.artifacts.read_text(artifact_id)[:4000]
            except Exception:
                return None
        if self.state.knowledge is not None:
            try:
                text = self.state.knowledge.chunk_text(citation)
                if text:
                    return str(text)
            except Exception:
                return None
        try:
            return self.state.artifacts.read_text(citation)[:4000]
        except Exception:
            return None

    async def _check_diff_applies(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        from yantra_server.tools.builtin.fs import _apply_hunks, _parse_patch

        try:
            diff_text = self.state.artifacts.read_text(str(check["patch_ref"]))
            for file_name, hunks in _parse_patch(diff_text):
                target = self._resolve(file_name)
                original = target.read_text(encoding="utf-8") if target.exists() else ""
                _apply_hunks(original, hunks)
        except Exception as exc:
            return CheckResult(check=check, passed=False, detail=str(exc)[:300])
        return CheckResult(check=check, passed=True, detail="patch applies cleanly")

    async def _check_table_totals(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        path = self._resolve(str(check["path"]))
        if not path.is_file():
            return CheckResult(check=check, passed=False, detail=f"file missing: {check['path']}")
        rows = _load_table(path)
        if rows is None:
            return CheckResult(check=check, passed=False, detail="unsupported table format")
        failures: list[str] = []
        for rule in check.get("rules", []):
            problem = _eval_table_rule(str(rule), rows)
            if problem:
                failures.append(problem)
        if failures:
            return CheckResult(check=check, passed=False, detail="; ".join(failures)[:400])
        return CheckResult(check=check, passed=True, detail=f"{len(rows)} rows, rules hold")

    async def _check_image_contains(
        self, check: dict[str, Any], plan_task: PlanTask, finish: FinishArgs
    ) -> CheckResult:
        from yantra_server.gateway.engines.base import ImagePart, TextPart

        path = self._resolve(str(check["path"]))
        if not path.is_file():
            return CheckResult(check=check, passed=False, detail=f"image missing: {check['path']}")
        import base64

        expectations = [str(e) for e in check.get("expectations", [])]
        question = (
            "Does this image contain ALL of the following? "
            + "; ".join(expectations)
            + " Answer yes or no."
        )
        result = await self.state.gateway.chat(
            ModelRequest(
                role="vision",
                messages=[
                    ChatMessage(
                        role="user",
                        content=[
                            TextPart(text=question),
                            ImagePart(data_b64=base64.b64encode(path.read_bytes()).decode()),
                        ],
                    )
                ],
                constraint=Constraint(kind="choice", choices=["yes", "no"]),
                decoding=Decoding(temperature=0.0, max_tokens=8),
            )
        )
        ok = result.parsed == "yes"
        return CheckResult(check=check, passed=ok, detail=f"vision judge: {result.parsed}")

    # ------------------------------------------------------------- reviewer

    async def _review(
        self, plan_task: PlanTask, finish: FinishArgs, check_results: list[CheckResult]
    ) -> ReviewerReport:
        reviewer = self.roster.get("reviewer")
        agent = self.roster.get(plan_task.role)
        rubric = (agent.rubric_text if agent else "") or "Grade against the acceptance criteria."
        evidence = self._artifact_excerpts(finish)
        checks_text = "\n".join(
            f"- {r.check.get('kind')}: {'PASS' if r.passed else 'FAIL'} — {r.detail}"
            for r in check_results
        )
        claims_text = "\n".join(
            f"- [{c.kind}] {c.text} (citations: {', '.join(c.citations) or 'NONE'})"
            for c in finish.claims[:30]
        )
        user = (
            f"Task: {plan_task.title}\nIntent: {plan_task.intent}\n"
            f"Acceptance criteria: {[c.model_dump() for c in plan_task.acceptance]}\n\n"
            f"Rubric:\n{rubric}\n\n"
            f"Finish summary (grade the work, not this prose):\n{finish.summary}\n\n"
            f"Claims:\n{claims_text or '(none)'}\n\n"
            f"Programmatic check results:\n{checks_text or '(none)'}\n\n"
            f"Artifact excerpts:\n{evidence or '(no artifacts)'}"
        )
        try:
            result = await self.state.gateway.chat(
                ModelRequest(
                    role="reviewer",
                    messages=[
                        ChatMessage(
                            role="system", content=reviewer.persona_text if reviewer else ""
                        ),
                        ChatMessage(role="user", content=user),
                    ],
                    schema_model=ReviewerReport,
                    decoding=Decoding(temperature=0.0, max_tokens=1500),
                )
            )
            report = result.parsed
            assert isinstance(report, ReviewerReport)
            return report
        except Exception as exc:
            return ReviewerReport(
                score=0,
                failures=[],
                fix_instructions=[f"reviewer unavailable: {exc}"],
                verdict="fail",
            )

    def _artifact_excerpts(self, finish: FinishArgs) -> str:
        blocks: list[str] = []
        for ref in finish.artifacts[:8]:
            path = self._resolve(ref)
            if path.is_file():
                suffix = path.suffix.lower()
                if suffix in (".png", ".jpg", ".jpeg", ".pdf", ".docx", ".xlsx", ".pptx"):
                    blocks.append(f"# {ref}\n(binary {suffix} artifact, {path.stat().st_size:,} B)")
                else:
                    text = path.read_text(encoding="utf-8", errors="replace")[
                        :REVIEW_ARTIFACT_BYTES
                    ]
                    blocks.append(f"# {ref}\n{text}")
                continue
            try:
                text = self.state.artifacts.read_text(ref)[:REVIEW_ARTIFACT_BYTES]
                blocks.append(f"# artifact {ref}\n{text}")
            except Exception:
                blocks.append(f"# {ref}\nMISSING — claimed but not found")
        return "\n\n".join(blocks)


# ------------------------------------------------------------------ table helpers


def _load_table(path: Path) -> list[dict[str, Any]] | None:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        import csv

        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    if suffix == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            return None
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            return []
        rows_iter = ws.iter_rows(values_only=True)
        header = [str(h) for h in next(rows_iter, [])]
        return [dict(zip(header, row, strict=False)) for row in rows_iter]
    return None


def _eval_table_rule(rule: str, rows: list[dict[str, Any]]) -> str | None:
    """Mini-rules: 'rows >= N', 'sum(col) == N', 'nonempty(col)'. Returns a problem or None."""
    import re

    if match := re.fullmatch(r"rows\s*(>=|==|<=)\s*(\d+)", rule.strip()):
        op, count = match.group(1), int(match.group(2))
        actual = len(rows)
        ok = (
            (actual >= count)
            if op == ">="
            else (actual == count)
            if op == "=="
            else actual <= count
        )
        return None if ok else f"rows {actual} violates '{rule}'"
    if match := re.fullmatch(r"sum\((\w+)\)\s*==\s*([\d.]+)", rule.strip()):
        column, want = match.group(1), float(match.group(2))
        try:
            total = sum(float(r.get(column) or 0) for r in rows)
        except (TypeError, ValueError):
            return f"column {column} is not numeric"
        return (
            None
            if abs(total - want) < 1e-6 * max(1.0, abs(want))
            else (f"sum({column})={total} != {want}")
        )
    if match := re.fullmatch(r"nonempty\((\w+)\)", rule.strip()):
        column = match.group(1)
        empty = sum(1 for r in rows if not str(r.get(column) or "").strip())
        return None if empty == 0 else f"{empty} empty values in {column}"
    return f"unknown rule syntax: {rule}"
