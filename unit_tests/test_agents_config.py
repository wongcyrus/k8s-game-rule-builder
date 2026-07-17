from pathlib import Path

from agents.config import (
    AzureOpenAI,
    Paths,
    _load_dotenv_if_exists,
    _parse_dotenv_value,
    _required_env,
    _required_absolute_path_env,
)


def test_paths_game_root_uses_game_name():
    paths = Paths(
        tests_root=Path("/tmp/tests"),
        game_name="game99",
        pytest_rootdir=Path("/tmp/project"),
        k8s_docs_root=Path("/tmp/docs"),
        unsuccessful_root=Path("/tmp/unsuccessful"),
    )
    assert paths.game_root == Path("/tmp/tests/game99")


def test_paths_unsuccessful_helpers_use_game_name():
    paths = Paths(
        tests_root=Path("/tmp/tests"),
        game_name="game77",
        pytest_rootdir=Path("/tmp/project"),
        k8s_docs_root=Path("/tmp/docs"),
        unsuccessful_root=Path("/tmp/unsuccessful"),
    )
    assert paths.unsuccessful_game_root == Path("/tmp/unsuccessful/game77")
    assert paths.unsuccessful_game_name == "unsuccessful/game77"


def test_use_responses_api_true_for_supported_prefix():
    cfg = AzureOpenAI(endpoint="https://example.openai.azure.com/", deployment_name="gpt-5.3-codex-fast")
    assert cfg.use_responses_api is True


def test_use_responses_api_false_for_chat_completion_model():
    cfg = AzureOpenAI(endpoint="https://example.openai.azure.com/", deployment_name="gpt-4o")
    assert cfg.use_responses_api is False


def test_required_env_raises_for_missing(monkeypatch):
    monkeypatch.delenv("UNIT_TEST_MISSING_ENV", raising=False)
    import pytest

    with pytest.raises(RuntimeError, match="Missing required environment variable"):
        _required_env("UNIT_TEST_MISSING_ENV")


def test_required_absolute_path_env_requires_absolute(monkeypatch):
    monkeypatch.setenv("UNIT_TEST_RELATIVE_PATH", "relative/path")
    import pytest

    with pytest.raises(RuntimeError, match="must be an absolute path"):
        _required_absolute_path_env("UNIT_TEST_RELATIVE_PATH")


def test_parse_dotenv_value_unmatched_quote_raises():
    import pytest

    with pytest.raises(RuntimeError, match="unmatched quote"):
        _parse_dotenv_value('"abc', 1)


def test_load_dotenv_if_exists_loads_values(monkeypatch, tmp_path: Path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "# comment",
                "A=1",
                "export B='two'",
                "C=three # inline comment",
                "D= spaced value ",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)
    monkeypatch.delenv("C", raising=False)
    monkeypatch.delenv("D", raising=False)

    from agents import config as config_module

    expected_env_path = config_module.Path(__file__).resolve()
    monkeypatch.setattr(
        config_module,
        "__file__",
        str(tmp_path / "agents" / "config.py"),
    )

    _load_dotenv_if_exists()

    assert expected_env_path  # keep linter happy about imported Path usage
    assert _required_env("A") == "1"
    assert _required_env("B") == "two"
    assert _required_env("C") == "three"
    assert _required_env("D") == "spaced value"


def test_load_dotenv_if_exists_preserves_existing_env(monkeypatch, tmp_path: Path):
    (tmp_path / ".env").write_text("EXISTING=from_file\n", encoding="utf-8")
    monkeypatch.setenv("EXISTING", "from_env")

    from agents import config as config_module

    monkeypatch.setattr(
        config_module,
        "__file__",
        str(tmp_path / "agents" / "config.py"),
    )
    _load_dotenv_if_exists()

    assert _required_env("EXISTING") == "from_env"


def test_load_dotenv_if_exists_rejects_invalid_line(monkeypatch, tmp_path: Path):
    (tmp_path / ".env").write_text("NOT_VALID\n", encoding="utf-8")

    from agents import config as config_module
    import pytest

    monkeypatch.setattr(
        config_module,
        "__file__",
        str(tmp_path / "agents" / "config.py"),
    )
    with pytest.raises(RuntimeError, match="expected KEY=VALUE"):
        _load_dotenv_if_exists()
