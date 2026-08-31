"""Deliverable + chart/diagram tools (SPEC §9.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from yantra_server.tools.base import Tool, ToolContext, ToolResult


class RenderDocumentArgs(BaseModel):
    type: Literal["docx", "xlsx", "pptx", "pdf", "md"]
    schema_id: str = Field(description="report|equipment_list|work_order_draft|pid_review|…")
    data_json: str = Field(description="Path to a JSON file, or inline JSON, matching the schema")
    out_path: str
    template_id: str = "house"


class RenderDocumentTool(Tool):
    name = "render_document"
    description = (
        "Render a validated deliverable JSON into DOCX/XLSX/PPTX/PDF/MD via a house template. "
        "You produce the JSON; the template does all formatting."
    )
    Args = RenderDocumentArgs
    side_effects = "render"
    idempotent = False

    async def run(self, args: RenderDocumentArgs, ctx: ToolContext) -> ToolResult:
        data = self._load_data(args.data_json, ctx)
        if data is None:
            return ToolResult.fail("data_json is neither a readable file nor valid inline JSON")
        service = _render_service(ctx)
        out_path = ctx.resolve_path(args.out_path)
        provenance = {
            "run_id": ctx.run_id,
            "task_id": ctx.task_id,
            "audit_head": (head.hash if (head := ctx.state.audit.head()) else None),
        }
        try:
            service.render(
                doc_type=args.type,
                schema_id=args.schema_id,
                data=data,
                out_path=out_path,
                template_id=args.template_id,
                provenance=provenance,
            )
        except Exception as exc:
            return ToolResult.fail(f"render failed: {exc}")
        return ToolResult(
            summary=f"rendered {args.out_path} ({args.type})",
            data={"path": args.out_path, "provenance": f"{args.out_path}.provenance.json"},
        )

    def _load_data(self, data_json: str, ctx: ToolContext) -> dict[str, Any] | None:
        stripped = data_json.strip()
        if stripped.startswith("{"):
            try:
                return dict(json.loads(stripped))
            except json.JSONDecodeError:
                return None
        try:
            path = ctx.resolve_path(data_json)
        except Exception:
            return None
        if path.is_file():
            try:
                return dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                return None
        return None


class ValidateDeliverableArgs(BaseModel):
    path: str
    schema_id: str


class ValidateDeliverableTool(Tool):
    name = "validate_deliverable"
    description = "Validate a deliverable JSON file against its schema before rendering."
    Args = ValidateDeliverableArgs
    side_effects = "read"

    async def run(self, args: ValidateDeliverableArgs, ctx: ToolContext) -> ToolResult:
        path = ctx.resolve_path(args.path)
        if not path.is_file():
            return ToolResult.fail(f"no such file: {args.path}")
        service = _render_service(ctx)
        try:
            service.validate(args.schema_id, json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            return ToolResult.fail(f"invalid: {exc}")
        return ToolResult(summary=f"{args.path} validates against {args.schema_id}")


class RenderChartArgs(BaseModel):
    spec: dict[str, Any] = Field(
        description="{type: line|bar|scatter, title, x_label, y_label, series: [{name, x, y}]}"
    )
    out_path: str


class RenderChartTool(Tool):
    name = "render_chart"
    description = "Render a chart spec (line/bar/scatter) to a PNG via matplotlib (house palette)."
    Args = RenderChartArgs
    side_effects = "render"
    idempotent = False

    async def run(self, args: RenderChartArgs, ctx: ToolContext) -> ToolResult:
        out_path = ctx.resolve_path(args.out_path)
        try:
            _render_chart(args.spec, out_path)
        except Exception as exc:
            return ToolResult.fail(f"chart render failed: {exc}")
        return ToolResult(summary=f"chart → {args.out_path}", data={"path": args.out_path})


class RenderDiagramArgs(BaseModel):
    dot: str = Field(description="Graphviz DOT source")
    out_path: str


class RenderDiagramTool(Tool):
    name = "render_diagram"
    description = (
        "Render a Graphviz DOT diagram to PNG (falls back to a text box if graphviz absent)."
    )
    Args = RenderDiagramArgs
    side_effects = "render"
    idempotent = False

    async def run(self, args: RenderDiagramArgs, ctx: ToolContext) -> ToolResult:
        import shutil

        out_path = ctx.resolve_path(args.out_path)
        dot_bin = shutil.which("dot")
        if dot_bin is None:
            return ToolResult.fail("graphviz 'dot' not installed on this host")
        import subprocess

        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [dot_bin, "-Tpng", "-o", str(out_path)],
                input=args.dot.encode(),
                check=True,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            return ToolResult.fail(f"dot failed: {exc}")
        return ToolResult(summary=f"diagram → {args.out_path}", data={"path": args.out_path})


class SpreadsheetReadArgs(BaseModel):
    path: str
    sheet: str | None = None
    max_rows: int = Field(default=200, ge=1, le=5000)


class SpreadsheetReadTool(Tool):
    name = "spreadsheet_read"
    description = "Read rows from an XLSX sheet as text."
    Args = SpreadsheetReadArgs
    side_effects = "read"

    async def run(self, args: SpreadsheetReadArgs, ctx: ToolContext) -> ToolResult:
        import openpyxl

        path = ctx.resolve_path(args.path)
        if not path.is_file():
            return ToolResult.fail(f"no such file: {args.path}")
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        ws = wb[args.sheet] if args.sheet and args.sheet in wb.sheetnames else wb.active
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(" | ".join("" if c is None else str(c) for c in row))
            if len(rows) >= args.max_rows:
                break
        wb.close()
        return ToolResult(
            summary=f"{len(rows)} rows from {ws.title}",
            content="\n".join(rows),
            data={"rows": len(rows), "sheet": ws.title},
        )


def _render_service(ctx: ToolContext) -> Any:
    from yantra_server.render.service import RenderService

    config = ctx.state.config
    templates = config.render.templates_dir
    if not templates.is_absolute():
        templates = ctx.state.loaded.assets_dir / templates
    return RenderService(templates, config.render.libreoffice_path)


def _render_chart(spec: dict[str, Any], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    palette = ["#1f6feb", "#238636", "#e3b341", "#a371f7", "#db6d28"]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    chart_type = spec.get("type", "line")
    for i, series in enumerate(spec.get("series", [])):
        color = palette[i % len(palette)]
        x = series.get("x", list(range(len(series.get("y", [])))))
        y = series.get("y", [])
        if chart_type == "bar":
            ax.bar([str(v) for v in x], y, label=series.get("name", ""), color=color)
        elif chart_type == "scatter":
            ax.scatter(x, y, label=series.get("name", ""), color=color)
        else:
            ax.plot(x, y, label=series.get("name", ""), color=color, marker="o")
    ax.set_title(spec.get("title", ""))
    ax.set_xlabel(spec.get("x_label", ""))
    ax.set_ylabel(spec.get("y_label", ""))
    if any(s.get("name") for s in spec.get("series", [])):
        ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def register_render_tools(registry: Any) -> None:
    for tool in (
        RenderDocumentTool(),
        ValidateDeliverableTool(),
        RenderChartTool(),
        RenderDiagramTool(),
        SpreadsheetReadTool(),
    ):
        if registry.get(tool.name) is None:
            registry.register(tool)
