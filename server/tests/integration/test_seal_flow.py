"""Seal verification, demo and audit-chain-of-side-effects on the mock profile."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import make_state
from yantra_server.state import AppState

pytestmark = pytest.mark.integration


async def _wire(state: AppState) -> None:
    from yantra_server.agents import AgentRoster
    from yantra_server.conductor.service import Conductor
    from yantra_server.observe.seal_monitor import SealMonitor
    from yantra_server.seal.socket_guard import install as install_guard

    state.bus.bind_loop(asyncio.get_running_loop())
    monitor = SealMonitor(state.config, state.db, state.bus, state.loaded.assets_dir)
    state.seal_monitor = monitor
    install_guard(allowlist=state.config.seal.allowlist, reporter=monitor.record_event)
    await state.supervisor.start_all()
    state.conductor = Conductor(state=state, roster=AgentRoster(state.loaded.assets_dir / "agents"))


@pytest.fixture
async def sealed_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    # dev box: no bwrap/docker, so run unsealed (local sandbox) but keep the guard active
    monkeypatch.setenv("YANTRA_SEALED", "0")
    state = make_state()
    await _wire(state)
    yield state
    await state.supervisor.stop_all()


async def test_seal_verify_produces_certificate(sealed_state: AppState) -> None:
    from yantra_server.seal.verify import run_verification

    report = await run_verification(sealed_state)
    names = {o.name for o in report.outcomes}
    assert {"socket_guard_python", "agent_smoke", "sandbox_no_network"} <= names
    guard = next(o for o in report.outcomes if o.name == "socket_guard_python")
    assert guard.passed
    assert report.certificate is not None
    assert report.certificate["models"]  # registry captured
    assert report.certificate["audit_head"] is not None
    assert sealed_state.audit.verify().ok


async def test_seal_certificate_signed_when_key_present(sealed_state: AppState) -> None:
    from yantra_server.seal.verify import keygen, run_verification

    keygen(sealed_state.config.paths.data_dir)
    report = await run_verification(sealed_state)
    assert report.signature and len(report.signature) == 128  # ed25519 hex

    # verify the signature with the public key
    import json

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    _, pub = keygen(sealed_state.config.paths.data_dir)  # regenerates — sign with the new key
    report2 = await run_verification(sealed_state)
    public_key = load_pem_public_key(Path(pub).read_bytes())
    assert isinstance(public_key, Ed25519PublicKey)
    payload = json.dumps(report2.certificate, sort_keys=True, separators=(",", ":")).encode()
    public_key.verify(bytes.fromhex(report2.signature or ""), payload)  # raises on mismatch


async def test_agent_smoke_completes(sealed_state: AppState) -> None:
    from yantra_server.evals.seal_smoke import run_seal_smoke

    outcome = await run_seal_smoke(sealed_state)
    assert outcome.passed, outcome.detail


async def test_seal_demo_blocks_egress(sealed_state: AppState) -> None:
    from yantra_server.seal.demo import run_seal_demo

    result = await run_seal_demo(sealed_state)
    probes = {p["name"]: p for p in result["probes"]}
    # urllib egress goes through the in-process guard → blocked deterministically
    assert probes["urllib https://example.com"]["blocked"], probes["urllib https://example.com"][
        "output"
    ]
    assert result["new_blocked_events"] >= 1


async def test_side_effects_are_audited(sealed_state: AppState) -> None:
    from sqlalchemy import select

    from yantra_server.db.models import AuditRow, RunRow
    from yantra_server.evals.seal_smoke import run_seal_smoke

    await run_seal_smoke(sealed_state)
    with sealed_state.db.session() as s:
        events = [row.event for row in s.execute(select(AuditRow)).scalars()]
        runs = list(s.execute(select(RunRow)).scalars())
    assert "run.start" in events
    assert "run.finished" in events
    assert any(e.startswith("tool.") for e in events)  # write_file was audited
    assert runs and runs[0].status in ("done", "done_with_gaps")
    assert sealed_state.audit.verify().ok


async def test_metrics_endpoint_renders(sealed_state: AppState) -> None:
    from yantra_server.observe.metrics import render_metrics

    text = render_metrics(sealed_state)
    assert "yantra_sealed" in text
    assert "yantra_seal_blocked_total" in text
