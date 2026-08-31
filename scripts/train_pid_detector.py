"""Fine-tune RF-DETR on P&ID symbols (SPEC §11.2 step 4). Runs on a GPU host.

Training data = the public synthetic Dataset-P&ID plus the bundled generator's sheets
(each sheet ships a ground-truth graph with symbol bboxes, so labels are exact). Produces
weights the bundle places at models/rfdetr_pid.pth; without them the pipeline uses the
OpenCV heuristic detector + VLM grounding, so this script is optional for a working demo.

    python scripts/train_pid_detector.py --data <coco_dir> --epochs 30 --out models/rfdetr_pid.pth

This build machine has no GPU, so the script is authored and import-checked but not run here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))


def build_dataset_from_generator(out_dir: Path, sheets: int = 200) -> Path:
    """Emit a COCO-format dataset from the synthetic P&ID generator's ground truth."""
    from corpus.pid_gen import build_unit3_lpg_sheet

    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)
    categories = [
        "centrifugal_pump",
        "vessel",
        "heat_exchanger",
        "control_valve",
        "check_valve",
        "relief_valve",
        "gate_valve",
        "instrument_field",
        "instrument_dcs",
        "off_page_connector",
    ]
    cat_index = {name: i + 1 for i, name in enumerate(categories)}
    coco: dict = {
        "images": [],
        "annotations": [],
        "categories": [{"id": i, "name": n} for n, i in cat_index.items()],
    }
    ann_id = 1
    for s in range(sheets):
        sheet = build_unit3_lpg_sheet(seed_deviations=(s % 2 == 0))
        png = images_dir / f"sheet_{s:04d}.png"
        sheet.to_png(png)
        coco["images"].append(
            {"id": s, "file_name": png.name, "width": sheet.width * 2, "height": sheet.height * 2}
        )
        for node in sheet.nodes:
            if node.kind not in cat_index:
                continue
            x0, y0, x1, y1 = (v * 2 for v in node.bbox())
            coco["annotations"].append(
                {
                    "id": ann_id,
                    "image_id": s,
                    "category_id": cat_index[node.kind],
                    "bbox": [x0, y0, x1 - x0, y1 - y0],
                    "area": (x1 - x0) * (y1 - y0),
                    "iscrowd": 0,
                }
            )
            ann_id += 1
    (out_dir / "annotations.json").write_text(json.dumps(coco), encoding="utf-8")
    return out_dir


def train(data_dir: Path, epochs: int, out_path: Path) -> None:
    try:
        from rfdetr import RFDETRBase
    except ImportError:
        print("rfdetr not installed; `uv pip install rfdetr` on the GPU host", file=sys.stderr)
        raise SystemExit(2) from None
    model = RFDETRBase()
    model.train(
        dataset_dir=str(data_dir), epochs=epochs, batch_size=4, output_dir=str(out_path.parent)
    )
    print(f"trained weights under {out_path.parent}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the P&ID symbol detector")
    parser.add_argument("--data", type=Path, help="COCO dataset dir (omit to synthesize)")
    parser.add_argument(
        "--synthesize", type=Path, help="Generate a dataset here from the generator"
    )
    parser.add_argument("--sheets", type=int, default=200)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--out", type=Path, default=ROOT / "models" / "rfdetr_pid.pth")
    args = parser.parse_args()

    if args.synthesize:
        data = build_dataset_from_generator(args.synthesize, args.sheets)
        print(f"synthesized dataset at {data}")
        if not args.data:
            args.data = data
    if not args.data:
        parser.error("provide --data or --synthesize")
    train(args.data, args.epochs, args.out)


if __name__ == "__main__":
    main()
