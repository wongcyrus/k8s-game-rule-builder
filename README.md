# K8s Game Rule Builder

A Python project for building Kubernetes learning game rules using AI agents powered by Azure OpenAI and the Model Context Protocol (MCP).

## Features

- **AI-Powered Task Generation**: Uses Azure OpenAI agents to generate progressive Kubernetes learning tasks (Beginner → Intermediate → Advanced)
- **Fix-on-Failure Workflow**: Failed tasks are fixed in place by a specialized Fixer Agent instead of regenerated from scratch
- **Intelligent Memory System**: Tracks generated and failed concepts across sessions to prevent duplicates
- **MCP Integration**: Leverages the official [Model Context Protocol filesystem server](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) for file operations
- **Automated Test Creation**: Generates complete test suites with setup, validation, and cleanup
- **Template-Based System**: Uses Jinja2 templates with dynamic variable substitution
- **Pure Python Validation**: No LLM for validation or testing — faster, more reliable, cost-effective
- **Retry Loop with Targeted Fixes**: Automatic retry on failure with a Fixer Agent that reads errors and patches only broken files
- **Responses API Support**: Automatic model detection — uses Chat Completions or Responses API based on the configured deployment
- **Skip-Answer Validation**: Extra validation step that confirms `test_05_check.py` fails when the answer is not deployed
- **Comprehensive Logging**: Built-in middleware for debugging and monitoring

## Setup

### Quick Start

Run the setup script to create a virtual environment and install dependencies:

```bash
bash setup.sh
```

The setup script will:
- Create a Python virtual environment (`.venv`)
- Install Jupyter and IPython kernel
- Install all dependencies from `requirements.txt`

**Note**: The MCP filesystem server is automatically managed via `npx` and doesn't require manual installation.

### Manual Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Azure OpenAI Setup

The project authenticates via **Azure CLI credentials** — no API keys in code or environment variables.

1. Install the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
2. Log in:
   ```bash
   az login
   ```
3. Edit `agents/config.py` to point to your Azure OpenAI resource:
   ```python
   @dataclass(frozen=True)
   class AzureOpenAI:
       endpoint: str = "https://your-resource-name.openai.azure.com/"
       deployment_name: str = "gpt-4o"  # Your deployment name
   ```

That's it. All agents pick up the endpoint and model from this single config.

### Changing the Model

To switch models, change `deployment_name` in `agents/config.py`:

```python
@dataclass(frozen=True)
class AzureOpenAI:
    endpoint: str = "https://your-resource-name.openai.azure.com/"
    deployment_name: str = "gpt-4o"  # ← change this
```

The project automatically selects the right API based on the model:

| Model | API Used | How It Works |
|-------|----------|--------------|
| `gpt-4o`, `gpt-4`, `gpt-4o-mini`, etc. | Chat Completions | Standard `OpenAIChatCompletionClient` from agent-framework |
| `gpt-5.3-codex`, `gpt-5-pro`, `gpt-5.1-codex-max`, etc. | Responses API | Custom `ResponsesAgent` with manual tool-call loop |

Detection is based on model prefix matching in `AzureOpenAI.RESPONSES_ONLY_PREFIXES`. If you deploy a new codex/responses-only model, add its prefix there:

```python
RESPONSES_ONLY_PREFIXES: tuple[str, ...] = (
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.1-codex",
    "gpt-5-codex",
    "gpt-5-pro",
    "gpt-5.1-codex-max",
    "your-new-model-prefix",  # ← add here
)
```

### Configuration

All paths and settings live in `agents/config.py`:

```python
@dataclass(frozen=True)
class Paths:
    tests_root: Path = Path("/path/to/tests")       # Where game tasks are generated
    game_name: str = "game02"                        # Target game folder
    pytest_rootdir: Path = Path("/path/to/project")  # Working dir for pytest
    k8s_docs_root: Path = Path("/path/to/k8s/docs")  # K8s docs for idea agent
    unsuccessful_root: Path = Path("/path/to/unsuccessful")  # Failed tasks
```

- **`game_name`** — Change this to generate tasks under a different game folder (e.g., `"game03"`)
- **`tests_root`** — Root directory where game folders live
- **`k8s_docs_root`** — Local copy of Kubernetes docs, read by the Idea Agent via MCP
- **`unsuccessful_root`** — Where failed tasks are moved after all retries are exhausted

### Workflow Tuning

