# Changelog

## [2.0.1] - 2026-01-21

### Fixed

#### Test Result Parsing Bug

**Issue**: Tests were incorrectly marked as failed even when all tests passed successfully.

**Example**:
```
All tests executed successfully.
- Total tests: 5
- Passed: ✅ 5
- Failed: ❌ 0

Result: ❌ FAILED Tests: Tests failed  <-- WRONG!
```

**Root Causes**:

1. **Exit Code Handling**: `run_pytest_command` used `subprocess.run(..., check=True)` which raised `CalledProcessError` on any non-zero exit code, even when tests passed with warnings.

2. **Naive String Parsing**: Logic was `"passed" in text and "failed" not in text`, which failed when text contained "Failed: ❌ 0" (the word "failed" was present even though 0 tests failed).

**Solution**:

1. Changed to `check=False` and manually handle pytest exit codes:
   - Exit code 0 = All tests passed
   - Exit code 1 = Some tests failed
   - Exit code 5 = No tests collected

2. Improved parsing to extract actual passed/failed counts using regex:
   - Looks for patterns like "Passed: ✅ 5, Failed: ❌ 0"
   - Also handles standard pytest output "5 passed in 10.5s"
   - Success when `passed_count > 0 AND failed_count == 0`

**Files Modified**:
- `agents/pytest_agent.py` - Exit code handling
- `workflow.py` - Parsing logic with regex
- `launch_devui_full.py` - ✅ Automatically fixed (imports from workflow.py)

**Impact**:
- Before: Tasks with passing tests were incorrectly removed ❌
- After: Tasks with passing tests are correctly kept ✅

---

## [2.0.0] - 2026-01-21

### Major Changes: Retry-Based Workflow

Complete redesign of workflow logic from multi-task generation to single-task with retry.

### Changed

#### Workflow Logic
- **BEFORE**: Generated multiple tasks (up to `max_tasks = 3`)
- **AFTER**: Generates 1 task with retry on failure (up to `max_retries = 3`)
- **Benefit**: Stops on first success, more efficient

#### Data Model
```python
# BEFORE
class CombinedValidationResult:
    task_count: int = 0      # How many tasks generated
    max_tasks: int = 3       # Total tasks to generate
    
    @property
    def should_continue(self) -> bool:
        return self.task_count < self.max_tasks

# AFTER
class CombinedValidationResult:
    retry_count: int = 0     # How many retries attempted
    max_retries: int = 3     # Max retry attempts
    
    @property
    def should_retry(self) -> bool:
        return not self.should_keep and self.retry_count < self.max_retries
```

#### Executors
- Renamed: `generate_next` → `retry_generation`
- Updated: `parse_generated_task` - Increments retry_count on parse failure
- Updated: `parse_tests_and_decide` - Uses retry_count instead of task_count
- Updated: `keep_task` - Logs retry attempts
- Updated: `remove_task` - Increments retry_count before check_loop
- Updated: `check_loop` - Checks retry logic instead of task count
- Updated: `complete_workflow` - Reports success or max retries

#### Prompts
- Added `target_topic` parameter for focused generation
- Added existing tasks list to prevent duplicates
- Retry prompt includes attempt number and emphasizes correctness
- No longer relies on thread-based deduplication

#### Selection Functions
- `select_loop_action`: Routes based on `should_retry` instead of `should_continue`
- Success path: `keep_task → check_loop → complete_workflow`
- Failure path: `remove_task → check_loop → [retry_generation OR complete_workflow]`

### Added

#### New Features
- Topic-focused generation (e.g., "ConfigMaps and environment variables")
- Explicit duplicate prevention via existing task list
- Independent iterations (no thread persistence required)
- Retry attempt tracking and logging

#### New Documentation
- `CHANGELOG.md` - This file
- `docs/RETRY_LOGIC.md` - Detailed retry implementation guide
- Consolidated change documentation

### Fixed

