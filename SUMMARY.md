# Project Summary

## K8s Game Rule Builder

AI-powered Kubernetes learning task generation with validation and testing workflows using Microsoft Agent Framework.

## Quick Commands

```bash
# Setup
bash setup.sh

# Run workflow (generates 1 task with retry on failure)
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
| [WORKFLOW.md](WORKFLOW.md) | Workflow architecture with retry loop |
| [CHANGELOG.md](CHANGELOG.md) | Version history and recent changes |
| [docs/RETRY_LOGIC.md](docs/RETRY_LOGIC.md) | Detailed retry implementation guide |
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
- **Retry Loop**: Generates 1 task with automatic retry on failure (max 3 retries)
- **Topic-Focused**: Each run targets a specific Kubernetes concept
- **Conditional Routing**: Two decision points (keep/remove, retry/complete)
- **Automatic Cleanup**: Removes failed tasks from filesystem
- **Duplicate Prevention**: Lists existing tasks to avoid ID conflicts
- **Shared State**: Tracks retry count and validation results
- **Interactive DevUI**: Web interface for agents and workflows
- **Visualization**: Mermaid, SVG, PNG, PDF workflow diagrams
- **Structured Output**: Type-safe Pydantic models

## Agents

1. **Generator** - Creates complete K8s tasks with all required files
2. **Validator** - Validates structure, YAML syntax, Python syntax, Jinja templates
3. **PyTest** - Runs pytest test suites

## Workflow Architecture

```
Generate → Validate → Test → Decision 1 (Keep/Remove) → Decision 2 (Retry/Complete)
                                                              ↓
                                                         Loop Back (Retry)
```

### Retry Loop Structure
```
keep_task → check_loop → complete_workflow (SUCCESS)
remove_task → check_loop → [retry_generation OR complete_workflow]
retry_generation → generator_agent (loop back)
complete_workflow → END
```

### Decision Logic
1. **Keep vs Remove**: `validation.is_valid AND test.is_valid`
2. **Retry vs Complete**: `NOT should_keep AND retry_count < max_retries`

### Workflow Components
- **3 Agents**: Generator, Validator, Pytest
- **10 Executors**: Parse, create requests, decision-making, retry control
- **2 Decision Points**: Keep/remove tasks, retry/complete workflow
- **Max Retries**: 3 (configurable in `workflow.py`)
- **Goal**: Generate 1 successful task (not multiple tasks)

## DevUI

Launch DevUI with the full workflow and all agents:

```bash
./launch_devui.sh
# or
python launch_devui_full.py
```

**Registered Entities (4):**
- ✅ **K8s Task Workflow** - Full workflow with retry loop
- ✅ **Generator Agent** - Creates K8s tasks with MCP filesystem
- ✅ **Validator Agent** - Validates task structure and syntax
- ✅ **Pytest Agent** - Runs tests on tasks

**Features:**
- Same as workflow.py
- Retry loop (up to 3 attempts)
- Topic-focused generation
- Two decision points
- Shared state management
- ⚠️ **k8s_generator_agent** - Placeholder (requires async context)

## Configuration

### Target Topic
Edit `workflow.py` main():
```python
target_topic = "ConfigMaps and environment variables"  # Change to desired topic
```

### Max Retries
Edit `workflow.py` main():
```python
initial_state = {
    "target_topic": target_topic,
    "retry_count": 0,
    "max_retries": 3  # Change to desired number
}
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
- Retry loop implemented and tested
- Topic-focused generation working
- Duplicate prevention via existing task list
- Edge-based loop with guaranteed termination
- Shared state management working
- DevUI entities loading correctly
- Documentation updated
- Visualization generating properly
- **Thread management fix applied** - All agents use in-memory conversation management
- **Prompt logic reviewed** - All prompts work with retry loop and topic input

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

**Result**: ✅ Workflow successfully completes retry loop without errors

---

### Workflow Logic Update (2026-01-21)

**Changes**: Converted from multi-task generation to single-task with retry

**Before**:
- Generated multiple tasks (up to max_tasks = 3)
- Used thread-based deduplication
- Continued until max_tasks reached

**After**:
- Generates 1 task with retry on failure
- Uses explicit existing task list for deduplication
- Stops on first success OR max retries reached
- Topic-focused generation

**Key Improvements**:
1. **Retry Logic**: `retry_count` instead of `task_count`
2. **Topic Input**: Each run targets a specific Kubernetes concept
3. **Duplicate Prevention**: Lists existing tasks in prompt
4. **Stop on Success**: No need to generate multiple tasks
5. **Independent Iterations**: No thread persistence required

**See**: [WORKFLOW_CHANGES.md](WORKFLOW_CHANGES.md) for detailed changes