In `workflow/runner.py` you can adjust how many tasks are generated per run and how many fix attempts each task gets:

```python
# workflow/runner.py
num_iterations = 80   # Number of tasks to generate per run

# workflow/models.py (passed via InitialWorkflowState)
max_retries = 3       # Fix attempts per task before giving up
```

## Usage

### Running the Workflow

```bash
source .venv/bin/activate

# Run the full workflow (generates up to 80 tasks with retry loop)
python workflow.py

# Launch DevUI (interactive browser UI)
./launch_devui.sh
# Opens http://localhost:8081
```

### DevUI Sample Prompt

When using DevUI, paste a prompt like this into the workflow input to generate a single task:

```
Generate a complete Kubernetes learning task with ID '050_secrets_management' about 'Kubernetes Secrets'.
Difficulty: BEGINNER.
Objective: Students will learn to create Secrets and mount them in Pods.
Directory already created: /home/developer/Documents/data-disk/k8s/k8s-game-rule/tests/game02/050_secrets_management/
Write all files directly into this directory.
Create ALL required files including __init__.py, instruction.md, concept.md, session.json,
setup.template.yaml, answer.template.yaml, and all test files.
```

Adjust the task ID, topic, difficulty, and directory path to match your setup. The workflow will generate the files, validate them, run tests, and retry with the Fixer Agent if anything fails.

### Running Individual Agents

```bash
source .venv/bin/activate

python -m agents.filesystem_agent
python -m agents.k8s_task_generator_agent
python -m agents.k8s_task_idea_agent
python -m agents.kubernetes_agent
python -m agents.k8s_task_validator
python -m agents.pytest_runner
```

## Architecture

### Agent Overview

| Agent | Uses LLM | Purpose |
|-------|----------|---------|
| **K8s Task Idea Agent** | Yes | Generates unique K8s concepts with 3 difficulty variations. Uses structured outputs or tool-call approach depending on model. |
| **K8s Task Generator Agent** | Yes | Creates complete task scaffolding (templates, tests, docs) via MCP filesystem. |
| **K8s Task Fixer Agent** | Yes | Reads failed tasks, analyzes errors, and makes targeted fixes to broken files only. |
| **Responses Agent** | Yes | Custom agent for codex models that only support the Responses API (not Chat Completions). |
| **K8s Task Validator** | No | Pure Python validation — checks file structure, YAML/Python/JSON syntax, Jinja templates. |
| **PyTest Runner** | No | Pure Python — runs `pytest` via subprocess and parses exit codes. |
| **Filesystem Agent** | Yes | General-purpose file operations via MCP filesystem server. |
| **Kubernetes Agent** | Yes | Executes `kubectl` commands against a K8s cluster. |

### Workflow

The main workflow (`workflow.py` → `workflow/runner.py`) runs 80 iterations by default, each generating one task:

```
Idea Agent → Generate concept with 3 variations
                ↓
         Generator Agent → Create all task files via MCP
                ↓
         Parse Task ID
                ↓
         Validate (pure Python) → Check files, YAML, Python, JSON, Jinja
                ↓
         Run Pytest (pure Python) → Execute test suite
                ↓
         Decision: Pass or Fail?
           ├─ Pass → Skip-Answer Test → Complete ✅
           └─ Fail → Check retry count
                       ├─ Retries left → Fixer Agent → Re-validate (loop)
                       └─ Max retries  → Move to unsuccessful/ ❌
```

Each iteration:
1. Resets minikube (delete + start)
2. Generates a unique concept via the Idea Agent
3. Runs the workflow with up to 3 fix attempts per task
4. Tracks success/failure in memory files

### Key Design Decisions

**Fix instead of regenerate**: On failure, the Fixer Agent reads the existing files, analyzes the specific errors (validation failures, test output), and patches only the broken files. This preserves working code and has a higher success rate than regenerating from scratch.

**No LLM for validation/testing**: Validation and test execution are deterministic operations. Using pure Python functions is faster, cheaper, and more reliable than routing through an LLM.

**Skip-answer validation**: After tests pass, an extra step runs pytest with `SKIP_ANSWER_TESTS=True` to confirm that `test_05_check.py` correctly fails when the answer isn't deployed. This catches tests that would pass regardless of the student's answer.

**Dual API support**: The `AzureOpenAI` config detects codex models and automatically uses the Responses API. Other models use Chat Completions. The `ResponsesAgent` class handles the Responses API tool-call loop manually.

