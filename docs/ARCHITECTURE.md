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
- `session.json` (JSON variables for templating)
- `setup.template.yaml` (creates namespace + prereqs)
- `answer.template.yaml` (full solution)
- `test_01_setup.py` (deploy_setup)
- `test_03_answer.py` (deploy_answer)
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

### 3. Filesystem Agent
**Purpose:** Perform file operations using MCP filesystem server

**Capabilities:**
- Read/write files
- Create directories
- List directory contents
- Search files

### 4. Kubernetes Agent
**Purpose:** Execute kubectl commands against K8s clusters

**Features:**
- Run kubectl commands with custom kubeconfig
- Parse JSON output
- Manage cluster resources

### 5. PyTest Agent
**Purpose:** Execute and validate test suites

**Features:**
- Run pytest commands
- Validate task correctness
- Report test results

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
   
3. PyTest Agent
   ↓ Validates generated tasks
   
4. Kubernetes Agent
   ↓ Executes tests against cluster
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
│   ├── k8s_task_generator_agent.py # Task generation
│   ├── k8s_task_idea_agent.py      # Idea generation with memory
│   ├── kubernetes_agent.py         # K8s cluster interaction
│   ├── pytest_agent.py             # Test execution
│   └── logging_middleware.py       # Agent logging
├── docs/
│   └── ARCHITECTURE.md            # This file
├── main.py                        # Main pipeline
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
