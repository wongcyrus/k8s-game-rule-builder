# K8s Game Rule Builder - Architecture

## System Overview

A Python project for building Kubernetes learning game rules using AI agents powered by Azure OpenAI and the Model Context Protocol (MCP).

## Agent Architecture

### 1. K8s Task Idea Agent
**Purpose:** Generate unique Kubernetes learning task concepts with progressive difficulty levels

**Key Features:**
- Reads official Kubernetes documentation
- Generates comprehensive learning concepts with 3 variations each (Beginner → Intermediate → Advanced)
- Persistent memory to prevent duplicate concepts
- Stores concepts in `.task_ideas_memory.json`

**Memory Structure:**
```json
{
  "ideas": {
    "concept_key": {
      "concept": "Pod Disruption Budgets (PDBs)",
      "description": "Detailed description...",
      "variations": [
        "071_pod_disruption_budget_basic",
        "072_pod_disruption_budget_intermediate", 
        "073_pod_disruption_budget_advanced"
      ],
      "difficulty": "Mixed (Beginner→Intermediate→Advanced)",
      "tags": ["scheduling", "policies", "availability"]
    }
  }
}
```

**Example Task Progression:**
- **BEGINNER (071)** — 30 min: Basic PDB with `minAvailable`
- **INTERMEDIATE (072)** — 45 min: `maxUnavailable` vs `minAvailable`  
- **ADVANCED (073)** — 75 min: Multi-tier apps with StatefulSets

### 2. K8s Task Generator Agent
**Purpose:** Generate fully scaffolded Kubernetes game tasks under `tests/game02/XXX_descriptive_name/`

**Generated Files per Task:**
- `__init__.py` (empty)
- `instruction.md` (user-facing challenge)
- `concept.md` (learning material explaining the Kubernetes concept - NO solution code)
- `session.json` (JSON variables for templating)
- `setup.template.yaml` (creates namespace + prereqs)
- `answer.template.yaml` (full solution)
- `test_01_setup.py` (deploy_setup)
- `test_02_ready.py` (wait for setup resources)
- `test_03_answer.py` (deploy_answer)
- `test_04_challenge.py` (optional - triggers/load if needed)
- `test_05_check.py` (validation with kubectl + JSON parsing)
- `test_06_cleanup.py` (delete_namespace)

**Template Variable Rules:**
- Use Jinja-style double braces with spaces: `{{ variable }}`
- Common patterns:
  - `{{random_name()}}{{random_number(1,10)}}{{student_id()}}`
  - `{{random_name()}}`, `{{random_number(1000, 9999)}}`
  - `{{base64_encode(random_name())}}`
- `session.json` is pure JSON (no Jinja conditionals)
- Templates can use Jinja loops/conditionals with `# {% ... %}` comment style

**TestCheck Pattern:**
```python
class TestCheck:
    def test_validation(self, json_input):
        kube_config = build_kube_config(json_input[...])
        output = run_kubectl_command(kube_config, "get pods -o json")
        data = json.loads(output)
        assert data['items'][0]['metadata']['name'] == expected_name
```

### 3. K8s Task Validator (Pure Python - No LLM)
**Purpose:** Validate generated task structure and syntax without using LLM

**Key Features:**
- **No LLM required** - Pure Python validation functions
- Deterministic file checks (required files, structure)
- YAML syntax validation with Jinja2 template support
- Python AST parsing for syntax errors
- JSON validation for session files
- Returns structured validation results

**Validation Checks:**
```python
def validate_task_directory(task_dir: str) -> dict:
    """Main validation function - call directly, no agent needed."""
    # 1. Check required files exist
    # 2. Validate YAML syntax (with Jinja2 sanitization)
    # 3. Validate Python syntax (AST parsing)
    # 4. Validate JSON structure
    # 5. Validate Jinja2 template syntax
    return {"is_valid": bool, "reason": str, "details": list}
```

**Why No LLM?**
- Validation is deterministic (file exists? syntax valid?)
- Faster execution (no API calls)
- More reliable (no LLM hallucinations)
- Cost-effective (no token usage)

### 4. PyTest Runner (Pure Python - No LLM)
**Purpose:** Execute pytest test suites without using LLM

**Key Features:**
- **No LLM required** - Direct subprocess execution
- Runs pytest commands with proper configuration
- Parses exit codes (0 = success, non-zero = failure)
- Returns structured test results
- Captures stdout/stderr for debugging

**Test Execution:**
```python
def run_pytest_command(pytest_command: str) -> dict:
    """Run pytest directly - no agent needed."""
    result = subprocess.run(
        pytest_command,
        shell=True,
        capture_output=True,
        text=True
    )
    return {
        "is_valid": result.returncode == 0,
        "reason": "All tests passed" if success else "Tests failed",
        "details": result.stdout + result.stderr
    }
```

**Why No LLM?**
- Test execution is deterministic (exit code 0 or not)
- Faster execution (no API calls)
- More reliable (no interpretation needed)
- Cost-effective (no token usage)

### 5. Filesystem Agent
**Purpose:** Perform file operations using MCP filesystem server

**Capabilities:**
- Read/write files
- Create directories
- List directory contents
- Search files

### 6. Kubernetes Agent
**Purpose:** Execute kubectl commands against K8s clusters

**Features:**
- Run kubectl commands with custom kubeconfig
- Parse JSON output
- Manage cluster resources

## MCP Integration

All agents use the official [@modelcontextprotocol/server-filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) package.

**Configuration:**
```python
mcp_tool = MCPStdioTool(
    name="filesystem",
    command="npx",
    args=[
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/allowed/directory"
    ],
    load_prompts=False
)
```

