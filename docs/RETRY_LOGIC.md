# Retry Logic Implementation Guide

## Overview

The workflow implements a retry-based loop that generates a single successful Kubernetes learning task. If generation, validation, or tests fail, the workflow automatically attempts to **fix** the failed task instead of regenerating from scratch, up to a configurable maximum number of retries.

## Key Change: Fix Instead of Regenerate

**Previous behavior**: On failure, the workflow would regenerate the entire task from scratch, often repeating the same mistakes.

**New behavior**: On failure, the workflow uses a specialized **Fixer Agent** that:
1. Reads the failed task files from the unsuccessful folder
2. Analyzes the specific errors (validation failures, test failures)
3. Makes targeted fixes to the problematic files
4. Moves the fixed files back to the game folder for re-validation

This approach is more effective because:
- The fixer can see exactly what went wrong
- It preserves working code and only fixes broken parts
- It learns from the specific error messages
- It's more likely to succeed on retry

## How It Works

### Flow Diagram

```
┌─────────────────┐
│ Generate Task   │ ← First attempt only
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Validate Files  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Run Tests     │
└────────┬────────┘
         │
         ▼
    ┌────┴────┐
    │ Success?│
    └────┬────┘
         │
    ┌────┴────┐
    │   YES   │ → Keep Task → Complete ✓
    └─────────┘
         │
    ┌────┴────┐
    │   NO    │ → Move to Unsuccessful → Check Retry Count
    └─────────┘                              │
                                             ▼
                                      ┌──────┴──────┐
                                      │ Retry < Max?│
                                      └──────┬──────┘
                                             │
                                      ┌──────┴──────┐
                                      │     YES     │ → Fix Task (not regenerate!)
                                      └─────────────┘      │
                                             │             ▼
                                      ┌──────┴──────┐  ┌─────────────┐
                                      │     NO      │  │ Fixer Agent │
                                      └─────────────┘  └──────┬──────┘
                                             │                │
                                             ▼                ▼
                                        Complete ✗      Validate Files (loop back)
```

## Configuration

### Basic Setup

```python
# In workflow.py main()
target_topic = "ConfigMaps and environment variables"

initial_state = {
    "target_topic": target_topic,
    "retry_count": 0,
    "max_retries": 3  # Adjust based on needs
}
```

### Recommended Retry Limits

| Task Complexity | Recommended max_retries |
|----------------|------------------------|
| Simple (basic resources) | 2 |
| Medium (multiple resources) | 3 (default) |
| Complex (advanced patterns) | 5 |

## Retry Logic Details

### When Retries Occur

Retries happen when:
1. **Parse Failure**: Task ID cannot be extracted from generator response
2. **Validation Failure**: Missing files, syntax errors, or template issues
3. **Test Failure**: Pytest tests fail

### What Happens on Retry

1. **Failed task moved**: Directory moved to unsuccessful folder with FAILURE_REPORT.txt
2. **Retry count incremented**: Tracked in shared state
3. **Fixer agent invoked**: Analyzes and fixes the specific errors (NEW!)
4. **Topic preserved**: Same topic and task ID used for fix attempt
5. **Targeted fixes**: Only broken parts are fixed, working code preserved

### Fixer Agent Approach

The fixer agent receives:
- Path to the failed task in unsuccessful folder
- Detailed failure reasons (validation errors, test failures)
- Full test output (if available)
- Task metadata (concept, description, difficulty, objective)

The fixer agent then:
1. **Reads** ALL existing files from unsuccessful folder (complete task)
2. **Analyzes** FAILURE_REPORT.txt and test output
3. **Identifies** specific errors (missing files, syntax errors, logic errors)
4. **Fixes** the problematic content in memory
5. **Writes** COMPLETE task directory (ALL 10-11 files) to the game folder

**CRITICAL**: 
- Tests run as a SUITE and need ALL files present together
- The fixer does NOT edit files in place
- It reads ALL files from unsuccessful folder
- Fixes broken files in memory
- Writes COMPLETE task directory to game folder (fixed + unchanged files)
- This ensures validation and tests run on the complete, fixed task

### Retry Prompt Enhancement

