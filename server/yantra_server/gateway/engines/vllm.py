"""vLLM engine: OpenAI-compatible dialect + vLLM structured_outputs request fields."""

from __future__ import annotations

from typing import Any

from yantra_server.gateway.structured import vllm_structured_fields

from .base import Capabilities, EngineChatRequest
from .openai_compat import OpenAICompatEngine


class VLLMEngine(OpenAICompatEngine):
    name = "vllm"

    def __init__(self, base_url: str, *, timeout_s: float = 300.0) -> None:
        super().__init__(
            base_url,
            timeout_s=timeout_s,
            capabilities=Capabilities(
                chat=True, embeddings=True, rerank=True, vision=True, tools=True, structured=True
            ),
        )

    def structured_fields(self, request: EngineChatRequest) -> dict[str, Any]:
        return vllm_structured_fields(request.constraint)

    def extra_chat_fields(self, request: EngineChatRequest) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        effort = request.decoding.reasoning_effort
        if effort is not None:
            # Qwen3-family reasoning effort; ignored by models without a reasoning parser.
            extra["chat_template_kwargs"] = {"reasoning_effort": effort}
            extra["reasoning_effort"] = effort
        return extra
