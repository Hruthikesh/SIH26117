"""OCR (SPEC §11.2 step 3): PaddleOCR-VL via the gateway when served, RapidOCR CPU fallback.

Returns text boxes with rotation; the ISA-5.1 parser consumes the recognised strings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yantra_server.gateway.service import Gateway

log = logging.getLogger(__name__)


@dataclass
class TextBox:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float = 1.0
    rotation: float = 0.0


class OCREngine:
    """Best-available OCR: gateway OCR model → RapidOCR → none."""

    def __init__(self, gateway: Gateway | None = None) -> None:
        self.gateway = gateway
        self._rapid: Any = None
        self._rapid_tried = False

    def _rapidocr(self) -> Any:
        if not self._rapid_tried:
            self._rapid_tried = True
            try:
                from rapidocr_onnxruntime import RapidOCR

                self._rapid = RapidOCR()
            except ImportError:
                log.info("RapidOCR not installed; OCR falls back to the served OCR model only")
                self._rapid = None
        return self._rapid

    def ocr_image(self, path: Path) -> list[TextBox]:
        engine = self._rapidocr()
        if engine is None:
            return []
        try:
            result, _elapsed = engine(str(path))
        except Exception as exc:
            log.warning("RapidOCR failed on %s: %s", path, exc)
            return []
        boxes: list[TextBox] = []
        for entry in result or []:
            quad, text, score = entry
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            boxes.append(
                TextBox(
                    text=str(text),
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                    confidence=float(score),
                )
            )
        return boxes

    async def ocr_via_gateway(self, path: Path) -> list[TextBox]:
        """Structured OCR through the served OCR VLM (PaddleOCR-VL/DeepSeek-OCR)."""
        if self.gateway is None:
            return self.ocr_image(path)
        import base64

        from yantra_server.gateway.engines.base import ChatMessage, Decoding, ImagePart, TextPart
        from yantra_server.gateway.service import ModelRequest

        try:
            data = base64.b64encode(path.read_bytes()).decode()
            result = await self.gateway.chat(
                ModelRequest(
                    role="ocr",
                    messages=[
                        ChatMessage(
                            role="user",
                            content=[
                                TextPart(
                                    text="Transcribe all text in this image, one token per line."
                                ),
                                ImagePart(data_b64=data),
                            ],
                        )
                    ],
                    decoding=Decoding(temperature=0.0, max_tokens=2000),
                )
            )
            lines = str(result.parsed).splitlines()
            return [TextBox(text=line.strip(), bbox=(0, 0, 0, 0)) for line in lines if line.strip()]
        except Exception as exc:
            log.warning("gateway OCR failed, falling back to RapidOCR: %s", exc)
            return self.ocr_image(path)