**Generator prompt** (first attempt):
```python
generation_prompt = (
    f"Generate a complete Kubernetes learning task with ID '{task_id}' about '{target_topic}' "
    f"with a unique ID in format '###_concept_name'. "
    f"\n\nEXISTING TASKS (avoid these IDs): {', '.join(existing_tasks)}"
    f"\n\nCreate ALL required files... "
)
```

**Fixer prompt** (retry attempts):
```python
fix_prompt = (
    f"Fix the failed Kubernetes task '{task_id}' located in 'unsuccessful/{game_name}/{task_id}/'."
    f"\n\nThis is fix attempt {retry_count + 1} of {max_retries}."
    f"\n\n⚠️  TASK FAILED WITH THESE ERRORS:"
    f"\n{failure_reasons}"
    f"\n\n📋 FULL TEST OUTPUT:"
    f"\n{raw_test_output}"
    f"\n\n🔍 YOUR TASK:"
    f"\n1. READ ALL existing files (complete task)"
    f"\n2. READ the FAILURE_REPORT.txt"
    f"\n3. ANALYZE the specific errors"
    f"\n4. Make TARGETED FIXES (do NOT regenerate everything)"
    f"\n5. CRITICAL: WRITE COMPLETE TASK DIRECTORY (ALL 10-11 files) to '{game_name}/{task_id}/'"
    f"\n\n⚠️  CRITICAL FILE WRITING REQUIREMENTS:"
    f"\n- Tests run as a SUITE - ALL files must be present together!"
    f"\n- Write ALL required files (10-11 files total)"
    f"\n- If a file is missing → create it"
    f"\n- If a file is broken → fix it"
    f"\n- If a file is working → copy it unchanged"
)
```

## Success Criteria

A task is kept only if **BOTH** conditions are met:
1. ✅ Validation passes (all files present, syntax correct)
2. ✅ Tests pass (all pytest tests succeed)

## Termination Conditions

The workflow completes when:
1. **Success**: Task passes validation AND tests → Keep task, complete workflow
2. **Max Retries**: Retry count reaches max_retries → Complete workflow without task

## State Management

### Shared State Variables

```python
{
    "target_topic": str,           # Kubernetes concept to generate
    "retry_count": int,            # Current retry attempt (0-based)
    "max_retries": int,            # Maximum allowed retries
    "validation_{task_id}": dict   # Validation results per task
}
```

### State Flow

```
Initial State:
  retry_count = 0
  target_topic = "ConfigMaps and environment variables"
  max_retries = 3

On Failure:
  retry_count += 1
  Failed task removed
  Check: retry_count < max_retries?
    YES → Retry with updated context
    NO  → Complete workflow

On Success:
  Keep task
  Complete workflow
```

## Example Scenarios

### Scenario 1: Success on First Try

```
🚀 Starting workflow for topic: ConfigMaps and environment variables
   Existing tasks: 15

✅ Extracted task ID: 082_configmap_env_vars
✅ PASSED Validation: All files present and valid
✅ PASSED Tests: All tests passed
✅ KEEPING TASK: 082_configmap_env_vars
   Retry attempts: 0
🏁 COMPLETE: Task 082_configmap_env_vars successfully generated after 0 retries
```

### Scenario 2: Success After Fix

```
🚀 Starting workflow for topic: Secrets and encryption
   Existing tasks: 15

❌ FAILED Validation: Missing file: test_05_check.py
❌ MOVING TASK to unsuccessful: 083_secrets_basic
   Retry attempts: 1/3
🔧 FIXING TASK: Attempt 2/3

[Fixer Agent reads files, analyzes FAILURE_REPORT.txt]
[Fixer Agent creates missing test_05_check.py]
[Fixer Agent moves fixed files to game02/083_secrets_basic/]

✅ Extracted task ID: 083_secrets_basic
✅ PASSED Validation: All files present and valid
✅ PASSED Tests: All tests passed
✅ KEEPING TASK: 083_secrets_basic
   Retry attempts: 1
🏁 COMPLETE: Task 083_secrets_basic successfully generated after 1 fix attempt
```

### Scenario 3: Multiple Fixes Required

