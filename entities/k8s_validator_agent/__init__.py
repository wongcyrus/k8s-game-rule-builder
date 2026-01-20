"""K8s Task Validator Agent.

Validates task structure, YAML syntax, Python syntax, and Jinja templates.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents import get_k8s_task_validator_agent

# For DevUI discovery - must be named 'agent'
# This agent is synchronous and can be used directly
agent = get_k8s_task_validator_agent()