#### Thread Management (2026-01-21)
- **Issue**: Azure OpenAI error on second loop iteration
- **Root Cause**: `AzureOpenAIResponsesClient` used server-side thread persistence
- **Solution**: Switched all agents to `AzureOpenAIChatClient` for in-memory conversation management
- **Files Modified**: 
  - `agents/k8s_task_generator_agent.py`
  - `agents/k8s_task_validator_agent.py`
  - `agents/pytest_agent.py`

#### Duplicate Prevention
- **Issue**: Thread-based deduplication didn't work with new threads each iteration
- **Solution**: Explicitly list existing tasks in each prompt
- **Benefit**: Works reliably without thread persistence

### Migration Guide

#### Configuration Changes
```python
# OLD: workflow.py
max_tasks: int = 3  # In CombinedValidationResult

# NEW: workflow.py main()
target_topic = "ConfigMaps and environment variables"
initial_state = {
    "target_topic": target_topic,
    "retry_count": 0,
    "max_retries": 3
}
```

#### Expected Behavior Changes
```bash
# OLD: Generates 3 tasks regardless of success
Task 1: Success → Keep
Task 2: Failure → Remove
Task 3: Success → Keep
Result: 2 tasks kept

# NEW: Generates 1 task, retries on failure
Attempt 1: Failure → Remove → Retry
Attempt 2: Success → Keep → Complete
Result: 1 task kept
```

### Breaking Changes

⚠️ **Workflow API Changes**:
- `generate_next` executor removed, use `retry_generation`
- `task_count` removed from shared state, use `retry_count`
- `max_tasks` removed from shared state, use `max_retries`
- `should_continue` property removed, use `should_retry`

⚠️ **Import Changes**:
```python
# OLD
from workflow import generate_next

# NEW
from workflow import retry_generation
```

### Deprecated

- Multi-task generation mode (use retry mode instead)
- Thread-based deduplication (use explicit task lists)

---

## [1.0.0] - 2026-01-20

### Initial Release

- Agent Framework workflow implementation
- Generator, Validator, and Pytest agents
- Conditional routing (keep/remove tasks)
- Loop implementation with shared state
- DevUI integration
- Workflow visualization (Mermaid, SVG, PNG, PDF)
- MCP filesystem integration
- Azure OpenAI integration

---

## Version Comparison

| Feature | v1.0.0 | v2.0.0 |
|---------|--------|--------|
| Goal | Generate N tasks | Generate 1 task |
| Loop Type | Multi-task | Retry |
| Stop Condition | task_count >= max_tasks | Success OR max_retries |
| Topic | Generic | Specific |
| Deduplication | Thread-based | Explicit list |
| Iterations | Thread-dependent | Independent |
| Thread Client | ResponsesClient | ChatClient |

---

## Upgrade Instructions

### Step 1: Update Imports
```python
# In any custom scripts using workflow executors
from workflow import retry_generation  # was: generate_next
```

### Step 2: Update Workflow Configuration
```python
# In workflow.py or custom workflow scripts
target_topic = "Your Kubernetes Topic"
initial_state = {
    "target_topic": target_topic,
    "retry_count": 0,
    "max_retries": 3  # Adjust as needed
}
```

### Step 3: Test
```bash
python workflow.py
# Should see retry behavior instead of multi-task generation
```

---

## Future Roadmap

### v2.1.0 (Planned)
- [ ] Configurable retry strategies (exponential backoff, etc.)
- [ ] Topic suggestion based on existing tasks
- [ ] Validation result persistence to database

### v2.2.0 (Planned)
- [ ] Parallel task generation for different topics
- [ ] Advanced duplicate detection (semantic similarity)
- [ ] Task difficulty levels

### v3.0.0 (Planned)
- [ ] Multi-agent collaboration for complex tasks
- [ ] Adaptive retry limits based on failure patterns
- [ ] Integration with CI/CD pipelines