```
🚀 Starting workflow for topic: Advanced networking
   Existing tasks: 15

❌ FAILED Tests: test_05_check.py - AssertionError: Expected port 80, got 8080
❌ MOVING TASK to unsuccessful: 085_network_advanced
🔧 FIXING TASK: Attempt 2/3

[Fixer Agent reads test output, identifies port mismatch]
[Fixer Agent fixes answer.template.yaml to use port 80]
[Fixer Agent moves fixed files back]

❌ FAILED Tests: test_02_ready.py - TimeoutError: Deployment not ready
❌ MOVING TASK to unsuccessful: 085_network_advanced
🔧 FIXING TASK: Attempt 3/3

[Fixer Agent reads test output, identifies missing readiness check]
[Fixer Agent adds proper polling loop to test_02_ready.py]
[Fixer Agent moves fixed files back]

✅ Extracted task ID: 085_network_advanced
✅ PASSED Validation: All files present and valid
✅ PASSED Tests: All tests passed
✅ KEEPING TASK: 085_network_advanced
   Retry attempts: 2
🏁 COMPLETE: Task 085_network_advanced successfully generated after 2 fix attempts
```

### Scenario 4: Max Retries Reached

```
🚀 Starting workflow for topic: Complex StatefulSet with PVCs
   Existing tasks: 15

❌ FAILED Tests: test_05_check.py failed
❌ MOVING TASK to unsuccessful: 086_statefulset_complex
🔧 FIXING TASK: Attempt 2/3

❌ FAILED Validation: YAML syntax error in setup.template.yaml
❌ MOVING TASK to unsuccessful: 086_statefulset_complex
🔧 FIXING TASK: Attempt 3/3

❌ FAILED Tests: test_05_check.py failed
❌ MOVING TASK to unsuccessful: 086_statefulset_complex
🏁 COMPLETE: Failed to generate valid task after 3 fix attempts
```

## Duplicate Prevention

### How It Works

Each retry gets a fresh list of existing tasks:

```python
# Get existing tasks
game02_dir = PATHS.tests_root / "game02"
existing_tasks = [d.name for d in game02_dir.iterdir() 
                  if d.is_dir() and d.name[0].isdigit()]

# Include in prompt
prompt = f"EXISTING TASKS (avoid these IDs): {', '.join(existing_tasks)}"
```

### Why This Works

- **No thread persistence**: Each iteration is independent
- **Explicit listing**: Generator sees all existing IDs
- **Refreshed each retry**: List updated after failed task removed
- **Clear instruction**: Generator told to avoid these IDs

## Agents in the Workflow

### Generator Agent (First Attempt)

**Purpose**: Creates a complete task from scratch based on the concept

**When used**: Only on the first attempt (retry_count = 0)

**Capabilities**:
- Generates all required files (11 files total)
- Creates proper Jinja2 templates
- Writes pytest test files
- Follows established patterns

**Instructions**: See `agents/k8s_task_generator_agent.py`

### Fixer Agent (Retry Attempts)

**Purpose**: Fixes failed tasks instead of regenerating from scratch

**When used**: On all retry attempts (retry_count > 0)

**Capabilities**:
- Reads existing files from unsuccessful folder
- Analyzes FAILURE_REPORT.txt
- Parses test output to identify errors
- Makes targeted fixes to specific files
- Moves fixed files back to game folder

**Instructions**: See `agents/k8s_task_fixer_agent.py`

**Key differences from Generator**:
- Focuses on fixing, not creating
- Preserves working code
- Analyzes specific error messages
- More likely to succeed on complex tasks

### Why Two Agents?

The separation provides several benefits:

1. **Specialized instructions**: Each agent has focused, specific instructions
2. **Better success rate**: Fixer can see exactly what went wrong
3. **Efficiency**: Fixer only changes what's broken
4. **Learning**: Fixer learns from specific errors, not generic requirements
5. **Debugging**: Easier to debug when agents have clear responsibilities

## Troubleshooting

### Issue: Tasks Keep Failing Validation

**Symptoms**: Multiple retries, all fail validation

**Solutions**:
1. Check generator agent instructions for clarity
2. Review validator agent rules
3. Examine failed task files before deletion (add logging)
4. Increase max_retries temporarily to see patterns

