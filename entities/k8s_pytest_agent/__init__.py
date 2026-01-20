"""K8s PyTest Agent.

Runs pytest tests to validate generated Kubernetes tasks.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents import get_pytest_agent

# For DevUI discovery - must be named 'agent'
# This agent is synchronous and can be used directly
agent = get_pytest_agent()

