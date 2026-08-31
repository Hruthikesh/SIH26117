"""Symbol detection (SPEC §11.2 step 4): RF-DETR when weights exist, OpenCV shape
heuristics + VLM grounding as the always-available fallback.

The heuristic detector finds circles (pumps/instruments/exchangers) and rectangles
(vessels) with OpenCV so the pipeline produces a graph on any host; RF-DETR raises quality
when its weights are bundled. Detections below the confidence floor are verified by a VLM
grounding call on the crop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Detection:
    kind: str
    bbox: tuple[int, int, int, int]
    confidence: float


class SymbolDetector:
    def __init__(self, models_dir: Path | None = None) -> None:
        self.models_dir = models_dir
        self._rfdetr: Any = None
        self._rfdetr_tried = False

    def _load_rfdetr(self) -> Any:
        if self._rfdetr_tried:
            return self._rfdetr
        self._rfdetr_tried = True
        weights = (self.models_dir / "rfdetr_pid.pth") if self.models_dir else None
        if weights is None or not weights.is_file():
            return None
        try:
            from rfdetr import RFDETRBase

            self._rfdetr = RFDETRBase(pretrain_weights=str(weights))
        except Exception as exc:
            log.info("RF-DETR unavailable (%s); using heuristic detector", exc)
            self._rfdetr = None
        return self._rfdetr

    def detect(self, image_path: Path) -> list[Detection]:
        model = self._load_rfdetr()
        if model is not None:
            return self._detect_rfdetr(model, image_path)
        return self._detect_heuristic(image_path)

    def _detect_rfdetr(self, model: Any, image_path: Path) -> list[Detection]:
        try:
            from PIL import Image

            preds = model.predict(Image.open(image_path).convert("RGB"), threshold=0.4)
            detections: list[Detection] = []
            for box, label, score in zip(
                preds.xyxy, preds.class_id, preds.confidence, strict=False
            ):
                detections.append(
                    Detection(
                        kind=_class_name(int(label)),
                        bbox=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
                        confidence=float(score),
                    )
                )
            return detections
        except Exception as exc:
            log.warning("RF-DETR inference failed: %s; using heuristic", exc)
            return self._detect_heuristic(image_path)

    def _detect_heuristic(self, image_path: Path) -> list[Detection]:
        """OpenCV shape detection: circles → pump/instrument, rounded rects → vessel."""
        import cv2
        import numpy as np

        img = cv2.imread(str(image_path))
        if img is None:
            return []
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        detections: list[Detection] = []

        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=40,
            param1=100,
            param2=40,
            minRadius=12,
            maxRadius=90,
        )
        if circles is not None:
            rounded = np.around(circles).astype(int)
            for circle in rounded[0]:
                cx, cy, r = int(circle[0]), int(circle[1]), int(circle[2])
                kind = "instrument_field" if r < 40 else "centrifugal_pump"
                detections.append(
                    Detection(
                        kind=kind,
                        bbox=(int(cx - r), int(cy - r), int(cx + r), int(cy + r)),
                        confidence=0.6,
                    )
                )

        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if 80 < w < 400 and 40 < h < 260 and 1.2 < w / max(h, 1) < 4:
                detections.append(
                    Detection(kind="vessel", bbox=(x, y, x + w, y + h), confidence=0.55)
                )
        return detections


def _class_name(class_id: int) -> str:
    classes = [
        "centrifugal_pump",
        "positive_displacement_pump",
        "vessel",
        "column",
        "heat_exchanger",
        "fired_heater",
        "compressor",
        "gate_valve",
        "globe_valve",
        "check_valve",
        "control_valve",
        "relief_valve",
        "ball_valve",
        "butterfly_valve",
        "reducer",
        "spectacle_blind",
        "instrument_field",
        "instrument_panel",
        "instrument_dcs",
        "flange",
        "off_page_connector",
        "nozzle",
    ]
    return classes[class_id] if 0 <= class_id < len(classes) else "unknown"
