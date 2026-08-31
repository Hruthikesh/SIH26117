"""Vision + P&ID tools (SPEC §9.2): view_image, crop_image, zoom_grid, ocr_image,
pid_analyze, pid_rules_check, annotate_image."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from yantra_server.tools.base import Tool, ToolContext, ToolResult


class ViewImageArgs(BaseModel):
    path: str
    region: list[int] | None = Field(default=None, description="[x, y, w, h] to view a sub-region")
    max_side: int = Field(default=1280, ge=256, le=4096)


class ViewImageTool(Tool):
    name = "view_image"
    description = (
        "Return an image (or a region of it) for the next model call, respecting the tiling policy."
    )
    Args = ViewImageArgs
    side_effects = "read"

    async def run(self, args: ViewImageArgs, ctx: ToolContext) -> ToolResult:
        from PIL import Image

        path = ctx.resolve_path(args.path)
        if not path.is_file():
            return ToolResult.fail(f"no such image: {args.path}")
        with Image.open(path) as opened:
            img = opened.convert("RGB")
            if args.region and len(args.region) == 4:
                x, y, w, h = args.region
                img = img.crop((x, y, x + w, y + h))
            scale = min(1.0, args.max_side / max(img.width, img.height))
            if scale < 1.0:
                img = img.resize((int(img.width * scale), int(img.height * scale)))
            out = ctx.workspace / ".yantra" / "views" / f"{path.stem}_view.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            img.save(out)
            dims = [img.width, img.height]
        artifact_id = ctx.state.artifacts.put_file(
            out, kind="image", mime="image/png", run_id=ctx.run_id
        )
        return ToolResult(
            summary=f"viewing {args.path} ({dims[0]}x{dims[1]})",
            data={"dims": dims, "region": args.region},
            images=[artifact_id],
        )


class CropImageArgs(BaseModel):
    path: str
    region: list[int] = Field(description="[x, y, w, h]")
    out_path: str


class CropImageTool(Tool):
    name = "crop_image"
    description = "Crop a region of an image to a new file."
    Args = CropImageArgs
    side_effects = "render"
    idempotent = False

    async def run(self, args: CropImageArgs, ctx: ToolContext) -> ToolResult:
        from PIL import Image

        path = ctx.resolve_path(args.path)
        out = ctx.resolve_path(args.out_path)
        if not path.is_file():
            return ToolResult.fail(f"no such image: {args.path}")
        x, y, w, h = args.region
        with Image.open(path) as img:
            img.convert("RGB").crop((x, y, x + w, y + h)).save(out)
        return ToolResult(summary=f"cropped → {args.out_path}", data={"path": args.out_path})


class ZoomGridArgs(BaseModel):
    path: str
    rows: int = Field(default=3, ge=1, le=8)
    cols: int = Field(default=3, ge=1, le=8)


class ZoomGridTool(Tool):
    name = "zoom_grid"
    description = "Split an image into numbered tiles for systematic inspection of large drawings."
    Args = ZoomGridArgs
    side_effects = "read"

    async def run(self, args: ZoomGridArgs, ctx: ToolContext) -> ToolResult:
        from yantra_server.vision.tiling import zoom_grid

        path = ctx.resolve_path(args.path)
        if not path.is_file():
            return ToolResult.fail(f"no such image: {args.path}")
        out_dir = ctx.workspace / ".yantra" / "tiles" / path.stem
        tiles = zoom_grid(path, args.rows, args.cols, out_dir)
        listing = "\n".join(
            f"tile {t['index']}: rows{t['row']},col{t['col']} → {t['path']}" for t in tiles
        )
        return ToolResult(
            summary=f"{len(tiles)} tiles ({args.rows}x{args.cols})",
            content=listing,
            data={"tiles": tiles},
        )


class OcrImageArgs(BaseModel):
    path: str
    mode: str = Field(default="text", description="text|layout|table")


class OcrImageTool(Tool):
    name = "ocr_image"
    description = (
        "Extract text from an image via OCR (PaddleOCR-VL when served, RapidOCR otherwise)."
    )
    Args = OcrImageArgs
    side_effects = "read"

    async def run(self, args: OcrImageArgs, ctx: ToolContext) -> ToolResult:
        from yantra_server.vision.ocr import OCREngine

        path = ctx.resolve_path(args.path)
        if not path.is_file():
            return ToolResult.fail(f"no such image: {args.path}")
        engine = OCREngine(ctx.state.gateway)
        boxes = await engine.ocr_via_gateway(path)
        text = "\n".join(b.text for b in boxes)
        if not text:
            return ToolResult(
                ok=True,
                summary="no text recognised (no OCR model served and RapidOCR not installed)",
                content="",
            )
        return ToolResult(
            summary=f"{len(boxes)} text boxes", content=text, data={"boxes": len(boxes)}
        )


class PidAnalyzeArgs(BaseModel):
    path: str
    legend_path: str | None = None


class PidAnalyzeTool(Tool):
    name = "pid_analyze"
    description = (
        "Analyse a P&ID: returns the equipment/instrument/line lists, control loops and a "
        "graph the model reasons over, plus an inspection coverage map."
    )
    Args = PidAnalyzeArgs
    side_effects = "read"

    async def run(self, args: PidAnalyzeArgs, ctx: ToolContext) -> ToolResult:
        from yantra_server.vision.pid.isa51 import TagPrefixMap
        from yantra_server.vision.pid.pipeline import PIDPipeline

        path = ctx.resolve_path(args.path)
        if not path.is_file():
            return ToolResult.fail(f"no such drawing: {args.path}")
        prefixes = TagPrefixMap.load(
            ctx.state.loaded.assets_dir / "knowledge" / "pid" / "tag_prefixes.yaml"
        )
        pipeline = PIDPipeline(ctx.state.gateway, ctx.state.config.paths.models_dir, prefixes)
        graph = await pipeline.analyze(path)
        graph_artifact = ctx.state.artifacts.put_json(
            graph.model_dump(mode="json"), kind="pid_graph", run_id=ctx.run_id, task_id=ctx.task_id
        )
        content = (
            f"Equipment ({len(graph.equipment_list())}): "
            + ", ".join(e["tag"] for e in graph.equipment_list())
            + f"\nInstruments ({len(graph.instrument_index())}): "
            + ", ".join(i["tag"] for i in graph.instrument_index())
            + f"\nLines ({len(graph.line_list())}): "
            + ", ".join(line["tag"] for line in graph.line_list())
            + "\nControl loops:\n"
            + "\n".join(f"  {loop.narrative}" for loop in graph.control_loops)
        )
        return ToolResult(
            summary=f"{len(graph.nodes)} elements, {len(graph.edges)} connections, coverage {graph.coverage:.0%}",
            content=content,
            data={
                "graph_ref": graph_artifact,
                "equipment": graph.equipment_list(),
                "instruments": graph.instrument_index(),
                "lines": graph.line_list(),
                "coverage": graph.coverage,
            },
        )


class PidRulesCheckArgs(BaseModel):
    graph_ref: str = Field(description="graph_ref returned by pid_analyze")
    rulepack: str = Field(default="knowledge/pid/rules.yaml")
    equipment_list: list[str] = Field(default_factory=list)


class PidRulesCheckTool(Tool):
    name = "pid_rules_check"
    description = "Run the design-rule pack over a P&ID graph and return findings with rule ids."
    Args = PidRulesCheckArgs
    side_effects = "read"

    async def run(self, args: PidRulesCheckArgs, ctx: ToolContext) -> ToolResult:
        from yantra_server.vision.pid.graph import PIDGraph
        from yantra_server.vision.pid.rules import RuleEngine, load_rulepack

        try:
            graph_data = ctx.state.artifacts.read_bytes(args.graph_ref)
        except Exception:
            return ToolResult.fail(f"no such graph_ref: {args.graph_ref}")
        import json

        graph = PIDGraph.model_validate(json.loads(graph_data))
        rulepack_path = Path(args.rulepack)
        if not rulepack_path.is_absolute():
            rulepack_path = ctx.state.loaded.assets_dir / args.rulepack
        if not rulepack_path.is_file():
            return ToolResult.fail(f"rulepack not found: {args.rulepack}")
        engine = RuleEngine(load_rulepack(rulepack_path), set(args.equipment_list))
        findings = engine.check(graph)
        content = "\n".join(
            f"[{f.severity}] {f.rule_id}: {f.explanation} ({f.standard})" for f in findings
        )
        return ToolResult(
            summary=f"{len(findings)} finding(s)",
            content=content or "(no rule violations found)",
            data={"findings": [f.to_dict() for f in findings]},
        )


class AnnotateImageArgs(BaseModel):
    path: str
    graph_ref: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    out_path: str


class AnnotateImageTool(Tool):
    name = "annotate_image"
    description = "Overlay node boxes and finding highlights on a P&ID and save the annotated PNG."
    Args = AnnotateImageArgs
    side_effects = "render"
    idempotent = False

    async def run(self, args: AnnotateImageArgs, ctx: ToolContext) -> ToolResult:
        import json

        from yantra_server.vision.pid.annotate import annotate_pid
        from yantra_server.vision.pid.graph import PIDGraph

        path = ctx.resolve_path(args.path)
        out = ctx.resolve_path(args.out_path)
        try:
            graph = PIDGraph.model_validate(
                json.loads(ctx.state.artifacts.read_bytes(args.graph_ref))
            )
        except Exception:
            return ToolResult.fail(f"no such graph_ref: {args.graph_ref}")
        annotate_pid(path, graph, args.findings, out)
        artifact_id = ctx.state.artifacts.put_file(
            out, kind="image", mime="image/png", run_id=ctx.run_id
        )
        return ToolResult(
            summary=f"annotated → {args.out_path}",
            data={"path": args.out_path},
            images=[artifact_id],
        )


def register_vision_tools(registry: Any) -> None:
    for tool in (
        ViewImageTool(),
        CropImageTool(),
        ZoomGridTool(),
        OcrImageTool(),
        PidAnalyzeTool(),
        PidRulesCheckTool(),
        AnnotateImageTool(),
    ):
        if registry.get(tool.name) is None:
            registry.register(tool)
