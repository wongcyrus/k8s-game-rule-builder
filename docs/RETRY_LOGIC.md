# Retry Logic Implementation Guide

## Overview

The workflow implements a retry-based loop that generates a single successful Kubernetes learning task. If generation, validation, or tests fail, the workflow automatically retries up to a configurable maximum.

## How It Works

### Flow Diagram

```
┌─────────────────┐
│ Generate Task   │ ← Loop back on retry
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
    │   NO    │ → Remove Task → Check Retry Count
    └─────────┘                      │
                                     ▼
                              ┌──────┴──────┐
                              │ Retry < Max?│
                              └──────┬──────┘
                                     │
                              ┌──────┴──────┐
                              │     YES     │ → Retry (loop back)
                              └─────────────┘
                                     │
                              ┌──────┴──────┐
                              │     NO      │ → Complete ✗
                              └─────────────┘
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

1. **Failed task removed**: Directory deleted from filesystem
2. **Retry count incremented**: Tracked in shared state
3. **Fresh context**: New prompt with updated existing tasks list
4. **Topic preserved**: Same topic used for retry attempt
5. **Emphasis on correctness**: Retry prompt stresses syntactic correctness

### Retry Prompt Enhancement

```python
generation_prompt = (
    f"Generate a complete Kubernetes learning task about '{target_topic}' "
    f"with a unique ID in format '###_concept_name'. "
    f"This is retry attempt {retry_count + 1} of {max_retries}. "
    f"\n\nEXISTING TASKS (avoid these IDs): {', '.join(existing_tasks)}"
    f"\n\nCreate ALL required files... "
    f"Make sure all files are syntactically correct and tests will pass."
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

### Scenario 2: Success After Retry

```
🚀 Starting workflow for topic: Secrets and encryption
   Existing tasks: 15

❌ FAILED Validation: Missing file: test_05_check.py
❌ REMOVING TASK: 083_secrets_basic
   Retry attempts: 1/3
🔄 RETRY: Attempt 2/3

✅ Extracted task ID: 084_secrets_encryption
✅ PASSED Validation: All files present and valid
✅ PASSED Tests: All tests passed
✅ KEEPING TASK: 084_secrets_encryption
   Retry attempts: 1
🏁 COMPLETE: Task 084_secrets_encryption successfully generated after 1 retries
```

### Scenario 3: Max Retries Reached

```
🚀 Starting workflow for topic: Advanced networking
   Existing tasks: 15

❌ FAILED Tests: test_05_check.py failed
❌ REMOVING TASK: 085_network_advanced
🔄 RETRY: Attempt 2/3

❌ FAILED Validation: YAML syntax error
❌ REMOVING TASK: 086_network_policies
🔄 RETRY: Attempt 3/3

❌ FAILED Tests: test_05_check.py failed
❌ REMOVING TASK: 087_network_ingress
🏁 COMPLETE: Failed to generate valid task after 3 retries
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

## Troubleshooting

### Issue: Tasks Keep Failing Validation

**Symptoms**: Multiple retries, all fail validation

**Solutions**:
1. Check generator agent instructions for clarity
2. Review validator agent rules
3. Examine failed task files before deletion (add logging)
4. Increase max_retries temporarily to see patterns

### Issue: Tests Always Fail

**Symptoms**: Validation passes, tests fail consistently

**Solutions**:
1. Verify pytest configuration
2. Check test helper functions
3. Review test file patterns in generator instructions
4. Add more specific test requirements to prompts

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
