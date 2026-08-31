import json
import struct
from pathlib import Path

import pytest

from yantra_server.gateway.gguf import read_gguf_metadata
from yantra_server.gateway.registry import (
    LargeModelRefused,
    ModelManifest,
    ModelRegistry,
    inspect_model_path,
)

REPO = Path(__file__).resolve().parents[3]


def test_bundled_registry_loads_and_all_under_cap() -> None:
    registry = ModelRegistry(REPO / "models" / "registry.yaml", Path("/opt/models"))
    manifests = registry.all()
    assert len(manifests) >= 15
    assert all(m.params_b < 120 for m in manifests)
    brain = registry.get("qwen3.8-27b-fp8")
    assert brain is not None and "vision" in brain.capabilities


def test_large_model_refused(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path / "reg.yaml", tmp_path)
    big = ModelManifest(id="huge", path="x", engine="vllm", params_b=122)
    with pytest.raises(LargeModelRefused):
        registry.register(big)
    registry.register(big, allow_large=True)
    assert registry.get("huge") is not None


def test_registry_save_roundtrip(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path / "reg.yaml", tmp_path)
    registry.register(
        ModelManifest(id="m1", path="p", engine="llamacpp", params_b=4, roles=["utility"])
    )
    registry.save()
    reloaded = ModelRegistry(tmp_path / "reg.yaml", tmp_path)
    manifest = reloaded.get("m1")
    assert manifest is not None and manifest.roles == ["utility"]


def _write_gguf(path: Path, kvs: list[tuple[str, int, bytes]]) -> None:
    """Handcraft a minimal GGUF header for tests: kvs are (key, type, encoded_value)."""
    blob = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", len(kvs))
    for key, vtype, encoded in kvs:
        kb = key.encode()
        blob += struct.pack("<Q", len(kb)) + kb + struct.pack("<I", vtype) + encoded
    path.write_bytes(blob)


def _gguf_str(s: str) -> bytes:
    b = s.encode()
    return struct.pack("<Q", len(b)) + b


def test_gguf_metadata_reader(tmp_path: Path) -> None:
    gguf = tmp_path / "tiny.gguf"
    _write_gguf(
        gguf,
        [
            ("general.architecture", 8, _gguf_str("qwen3")),
            ("general.name", 8, _gguf_str("Tiny Test 0.8B")),
            ("general.parameter_count", 10, struct.pack("<Q", 800_000_000)),
            ("qwen3.context_length", 4, struct.pack("<I", 32768)),
        ],
    )
    meta = read_gguf_metadata(gguf, wanted_prefixes=())
    assert meta["general.architecture"] == "qwen3"
    assert meta["general.parameter_count"] == 800_000_000
    assert meta["qwen3.context_length"] == 32768


def test_inspect_gguf(tmp_path: Path) -> None:
    gguf = tmp_path / "model.gguf"
    _write_gguf(
        gguf,
        [
            ("general.architecture", 8, _gguf_str("qwen3")),
            ("general.name", 8, _gguf_str("Tiny-0.8B")),
            ("general.parameter_count", 10, struct.pack("<Q", 800_000_000)),
            ("qwen3.context_length", 4, struct.pack("<I", 32768)),
        ],
    )
    manifest = inspect_model_path(gguf)
    assert manifest.engine == "llamacpp"
    assert manifest.params_b == pytest.approx(0.8)
    assert manifest.context_len == 32768


def test_inspect_hf_dir(tmp_path: Path) -> None:
    model_dir = tmp_path / "Test-Model-FP8"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen3ForCausalLM"],
                "model_type": "qwen3",
                "hidden_size": 1024,
                "num_hidden_layers": 4,
                "intermediate_size": 4096,
                "vocab_size": 32000,
                "max_position_embeddings": 65536,
            }
        )
    )
    manifest = inspect_model_path(model_dir)
    assert manifest.engine == "vllm"
    assert manifest.context_len == 65536
    assert manifest.quant == "fp8"  # inferred from dir name
    assert manifest.params_b > 0


def test_inspect_missing_path(tmp_path: Path) -> None:
    from yantra_server.gateway.registry import RegistryError

    with pytest.raises(RegistryError):
        inspect_model_path(tmp_path / "nope")
