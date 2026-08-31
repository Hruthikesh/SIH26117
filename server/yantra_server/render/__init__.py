"""Deliverable rendering (SPEC §12): schema-validated JSON → templates → files.

The model never formats — it produces JSON matching a schema and the renderers turn it into
DOCX/XLSX/PPTX/PDF/MD with a provenance sidecar.
"""

from .service import RenderError, RenderService

__all__ = ["RenderError", "RenderService"]
