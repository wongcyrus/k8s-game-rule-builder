# Project Summary

## K8s Game Rule Builder

AI-powered Kubernetes learning task generation with validation and testing workflows using Microsoft Agent Framework.

## Quick Commands

```bash
# Setup
bash setup.sh

# Run workflow (generates 3 tasks with loop)
python workflow.py

# Generate workflow visualization
python visualize_workflow.py

# Launch DevUI with full workflow
./launch_devui.sh
```

## Documentation

| File | Purpose |
|------|---------|
| [README.md](README.md) | Quick start and overview |
| [WORKFLOW.md](WORKFLOW.md) | Workflow architecture with loop implementation |
| [entities/README.md](entities/README.md) | DevUI entities guide |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical deep dive |

## Project Structure

```
k8s-game-rule-builder/
├── agents/                 # AI agent modules
│   ├── k8s_task_generator_agent.py
│   ├── k8s_task_validator_agent.py
│   ├── pytest_agent.py
│   └── config.py
├── entities/              # DevUI entities
│   ├── k8s_task_workflow/
│   ├── k8s_generator_agent/
│   ├── k8s_validator_agent/
│   └── k8s_pytest_agent/
├── docs/                  # Documentation
├── workflow.py           # Looping conditional workflow
└── visualize_workflow.py # Visualization generator
```

## Key Features

- **AI-Powered Generation**: Azure OpenAI agents create K8s learning tasks
- **Looping Workflow**: Generates multiple tasks (configurable max: 3)
- **Conditional Routing**: Two decision points (keep/remove, continue/complete)
- **Automatic Cleanup**: Removes failed tasks from filesystem
- **Shared State**: Tracks task count and validation results
- **Interactive DevUI**: Web interface for agents and workflows
- **Visualization**: Mermaid, SVG, PNG, PDF workflow diagrams
- **Structured Output**: Type-safe Pydantic models

## Agents

1. **Generator** - Creates complete K8s tasks with all required files
2. **Validator** - Validates structure, YAML syntax, Python syntax, Jinja templates
3. **PyTest** - Runs pytest test suites

## Workflow Architecture

```
Generate → Validate → Test → Decision 1 (Keep/Remove) → Decision 2 (Continue/Complete)
                                                              ↓
                                                         Loop Back
```

### Loop Structure
```
keep_task → check_loop → [generate_next OR complete_workflow]
remove_task → check_loop → [generate_next OR complete_workflow]
generate_next → generator_agent (loop back)
complete_workflow → END
```

### Decision Logic
1. **Keep vs Remove**: `validation.is_valid AND test.is_valid`
2. **Continue vs Complete**: `task_count < max_tasks`

### Workflow Components
- **3 Agents**: Generator, Validator, Pytest
- **10 Executors**: Parse, create requests, decision-making, loop control
- **2 Decision Points**: Keep/remove tasks, continue/complete workflow
- **Max Tasks**: 3 (configurable in `workflow.py`)

## DevUI

Launch DevUI with the full workflow and all agents:

```bash
./launch_devui.sh
# or
python launch_devui_full.py
```

**Registered Entities (4):**
- ✅ **K8s Task Workflow** - Full workflow with loop
- ✅ **Generator Agent** - Creates K8s tasks with MCP filesystem
- ✅ **Validator Agent** - Validates task structure and syntax
- ✅ **Pytest Agent** - Runs tests on tasks

**Features:**
- Same as workflow.py
- Loop functionality (generates 3 tasks)
- Two decision points
- Shared state management
- ⚠️ **k8s_generator_agent** - Placeholder (requires async context)

## Configuration

### Max Tasks
Edit `workflow.py`:
```python
max_tasks: int = 3  # Change to desired number
```

### Paths
Edit `agents/config.py`:
```python
PATHS = PathConfig(
    tests_root=Path("/path/to/tests"),
    # ...
)
```

## Requirements

- Python 3.12+
- Azure OpenAI access
- Microsoft Agent Framework
- Graphviz (for visualization)
- DevUI: `pip install agent-framework[devui]`

## Technology Stack

- **Microsoft Agent Framework** - Workflow orchestration
- **Azure OpenAI** - LLM for agents
- **MCP (Model Context Protocol)** - Filesystem operations
- **Pydantic** - Data validation
- **Graphviz** - Workflow visualization
- **Pytest** - Testing framework

## Status

✅ All systems operational
- Looping workflow implemented and tested
- Edge-based loop with guaranteed termination
- Shared state management working
- DevUI entities loading correctly
- Documentation updated
- Visualization generating properly
- **Thread management fix applied** - All agents use in-memory conversation management

## Troubleshooting

### Workflow Loop Issue (Fixed 2026-01-21)

**Problem**: Azure OpenAI error on second loop iteration:
```
Error code: 400 - {'error': {'message': 'No tool call found for function call output with call_id...'}}
```

**Root Cause**: 
- All three agents (generator, validator, pytest) were using `AzureOpenAIResponsesClient`
- This client stores conversation threads on Azure service (server-side persistence)
- When workflow looped, agents reused Azure threads from previous iterations
- Tool call IDs from iteration 1 conflicted with iteration 2

**Solution**: Switched all agents to `AzureOpenAIChatClient`
- Chat client manages conversations **in-memory** (no server-side persistence)
- Each workflow iteration gets clean conversation context
- No tool call ID conflicts between iterations

**Files Modified**:
```python
# agents/k8s_task_generator_agent.py
from agent_framework.azure import AzureOpenAIChatClient  # was: AzureOpenAIResponsesClient
chat_client = AzureOpenAIChatClient(...)
agent = chat_client.as_agent(...)

# agents/k8s_task_validator_agent.py  
from agent_framework.azure import AzureOpenAIChatClient  # was: AzureOpenAIResponsesClient
chat_client = AzureOpenAIChatClient(...)
agent = chat_client.as_agent(...)

# agents/pytest_agent.py
from agent_framework.azure import AzureOpenAIChatClient  # was: AzureOpenAIResponsesClient
chat_client = AzureOpenAIChatClient(...)
agent = chat_client.as_agent(...)
```

**Key Difference**:
- **AzureOpenAIResponsesClient**: Server-side thread persistence (causes loop issues)
- **AzureOpenAIChatClient**: In-memory conversation management (works with loops)

**Result**: ✅ Workflow successfully completes all 3 task generations without errors
