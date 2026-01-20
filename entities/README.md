# DevUI Entities

This directory contains agents and workflows for DevUI.

## Quick Start

```bash
# Launch DevUI
source .venv/bin/activate
devui entities

# Or use launch script
./launch_devui.sh

# Open browser to http://localhost:8000
```

## Available Entities

### k8s_task_workflow
**Type**: Workflow  
**Description**: Validation and testing workflow

**Flow**: `Validate → Test → [Keep or Remove]`

**Note**: Simplified for DevUI. For complete workflow with task generation, use:
```bash
python workflow.py
```

### k8s_validator_agent
**Type**: Agent  
**Description**: Validates task structure, YAML, Python, and Jinja syntax

**Example**: `Validate the task directory 001_configmap_env`

### k8s_pytest_agent
**Type**: Agent  
**Description**: Runs pytest tests on tasks

**Example**: `Run all tests in tests/game02/001_configmap_env/`

### k8s_generator_agent
**Type**: Placeholder  
**Note**: Use `python workflow.py` for task generation (requires async context)

## Usage

1. Launch DevUI: `devui entities`
2. Open browser: http://localhost:8000
3. Select entity from sidebar
4. Chat with agents or run workflows

## Development

### Add New Entity

1. Create directory: `entities/my_entity/`
2. Add `__init__.py` with `agent` or `workflow` export
3. Restart DevUI

### Example

```python
# entities/my_agent/__init__.py
from agent_framework import ChatAgent

agent = ChatAgent(
    name="my_agent",
    instructions="You are helpful."
)
```

## References

- [DevUI Docs](https://learn.microsoft.com/en-us/agent-framework/user-guide/devui/)
- [Directory Discovery](https://learn.microsoft.com/en-us/agent-framework/user-guide/devui/directory-discovery)
