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


def test_unlisted_role_falls_back_to_best_available(tmp_path: Path) -> None:
    """A small installation: role has no listed candidate up -> strongest available model."""
    router = Router(POLICY, make_registry(tmp_path), lambda m: m in ("small", "brain"))
    decision = router.route(RouteNeed(role="reviewer"))  # role absent from POLICY
    assert decision.model == "brain"  # bigger of the two available
    assert "best-available" in decision.reason


def test_fallback_prefers_probe_scores(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    small = registry.get("small")
    assert small is not None
    small.probes.update({"json": "pass", "tools": "pass", "coding_score": 80})
    router = Router(POLICY, registry, lambda m: m in ("small", "brain"))
    decision = router.route(RouteNeed(role="reviewer"))
    assert decision.model == "small"  # probe evidence beats raw size


def test_fallback_uses_mock_only_when_allowed(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    sealed = Router(POLICY, registry, lambda m: m == "mock", allow_mock=False)
    with pytest.raises(NoRouteAvailable):
        sealed.route(RouteNeed(role="reviewer"))
    dev = Router(POLICY, registry, lambda m: m == "mock", allow_mock=True)
    assert dev.route(RouteNeed(role="reviewer")).model == "mock"


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


def test_assignments_policy_pick(tmp_path: Path) -> None:
    router = Router(POLICY, make_registry(tmp_path), lambda m: True)
    by_role = {a.role: a for a in router.current_assignments()}
    executor = by_role["executor"]
    assert executor.model_id == "brain"
    assert executor.source == "policy"
    assert executor.reason == "first available policy candidate"
    assert executor.probes_passed is None and executor.probes_total is None  # never probed


def test_assignments_fallback_pick_and_role_order(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    brain = registry.get("brain")
    assert brain is not None
    brain.roles = ["reviewer"]  # claimed by the model, absent from the policy
    brain.probes.update({"json": "pass", "tools": "fail", "coding_score": 80})
    router = Router(POLICY, registry, lambda m: m in ("brain", "small"))
    assignments = router.current_assignments()
    # planner/executor/reviewer/router/utility first, remaining roles alphabetically.
    assert [a.role for a in assignments] == ["executor", "reviewer", "utility", "heavy"]
    reviewer = next(a for a in assignments if a.role == "reviewer")
    assert reviewer.model_id == "brain"
    assert reviewer.source == "fallback"
    assert reviewer.reason == "best available model by probe evidence"
    assert reviewer.probes_passed == 1 and reviewer.probes_total == 2  # scores not counted


def test_assignments_none_when_nothing_can_serve(tmp_path: Path) -> None:
    router = Router(POLICY, make_registry(tmp_path), lambda m: False)
    assignments = router.current_assignments()
    assert assignments  # every policy role is still reported
    for assignment in assignments:
        assert assignment.model_id is None
        assert assignment.source == "none"
        assert assignment.probes_passed is None and assignment.probes_total is None


def test_assignments_match_live_routing(tmp_path: Path) -> None:
    """current_assignments must agree with what route() would actually do."""
    router = Router(POLICY, make_registry(tmp_path), lambda m: m == "small")
    by_role = {a.role: a for a in router.current_assignments()}
    assert by_role["executor"].model_id == router.route(RouteNeed(role="executor")).model
    assert by_role["heavy"].model_id == router.route(RouteNeed(role="heavy")).model
    assert by_role["heavy"].source == "fallback"  # big/brain down; small is unlisted for heavy


def test_bundled_routing_policy_parses() -> None:
    policy = RoutingPolicy.load(REPO / "models" / "routing.yaml")
    assert policy.roles["executor"][0] == "qwen3.8-27b-fp8"
    assert [r.action for r in policy.escalation] == [
        "raise_effort",
        "best_of_n",
        "switch_role",
        "replan",
    ]
