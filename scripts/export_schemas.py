"""Write templates/schemas/<id>.json from the render Pydantic models (SPEC §12).

Committed so verifier schema_valid checks and validate_deliverable work offline without
re-deriving them. Regenerate after changing render/schemas.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from yantra_server.gateway.structured import inline_refs  # noqa: E402
from yantra_server.render.schemas import SCHEMA_MODELS  # noqa: E402


def main() -> None:
    out_dir = ROOT / "templates" / "schemas"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for schema_id, model in SCHEMA_MODELS.items():
        schema = inline_refs(model.model_json_schema())
        (out_dir / f"{schema_id}.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
        written += 1
    # Also emit the P&ID graph schema.
    from yantra_server.vision.pid.graph import PIDGraph

    (out_dir / "pid_graph.json").write_text(
        json.dumps(inline_refs(PIDGraph.model_json_schema()), indent=2), encoding="utf-8"
    )
    print(f"wrote {written + 1} schemas to {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
