"""Agents package for k8s-game-rule-builder."""
from .filesystem_agent import get_filesystem_agent
from .kubernetes_agent import get_kubernetes_agent
from .pytest_runner import get_pytest_runner, get_pytest_agent, run_pytest_command
from .k8s_task_generator_agent import get_k8s_task_generator_agent
from .k8s_task_idea_agent import create_idea_agent_with_mcp
from .k8s_task_validator import get_k8s_task_validator, get_k8s_task_validator_agent, validate_task_directory
from .config import PATHS, VALIDATION, AZURE
from .logging_middleware import LoggingFunctionMiddleware, get_logging_middleware

__all__ = [
	"get_filesystem_agent",
	"get_kubernetes_agent",
	"get_pytest_runner",
	"get_pytest_agent",  # Backward compatibility alias
	"run_pytest_command",
	"get_k8s_task_generator_agent",
	"get_k8s_task_idea_agent",
	"get_k8s_task_validator",
	"get_k8s_task_validator_agent",  # Backward compatibility alias
	"validate_task_directory",
	"PATHS",
	"VALIDATION",
	"AZURE",
	"LoggingFunctionMiddleware",
	"get_logging_middleware",
]