### Issue: Tests Always Fail

**Symptoms**: Multiple retries, all fail tests, especially test_02_ready.py

**Common Root Cause**: test_02_ready.py checking answer.template.yaml resources instead of setup.template.yaml resources

**Solutions**:
1. Verify test_02_ready.py checks resources from setup.template.yaml (NOT answer.template.yaml)
2. Check test flow: test_01_setup → test_02_ready (checks setup) → test_03_answer → test_05_check (checks answer)
3. See [TEST_02_READY_COMMON_ERROR.md](../TEST_02_READY_COMMON_ERROR.md) for detailed explanation
4. Verify pytest configuration
5. Check test helper functions
6. Review test file patterns in generator instructions
7. Add more specific test requirements to prompts

### Issue: Tests Marked as Failed When They Passed (Fixed in v2.0.1)

**Symptoms**: Output shows "Passed: ✅ 5, Failed: ❌ 0" but workflow says "Tests failed"

**Root Cause**: 
- Pytest exit code handling issue
- Naive string parsing that failed on "Failed: ❌ 0"

**Solution**: 
- Fixed in v2.0.1
- Upgrade to latest version
- See [CHANGELOG.md](../CHANGELOG.md) for details

**Verification**:
```bash
# Check version
grep "## \[2.0.1\]" CHANGELOG.md

# Should see the bug fix entry
```

### Issue: Duplicate Task IDs

**Symptoms**: Same task ID generated multiple times

**Solutions**:
1. Verify existing_tasks list is populated correctly
2. Check generator agent receives the list
3. Review task ID extraction regex
4. Add more emphasis in prompt to avoid duplicates

### Issue: Max Retries Too Low

**Symptoms**: Workflow completes without success frequently

**Solutions**:
1. Increase max_retries (try 5 for complex topics)
2. Improve generator instructions
3. Add more examples to agent prompts
4. Simplify topic if too complex

## Best Practices

### 1. Topic Selection

✅ **Good Topics** (specific, focused):
- "ConfigMaps and environment variables"
- "Persistent Volumes and Claims"
- "Network Policies for pod isolation"
- "Resource limits and requests"

❌ **Bad Topics** (vague, broad):
- "Kubernetes basics"
- "Advanced concepts"
- "Everything about pods"

### 2. Retry Configuration

```python
# Simple tasks
max_retries = 2

# Medium complexity (default)
max_retries = 3

# Complex tasks
max_retries = 5

# Very complex or experimental
max_retries = 7
```

### 3. Monitoring

Add logging to track patterns:

```python
# In remove_task executor
logging.info(f"Failure reason: {combined.validation.reason}")
logging.info(f"Test output: {combined.test.reason}")
```

### 4. Prompt Tuning

If success rate is low:
- Add more examples to generator instructions
- Emphasize common failure points
- Include specific syntax requirements
- Reference successful task examples

## Performance Considerations

### Time per Retry

Approximate times:
- Generation: 30-60 seconds
- Validation: 5-10 seconds
- Tests: 10-30 seconds
- **Total per attempt**: ~1-2 minutes

### Total Workflow Time

```
Best case (success on first try): ~1-2 minutes
Average case (1-2 retries): ~3-5 minutes
Worst case (max retries): ~5-10 minutes
```

## Advanced Usage

### Custom Retry Strategy

```python
# Exponential backoff (future enhancement)
retry_delays = [0, 5, 15, 45]  # seconds
await asyncio.sleep(retry_delays[retry_count])
```

### Conditional Max Retries

```python
# Adjust based on topic complexity
if "advanced" in target_topic.lower():
    max_retries = 5
else:
    max_retries = 3
```

### Retry Metrics

```python
# Track success rate
total_attempts = retry_count + 1
success_rate = 1.0 if should_keep else 0.0
logging.info(f"Success rate: {success_rate} after {total_attempts} attempts")
```

## Related Documentation

- [WORKFLOW.md](../WORKFLOW.md) - Complete workflow architecture
- [CHANGELOG.md](../CHANGELOG.md) - Version history and changes
- [README.md](../README.md) - Quick start guide
