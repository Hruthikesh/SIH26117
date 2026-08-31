#!/usr/bin/env python3
"""Fetch model weights on a CONNECTED machine (never the plant host) — SPEC §21.

This is the only file in the repository that knows hub identifiers. It downloads the
models a profile needs into --dest (default models/weights/), resumably, then writes
MODELS.sha256 so `install.sh` and `yantra seal verify` can check integrity offline.

Usage (connected machine):
    python scripts/fetch_models.py --profile standard --dest models/weights
    python scripts/fetch_models.py --model qwen3.8-27b-fp8 ...
    python scripts/fetch_models.py --verify --dest models/weights   # offline re-check

Requires `huggingface_hub` (pip install huggingface_hub) for downloads; --verify is
stdlib-only. Downloads are resumable — re-run after an interruption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

# registry `path` -> (hub repo, optional single filename for GGUF)
HUB: dict[str, tuple[str, str | None]] = {
    "Qwen3.8-27B": ("Qwen/Qwen3.8-27B", None),
    "Qwen3.8-27B-FP8": ("Qwen/Qwen3.8-27B-FP8", None),
    "Qwen3.8-27B-GPTQ-Int4": ("Qwen/Qwen3.8-27B-GPTQ-Int4", None),
    "Qwen3.6-27B-FP8": ("Qwen/Qwen3.6-27B-FP8", None),
    "Qwen3.5-9B-FP8": ("Qwen/Qwen3.5-9B-FP8", None),
    "Qwen3.5-4B-Q4_K_M.gguf": ("Qwen/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf"),
    "Qwen3.5-0.8B-Q4_K_M.gguf": ("Qwen/Qwen3.5-0.8B-GGUF", "Qwen3.5-0.8B-Q4_K_M.gguf"),
    "gpt-oss-120b": ("openai/gpt-oss-120b", None),
    "Mistral-Small-4-119B-NVFP4": ("mistralai/Mistral-Small-4-119B-NVFP4", None),
    "Qwen3-Embedding-0.6B": ("Qwen/Qwen3-Embedding-0.6B", None),
    "Qwen3-Embedding-0.6B-Q8_0.gguf": (
        "Qwen/Qwen3-Embedding-0.6B-GGUF",
        "Qwen3-Embedding-0.6B-Q8_0.gguf",
    ),
    "Qwen3-Embedding-4B": ("Qwen/Qwen3-Embedding-4B", None),
    "Qwen3-Reranker-0.6B": ("Qwen/Qwen3-Reranker-0.6B", None),
    "Qwen3-Reranker-0.6B-Q8_0.gguf": (
        "Qwen/Qwen3-Reranker-0.6B-GGUF",
        "Qwen3-Reranker-0.6B-Q8_0.gguf",
    ),
    "Qwen3-VL-Embedding-2B": ("Qwen/Qwen3-VL-Embedding-2B", None),
    "Qwen3-VL-Reranker-2B": ("Qwen/Qwen3-VL-Reranker-2B", None),
    "PaddleOCR-VL-1.6": ("PaddlePaddle/PaddleOCR-VL-1.6", None),
    "DeepSeek-OCR": ("deepseek-ai/DeepSeek-OCR", None),
}


def registry_paths() -> dict[str, str]:
    """model id -> local path (relative to models dir), from models/registry.yaml."""
    data = yaml.safe_load((REPO_ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    return {m["id"]: m["path"] for m in data if m.get("path") and m["path"] != "-"}


def models_for_profile(profile: str) -> list[str]:
    path = REPO_ROOT / "models" / "profiles" / f"{profile}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    wanted: list[str] = []
    for engine in data.get("engines", []):
        wanted += [m for m in [engine.get("model"), *engine.get("models", [])] if m]
    return list(dict.fromkeys(wanted))


def fetch(model_id: str, local_path: str, dest: Path) -> Path:
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError:
        sys.exit("huggingface_hub not installed - pip install huggingface_hub (connected machine)")
    if local_path not in HUB:
        sys.exit(f"no hub mapping for {model_id} (path {local_path}) - add it to HUB in this file")
    repo, filename = HUB[local_path]
    target = dest / local_path
    print(f"[fetch] {model_id}: {repo}" + (f" :: {filename}" if filename else ""))
    if filename:
        target.parent.mkdir(parents=True, exist_ok=True)
        got = hf_hub_download(repo_id=repo, filename=filename, local_dir=dest)
        Path(got).replace(target) if Path(got) != target else None
    else:
        snapshot_download(repo_id=repo, local_dir=target)
    return target


def sha256_tree(path: Path) -> dict[str, str]:
    """sha256 of every file under path (or the file itself), keyed by relative posix path."""
    sums: dict[str, str] = {}
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    base = path.parent if path.is_file() else path
    for f in files:
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        sums[f.relative_to(base).as_posix()] = h.hexdigest()
    return sums


def write_manifest(dest: Path, entries: dict[str, dict[str, str]]) -> None:
    manifest = dest / "MODELS.sha256"
    manifest.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[manifest] {manifest} ({sum(len(v) for v in entries.values())} files)")


def verify(dest: Path) -> int:
    manifest = dest / "MODELS.sha256"
    if not manifest.is_file():
        print("no MODELS.sha256 - nothing to verify", file=sys.stderr)
        return 2
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    bad = 0
    for model_path, files in entries.items():
        root = dest / model_path
        actual = sha256_tree(root) if root.exists() else {}
        for rel, want in files.items():
            got = actual.get(rel if root.is_dir() else Path(model_path).name)
            if root.is_file():
                got = next(iter(actual.values()), None)
            if got != want:
                print(f"MISMATCH {model_path}/{rel}: {got or 'missing'}", file=sys.stderr)
                bad += 1
    print("verify:", "OK" if bad == 0 else f"{bad} mismatched/missing file(s)")
    return 0 if bad == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="Fetch every model the profile needs")
    parser.add_argument(
        "--model", action="append", default=[], help="Fetch one model id (repeatable)"
    )
    parser.add_argument("--dest", type=Path, default=REPO_ROOT / "models" / "weights")
    parser.add_argument("--verify", action="store_true", help="Offline integrity check only")
    args = parser.parse_args()

    if args.verify:
        raise SystemExit(verify(args.dest))

    paths = registry_paths()
    wanted = list(args.model)
    if args.profile:
        wanted += models_for_profile(args.profile)
    wanted = [m for m in dict.fromkeys(wanted) if m in paths]
    if not wanted:
        parser.error("nothing to fetch - pass --profile or --model")

    args.dest.mkdir(parents=True, exist_ok=True)
    entries: dict[str, dict[str, str]] = {}
    manifest_file = args.dest / "MODELS.sha256"
    if manifest_file.is_file():
        entries = json.loads(manifest_file.read_text(encoding="utf-8"))
    for model_id in wanted:
        target = fetch(model_id, paths[model_id], args.dest)
        entries[paths[model_id]] = sha256_tree(target)
        write_manifest(args.dest, entries)  # after each model so an interrupt keeps progress
    print(f"done: {len(wanted)} model(s) under {args.dest}")


if __name__ == "__main__":
    main()
