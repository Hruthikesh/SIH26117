"""RenderService (SPEC §12): validate deliverable JSON, render to the requested format,
write a provenance sidecar. Fonts are bundled; rendering is hermetic."""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .schemas import SCHEMA_MODELS


class RenderError(Exception):
    pass


class RenderService:
    def __init__(self, templates_dir: Path, libreoffice_path: Path | None = None) -> None:
        self.templates_dir = templates_dir
        self.libreoffice = str(libreoffice_path) if libreoffice_path else shutil.which("soffice")

    # ------------------------------------------------------------- validation

    def validate(self, schema_id: str, data: dict[str, Any]) -> Any:
        model = SCHEMA_MODELS.get(schema_id)
        if model is None:
            raise RenderError(f"unknown schema_id {schema_id!r}")
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise RenderError(f"deliverable does not match schema {schema_id}: {exc}") from exc

    # ------------------------------------------------------------- entry

    def render(
        self,
        *,
        doc_type: str,
        schema_id: str,
        data: dict[str, Any],
        out_path: Path,
        template_id: str = "house",
        provenance: dict[str, Any] | None = None,
    ) -> Path:
        obj = self.validate(schema_id, data)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if doc_type == "docx":
            self._render_docx(schema_id, obj, out_path)
        elif doc_type == "xlsx":
            self._render_xlsx(schema_id, obj, out_path)
        elif doc_type == "pptx":
            self._render_pptx(obj, out_path)
        elif doc_type == "md":
            self._render_md(schema_id, obj, out_path)
        elif doc_type == "pdf":
            self._render_pdf(schema_id, obj, out_path)
        else:
            raise RenderError(f"unsupported deliverable type {doc_type!r}")
        self._write_provenance(out_path, schema_id, template_id, provenance or {})
        return out_path

    def _write_provenance(
        self, out_path: Path, schema_id: str, template_id: str, provenance: dict[str, Any]
    ) -> None:
        sidecar = out_path.with_suffix(out_path.suffix + ".provenance.json")
        payload = {
            "artifact": out_path.name,
            "schema_id": schema_id,
            "template_id": template_id,
            "rendered_at": provenance.get("rendered_at", datetime.now(UTC).isoformat()),
            "run_id": provenance.get("run_id"),
            "task_id": provenance.get("task_id"),
            "model_ids": provenance.get("model_ids", []),
            "source_document_hashes": provenance.get("source_document_hashes", []),
            "audit_head": provenance.get("audit_head"),
            "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
        }
        sidecar.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------- DOCX

    def _render_docx(self, schema_id: str, obj: Any, out_path: Path) -> None:
        import docx
        from docx.shared import Pt

        document = docx.Document()
        banner = document.add_paragraph()
        run = banner.add_run("CONFIDENTIAL - Engineering review required before use")
        run.bold = True
        run.font.size = Pt(9)

        title = getattr(obj, "title", "Document")
        document.add_heading(title, level=0)

        if schema_id in ("report", "inspection_summary", "meeting_minutes"):
            self._docx_report(document, obj)
        elif schema_id == "pid_review":
            self._docx_pid_review(document, obj)
        elif schema_id == "work_order_draft":
            self._docx_work_order(document, obj)
        elif schema_id == "email_draft":
            document.add_paragraph(f"To: {obj.to}")
            document.add_paragraph(f"Subject: {obj.subject}")
            document.add_paragraph(obj.body)
        elif schema_id == "code_change_summary":
            document.add_heading("Files", level=1)
            for f in obj.files:
                document.add_paragraph(f, style="List Bullet")
            document.add_heading("Rationale", level=1)
            document.add_paragraph(obj.rationale)
            document.add_heading("Tests", level=1)
            document.add_paragraph(obj.tests)
            if obj.risks:
                document.add_heading("Risks", level=1)
                for r in obj.risks:
                    document.add_paragraph(r, style="List Bullet")
        else:
            document.add_paragraph(json.dumps(obj.model_dump(), indent=2))
        document.save(str(out_path))

    def _docx_report(self, document: Any, obj: Any) -> None:
        if obj.executive_summary:
            document.add_heading("Executive summary", level=1)
            document.add_paragraph(obj.executive_summary)
        for section in obj.sections:
            document.add_heading(section.heading, level=1)
            for para in section.paragraphs:
                document.add_paragraph(para)
            for bullet in section.bullets:
                document.add_paragraph(bullet, style="List Bullet")
            for table in section.tables:
                self._docx_table(document, table)
            for figure in section.figures:
                self._docx_figure(document, figure)
        if obj.findings:
            document.add_heading("Findings", level=1)
            for i, finding in enumerate(obj.findings, 1):
                document.add_paragraph(f"{i}. [{finding.severity}] {finding.statement}")
                if finding.evidence:
                    document.add_paragraph(f"    Evidence: {finding.evidence}")
        if obj.recommendations:
            document.add_heading("Recommendations", level=1)
            for i, rec in enumerate(obj.recommendations, 1):
                document.add_paragraph(f"{i}. [{rec.priority}] {rec.text}")
        self._docx_appendix(document, obj.appendix)

    def _docx_pid_review(self, document: Any, obj: Any) -> None:
        document.add_paragraph(f"Drawing {obj.drawing_number} Rev {obj.revision}")
        document.add_paragraph(
            f"Equipment: {obj.equipment_count}  Instruments: {obj.instrument_count}  "
            f"Coverage: {obj.coverage:.0%}"
        )
        if obj.overlay_figure:
            self._docx_figure(
                document,
                type("F", (), {"path": obj.overlay_figure, "caption": "Annotated drawing"})(),
            )
        document.add_heading("Findings", level=1)
        for i, finding in enumerate(obj.findings, 1):
            document.add_paragraph(f"{i}. [{finding.severity}] {finding.statement}")
            if finding.evidence:
                document.add_paragraph(f"    {finding.evidence}")
        self._docx_appendix(document, obj.appendix)

    def _docx_work_order(self, document: Any, obj: Any) -> None:
        document.add_paragraph(f"Equipment: {obj.equipment}")
        document.add_paragraph(f"Priority: {obj.priority}")
        document.add_heading("Description", level=1)
        document.add_paragraph(obj.description)
        if obj.steps:
            document.add_heading("Steps", level=1)
            for i, step in enumerate(obj.steps, 1):
                document.add_paragraph(f"{i}. {step}")
        if obj.parts:
            document.add_heading("Parts", level=1)
            for part in obj.parts:
                document.add_paragraph(part, style="List Bullet")
        if obj.safety_notes:
            document.add_heading("Safety", level=1)
            for note in obj.safety_notes:
                document.add_paragraph(note, style="List Bullet")

    def _docx_table(self, document: Any, table: Any) -> None:
        if not table.columns:
            return
        t = document.add_table(rows=1, cols=len(table.columns))
        t.style = "Light Grid Accent 1"
        for i, col in enumerate(table.columns):
            t.rows[0].cells[i].text = str(col)
        for row in table.rows:
            cells = t.add_row().cells
            for i, value in enumerate(row[: len(table.columns)]):
                cells[i].text = str(value)
        if table.caption:
            document.add_paragraph(table.caption, style="Caption")

    def _docx_figure(self, document: Any, figure: Any) -> None:
        from docx.shared import Inches

        path = Path(figure.path)
        if path.is_file():
            try:
                document.add_picture(str(path), width=Inches(6))
            except Exception:
                document.add_paragraph(f"[figure: {figure.path}]")
        else:
            document.add_paragraph(f"[figure: {figure.path}]")
        if getattr(figure, "caption", ""):
            document.add_paragraph(figure.caption, style="Caption")

    def _docx_appendix(self, document: Any, appendix: Any) -> None:
        if appendix.citations:
            document.add_heading("Sources", level=1)
            for citation in appendix.citations:
                document.add_paragraph(citation, style="List Bullet")
        if appendix.assumptions:
            document.add_heading("Assumptions", level=1)
            for assumption in appendix.assumptions:
                document.add_paragraph(assumption, style="List Bullet")
        if appendix.unverified_claims:
            document.add_heading("Unverified claims", level=1)
            for claim in appendix.unverified_claims:
                document.add_paragraph(claim, style="List Bullet")

    # ------------------------------------------------------------- XLSX

    def _render_xlsx(self, schema_id: str, obj: Any, out_path: Path) -> None:
        import openpyxl

        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        if schema_id in ("equipment_list", "instrument_index", "line_list"):
            for name, rows in [
                ("Equipment", obj.equipment),
                ("Instruments", obj.instruments),
                ("Lines", obj.lines),
                ("Loops", obj.loops),
                ("Findings", obj.findings),
            ]:
                self._xlsx_sheet(wb, name, rows)
        elif schema_id == "data_table":
            for i, sheet in enumerate(obj.sheets, 1):
                ws = wb.create_sheet(sheet.caption[:28] or f"Sheet{i}")
                ws.append(sheet.columns)
                for row in sheet.rows:
                    ws.append(row)
                ws.freeze_panes = "A2"
        else:
            ws = wb.create_sheet("Data")
            ws.append(["field", "value"])
            for key, value in obj.model_dump().items():
                ws.append(
                    [key, json.dumps(value) if isinstance(value, (list, dict)) else str(value)]
                )
        if not wb.sheetnames:
            wb.create_sheet("Empty")
        wb.save(str(out_path))

    def _xlsx_sheet(self, wb: Any, name: str, rows: list[dict[str, Any]]) -> None:
        ws = wb.create_sheet(name)
        if not rows:
            ws.append([name])
            return
        columns = list({key for row in rows for key in row})
        ws.append(columns)
        for row in rows:
            ws.append([str(row.get(col, "")) for col in columns])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    # ------------------------------------------------------------- PPTX

    def _render_pptx(self, obj: Any, out_path: Path) -> None:
        import pptx
        from pptx.util import Inches

        presentation = pptx.Presentation()
        title_layout = presentation.slide_layouts[0]
        slide = presentation.slides.add_slide(title_layout)
        slide.shapes.title.text = obj.title

        bullet_layout = presentation.slide_layouts[1]
        for spec in obj.slides:
            slide = presentation.slides.add_slide(bullet_layout)
            slide.shapes.title.text = spec.title
            body = slide.placeholders[1].text_frame
            body.clear()
            for i, bullet in enumerate(spec.bullets):
                para = body.paragraphs[0] if i == 0 else body.add_paragraph()
                para.text = bullet
            if spec.figure and Path(spec.figure).is_file():
                with contextlib.suppress(Exception):
                    slide.shapes.add_picture(spec.figure, Inches(5), Inches(1.5), width=Inches(4))
            if spec.notes:
                slide.notes_slide.notes_text_frame.text = spec.notes
        presentation.save(str(out_path))

    # ------------------------------------------------------------- MD / PDF

    def _render_md(self, schema_id: str, obj: Any, out_path: Path) -> None:
        out_path.write_text(self.to_markdown(schema_id, obj), encoding="utf-8")

    def to_markdown(self, schema_id: str, obj: Any) -> str:
        lines = [f"# {getattr(obj, 'title', 'Document')}", ""]
        if schema_id in ("report", "inspection_summary", "meeting_minutes", "pid_review"):
            if getattr(obj, "executive_summary", ""):
                lines += ["## Executive summary", obj.executive_summary, ""]
            for section in getattr(obj, "sections", []):
                lines += [f"## {section.heading}", *section.paragraphs, ""]
                lines += [f"- {b}" for b in section.bullets]
            for i, finding in enumerate(getattr(obj, "findings", []), 1):
                lines.append(f"{i}. **[{finding.severity}]** {finding.statement}")
            for rec in getattr(obj, "recommendations", []):
                lines.append(f"- [{rec.priority}] {rec.text}")
        elif schema_id == "work_order_draft":
            lines += [
                f"**Equipment:** {obj.equipment}",
                f"**Priority:** {obj.priority}",
                "",
                obj.description,
            ]
            lines += [f"{i}. {s}" for i, s in enumerate(obj.steps, 1)]
        elif schema_id == "email_draft":
            lines += [f"**To:** {obj.to}", f"**Subject:** {obj.subject}", "", obj.body]
        elif schema_id == "code_change_summary":
            lines += [
                "## Files",
                *[f"- {f}" for f in obj.files],
                "",
                "## Rationale",
                obj.rationale,
                "",
                "## Tests",
                obj.tests,
            ]
        else:
            lines.append("```json")
            lines.append(json.dumps(obj.model_dump(), indent=2))
            lines.append("```")
        appendix = getattr(obj, "appendix", None)
        if appendix and appendix.citations:
            lines += ["", "## Sources", *[f"- {c}" for c in appendix.citations]]
        return "\n".join(lines)

    def _render_pdf(self, schema_id: str, obj: Any, out_path: Path) -> None:
        # Prefer LibreOffice for fidelity; fall back to ReportLab (always available).
        if self.libreoffice:
            docx_tmp = out_path.with_suffix(".docx")
            self._render_docx(schema_id, obj, docx_tmp)
            try:
                subprocess.run(
                    [
                        self.libreoffice,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(out_path.parent),
                        str(docx_tmp),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
                produced = docx_tmp.with_suffix(".pdf")
                if produced != out_path and produced.is_file():
                    produced.replace(out_path)
                docx_tmp.unlink(missing_ok=True)
                if out_path.is_file():
                    return
            except (subprocess.SubprocessError, OSError):
                docx_tmp.unlink(missing_ok=True)
        self._render_pdf_reportlab(schema_id, obj, out_path)

    def _render_pdf_reportlab(self, schema_id: str, obj: Any, out_path: Path) -> None:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        styles = getSampleStyleSheet()
        story: list[Any] = []
        for line in self.to_markdown(schema_id, obj).splitlines():
            if not line.strip():
                story.append(Spacer(1, 6))
            elif line.startswith("# "):
                story.append(Paragraph(line[2:], styles["Title"]))
            elif line.startswith("## "):
                story.append(Paragraph(line[3:], styles["Heading2"]))
            else:
                story.append(Paragraph(_escape(line), styles["BodyText"]))
        SimpleDocTemplate(str(out_path), pagesize=A4).build(story)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