## Project Structure

```
k8s-game-rule-builder/
├── agents/
│   ├── config.py                   # Centralized paths, Azure, validation config
│   ├── filesystem_agent.py         # MCP filesystem operations
│   ├── k8s_task_generator_agent.py # Task generation (LLM + MCP)
│   ├── k8s_task_fixer_agent.py     # Targeted task fixing (LLM + MCP)
│   ├── k8s_task_idea_agent.py      # Idea generation with memory
│   ├── k8s_task_validator.py       # Pure Python validator (no LLM)
│   ├── kubernetes_agent.py         # kubectl command execution
│   ├── pytest_runner.py            # Pure Python test runner (no LLM)
│   ├── responses_agent.py          # Custom Responses API agent for codex models
│   └── logging_middleware.py       # Function invocation logging
├── workflow/
│   ├── builder.py                  # Workflow graph construction
│   ├── executors.py                # Step implementations (12 executors)
│   ├── models.py                   # Data models (Pydantic + dataclasses)
│   ├── selectors.py                # Conditional routing functions
│   ├── runner.py                   # Main runner (multi-iteration loop)
│   ├── idea_generator.py           # Idea generation logic
│   └── README.md                   # Workflow package docs
├── docs/
│   ├── ARCHITECTURE.md             # Technical architecture & design
│   ├── FIX_WORKFLOW.md             # Fix-on-failure workflow details
│   └── RETRY_LOGIC.md             # Retry implementation guide
├── workflow.py                     # Entry point (delegates to workflow/runner.py)
├── launch_devui.sh                 # Launch DevUI script
├── launch_devui_full.py            # DevUI setup with full workflow
├── setup.sh                        # Environment setup
├── requirements.txt                # Python dependencies
├── task_ideas_memory.json          # Generated concepts memory
├── task_ideas_failure_memory.json  # Failed concepts memory
├── workflow_graph.png              # Workflow visualization
├── CHANGELOG.md                    # Version history
└── README.md                       # This file
```

## Generated Task Structure

Each task is generated under `tests/<game_name>/<task_id>/`:

| File | Description |
|------|-------------|
| `__init__.py` | Empty (package marker) |
| `instruction.md` | Student-facing challenge description |
| `concept.md` | Learning material (no solution code) |
| `session.json` | Template variables (plain JSON) |
| `setup.template.yaml` | Namespace + prerequisites (Jinja2) |
| `answer.template.yaml` | Complete solution (Jinja2) |
| `test_01_setup.py` | Deploy setup resources |
| `test_02_ready.py` | Wait for setup resources to be ready |
| `test_03_answer.py` | Deploy answer resources |
| `test_04_challenge.py` | Optional — triggers/load generation |
| `test_05_check.py` | Validate the solution |
| `test_06_cleanup.py` | Delete namespace |

## Memory System

The project uses two JSON files for cross-session memory:

- **`task_ideas_memory.json`** — Successfully generated concepts (prevents re-generation)
- **`task_ideas_failure_memory.json`** — Concepts that failed validation/testing (prevents retrying known failures)

Memory is injected into the Idea Agent via `TaskIdeasMemoryMiddleware` (Chat Completions) or prepended to instructions (Responses API).

## MCP Integration

Agents interact with the filesystem through the official [@modelcontextprotocol/server-filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) package:

```python
mcp_tool = MCPStdioTool(
    name="filesystem",
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", str(allowed_directory)],
    load_prompts=False,
)
```

- Launched via `npx` (no manual installation)
- Sandboxed to specified directories
- Supports read/write files, directory operations, search
- Lazy connection — connects on first use in DevUI

## Documentation

- [CHANGELOG.md](CHANGELOG.md) — Version history and migration guides
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Agent architecture, validation patterns, MCP details
- [docs/FIX_WORKFLOW.md](docs/FIX_WORKFLOW.md) — Fix-on-failure workflow architecture
- [docs/RETRY_LOGIC.md](docs/RETRY_LOGIC.md) — Retry configuration, troubleshooting, best practices
- [workflow/README.md](workflow/README.md) — Workflow package structure and components

## Requirements

- Python 3.x
- Azure OpenAI API access (with Azure CLI credential)
- Node.js (for `npx` to run MCP server)
- kubectl + minikube (for Kubernetes interaction and testing)
- DevUI (optional): `pip install agent-framework[devui]`
