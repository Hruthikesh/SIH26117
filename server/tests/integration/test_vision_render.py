"""P&ID pipeline + rules + rendering end-to-end (M7 DoD)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import make_ctx, make_state
from yantra_server.state import AppState

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]


def make_pid(tmp_path: Path) -> dict[str, Any]:
    sys.path.insert(0, str(REPO))
    from corpus.pid_gen import generate_pids

    return generate_pids(tmp_path / "drawings")


@pytest.fixture
async def vision_state() -> Any:
    state = make_state()
    state.bus.bind_loop(asyncio.get_running_loop())
    await state.supervisor.start_all()
    yield state
    await state.supervisor.stop_all()


async def test_pid_generation_and_rules_find_planted_deviations(
    vision_state: AppState, tmp_path: Path
) -> None:
    from yantra_server.vision.pid.graph import PIDGraph
    from yantra_server.vision.pid.pipeline import PIDPipeline
    from yantra_server.vision.pid.rules import RuleEngine, load_rulepack

    pid = make_pid(tmp_path)
    assert Path(pid["png"]).stat().st_size > 1000  # a real raster

    pipeline = PIDPipeline()
    graph = await pipeline.analyze(Path(pid["png"]))
    assert isinstance(graph, PIDGraph)
    assert len(graph.nodes) >= 10
    # control loop 3201 assembled
    assert any(loop.loop_number == "3201" for loop in graph.control_loops)

    engine = RuleEngine(load_rulepack(REPO / "knowledge" / "pid" / "rules.yaml"))
    findings = engine.check(graph)
    found_rules = {f.rule_id for f in findings}
    planted = {d["rule_id"] for d in pid["graph"]["planted_deviations"]}
    assert planted <= found_rules, f"missed planted deviations: {planted - found_rules}"


async def test_pid_tools_end_to_end(vision_state: AppState, tmp_path: Path) -> None:
    pid = make_pid(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    # copy the drawing + its truth sidecar into the workspace
    import shutil

    draw_dir = ws / "drawings"
    draw_dir.mkdir()
    for f in Path(pid["png"]).parent.iterdir():
        shutil.copy(f, draw_dir / f.name)
    ctx = make_ctx(vision_state, ws)

    analyze = await vision_state.tools.runtime.execute(
        "pid_analyze", {"path": "drawings/PID_3-1201_RevC.png"}, ctx
    )
    assert analyze.ok
    graph_ref = analyze.data["graph_ref"]
    assert analyze.data["equipment"]

    rules = await vision_state.tools.runtime.execute(
        "pid_rules_check", {"graph_ref": graph_ref}, ctx
    )
    assert rules.ok
    rule_ids = {f["rule_id"] for f in rules.data["findings"]}
    assert "psv_on_vessel" in rule_ids

    annotate = await vision_state.tools.runtime.execute(
        "annotate_image",
        {
            "path": "drawings/PID_3-1201_RevC.png",
            "graph_ref": graph_ref,
            "findings": rules.data["findings"],
            "out_path": "annotated.png",
        },
        ctx,
    )
    assert annotate.ok
    assert (ws / "annotated.png").is_file()


async def test_render_all_formats_with_provenance(vision_state: AppState, tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = make_ctx(vision_state, ws)
    report_data = {
        "title": "Pump P-3101A Root-Cause Report",
        "executive_summary": "P-3101A shows recurring seal failures.",
        "sections": [
            {
                "heading": "Findings",
                "paragraphs": ["Five failures in two years."],
                "bullets": ["Check the plan 11 flush"],
                "tables": [
                    {
                        "caption": "MTBF",
                        "columns": ["pump", "mtbf_h"],
                        "rows": [["P-3101A", "1200"]],
                    }
                ],
                "figures": [],
            }
        ],
        "findings": [
            {
                "severity": "high",
                "statement": "Recurring seal failure on P-3101A",
                "evidence": "MaintLog p.4",
            }
        ],
        "recommendations": [{"priority": "high", "text": "Root-cause the seal flush"}],
        "appendix": {
            "citations": ["MaintLog_Unit3, p.4"],
            "assumptions": [],
            "unverified_claims": [],
        },
    }
    import json

    (ws / "report.json").write_text(json.dumps(report_data))

    for fmt, ext in [("docx", "docx"), ("xlsx", "xlsx"), ("md", "md")]:
        result = await vision_state.tools.runtime.execute(
            "render_document",
            {
                "type": fmt,
                "schema_id": "report",
                "data_json": "report.json",
                "out_path": f"out.{ext}",
            },
            ctx,
        )
        assert result.ok, result.error
        out = ws / f"out.{ext}"
        assert out.is_file() and out.stat().st_size > 0
        prov = ws / f"out.{ext}.provenance.json"
        assert prov.is_file()
        p = json.loads(prov.read_text())
        assert p["schema_id"] == "report" and p["sha256"]

    # xlsx opens as a real workbook
    import openpyxl

    wb = openpyxl.load_workbook(ws / "out.xlsx")
    assert wb.sheetnames
    wb.close()


async def test_render_chart(vision_state: AppState, tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = make_ctx(vision_state, ws)
    result = await vision_state.tools.runtime.execute(
        "render_chart",
        {
            "spec": {
                "type": "line",
                "title": "MTBF trend",
                "x_label": "quarter",
                "y_label": "hours",
                "series": [{"name": "P-3101A", "x": ["Q1", "Q2", "Q3"], "y": [1400, 1100, 900]}],
            },
            "out_path": "mtbf.png",
        },
        ctx,
    )
    assert result.ok
    assert (ws / "mtbf.png").stat().st_size > 1000


async def test_render_pid_review_docx(vision_state: AppState, tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = make_ctx(vision_state, ws)
    import json

    review = {
        "title": "P&ID 3-1201 Rev C Review",
        "drawing_number": "3-1201",
        "revision": "C",
        "equipment_count": 5,
        "instrument_count": 3,
        "coverage": 0.95,
        "findings": [
            {
                "severity": "high",
                "statement": "V-3110 has no PSV",
                "evidence": "rule psv_on_vessel",
            },
            {
                "severity": "high",
                "statement": "P-3101B discharge missing check valve",
                "evidence": "rule pump_discharge_check_valve",
            },
        ],
        "appendix": {"citations": [], "assumptions": [], "unverified_claims": []},
    }
    (ws / "review.json").write_text(json.dumps(review))
    result = await vision_state.tools.runtime.execute(
        "render_document",
        {
            "type": "docx",
            "schema_id": "pid_review",
            "data_json": "review.json",
            "out_path": "review.docx",
        },
        ctx,
    )
    assert result.ok, result.error
    assert (ws / "review.docx").stat().st_size > 0

    # verifier schema_valid check accepts it
    from yantra_server.render.service import RenderService

    service = RenderService(REPO / "templates")
    service.validate("pid_review", review)


def test_tiling_plan():
    from yantra_server.vision.tiling import CoverageMap, plan_tiles

    tiles = plan_tiles(3000, 2000, tile_size=1280, overlap=0.15)
    assert len(tiles) > 1
    coverage = CoverageMap(total_tiles=len(tiles))
    coverage.mark(0, 0)
    assert 0 < coverage.fraction() < 1.0
