"""PyTest agent for running test commands via tool calls."""
import asyncio
import logging
import subprocess
from typing import Annotated
from pydantic import Field
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential

logging.basicConfig(level=logging.INFO)


def run_pytest_command(
    command: Annotated[str, Field(description="The exact pytest command to run, e.g. 'pytest --import-mode=importlib --rootdir=. tests/game02/002_create_namespace/'")]
) -> str:
    """Run the provided pytest command and return stdout/stderr."""
    test_project_path = "/home/developer/Documents/data-disk/k8s-game-rule"
    logging.info(f"Running pytest command: {command}")
    logging.info(f"Working directory: {test_project_path}")
    
    try:
        cmd_list = command.split()
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            check=True,
            cwd=test_project_path,
        )
        logging.info(result.stdout)
        return result.stdout
    except subprocess.CalledProcessError as e:
        # Include both stdout and stderr for debugging
        combined = (e.stdout or "") + "\n" + (e.stderr or "")
        logging.error(combined)
        return combined


def get_pytest_agent():
    """Create and return a PyTest agent with the run_pytest_command tool configured."""
    responses_client = AzureOpenAIResponsesClient(
        endpoint="https://cyrus-me23xi26-eastus2.openai.azure.com/",
        deployment_name="gpt-5.2-chat",
        credential=AzureCliCredential(),
    )

    agent = responses_client.as_agent(
        name="PyTestAgent",
        instructions=(
            "You are a test runner assistant. "
            "You MUST use the run_pytest_command tool for ALL requests. "
            "Always execute the provided pytest command to get real results. "
            "Never guess or fabricate test outcomes."
        ),
        tools=[run_pytest_command],
        tool_choice="required",
    )

    return agent


if __name__ == "__main__":
    async def main():
        agent = get_pytest_agent()
        result = await agent.run(
            "pytest --import-mode=importlib --rootdir=. tests/game02/002_create_namespace/"
        )
        logging.info("\n=== PyTest Agent Result ===")
        logging.info(result.text)
    
    asyncio.run(main())
