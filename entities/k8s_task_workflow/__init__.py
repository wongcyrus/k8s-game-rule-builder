"""K8s Task Generation Workflow with Validation and Testing.

This workflow generates Kubernetes learning tasks, validates them,
runs tests, and automatically removes tasks that fail.

Note: This workflow uses the generator agent which requires async context management.
For DevUI, we provide a simplified version that can be executed.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agent_framework import WorkflowBuilder, AgentExecutor
from azure.identity import AzureCliCredential

from agents import (
    get_pytest_agent,
    get_k8s_task_validator_agent,
)
from agents.config import AZURE

# Import executors from workflow
from workflow import (
    parse_generated_task,
    create_validation_request,
    parse_validation_result,
    create_pytest_request,
    parse_tests_and_decide,
    keep_task,
    remove_task,
    select_action,
)


# Note: The generator agent requires async context management
# For DevUI, we'll create a placeholder workflow that explains this limitation
# The full workflow should be run via: python workflow.py

# Create a simple workflow with just validator and pytest agents
# This demonstrates the workflow structure without the generator

validator_agent = get_k8s_task_validator_agent()
validator_executor = AgentExecutor(validator_agent, id="validator_agent")

pytest_agent = get_pytest_agent()
pytest_executor = AgentExecutor(pytest_agent, id="pytest_agent")

# Build a simplified workflow for DevUI
# This workflow starts with validation (assumes task already exists)
workflow = (
    WorkflowBuilder()
    .set_start_executor(validator_executor)
    .add_edge(validator_executor, parse_validation_result)
    .add_edge(parse_validation_result, create_pytest_request)
    .add_edge(create_pytest_request, pytest_executor)
    .add_edge(pytest_executor, parse_tests_and_decide)
    .add_multi_selection_edge_group(
        parse_tests_and_decide,
        [keep_task, remove_task],
        selection_func=select_action,
    )
    .build()
)

# For DevUI discovery - must be named 'workflow'
# This is now a synchronous workflow object

