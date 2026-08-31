"""In-process embeddings/reranker fallback via sentence-transformers (SPEC §7.1).

Loaded lazily off the event loop; reports unhealthy with a clear reason when the optional
dependency or the model weights are absent, so the router can fall through.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .base import (
    Capabilities,
    ChatEvent,
    ContentDelta,
    Engine,
    EngineChatRequest,
    EngineError,
    EngineHealth,
)


class PoolingWorker(Engine):
    name = "pooling"

    def __init__(self, models_dir: Path, model_paths: dict[str, str], device: str = "cpu") -> None:
        self.models_dir = models_dir
        self.model_paths = model_paths  # model id -> relative/absolute path
        self.device = device
        self._embedders: dict[str, Any] = {}
        self._rankers: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._import_error: str | None = None

    def _resolve(self, model: str) -> Path:
        rel = self.model_paths.get(model, model)
        p = Path(rel)
        return p if p.is_absolute() else self.models_dir / rel

    def _load_embedder(self, model: str) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # optional extra not installed
            self._import_error = str(exc)
            raise EngineError(
                "pooling worker unavailable: install the 'pooling' extra (sentence-transformers)"
            ) from exc
        path = self._resolve(model)
        if not path.exists():
            raise EngineError(f"pooling model weights missing: {path}")
        return SentenceTransformer(str(path), device=self.device, local_files_only=True)

    def _load_ranker(self, model: str) -> Any:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            self._import_error = str(exc)
            raise EngineError(
                "pooling worker unavailable: install the 'pooling' extra (sentence-transformers)"
            ) from exc
        path = self._resolve(model)
        if not path.exists():
            raise EngineError(f"pooling model weights missing: {path}")
        return CrossEncoder(str(path), device=self.device, local_files_only=True)

    async def embed(
        self, model: str, texts: list[str], instruction: str | None = None
    ) -> list[list[float]]:
        async with self._lock:
            if model not in self._embedders:
                self._embedders[model] = await asyncio.to_thread(self._load_embedder, model)
        embedder = self._embedders[model]
        inputs = [f"{instruction}\n{t}" if instruction else t for t in texts]

        def encode() -> list[list[float]]:
            vectors = embedder.encode(inputs, normalize_embeddings=True, show_progress_bar=False)
            return [list(map(float, v)) for v in vectors]

        return await asyncio.to_thread(encode)

    async def rerank(self, model: str, query: str, documents: list[str]) -> list[float]:
        async with self._lock:
            if model not in self._rankers:
                self._rankers[model] = await asyncio.to_thread(self._load_ranker, model)
        ranker = self._rankers[model]

        def score() -> list[float]:
            pairs = [(query, doc) for doc in documents]
            return [float(s) for s in ranker.predict(pairs, show_progress_bar=False)]

        return await asyncio.to_thread(score)

    async def chat_stream(self, request: EngineChatRequest) -> AsyncIterator[ChatEvent]:
        raise EngineError("pooling worker serves embeddings/rerank only")
        yield ContentDelta(text="")  # type: ignore[unreachable]  # makes this an async generator

    async def health(self) -> EngineHealth:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return EngineHealth(ok=False, detail="sentence-transformers not installed")
        missing = [m for m in self.model_paths if not self._resolve(m).exists()]
        if missing and len(missing) == len(self.model_paths):
            return EngineHealth(ok=False, detail=f"no pooling model weights present ({missing})")
        return EngineHealth(
            ok=True, models=[m for m in self.model_paths if self._resolve(m).exists()]
        )

    def capabilities(self) -> Capabilities:
        return Capabilities(chat=False, embeddings=True, rerank=True)
