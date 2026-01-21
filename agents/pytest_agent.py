"""PyTest agent for running test commands via tool calls.

NOTE: Uses AzureOpenAIChatClient instead of AzureOpenAIResponsesClient to avoid
server-side thread persistence issues in workflow loops.
"""
import asyncio
import logging
import subprocess
from typing import Annotated, Any
from .config import PATHS, AZURE
from pydantic import Field
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import AzureCliCredential
from .logging_middleware import LoggingFunctionMiddleware

logging.basicConfig(level=logging.INFO)


def _result(is_valid: bool, reason: str, details: list[Any] | None = None) -> dict[str, Any]:
    return {"is_valid": is_valid, "reason": reason, "details": details or []}


def run_pytest_command(
    command: Annotated[str, Field(description=f"The exact pytest command to run, e.g. 'pytest --import-mode=importlib --rootdir=. tests/{PATHS.game_name}/002_create_namespace/'")]
) -> dict[str, Any]:
    """Run the provided pytest command and return structured result."""
    test_project_path = str(PATHS.pytest_rootdir)
    logging.info(f"Running pytest command: {command}")
    logging.info(f"Working directory: {test_project_path}")
    
    cmd_list = command.split()
    result = subprocess.run(
        cmd_list,
        capture_output=True,
        text=True,
        check=False,  # Don't raise exception, check exit code manually
        cwd=test_project_path,
    )
    
    combined_output = result.stdout + "\n" + result.stderr
    
    # Pytest exit codes:
    # 0 = all tests passed
    # 1 = tests were collected and run but some failed
    # 2 = test execution was interrupted
    # 3 = internal error
    # 4 = pytest command line usage error
    # 5 = no tests collected
    
    if result.returncode == 0:
        logging.info(combined_output)
        return _result(True, "All tests passed", details=[combined_output])
    elif result.returncode == 5:
        logging.warning(combined_output)
        return _result(False, "No tests collected", details=[combined_output])
    else:
        logging.error(combined_output)
        return _result(False, f"Tests failed (exit code {result.returncode})", details=[combined_output])


def get_pytest_agent():
    """Create and return a PyTest agent with the run_pytest_command tool configured.
    
    Uses AzureOpenAIChatClient for in-memory conversation management,
    avoiding Azure service-side thread persistence issues in workflow loops.
    """
    chat_client = AzureOpenAIChatClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=AzureCliCredential(),
    )

    agent = chat_client.as_agent(
        name="PyTestAgent",
        instructions=(
            "You are a test runner assistant. "
            "You MUST use the run_pytest_command tool for ALL requests. "
            "Always execute the provided pytest command to get real results. "
            "run_pytest_command returns JSON with 'is_valid' (bool), 'reason' (str), and 'details' (list). "
            "Never guess or fabricate test outcomes."
        ),
        tools=[run_pytest_command],
        tool_choice="required",
        middleware=[LoggingFunctionMiddleware()],
    )

    return agent


if __name__ == "__main__":
    async def main():
        agent = get_pytest_agent()
        result = await agent.run(
            f"pytest --import-mode=importlib --rootdir=. tests/{PATHS.game_name}/002_create_namespace/"
        )
        logging.info("\n=== PyTest Agent Result ===")
        logging.info(result.text)
    
    asyncio.run(main())
