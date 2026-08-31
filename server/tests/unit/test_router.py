from pathlib import Path

import pytest

from yantra_server.gateway.registry import ModelManifest, ModelRegistry
from yantra_server.gateway.router import (
    NoRouteAvailable,
    RouteNeed,
    Router,
    RoutingPolicy,
)

REPO = Path(__file__).resolve().parents[3]


def make_registry(tmp_path: Path) -> ModelRegistry:
    registry = ModelRegistry(tmp_path / "r.yaml", tmp_path)
    registry.register(
        ModelManifest(
            id="brain",
            path="p",
            engine="vllm",
            params_b=27,
            capabilities=["chat", "json", "vision", "tools"],
            serve_context_len=131072,
        )
    )
    registry.register(
        ModelManifest(
            id="small",
            path="p",
            engine="llamacpp",
            params_b=4,
            capabilities=["chat", "json"],
            serve_context_len=16384,
        )
    )
    registry.register(
        ModelManifest(
            id="big",
            path="p",
            engine="vllm",
            params_b=117,
            capabilities=["chat", "json", "tools"],
            serve_context_len=131072,
        )
    )
    registry.register(
        ModelManifest(
            id="mock",
            path="-",
            engine="mock",
            params_b=0,
            capabilities=["chat", "json", "vision"],
            serve_context_len=10**6,
        )
    )
    return registry


POLICY = RoutingPolicy.model_validate(
    {
        "roles": {
            "executor": ["brain", "small", "mock"],
            "utility": ["small", "mock"],
            "heavy": ["big", "brain", "mock"],
        },
        "effort": {"executor": "low", "utility": "low"},
        "escalation": [
            {"action": "raise_effort", "to": "high"},
            {"action": "best_of_n", "n": 3, "select_with": "reviewer"},
            {"action": "switch_role", "to": "heavy"},
            {"action": "replan"},
        ],
        "difficulty": {"start_rung": {"hard": 1, "extreme": 2}},
    }
)


def test_first_available_wins(tmp_path: Path) -> None:
    router = Router(POLICY, make_registry(tmp_path), lambda m: True)
    decision = router.route(RouteNeed(role="executor"))
    assert decision.model == "brain"
    assert decision.effort == "low"
    assert decision.rejected == []


def test_health_filtering_with_reasons(tmp_path: Path) -> None:
    router = Router(POLICY, make_registry(tmp_path), lambda m: m == "small")
    decision = router.route(RouteNeed(role="executor"))
    assert decision.model == "small"
    assert decision.rejected[0].model == "brain"
    assert "healthy" in decision.rejected[0].reason


def test_vision_capability_filter(tmp_path: Path) -> None:
    router = Router(POLICY, make_registry(tmp_path), lambda m: m == "small")
    with pytest.raises(NoRouteAvailable):
        router.route(RouteNeed(role="executor", needs_vision=True))


def test_context_length_filter(tmp_path: Path) -> None:
    router = Router(POLICY, make_registry(tmp_path), lambda m: True)
    decision = router.route(RouteNeed(role="executor", context_tokens=50_000))
    assert decision.model == "brain"
    rejected_models = {r.model for r in decision.rejected}
    assert "small" not in rejected_models  # brain won before small was considered


def test_ladder_raises_effort_then_switches_to_heavy(tmp_path: Path) -> None:
    router = Router(POLICY, make_registry(tmp_path), lambda m: True)
    rung1 = router.route(RouteNeed(role="executor", ladder_rung=1))
    assert rung1.model == "brain" and rung1.effort == "high"
    rung2 = router.route(RouteNeed(role="executor", ladder_rung=2))
    assert rung2.best_of_n == 3
    rung3 = router.route(RouteNeed(role="executor", ladder_rung=3))
    assert rung3.model == "big"
    assert "ladder→heavy" in rung3.reason


def test_difficulty_starts_up_the_ladder(tmp_path: Path) -> None:
    router = Router(POLICY, make_registry(tmp_path), lambda m: True)
    decision = router.route(RouteNeed(role="executor", difficulty="hard"))
    assert decision.ladder_rung == 1 and decision.effort == "high"


def test_mock_disallowed_when_sealed(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    sealed_router = Router(POLICY, registry, lambda m: m == "mock", allow_mock=False)
    with pytest.raises(NoRouteAvailable):
        sealed_router.route(RouteNeed(role="executor"))
    dev_router = Router(POLICY, registry, lambda m: m == "mock", allow_mock=True)
    assert dev_router.route(RouteNeed(role="executor")).model == "mock"


def test_bundled_routing_policy_parses() -> None:
    policy = RoutingPolicy.load(REPO / "models" / "routing.yaml")
    assert policy.roles["executor"][0] == "qwen3.8-27b-fp8"
    assert [r.action for r in policy.escalation] == [
        "raise_effort",
        "best_of_n",
        "switch_role",
        "replan",
    ]
