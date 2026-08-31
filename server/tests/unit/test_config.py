from pathlib import Path

import pytest

from yantra_server.config import ConfigError, effective_report, load_config


def test_defaults_load_without_any_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    loaded = load_config()
    assert loaded.config.profile == "lite"
    assert loaded.config.server.port == 7331
    assert loaded.config.permissions, "default permission rules must be installed"


def test_default_paths_are_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pydantic never validates defaults, so a literal ~ default would create a './~' dir."""
    monkeypatch.chdir(tmp_path)
    paths = load_config().config.paths
    for p in (paths.data_dir, paths.models_dir):
        assert "~" not in str(p), p
        assert p.is_absolute(), p


def test_configured_paths_are_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YANTRA_PATHS__DATA_DIR", "~/custom-yantra")
    paths = load_config().config.paths
    assert "~" not in str(paths.data_dir) and str(paths.data_dir).endswith("custom-yantra")


def test_precedence_profile_file_env_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "models" / "profiles").mkdir(parents=True)
    (tmp_path / "models" / "registry.yaml").write_text("[]", encoding="utf-8")
    (tmp_path / "models" / "profiles" / "lite.yaml").write_text(
        "config_defaults:\n  server: {port: 1111}\n  context: {utility: 1234}\n", encoding="utf-8"
    )
    (tmp_path / "yantra.yaml").write_text("server:\n  port: 2222\n", encoding="utf-8")
    monkeypatch.setenv("YANTRA_ASSETS_DIR", str(tmp_path))

    loaded = load_config()
    assert loaded.config.server.port == 2222  # file beats profile
    assert loaded.config.context.utility == 1234  # profile fills unset values

    monkeypatch.setenv("YANTRA_SERVER__PORT", "3333")
    loaded = load_config()
    assert loaded.config.server.port == 3333  # env beats file

    loaded = load_config(cli_overrides={"server": {"port": 4444}})
    assert loaded.config.server.port == 4444  # cli beats env
    assert loaded.sources["server.port"] == "cli"


def test_env_yaml_typing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YANTRA_BUDGETS__MAX_TOKENS", "12345")
    monkeypatch.setenv("YANTRA_KNOWLEDGE__COLLECTIONS", "[a, b]")
    loaded = load_config()
    assert loaded.config.budgets.max_tokens == 12345
    assert loaded.config.knowledge.collections == ["a", "b"]


def test_invalid_config_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "yantra.yaml").write_text("server:\n  port: not-a-port\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config()


def test_missing_explicit_config_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(config_path=tmp_path / "nope.yaml")


def test_example_config_validates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    monkeypatch.chdir(tmp_path)
    loaded = load_config(config_path=repo / "yantra.example.yaml")
    assert loaded.config.seal.allowlist
    assert loaded.config.knowledge.fusion_weights["lexical"] == 1.0


def test_effective_report_has_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YANTRA_SERVER__PORT", "9999")
    loaded = load_config()
    rows = {key: source for key, _value, source in effective_report(loaded)}
    assert rows["server.port"] == "env"
    assert rows["server.host"] == "default"