**Benefits:**
- ✅ No manual installation (npx handles it)
- ✅ Always uses latest version
- ✅ Official Model Context Protocol implementation
- ✅ Directory access control for security

## Logging Middleware

All agents include `LoggingFunctionMiddleware` for comprehensive observability.

**Features:**
- Pre-execution logging
- Argument tracking
- Execution timing
- Result logging
- Error handling with full traceback

**Usage:**
```python
from agents.logging_middleware import get_logging_middleware

agent = responses_client.as_agent(
    name="MyAgent",
    instructions="...",
    tools=my_tools,
    middleware=[get_logging_middleware()],
)
```

**Log Output:**
```
INFO:agents.logging_middleware:[Function] Calling run_kubectl_command
DEBUG:agents.logging_middleware:[Function] Arguments: {'command': 'get pods'}
INFO:agents.logging_middleware:[Function] run_kubectl_command completed successfully in 2.345s
```

## Workflow Pipeline

```
1. K8s Task Idea Agent
   ↓ Generates unique concept with 3 variations
   
2. K8s Task Generator Agent
   ↓ Creates full task structure (templates, tests)
   
3. K8s Task Validator (Pure Python - No LLM)
   ↓ Validates file structure and syntax
   
4. PyTest Runner (Pure Python - No LLM)
   ↓ Executes tests and validates results
   
5. Kubernetes Agent (Optional)
   ↓ Executes tests against cluster
```

## Validation & Testing (No LLM Required)

### Why Remove LLM from Validation/Testing?

**Before (with LLM):**
- Validator agent called LLM to "validate" files
- PyTest agent called LLM to "run tests"
- Slower (API calls), less reliable (hallucinations), costly (tokens)

**After (without LLM):**
- Direct Python functions for validation
- Direct subprocess calls for pytest
- Faster, more reliable, cost-effective

### Validator Implementation

```python
# agents/k8s_task_validator.py
def validate_task_directory(task_dir: str) -> dict:
    """Pure Python validation - no LLM needed."""
    results = []
    
    # Check required files
    results.append(check_required_files(task_dir))
    
    # Validate YAML syntax
    for yaml_file in VALIDATION.yaml_files:
        results.append(validate_yaml_file(yaml_file))
    
    # Validate Python syntax (AST parsing)
    for py_file in VALIDATION.py_files:
        results.append(validate_python_file(py_file))
    
    # Validate JSON
    for json_file in VALIDATION.json_files:
        results.append(validate_json_file(json_file))
    
    overall_valid = all(r["is_valid"] for r in results)
    return {"is_valid": overall_valid, "reason": "...", "details": results}
```

### PyTest Runner Implementation

```python
# agents/pytest_runner.py
def run_pytest_command(pytest_command: str) -> dict:
    """Direct pytest execution - no LLM needed."""
    result = subprocess.run(
        pytest_command,
        shell=True,
        capture_output=True,
        text=True,
        cwd=PATHS.pytest_rootdir
    )
    
    is_valid = result.returncode == 0
    return {
        "is_valid": is_valid,
        "reason": "All tests passed" if is_valid else "Tests failed",
        "details": result.stdout + result.stderr
    }
```

### Workflow Integration

```python
# workflow.py - Direct executor calls (no agent wrappers)

@executor(id="run_validation")
async def run_validation(task_info: TaskInfo, ctx: WorkflowContext) -> None:
    """Run validation directly without LLM."""
    from agents.k8s_task_validator import validate_task_directory
    result = validate_task_directory(task_info.task_id)
    # ... process result

@executor(id="run_pytest")
async def run_pytest(task_with_val: TaskWithValidation, ctx: WorkflowContext) -> None:
    """Run pytest directly without LLM."""
    from agents.pytest_runner import run_pytest_command
    result = run_pytest_command(f"pytest {task_with_val.task_directory}/")
    # ... process result
```

## Memory Management

**Context Providers (Dynamic Memory):**
- `TaskIdeasMemory` extends `ContextProvider`
- **invoking()**: Injects previously generated ideas before each call
- **invoked()**: Extracts and stores new ideas from responses

**File-Based Persistence:**
- Ideas stored in `.task_ideas_memory.json`
- Survives application restarts
- Prevents duplicate generation

## Running the System

### Full Pipeline
```bash
source .venv/bin/activate
python main.py
```

### Individual Agents
```bash
# Generate task ideas
python -m agents.k8s_task_idea_agent

# Generate complete task
python -m agents.k8s_task_generator_agent

# Test file operations
python -m agents.filesystem_agent
```

## Project Structure
```
k8s-game-rule-builder/
├── agents/
│   ├── filesystem_agent.py         # MCP filesystem operations
│   ├── k8s_task_generator_agent.py # Task generation (uses LLM)
│   ├── k8s_task_idea_agent.py      # Idea generation with memory (uses LLM)
│   ├── k8s_task_validator.py       # Pure Python validator (NO LLM)
│   ├── kubernetes_agent.py         # K8s cluster interaction
│   ├── pytest_runner.py            # Pure Python test runner (NO LLM)
│   ├── logging_middleware.py       # Agent logging
│   └── config.py                   # Centralized configuration
├── docs/
│   ├── ARCHITECTURE.md            # This file
│   └── RETRY_LOGIC.md             # Retry implementation guide
├── main.py                        # Main pipeline
├── workflow.py                    # Conditional workflow with retry
├── visualize_workflow.py          # Workflow visualization
├── setup.sh                       # Environment setup
└── requirements.txt               # Dependencies
```

## Technical Stack

- **Python 3.x** with virtual environment
- **Azure OpenAI** for agent intelligence
- **Model Context Protocol (MCP)** for tool integration
- **Jinja2** for templating
- **PyTest** for validation
- **kubectl** for Kubernetes interaction
