"""Deep disk discovery for /api/models/discover: model weights already on this machine.

Pure, depth-limited filesystem walks (no app state) so every piece unit-tests against a
temp tree: weight folders, user folders, LM Studio / GPT4All / Hugging Face / Ollama
stores, and bare drive roots.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .registry import is_gguf_file

WALK_MAX_DEPTH = 4
MAX_CANDIDATES = 300
PRUNED_DIR_NAMES = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "site-packages", "dist", "build"}
)
DRIVE_ROOTS: tuple[Path, ...] = (Path("C:/models"), Path("D:/models"))

# (path, display name, kind) where kind is "gguf" | "hf" | "hf-folder".
RawCandidate = tuple[Path, str, str]


def walk_candidate_paths(root: Path, *, max_depth: int = WALK_MAX_DEPTH) -> list[RawCandidate]:
    """Depth-limited walk under one root: magic-verified GGUF files and HF model dirs.

    Dot-entries and dirs named in PRUNED_DIR_NAMES are skipped; a dir carrying a
    config.json is ONE "hf" candidate and is not descended into."""
    found: list[RawCandidate] = []
    queue: list[tuple[Path, int]] = [(root, 0)]
    index = 0
    while index < len(queue):
        directory, depth = queue[index]
        index += 1
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if name.startswith(".") or name == "MODELS.sha256":
                continue
            try:
                if entry.is_dir():
                    if name in PRUNED_DIR_NAMES:
                        continue
                    if (entry / "config.json").is_file():
                        found.append((entry, name, "hf"))
                    elif depth + 1 < max_depth:
                        queue.append((entry, depth + 1))
                elif name.endswith(".gguf") and is_gguf_file(entry, require_magic=True):
                    found.append((entry, entry.stem, "gguf"))
            except OSError:
                continue
    return found


def hf_cache_candidates(hub_dir: Path) -> list[RawCandidate]:
    """Hugging Face cache: each models--*/snapshots/<hash> dir holding a config.json is
    ONE "hf-folder" candidate; loose GGUFs anywhere in the cache are picked up too."""
    found: list[RawCandidate] = []
    for model_dir in sorted(hub_dir.glob("models--*")):
        display = model_dir.name.removeprefix("models--").replace("--", "/")
        snapshots = model_dir / "snapshots"
        try:
            snaps = sorted(snapshots.iterdir()) if snapshots.is_dir() else []
        except OSError:
            continue
        for snap in snaps:
            if snap.is_dir() and (snap / "config.json").is_file():
                found.append((snap, display, "hf-folder"))
    try:
        ggufs = sorted(hub_dir.rglob("*.gguf"))
    except OSError:
        ggufs = []
    for gguf in ggufs:
        if is_gguf_file(gguf, require_magic=True):
            found.append((gguf, gguf.stem, "gguf"))
    return found


def ollama_candidates(store: Path) -> list[RawCandidate]:
    """Ollama store: follow each manifest's image.model layer to its extensionless blob
    (identified by the GGUF magic sniff, never by extension)."""
    found: list[RawCandidate] = []
    manifest_root = store / "manifests"
    if not manifest_root.is_dir():
        return found
    for mf in sorted(manifest_root.rglob("*")):
        if not mf.is_file():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            layer = next(
                layer
                for layer in data.get("layers", [])
                if str(layer.get("mediaType", "")).endswith("image.model")
            )
            digest = str(layer["digest"]).replace(":", "-")
            blob = store / "blobs" / digest
            if is_gguf_file(blob):  # extensionless: sniffs the magic bytes
                found.append((blob, f"{mf.parent.name}:{mf.name}", "gguf"))
        except (json.JSONDecodeError, UnicodeDecodeError, StopIteration, KeyError, OSError):
            continue
    return found


def discovery_roots(models_dir: Path, assets_dir: Path, home: Path) -> list[tuple[Path, str]]:
    """Generic walk roots with their source labels, in presentation order (existing or not).

    The Hugging Face cache and the Ollama store are NOT here: both need structure-aware
    scans (snapshots dirs, manifest-to-blob chasing) rather than the generic walk."""
    return [
        (models_dir, "weights folder"),
        (assets_dir / "models" / "weights", "weights folder"),
        (home / "Downloads", "downloads"),
        (home / "Desktop", "desktop"),
        (home / "Documents", "documents"),
        (home / ".lmstudio" / "models", "lm-studio"),
        (home / "AppData" / "Local" / "LM-Studio" / "models", "lm-studio"),
        (home / "AppData" / "Local" / "nomic.ai" / "GPT4All", "gpt4all"),
    ]


def discover_local_models(
    models_dir: Path,
    assets_dir: Path,
    registered_paths: set[str],
    *,
    home: Path | None = None,
    drive_roots: Sequence[Path] = DRIVE_ROOTS,
    max_total: int = MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Scan every root that exists; dedup by resolved path; largest-first within a source.

    registered_paths holds RESOLVED weight paths from the registry; a candidate whose
    resolved path matches one is flagged registered=True. Capped at max_total entries."""
    home = home or Path.home()
    roots = discovery_roots(models_dir, assets_dir, home)
    roots += [(p, "disk") for p in drive_roots]
    raw: list[tuple[Path, str, str, str]] = []
    seen_roots: set[str] = set()
    for root, source in roots:
        try:
            if not root.is_dir():
                continue
            root_key = str(root.resolve())
        except OSError:
            continue
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        raw += [(p, n, k, source) for p, n, k in walk_candidate_paths(root)]
    hub = home / ".cache" / "huggingface" / "hub"
    if hub.is_dir():
        raw += [(p, n, k, "hf-cache") for p, n, k in hf_cache_candidates(hub)]
    store = home / ".ollama" / "models"
    if store.is_dir():
        raw += [(p, n, k, "ollama") for p, n, k in ollama_candidates(store)]
    return _finalize(raw, registered_paths, max_total)


def _finalize(
    raw: list[tuple[Path, str, str, str]], registered_paths: set[str], max_total: int
) -> list[dict[str, Any]]:
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    seen: set[str] = set()
    for path, name, kind, source in raw:
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        size = _size_bytes(path)
        if size is None:
            continue
        entry = {
            "path": str(path),
            "name": name,
            "kind": kind,
            "source": source,
            "size_gb": round(size / 1e9, 2),
            "registered": resolved in registered_paths,
        }
        grouped.setdefault(source, []).append((size, entry))
    out: list[dict[str, Any]] = []
    for pairs in grouped.values():  # dict preserves first-appearance source order
        pairs.sort(key=lambda item: item[0], reverse=True)
        out += [entry for _size, entry in pairs]
    return out[:max_total]


def _size_bytes(path: Path) -> int | None:
    try:
        if path.is_file():
            return path.stat().st_size
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return None
