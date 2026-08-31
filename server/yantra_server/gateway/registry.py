"""Model registry (SPEC §7.4): manifests, inspection, the 120B cap, DB mirror."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from yantra_server.db.base import Database
from yantra_server.db.models import ModelRow

log = logging.getLogger(__name__)

PARAM_CAP_B = 120.0

Capability = str  # chat|tools|json|vision|reasoning|code|long_context|embed|rerank|ocr


class ModelManifest(BaseModel):
    model_config = ConfigDict(extra="allow")  # embedding_dim, mrl_dims, notes...

    id: str
    family: str | None = None
    path: str
    engine: str  # vllm | llamacpp | pooling | mock
    params_b: float = 0.0
    license: str | None = None
    capabilities: list[Capability] = Field(default_factory=list)
    context_len: int = 0
    serve_context_len: int = 0
    vram_gb: float = 0.0
    quant: str | None = None
    roles: list[str] = Field(default_factory=list)
    serve_args: list[str] = Field(default_factory=list)
    prompt_template: str | None = None
    probes: dict[str, Any] = Field(default_factory=dict)

    def resolved_path(self, models_dir: Path) -> Path:
        p = Path(self.path)
        return p if p.is_absolute() else models_dir / p


class RegistryError(Exception):
    pass


class LargeModelRefused(RegistryError):
    def __init__(self, model_id: str, params_b: float) -> None:
        super().__init__(
            f"{model_id}: {params_b:.0f}B parameters is at/over the {PARAM_CAP_B:.0f}B cap; "
            "pass --allow-large to register anyway (the decision is audited)"
        )


class ModelRegistry:
    def __init__(
        self, registry_file: Path, models_dir: Path, *, local_file: Path | None = None
    ) -> None:
        self.registry_file = registry_file
        self.models_dir = models_dir
        # Machine-local registrations (one-click integrations) overlay the shipped registry
        # so the checked-in defaults stay pristine; local entries win on id collision.
        self.local_file = local_file
        self._manifests: dict[str, ModelManifest] = {}
        self._local_ids: set[str] = set()
        self.load()

    def load(self) -> None:
        self._manifests.clear()
        self._local_ids.clear()
        if self.registry_file.is_file():
            for entry in self._read_list(self.registry_file):
                manifest = ModelManifest.model_validate(entry)
                self._manifests[manifest.id] = manifest
        else:
            log.warning("model registry %s missing; starting empty", self.registry_file)
        if self.local_file is not None and self.local_file.is_file():
            for entry in self._read_list(self.local_file):
                manifest = ModelManifest.model_validate(entry)
                self._manifests[manifest.id] = manifest
                self._local_ids.add(manifest.id)

    @staticmethod
    def _read_list(path: Path) -> list[Any]:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(raw, list):
            raise RegistryError(f"{path} must be a YAML list of manifests")
        return raw

    def save(self) -> None:
        shipped = [
            m.model_dump(mode="json", exclude_none=True)
            for m in self._manifests.values()
            if m.id not in self._local_ids
        ]
        self.registry_file.write_text(
            "# Model registry (SPEC §7.4). Managed by `yantra models add|remove|probe`.\n"
            + yaml.safe_dump(shipped, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        if self.local_file is not None:
            local = [
                m.model_dump(mode="json", exclude_none=True)
                for m in self._manifests.values()
                if m.id in self._local_ids
            ]
            self.local_file.parent.mkdir(parents=True, exist_ok=True)
            self.local_file.write_text(
                "# Machine-local models (one-click integrations); overlays the shipped registry.\n"
                + yaml.safe_dump(local, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

    def all(self) -> list[ModelManifest]:
        return list(self._manifests.values())

    def get(self, model_id: str) -> ModelManifest | None:
        return self._manifests.get(model_id)

    def register(
        self, manifest: ModelManifest, *, allow_large: bool = False, local: bool = False
    ) -> None:
        if manifest.params_b >= PARAM_CAP_B and not allow_large:
            raise LargeModelRefused(manifest.id, manifest.params_b)
        self._manifests[manifest.id] = manifest
        if local and self.local_file is not None:
            self._local_ids.add(manifest.id)

    def remove(self, model_id: str) -> bool:
        self._local_ids.discard(model_id)
        return self._manifests.pop(model_id, None) is not None

    def set_probes(self, model_id: str, probes: dict[str, Any]) -> None:
        manifest = self._manifests.get(model_id)
        if manifest is None:
            raise RegistryError(f"unknown model {model_id}")
        manifest.probes.update(probes)

    def sync_to_db(self, db: Database) -> None:
        with db.session() as s:
            for m in self._manifests.values():
                extras = m.model_dump(mode="json")
                s.merge(
                    ModelRow(
                        id=m.id,
                        family=m.family,
                        path=m.path,
                        engine=m.engine,
                        params_b=m.params_b,
                        license=m.license,
                        capabilities=list(m.capabilities),
                        context_len=m.context_len,
                        serve_context_len=m.serve_context_len,
                        vram_gb=m.vram_gb,
                        quant=m.quant,
                        roles=list(m.roles),
                        serve_args=list(m.serve_args),
                        probes=dict(m.probes),
                        status=str(extras.get("status", "registered")),
                    )
                )


# ------------------------------------------------------------------ inspection


def is_gguf_file(path: Path) -> bool:
    """A GGUF file by extension or magic — Ollama stores GGUFs as extensionless blobs."""
    if not path.is_file():
        return False
    if path.suffix == ".gguf":
        return True
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"GGUF"
    except OSError:
        return False


def inspect_model_path(path: Path) -> ModelManifest:
    """Infer a manifest from a local model directory (HF layout) or a GGUF file."""
    path = path.expanduser()
    if not path.exists():
        raise RegistryError(f"model path does not exist: {path}")
    if is_gguf_file(path):
        return _inspect_gguf(path)
    if (path / "config.json").is_file():
        return _inspect_hf_dir(path)
    ggufs = sorted(path.glob("*.gguf")) if path.is_dir() else []
    if ggufs:
        return _inspect_gguf(ggufs[0])
    raise RegistryError(f"{path}: neither an HF model directory (config.json) nor a GGUF file")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", name.lower()).strip("-")


def _inspect_gguf(path: Path) -> ModelManifest:
    from .gguf import read_gguf_metadata

    meta = read_gguf_metadata(path, wanted_prefixes=())
    params = float(meta.get("general.parameter_count", 0)) / 1e9
    if params <= 0:  # older GGUFs: estimate from file size and quant ~4.5 bit/param
        params = path.stat().st_size / (4.5 / 8) / 1e9
    arch = str(meta.get("general.architecture", ""))
    name = str(meta.get("general.name", "") or path.stem)
    ctx = int(meta.get(f"{arch}.context_length", 0)) if arch else 0
    capabilities = ["chat", "json"]
    if "clip" in arch or "vl" in name.lower():
        capabilities.append("vision")
    return ModelManifest(
        id=_slug(name) + "-gguf",
        family=_slug(arch or name.split("-")[0]),
        path=str(path),
        engine="llamacpp",
        params_b=round(params, 2),
        license=str(meta.get("general.license", "")) or None,
        capabilities=capabilities,
        context_len=ctx,
        serve_context_len=min(ctx, 16384) if ctx else 8192,
        vram_gb=0.0,
        quant=str(meta.get("general.file_type", "")) or "gguf",
        roles=[],
    )


def _inspect_hf_dir(path: Path) -> ModelManifest:
    config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    arch = (config.get("architectures") or [""])[0]
    model_type = str(config.get("model_type", ""))
    params_b = _estimate_params_b(path, config)
    capabilities: list[str] = ["chat", "json", "tools"]
    if "vision_config" in config or "VL" in arch or "vl" in model_type:
        capabilities.append("vision")
    if any(token in arch.lower() for token in ("embed",)):
        capabilities = ["embed"]
    if "rerank" in path.name.lower() or "reranker" in arch.lower():
        capabilities = ["rerank"]
    ctx = int(
        config.get("max_position_embeddings")
        or config.get("text_config", {}).get("max_position_embeddings", 0)
        or 0
    )
    quant_config = config.get("quantization_config", {})
    quant = str(quant_config.get("quant_method", "")) or (
        "fp8" if "fp8" in path.name.lower() else "bf16"
    )
    engine = "pooling" if capabilities in (["embed"], ["rerank"]) else "vllm"
    return ModelManifest(
        id=_slug(path.name),
        family=_slug(model_type or arch or path.name.split("-")[0]),
        path=str(path),
        engine=engine,
        params_b=round(params_b, 2),
        license=None,
        capabilities=capabilities,
        context_len=ctx,
        serve_context_len=min(ctx, 131072) if ctx else 32768,
        vram_gb=round(params_b * _bytes_per_param(quant) + 4, 1),
        quant=quant,
        roles=[],
    )


def _bytes_per_param(quant: str) -> float:
    quant = quant.lower()
    if "int4" in quant or "awq" in quant or "gptq" in quant or "nvfp4" in quant or "mxfp4" in quant:
        return 0.55
    if "fp8" in quant or "int8" in quant:
        return 1.05
    return 2.1  # bf16 + overhead


def _estimate_params_b(path: Path, config: dict[str, Any]) -> float:
    if isinstance(config.get("num_parameters"), int | float):
        return float(config["num_parameters"]) / 1e9
    index = path / "model.safetensors.index.json"
    if index.is_file():
        total = json.loads(index.read_text(encoding="utf-8")).get("metadata", {}).get("total_size")
        if total:
            quant = str(config.get("quantization_config", {}).get("quant_method", "")) or (
                "fp8" if "fp8" in path.name.lower() else "bf16"
            )
            divisor = {"fp8": 1.0, "int8": 1.0}.get(quant, 2.0)
            if "4" in quant:
                divisor = 0.5
            return float(total) / divisor / 1e9
    hidden = int(config.get("hidden_size", 0))
    layers = int(config.get("num_hidden_layers", 0))
    inter = int(config.get("intermediate_size", hidden * 4))
    vocab = int(config.get("vocab_size", 32000))
    if hidden and layers:
        per_layer = 4 * hidden * hidden + 3 * hidden * inter
        return (layers * per_layer + 2 * vocab * hidden) / 1e9
    return 0.0
