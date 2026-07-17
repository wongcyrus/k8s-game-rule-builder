from pathlib import Path

from agents.config import AzureOpenAI, Paths


def test_paths_game_root_uses_game_name():
    paths = Paths(tests_root=Path("/tmp/tests"), game_name="game99")
    assert paths.game_root == Path("/tmp/tests/game99")


def test_paths_unsuccessful_helpers_use_game_name():
    paths = Paths(unsuccessful_root=Path("/tmp/unsuccessful"), game_name="game77")
    assert paths.unsuccessful_game_root == Path("/tmp/unsuccessful/game77")
    assert paths.unsuccessful_game_name == "unsuccessful/game77"


def test_use_responses_api_true_for_supported_prefix():
    cfg = AzureOpenAI(deployment_name="gpt-5.3-codex-fast")
    assert cfg.use_responses_api is True


def test_use_responses_api_false_for_chat_completion_model():
    cfg = AzureOpenAI(deployment_name="gpt-4o")
    assert cfg.use_responses_api is False
