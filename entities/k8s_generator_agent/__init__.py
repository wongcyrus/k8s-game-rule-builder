"""K8s Task Generator Agent.

Generates complete Kubernetes learning tasks with all required files.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents import get_k8s_task_generator_agent
from agent_framework import AgentExecutor


# For DevUI discovery - must be named 'agent'
# Since get_k8s_task_generator_agent is async, we need to handle it differently
# DevUI expects a synchronous agent object, not a coroutine

# We'll create a simple wrapper that DevUI can use
# Note: This won't work with the async context manager
# Let's just document that this agent should be used via the workflow

# For now, provide a placeholder that explains the limitation
class GeneratorAgentPlaceholder:
    """Placeholder for generator agent.
    
    This agent uses an async context manager and should be accessed
    via the k8s_task_workflow instead.
    """
    def __init__(self):
        self.name = "k8s_generator_agent"
        self.description = (
            "This agent requires async context management. "
            "Please use the 'k8s_task_workflow' entity instead, "
            "which properly handles the async lifecycle."
        )

# For DevUI discovery
agent = GeneratorAgentPlaceholder()

