"""Centralized configuration for agent paths and validation defaults."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    tests_root: Path = Path("/home/developer/Documents/data-disk/k8s/k8s-game-rule/tests")
    game_name: str = "game02"  # Configurable game name
    pytest_rootdir: Path = Path("/home/developer/Documents/data-disk/k8s/k8s-game-rule")
    k8s_docs_root: Path = Path("/home/developer/Documents/data-disk/website/content/en/docs/concepts")
    unsuccessful_root: Path = Path("/home/developer/Documents/data-disk/k8s/k8s-game-rule/unsuccessful")
    
    @property
    def game_root(self) -> Path:
        """Dynamic game root based on game_name."""
        return self.tests_root / self.game_name
    
    @property
    def unsuccessful_game_root(self) -> Path:
        """Unsuccessful tasks directory for the current game."""
        return self.unsuccessful_root / self.game_name
    
    @property
    def unsuccessful_game_name(self) -> str:
        """Unsuccessful game folder name for filesystem operations."""
        return f"unsuccessful/{self.game_name}"


@dataclass(frozen=True)
class AzureOpenAI:
    endpoint: str = "https://cyrus-me23xi26-eastus2.openai.azure.com/"
    deployment_name: str = "gpt-5.2-chat"

    # Models that require the Responses API (no Chat Completions support).
    # Add model prefixes here as needed.
    RESPONSES_ONLY_PREFIXES: tuple[str, ...] = (
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-5.1-codex",
        "gpt-5-codex",
        "gpt-5-pro",
        "gpt-5.1-codex-max",
    )

    @property
    def use_responses_api(self) -> bool:
        """Whether the configured model requires the Responses API."""
        return any(
            self.deployment_name.startswith(prefix)
            for prefix in self.RESPONSES_ONLY_PREFIXES
        )

@dataclass(frozen=True)
class ValidationConfig:
    base_task_root: Path = Paths().game_root
    required_files: tuple[str, ...] = (
        "__init__.py",
        "instruction.md",
        "concept.md",
        "session.json",
        "setup.template.yaml",
        "answer.template.yaml",
        "test_01_setup.py",
        "test_02_ready.py",
        "test_03_answer.py",
        # test_04_challenge.py is optional
        "test_05_check.py",
        "test_06_cleanup.py",
    )
    yaml_files: tuple[str, ...] = ("setup.template.yaml", "answer.template.yaml")
    py_files: tuple[str, ...] = (
        "test_01_setup.py",
        "test_02_ready.py",
        "test_03_answer.py",
        "test_04_challenge.py",  # Optional but validate if present
        "test_05_check.py",
        "test_06_cleanup.py",
    )
    json_files: tuple[str, ...] = ("session.json",)


PATHS = Paths()
VALIDATION = ValidationConfig()
AZURE = AzureOpenAI()
