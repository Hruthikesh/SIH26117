"""Planner + plan critic (SPEC §8.3): constrained Plan, cheap critique, ≤2 revisions."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from yantra_server.agents import AgentRoster
from yantra_server.gateway.engines.base import ChatMessage, Decoding
from yantra_server.gateway.service import ModelRequest
from yantra_server.observe.tracing import span

from .types import GoalSpec, Plan, PlanCritique

if TYPE_CHECKING:
    from yantra_server.state import AppState

MAX_REVISIONS = 2

PLANNER_INSTRUCTION = """Produce the Plan as JSON. Task ids are t1, t2, … in a sensible
execution order. Every task needs at least one machine-checkable acceptance check. Bind
each GoalSpec deliverable to exactly one task whose outputs include it."""

CRITIC_SYSTEM = """You are a plan critic. Check the plan mechanically and list ONLY real
defects, one line each:
- a GoalSpec deliverable no task produces
- a dependency cycle, or a task consuming an output no earlier task produces
- a task with no machine-checkable acceptance check
- a task assigned to an agent that does not exist in the roster
- an obviously oversized task (mixes discovery, analysis and deliverable production)
- planned verification/review tasks (verification is automatic; they must be removed)
If the plan is sound, ok=true with no findings. Do not suggest stylistic changes."""


async def make_plan(
    state: AppState,
    roster: AgentRoster,
    goal_spec: GoalSpec,
    *,
    failure_context: str | None = None,
    previous_plan: Plan | None = None,
) -> Plan:
    """Plan → critic → up to MAX_REVISIONS repair rounds; structural checks always enforced."""
    with span("plan", kind="plan") as sp:
        exemplars = _plan_exemplars(state, goal=goal_spec.objective)
        plan = await _draft_plan(
            state, roster, goal_spec, exemplars, failure_context, previous_plan
        )
        for round_no in range(MAX_REVISIONS + 1):
            structural = _structural_findings(plan, goal_spec, roster)
            critique = await _critique(state, roster, goal_spec, plan)
            findings = structural + [f for f in critique.findings if f not in structural]
            sp.set(f"round_{round_no}_findings", findings)
            if not findings or round_no == MAX_REVISIONS:
                break
            plan = await _draft_plan(
                state,
                roster,
                goal_spec,
                exemplars,
                failure_context,
                plan,
                critic_findings=findings,
            )
        plan.version = (previous_plan.version + 1) if previous_plan else 1
        sp.set("tasks", [t.id for t in plan.tasks])
        return plan


async def _draft_plan(
    state: AppState,
    roster: AgentRoster,
    goal_spec: GoalSpec,
    exemplars: str,
    failure_context: str | None,
    previous_plan: Plan | None,
    critic_findings: list[str] | None = None,
) -> Plan:
    planner = roster.get("planner")
    system = (planner.persona_text if planner else "") + "\n\n" + PLANNER_INSTRUCTION
    parts = [f"GoalSpec:\n{goal_spec.model_dump_json(indent=2)}"]
    parts.append(f"Agent roster:\n{roster.roster_text()}")
    manifest = state.tools.registry.manifest_text(state.tools.registry.names())
    parts.append(f"Tools that exist (summary):\n{manifest}")
    if exemplars:
        parts.append(f"Example plans for similar work:\n{exemplars}")
    if previous_plan is not None:
        parts.append(f"Previous plan (revise, do not restart):\n{previous_plan.model_dump_json()}")
    if failure_context:
        parts.append(f"Execution failures to address:\n{failure_context}")
    if critic_findings:
        parts.append("Critic findings to fix:\n" + "\n".join(f"- {f}" for f in critic_findings))
    result = await state.gateway.chat(
        ModelRequest(
            role="planner",
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content="\n\n".join(parts)),
            ],
            schema_model=Plan,
            decoding=Decoding(temperature=0.0, max_tokens=6000),
        )
    )
    plan = result.parsed
    assert isinstance(plan, Plan)
    return plan


async def _critique(
    state: AppState, roster: AgentRoster, goal_spec: GoalSpec, plan: Plan
) -> PlanCritique:
    result = await state.gateway.chat(
        ModelRequest(
            role="utility",
            messages=[
                ChatMessage(role="system", content=CRITIC_SYSTEM),
                ChatMessage(
                    role="user",
                    content=f"Roster:\n{roster.roster_text()}\n\n"
                    f"GoalSpec deliverables: {[d.name for d in goal_spec.deliverables]}\n\n"
                    f"Plan:\n{plan.model_dump_json(indent=2)}",
                ),
            ],
            schema_model=PlanCritique,
            decoding=Decoding(temperature=0.0, max_tokens=1000),
        )
    )
    critique = result.parsed
    assert isinstance(critique, PlanCritique)
    return critique


def _structural_findings(plan: Plan, goal_spec: GoalSpec, roster: AgentRoster) -> list[str]:
    """Deterministic checks the critic model cannot be trusted to always catch."""
    findings: list[str] = []
    ids = {t.id for t in plan.tasks}
    if len(ids) != len(plan.tasks):
        findings.append("duplicate task ids")
    known_agents = set(roster.names())
    for task in plan.tasks:
        if task.role not in known_agents:
            findings.append(f"{task.id}: unknown agent {task.role!r}")
        for input_ref in task.inputs:
            if input_ref.startswith("t") and input_ref not in ids:
                findings.append(f"{task.id}: input {input_ref} is not a task id in the plan")
    for edge in plan.edges:
        if len(edge) != 2 or edge[0] not in ids or edge[1] not in ids:
            findings.append(f"invalid edge {edge}")
    if _has_cycle(plan):
        findings.append("dependency cycle")
    produced = {o.name.lower() for t in plan.tasks for o in t.outputs}
    for deliverable in goal_spec.deliverables:
        tokens = {deliverable.name.lower()}
        if deliverable.path_hint:
            tokens.add(deliverable.path_hint.lower())
        if not any(any(tok in p or p in tok for tok in tokens) for p in produced):
            findings.append(f"deliverable {deliverable.name!r} is not produced by any task")
    return findings


def dependency_map(plan: Plan) -> dict[str, set[str]]:
    """task id → prerequisite ids, from `inputs` (t-refs) plus explicit edges."""
    deps: dict[str, set[str]] = {t.id: set() for t in plan.tasks}
    ids = set(deps)
    for task in plan.tasks:
        for input_ref in task.inputs:
            if input_ref in ids:
                deps[task.id].add(input_ref)
    for edge in plan.edges:
        if len(edge) == 2 and edge[0] in ids and edge[1] in ids:
            deps[edge[1]].add(edge[0])
    return deps


def _has_cycle(plan: Plan) -> bool:
    deps = dependency_map(plan)
    visited: dict[str, int] = {}

    def visit(node: str) -> bool:
        state_ = visited.get(node, 0)
        if state_ == 1:
            return True
        if state_ == 2:
            return False
        visited[node] = 1
        if any(visit(dep) for dep in deps.get(node, ())):
            return True
        visited[node] = 2
        return False

    return any(visit(t) for t in deps)


def _plan_exemplars(state: AppState, goal: str = "", limit: int = 2) -> str:
    """The `limit` exemplar plans most relevant to the goal (word overlap, name-order ties).

    Relevance matters more than it looks: small models copy whatever exemplar they see, so
    an analysis-shaped example on a trivial file-write goal produces a parroted 5-task plan.
    """
    exemplar_dir = state.loaded.assets_dir / "tools" / "fewshot" / "plans"
    if not exemplar_dir.is_dir():
        return ""
    goal_words = {w for w in re.findall(r"[a-z]+", goal.lower()) if len(w) > 2}
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for path in sorted(exemplar_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        exemplar_words = {
            w for w in re.findall(r"[a-z]+", str(data.get("goal", "")).lower()) if len(w) > 2
        }
        overlap = len(goal_words & exemplar_words) / (len(exemplar_words) or 1)
        scored.append((-overlap, path.stem, data))
    scored.sort()
    return "\n\n".join(
        f"# {data.get('goal', stem)}\n{json.dumps(data.get('plan', data))[:2500]}"
        for _, stem, data in scored[:limit]
    )
