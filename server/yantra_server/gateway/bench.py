"""`yantra bench llm`: TTFT and tokens/s through the live gateway (SPEC §7.7)."""

from __future__ import annotations

import statistics
from typing import Any

from .engines.base import ChatMessage, Decoding
from .service import Gateway, ModelRequest

BENCH_PROMPTS = [
    "Explain, step by step, how a centrifugal pump mechanical seal flush plan 11 works.",
    "List ten common causes of premature mechanical seal failure in light hydrocarbon service.",
    "Write a short procedure for safely isolating a pressure vessel for internal inspection.",
]


async def bench_llm(
    gateway: Gateway, *, role: str = "executor", max_tokens: int = 384
) -> dict[str, Any]:
    runs: list[dict[str, float]] = []
    model = ""
    for prompt in BENCH_PROMPTS:
        result = await gateway.chat(
            ModelRequest(
                role=role,
                messages=[ChatMessage(role="user", content=prompt)],
                decoding=Decoding(temperature=0.7, max_tokens=max_tokens),  # sampling: no cache
                priority=0,
            )
        )
        model = result.result.model
        completion = result.result.usage.completion_tokens
        latency_s = result.result.latency_ms / 1000 or 1e-9
        runs.append(
            {
                "ttft_ms": result.result.ttft_ms or 0.0,
                "tokens_per_s": completion / latency_s,
                "completion_tokens": float(completion),
            }
        )
    return {
        "role": role,
        "model": model,
        "runs": runs,
        "ttft_ms_p50": round(statistics.median(r["ttft_ms"] for r in runs), 1),
        "tokens_per_s_p50": round(statistics.median(r["tokens_per_s"] for r in runs), 1),
    }
