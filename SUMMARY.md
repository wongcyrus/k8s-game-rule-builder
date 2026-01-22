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
│   ├── k8s_task_validator.py  # Pure Python validator (no LLM)
│   ├── pytest_runner.py       # Pure Python test runner (no LLM)
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
- **No LLM for Validation/Testing**: Pure Python functions for faster, more reliable checks
- **Max Consecutive Errors**: Configurable limit (default: 15) for file generation retries

## Agents

1. **Generator** - Creates complete K8s tasks with all required files (uses LLM)
2. **Validator** - Pure Python validation (NO LLM - direct file checks)
3. **PyTest Runner** - Pure Python test execution (NO LLM - subprocess calls)

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
- **1 Agent**: Generator (uses LLM for task creation)
- **2 Direct Executors**: run_validation, run_pytest (NO LLM - pure Python)
- **6 Other Executors**: Parse, decision-making, retry control
- **2 Decision Points**: Keep/remove tasks, retry/complete workflow
- **Max Retries**: 3 (configurable in `workflow.py`)
- **Goal**: Generate 1 successful task (not multiple tasks)
- **LLM Usage**: Only for generation (validation/testing are deterministic)

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
- **Validator refactored** - No LLM needed, pure Python validation (faster, more reliable)
- **PyTest runner refactored** - No LLM needed, direct subprocess execution
- **Max consecutive errors** - Set to 15 for generator agent (default was 3)
- **Improved error reporting** - Validation failures show specific errors, not generic messages
- **Test file requirements updated** - Added test_02_ready.py (REQUIRED) and test_04_challenge.py (OPTIONAL)

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

### Validator & PyTest Refactoring (2026-01-22)

**Problem**: Validator and PyTest agents were using LLM unnecessarily

**Why This Was Inefficient**:
- Validation is deterministic (file exists? syntax valid?)
- Test execution is deterministic (exit code 0 or not?)
- LLM adds latency, cost, and potential hallucinations
- No benefit from using AI for these tasks

**Solution**: Removed LLM from both agents

**Changes Made**:

1. **Validator Agent → Pure Python Validator**
   ```python
   # Before: agents/k8s_task_validator_agent.py (used LLM)
   validator_agent = responses_client.as_agent(...)
   result = await validator_agent.run("Validate task...")
   
   # After: agents/k8s_task_validator.py (pure Python)
   from agents.k8s_task_validator import validate_task_directory
   result = validate_task_directory(task_id)
   ```

2. **PyTest Agent → Pure Python Runner**
   ```python
   # Before: agents/pytest_agent.py (used LLM)
   pytest_agent = responses_client.as_agent(...)
   result = await pytest_agent.run("Run pytest...")
   
   # After: agents/pytest_runner.py (pure Python)
   from agents.pytest_runner import run_pytest_command
   result = run_pytest_command(pytest_command)
   ```

3. **Workflow Integration**
   ```python
   # Before: Used AgentExecutor wrappers
   validator_executor = AgentExecutor(validator_agent)
   pytest_executor = AgentExecutor(pytest_agent)
   
   # After: Direct executor functions
   @executor(id="run_validation")
   async def run_validation(task_info, ctx):
       result = validate_task_directory(task_info.task_id)
       # ... process result
   
   @executor(id="run_pytest")
   async def run_pytest(task_with_val, ctx):
       result = run_pytest_command(pytest_command)
       # ... process result
   ```

**Benefits**:
- ✅ **Faster**: No API calls to Azure OpenAI
- ✅ **More Reliable**: No LLM hallucinations or interpretation errors
- ✅ **Cost-Effective**: No token usage for validation/testing
- ✅ **Deterministic**: Same input always produces same output
- ✅ **Simpler**: Direct function calls instead of agent wrappers

**Files Modified**:
- `agents/k8s_task_validator_agent.py` → `agents/k8s_task_validator.py`
- `agents/pytest_agent.py` → `agents/pytest_runner.py`
- `workflow.py` (updated executors)
- `agents/__init__.py` (updated exports)

---

### Max Consecutive Errors Configuration (2026-01-22)

**Problem**: Generator agent stopped after 3 consecutive file creation errors (default limit)

**Why This Was Limiting**:
- Generator needs to create 10-11 files per task
- If MCP filesystem has issues, 3 errors is too low
- Tasks were failing unnecessarily

**Solution**: Increased `max_consecutive_errors_per_request` to 15

**Implementation**:
```python
# agents/k8s_task_generator_agent.py
chat_client = AzureOpenAIChatClient(...)

# Increase from default 3 to 15
chat_client.function_invocation_configuration.max_consecutive_errors_per_request = 15
logging.info(f"✅ Set max_consecutive_errors_per_request to 15")

agent = chat_client.as_agent(...)
```

**Verification**:
- Added logging to show before/after values
- Tested that setting persists after agent creation
- Updated generator instructions to mention "15 consecutive error retries available"

**Benefits**:
- ✅ More resilient to transient MCP filesystem issues
- ✅ Better chance of completing all file creations
- ✅ Reduces false negatives from temporary errors

---

### Improved Validation Error Reporting (2026-01-22)

**Problem**: Validation failures showed generic "Validation completed" message

**Why This Was Confusing**:
- User couldn't tell WHY validation failed
- Made debugging difficult
- Looked like validation passed when it actually failed

**Solution**: Extract and show specific error messages

**Implementation**:
```python
# workflow.py - run_validation executor
failure_reasons = []
if not result["is_valid"] and result.get("details"):
    for detail in result["details"]:
        if isinstance(detail, dict) and not detail.get("is_valid", True):
            reason = detail.get("reason", "Unknown error")
            # Skip generic messages
            if reason not in ["Validation completed", "Directory listing"]:
                failure_reasons.append(reason)

# Show first 3 specific errors
if failure_reasons:
    detailed_reason = "; ".join(failure_reasons[:3])
    if len(failure_reasons) > 3:
        detailed_reason += f" (and {len(failure_reasons) - 3} more errors)"
```

**Example Output**:
```
Before: ❌ FAILED Validation: Validation completed
After:  ❌ FAILED Validation: Missing file: test_05_check.py; Python syntax error in test_02_ready.py
```

**Benefits**:
- ✅ Clear error messages for debugging
- ✅ Shows multiple errors at once
- ✅ Filters out noise (generic messages)
- ✅ Makes decision logging more informative

---

### Test File Requirements Update (2026-01-22)

**Changes**: Added new test files to task structure

**New Files**:
1. **test_02_ready.py** (REQUIRED)
   - Tests that setup resources are ready
   - Uses polling loops with `time.sleep()` for pods, deployments, etc.
   - AI analyzes setup.template.yaml to determine what to test
   
2. **test_04_challenge.py** (OPTIONAL)
   - Pre-validation actions (load generation, CronJob triggers, etc.)
   - Only created if task requires it
   - AI decides based on task objective

**Why This Matters**:
- Resources take time to become ready (pods starting, deployments rolling out)
- Tests were failing because they checked too early
- Challenge file enables testing of dynamic behaviors (autoscaling, events, etc.)

**Generator Instructions Updated**:
- Emphasizes polling loops with timeouts
- Provides examples for different resource types
- Explains when to create test_04_challenge.py vs when to skip it

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
