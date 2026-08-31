import json
from pathlib import Path

from yantra_server.gateway.discovery import (
    discover_local_models,
    walk_candidate_paths,
)

GGUF_MAGIC_BLOB = b"GGUF" + b"\x00" * 28


def _make_gguf(path: Path, extra_bytes: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(GGUF_MAGIC_BLOB + b"\x00" * extra_bytes)


def test_walk_finds_magic_verified_ggufs_and_hf_dirs(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _make_gguf(root / "a" / "b" / "real.gguf")  # depth 3: found
    _make_gguf(root / "a" / "b" / "c" / "edge.gguf")  # depth 4: still inside the walk
    _make_gguf(root / "d1" / "d2" / "d3" / "d4" / "deep.gguf")  # depth 5: beyond the walk
    _make_gguf(root / "node_modules" / "dep.gguf")  # pruned dir name: skipped
    _make_gguf(root / ".hidden" / "dot.gguf")  # dot-entry: skipped
    fake = root / "fake.gguf"
    fake.write_bytes(b"not a gguf at all")  # right extension, wrong magic: skipped
    hf = root / "some-hf-model"
    hf.mkdir()
    (hf / "config.json").write_text("{}", encoding="utf-8")

    found = {(path.name, kind) for path, _name, kind in walk_candidate_paths(root)}
    assert ("real.gguf", "gguf") in found
    assert ("edge.gguf", "gguf") in found
    assert ("some-hf-model", "hf") in found
    assert {name for name, _ in found}.isdisjoint(
        {"deep.gguf", "dep.gguf", "dot.gguf", "fake.gguf"}
    )


def test_discover_sources_registered_dedup_and_size_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assets_dir = tmp_path / "assets"  # has no models/weights: silently skipped
    models_dir = home / "Downloads" / "models"  # nested under Downloads to exercise dedup
    _make_gguf(models_dir / "registered.gguf")
    _make_gguf(home / "Downloads" / "tiny.gguf")
    _make_gguf(home / "Downloads" / "big.gguf", extra_bytes=4096)
    _make_gguf(home / "Desktop" / "dropped.gguf")

    snap = home / ".cache" / "huggingface" / "hub" / "models--org--tiny" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")

    ollama = home / ".ollama" / "models"
    _make_gguf(ollama / "blobs" / "sha256-abc")  # extensionless blob, GGUF magic
    manifest_dir = ollama / "manifests" / "registry.ollama.ai" / "library" / "tinymodel"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "latest").write_text(
        json.dumps(
            {
                "layers": [
                    {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:abc"}
                ]
            }
        ),
        encoding="utf-8",
    )

    registered = {str((models_dir / "registered.gguf").resolve())}
    candidates = discover_local_models(
        models_dir, assets_dir, registered, home=home, drive_roots=()
    )

    assert all(
        set(c) == {"path", "name", "kind", "source", "size_gb", "registered"} for c in candidates
    )
    by_name = {c["name"]: c for c in candidates}
    assert by_name["registered"]["registered"] is True
    assert by_name["registered"]["source"] == "weights folder"
    assert sum(c["name"] == "registered" for c in candidates) == 1  # deduped across roots
    assert by_name["dropped"]["source"] == "desktop"
    assert by_name["org/tiny"] == {
        "path": str(snap),
        "name": "org/tiny",
        "kind": "hf-folder",
        "source": "hf-cache",
        "size_gb": 0.0,
        "registered": False,
    }
    assert by_name["tinymodel:latest"]["source"] == "ollama"
    assert by_name["tinymodel:latest"]["registered"] is False
    downloads = [c["name"] for c in candidates if c["source"] == "downloads"]
    assert downloads == ["big", "tiny"]  # largest first within a source
