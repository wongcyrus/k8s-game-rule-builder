"""Centralized configuration for agent paths and validation defaults."""
from dataclasses import dataclass
import os
from pathlib import Path


def _parse_dotenv_value(raw: str, line_number: int) -> str:
    value = raw.strip()
    if value == "":
        return ""
    if value[0] in {"'", '"'}:
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise RuntimeError(f"Invalid .env line {line_number}: unmatched quote")
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _load_dotenv_if_exists() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for line_number, line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].strip()
        if "=" not in stripped:
            raise RuntimeError(f"Invalid .env line {line_number}: expected KEY=VALUE")
        key, raw_value = stripped.split("=", 1)
        env_key = key.strip()
        if env_key == "":
            raise RuntimeError(f"Invalid .env line {line_number}: missing key")
        env_value = _parse_dotenv_value(raw_value, line_number)
        os.environ.setdefault(env_key, env_value)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _required_absolute_path_env(name: str) -> Path:
    value = Path(_required_env(name))
    if not value.is_absolute():
        raise RuntimeError(
            f"Environment variable {name} must be an absolute path, got: {value}"
        )
    return value


@dataclass(frozen=True)
class Paths:
    tests_root: Path
    game_name: str
    pytest_rootdir: Path
    k8s_docs_root: Path
    unsuccessful_root: Path
    
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
    endpoint: str
    deployment_name: str

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
    base_task_root: Path
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


_load_dotenv_if_exists()

PATHS = Paths(
    tests_root=_required_absolute_path_env("K8S_RULE_TESTS_ROOT"),
    game_name=_required_env("K8S_RULE_GAME_NAME"),
    pytest_rootdir=_required_absolute_path_env("K8S_RULE_PYTEST_ROOTDIR"),
    k8s_docs_root=_required_absolute_path_env("K8S_RULE_K8S_DOCS_ROOT"),
    unsuccessful_root=_required_absolute_path_env("K8S_RULE_UNSUCCESSFUL_ROOT"),
)
VALIDATION = ValidationConfig(base_task_root=PATHS.game_root)
AZURE = AzureOpenAI(
    endpoint=_required_env("AZURE_OPENAI_ENDPOINT"),
    deployment_name=_required_env("AZURE_OPENAI_DEPLOYMENT_NAME"),
)
