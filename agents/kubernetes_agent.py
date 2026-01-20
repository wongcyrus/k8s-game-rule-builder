"""Kubernetes agent for managing K8s clusters."""
import asyncio
import logging
import os
import subprocess
from typing import Annotated
from pydantic import Field
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential

logging.basicConfig(level=logging.INFO)


def run_kubectl_command(
    command: Annotated[str, Field(description="The kubectl command to run (e.g., 'get pods', 'get namespaces -o wide', 'delete namespace test')")]
) -> str:
    """Run any kubectl command using the existing kubeconfig."""
    kubeconfig_path = os.environ.get("KUBECONFIG", "/home/developer/.kube/config")

    logging.info(f"[RUN]: kubectl {command}")
    
    try:
        cmd_list = ['kubectl'] + command.split()
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "KUBECONFIG": kubeconfig_path}
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        logging.error(e.stderr)
        return e.stderr


def get_kubernetes_agent():
    """Create and return a Kubernetes agent with kubectl tools.
    
    Returns:
        An agent with kubectl tools configured.
    """
    responses_client = AzureOpenAIResponsesClient(
        endpoint="https://cyrus-me23xi26-eastus2.openai.azure.com/",
        deployment_name="gpt-5.2-chat",
        credential=AzureCliCredential(),
    )

    agent = responses_client.as_agent(
        name="KubernetesAgent",
        instructions=(
            "You are a Kubernetes cluster administrator assistant. "
            "You MUST use the run_kubectl_command tool for ALL queries - never provide information without using the tool. "
            "ALWAYS execute kubectl commands to get real-time cluster data. "
            "NEVER make up or guess information. "
            "For any question about the cluster, you MUST call run_kubectl_command with the appropriate kubectl command."
        ),
        tools=[run_kubectl_command],
        tool_choice="required",
    )
    
    return agent


if __name__ == "__main__":
    async def main():
        agent = get_kubernetes_agent()
        result = await agent.run(
            "List all namespaces in the cluster"
        )
        logging.info("\n=== Kubernetes Agent Result ===")
        logging.info(result.text)
    
    asyncio.run(main())
