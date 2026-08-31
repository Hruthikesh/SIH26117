"""Memory + skills (SPEC §13) and agent hot-reload."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.helpers import make_state
from yantra_server.memory.service import MemoryError, MemoryService
from yantra_server.state import AppState

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
async def state() -> Any:
    import asyncio

    st = make_state()
    st.bus.bind_loop(asyncio.get_running_loop())
    await st.supervisor.start_all()
    yield st
    await st.supervisor.stop_all()


@pytest.fixture
def memory(state: AppState, tmp_path: Path) -> MemoryService:
    return MemoryService(state.db, state.gateway, tmp_path / "skills")


async def test_facts_require_provenance(memory: MemoryService) -> None:
    with pytest.raises(MemoryError):
        await memory.remember_fact("P-3101A failed", provenance=[])
    mem_id = await memory.remember_fact("P-3101A failed 5 times", provenance=["c:abc123"])
    assert mem_id


async def test_recall_returns_stored_facts(memory: MemoryService) -> None:
    # Semantic ranking needs a real embedding model; mock embeddings are hash-based, so this
    # asserts recall returns the stored facts with provenance, not the specific order.
    await memory.remember_fact("P-3101A has recurring seal failures", provenance=["c:1"])
    await memory.remember_fact("E-3102 design duty is 4 MW", provenance=["c:2"])
    hits = await memory.recall("pump seal failure", top=5)
    assert len(hits) == 2
    assert all(h["provenance"] for h in hits)


async def test_episodes_recorded_and_recalled(memory: MemoryService) -> None:
    await memory.record_episode("run1", "review pump reliability", "produced root-cause report")
    similar = await memory.similar_episodes("pump reliability review", top=1)
    assert similar and "run:run1" in similar[0]["provenance"]


async def test_memory_review_purge(memory: MemoryService) -> None:
    mem_id = await memory.remember_fact("temp fact", provenance=["c:x"])
    assert memory.review_memory(mem_id, "purge")
    assert all(m["id"] != mem_id for m in memory.list_memories())


def test_bundled_skills_load(state: AppState) -> None:
    memory = MemoryService(state.db, state.gateway, REPO / "skills")
    skills = memory.list_skills()
    names = {s["name"] for s in skills}
    assert "pump-reliability-review" in names
    assert "psv-adequacy-review" in names
    assert len(names) >= 8


def test_matching_skills_by_trigger(state: AppState) -> None:
    memory = MemoryService(state.db, state.gateway, REPO / "skills")
    matches = memory.matching_skills(
        "investigate recurring pump seal failures from the maintenance log"
    )
    assert matches
    assert matches[0].name == "pump-reliability-review"
    text = memory.matching_skills_text("review the P&ID for PSV adequacy")
    assert "psv" in text.lower()


async def test_skill_proposal_and_approval(state: AppState, tmp_path: Path) -> None:
    memory = MemoryService(state.db, state.gateway, tmp_path / "skills")
    skill_id = await memory.propose_skill(
        "run1",
        "consolidate the 2025 inspection reports",
        ["find reports", "extract", "register"],
        ["analyst", "writer"],
    )
    proposed = [s for s in memory.list_skills() if s["id"] == skill_id]
    assert proposed and proposed[0]["status"] == "proposed"
    assert memory.approve_skill(skill_id, "approve")
    assert (tmp_path / "skills").glob("*/SKILL.md")
    # second identical run bumps success_count instead of duplicating
    skill_id2 = await memory.propose_skill(
        "run2", "consolidate the 2025 inspection reports", ["a", "b"], ["analyst"]
    )
    assert skill_id2 == skill_id


def test_agent_roster_hot_reload(tmp_path: Path) -> None:
    from yantra_server.agents import AgentRoster

    agents_dir = tmp_path / "agents"
    (agents_dir / "prompts").mkdir(parents=True)
    (agents_dir / "prompts" / "p.md").write_text("persona", encoding="utf-8")
    (agents_dir / "custom.yaml").write_text(
        "name: hse_auditor\ndescription: permit-to-work audits\nmodel_role: executor\n"
        "tools: [read_file, search_knowledge]\nsystem_prompt: prompts/p.md\n",
        encoding="utf-8",
    )
    roster = AgentRoster(agents_dir)
    assert roster.get("hse_auditor") is not None
    # add a second agent → hot reload picks it up
    (agents_dir / "second.yaml").write_text(
        "name: permit_writer\ndescription: writes permits\nmodel_role: executor\n"
        "tools: [write_file]\nsystem_prompt: prompts/p.md\n",
        encoding="utf-8",
    )
    assert "permit_writer" in roster.names()


def test_bundled_agents_valid() -> None:
    from yantra_server.agents import AgentRoster

    roster = AgentRoster(REPO / "agents")
    assert roster.validate_all() == []
    assert {
        "planner",
        "analyst",
        "coder",
        "writer",
        "reviewer",
        "drawing_engineer",
        "data_engineer",
    } <= set(roster.names())


async def test_memory_tools(state: AppState, tmp_path: Path) -> None:
    from tests.helpers import make_ctx

    state.memory = MemoryService(state.db, state.gateway, tmp_path / "skills")
    ctx = make_ctx(state, tmp_path / "ws")
    remembered = await state.tools.runtime.execute(
        "remember",
        {"kind": "fact", "text": "PSV-3105 weeps at the flange", "provenance": ["c:9"]},
        ctx,
    )
    assert remembered.ok
    # fact without provenance is refused
    refused = await state.tools.runtime.execute(
        "remember", {"kind": "fact", "text": "no source", "provenance": []}, ctx
    )
    assert not refused.ok
    recalled = await state.tools.runtime.execute("recall", {"query": "PSV weep flange"}, ctx)
    assert recalled.ok and "PSV-3105" in recalled.content
