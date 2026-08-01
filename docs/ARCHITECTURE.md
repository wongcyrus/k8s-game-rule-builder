# K8s Game Rule Builder — Architecture

## System Overview

AI agents powered by Azure OpenAI generate Kubernetes learning game tasks. Each task is a self-contained directory with templates, tests, and documentation. The workflow generates tasks in a loop, validates them, runs tests against a minikube cluster, and uses a Fixer Agent to patch failures in place.

Authentication uses **Azure CLI credentials** (`AzureCliCredential`). The configured model determines which API is used — Chat Completions for standard models, Responses API for codex models. See `agents/config.py`.
The runtime is intentionally **fail-fast**: required state/config must be present, and malformed tool outputs are surfaced as errors instead of being silently defaulted.

### High-Level Overview

```mermaid
graph LR
    subgraph "Per Iteration (×80)"
        A[🧠 Idea Agent] --> B[⚙️ Generator Agent]
        B --> C[✅ Validate + Test]
        C -->|Pass| D[🏁 Done]
        C -->|Fail| E[🔧 Fixer Agent]
        E --> C
    end
    M[(Memory JSON)] <-.-> A
    MCP[📁 MCP Filesystem] <-.-> B
    MCP <-.-> E
    K8s[☸ Minikube] <-.-> C
```

## Agents

| Agent | File | LLM | Purpose |
|-------|------|-----|---------|
| Task Idea | `k8s_task_idea_agent.py` | Yes | Generate unique K8s concepts with 3 difficulty variations |
| Task Generator | `k8s_task_generator_agent.py` | Yes | Create complete task scaffolding via MCP filesystem |
| Task Fixer | `k8s_task_fixer_agent.py` | Yes | Read errors, patch only broken files in place |
| Responses Agent | `responses_agent.py` | Yes | Custom agent for codex models (Responses API only) |
| Task Validator | `k8s_task_validator.py` | No | Check file structure, YAML/Python/JSON syntax, Jinja templates |
| PyTest Runner | `pytest_runner.py` | No | Run pytest via subprocess, parse exit codes |
| Filesystem | `filesystem_agent.py` | Yes | General-purpose MCP file operations |
| Kubernetes | `kubernetes_agent.py` | Yes | Execute kubectl commands |

## Workflow

The runner (`workflow/runner.py`) executes **80 iterations by default** and supports CLI overrides (`--iterations`, `--max-retries`, minikube reset/timeouts, graph output, stop file). Each iteration generates one task:

```mermaid
flowchart TD
    START([Start Iteration]) --> RESET[🔄 Reset Minikube]
    RESET --> IDEA[🧠 Idea Agent<br/>Generate concept]
    IDEA --> INIT[Initialize Retry<br/>Pre-create task dir]
    INIT --> GEN[⚙️ Generator Agent<br/>Create all files via MCP]
    GEN --> PARSE[Parse Task ID]
    PARSE --> VAL[✅ Validate<br/>Files · YAML · Python · JSON · Jinja]
    VAL --> TEST[🧪 Run Pytest<br/>Against minikube]
    TEST --> DEC{Pass?}

    DEC -->|Yes| KEEP[Keep Task]
    DEC -->|No| FAIL[Record Failure<br/>Increment retry]

    KEEP --> SKIP[🧪 Skip-Answer Test<br/>SKIP_ANSWER_TESTS=True]
    SKIP --> SKIPQ{test_05 failed<br/>as expected?}
    SKIPQ -->|Yes| DONE([✅ Complete])
    SKIPQ -->|No| LOOP

    FAIL --> LOOP{Retry < Max?}
    LOOP -->|Yes| FIX[🔧 Fix Task<br/>Build prompt with errors]
    LOOP -->|No| MOVE[❌ Move to<br/>unsuccessful/]
    MOVE --> DONE2([❌ Complete])

    FIX --> FIXER[🔧 Fixer Agent<br/>Patch broken files in place]
    FIXER --> PARSE

    style GEN fill:#4a9eff,color:#fff
    style FIXER fill:#ff9f43,color:#fff
    style DONE fill:#2ecc71,color:#fff
    style DONE2 fill:#e74c3c,color:#fff
    style IDEA fill:#a29bfe,color:#fff
```

Minikube is reset (delete + start) before each iteration.

### Key behaviors

- **Fix, not regenerate**: On failure the Fixer Agent reads existing files, analyzes errors, and writes only the broken files back. The task stays in the game folder throughout retries.
- **No fallback assumptions**: Executors require explicit state (`retry_count`, `max_retries`, validation state, failure reason state). Missing data raises explicit errors to avoid hidden drift.
- **Skip-answer validation**: After tests pass, pytest runs again with `SKIP_ANSWER_TESTS=True` to confirm `test_05_check.py` fails when the answer isn't deployed.
- **Failure reporting**: After max retries, the task is moved to `unsuccessful/<game_name>/` with a `FAILURE_REPORT.txt` containing failure reasons, session.json content, and raw test output.
- **Interrupt-safe stop path**: User-requested stops do not classify the current concept into success or failure memory. Instead, the runner removes it from memory and cleans partial task artifacts.
- **Preferred stop mechanism**: The primary stop path is a polled stop file (default `.workflow-stop`). `Ctrl+C` requests the same graceful stop path and only the second `Ctrl+C` hard-aborts.
- **Interrupted task cleanup**: Generated artifacts such as `*.gen.yaml`, `test_result.txt`, `no_answer_test_result.txt`, `test_*.json`, and `__pycache__/` are removed. Newly created task directories are removed entirely; pre-existing task directories keep authored files and only lose generated artifacts.
- **Best-effort runtime cleanup on interrupt**: If rendered runtime context exists, the cleanup path deletes the namespace, rendered manifests, and selected cluster-scoped resources such as PVs before removing local artifacts.

### Executors

All defined in `workflow/executors.py`:

| Executor | ID | What it does |
|----------|----|-------------|
| `initialize_retry` | `initialize_retry` | Set up shared state, pre-create task directory |
| Generator Agent | `generator_agent` | LLM creates all files (first attempt) |
| `parse_generated_task` | `parse_generated_task` | Extract task ID from response or state |
| `run_validation` | `run_validation` | Pure Python file/syntax checks |
| `run_pytest` | `run_pytest` | Subprocess pytest execution |
| `make_decision` | `make_decision` | Combine results, route keep/remove |
| `keep_task` | `keep_task` | Mark success, route to skip-answer test |
| `remove_task` | `remove_task` | Record failure, increment retry count |
| `run_pytest_skip_answer` | `run_pytest_skip_answer` | Validate test_05 fails without answer |
| `check_loop` | `check_loop` | Route to fix or complete |
| `fix_task` | `fix_task` | Build fix prompt with errors + test output |
| Fixer Agent | `fixer_agent` | LLM patches broken files (retries) |
| `complete_workflow` | `complete_workflow` | Success message or move to unsuccessful |

### Shared state

```python
{
    "task_id": str,
    "target_topic": str,
    "concept_description": str,
    "difficulty": str,
    "objective": str,
    "retry_count": int,           # 0-based
    "max_retries": int,           # default 3
    "stop_requested_callback": Callable[[], bool] | None,
    "task_dir_preexisting": bool,
    "validation_{task_id}": ValidationResult,
    "raw_output_{task_id}": str,  # full pytest output
    "failure_reasons_{task_id}": list[str],
}
```

### Selection functions

Defined in `workflow/selectors.py`:

- `select_action` — routes `make_decision` → `keep_task` or `remove_task`
- `select_skip_answer_action` — routes `run_pytest_skip_answer` → `check_loop` or `complete_workflow`
- `select_loop_action` — routes `check_loop` → `fix_task` or `complete_workflow`

## Dual API Support

```mermaid
flowchart LR
    CFG[agents/config.py<br/>deployment_name] --> CHK{Codex model?}
    CHK -->|No| CHAT[Chat Completions API<br/>OpenAIChatCompletionClient]
    CHK -->|Yes| RESP[Responses API<br/>OpenAIChatClient /<br/>ResponsesAgent]
    CHAT --> AGENT[Agent with MCP tools]
    RESP --> AGENT
```

| Model type | API | Client |
|-----------|-----|--------|
| Standard (gpt-4o, etc.) | Chat Completions | `OpenAIChatCompletionClient` |
| Standard (gpt-5.6-terra, gpt-5.6-luna, gpt-5.6-sol, etc.) | Chat Completions | `OpenAIChatCompletionClient` |
| Codex models (for example, `gpt-5.x-codex`, `gpt-5-pro`) | Responses API | `OpenAIChatClient` or custom `ResponsesAgent` |

Detection is automatic via `AzureOpenAI.use_responses_api` in `agents/config.py`.

For the Idea Agent:
- **Chat Completions** → structured outputs (`response_format=K8sTaskConcept`)
- **Responses API** → tool-call approach (`save_k8s_task_concept`)

## Memory

Three active JSON files at the project root plus timestamped backups:

| File | Purpose |
|------|---------|
| `task_ideas_memory.json` | Successfully generated concepts — prevents re-generation |
| `task_ideas_failure_memory.json` | Concepts that failed validation/testing — prevents retrying |
| `task_ideas_unresolved_memory.json` | Concepts not confidently classified from folder truth yet |
| `memory-backups-YYYYMMDD-HHMMSS/` | Automatic pre-write snapshots created by the reconstruction tool |

`TaskIdeasMemory` owns memory mutation/query APIs (`add_structured_concept`, `add_failed_concept`, `concept_exists`).
`TaskIdeasMemoryMiddleware` is read-only injection for Chat Completions, while Responses API paths prepend constraints to instructions.

### Memory mutation rules

`TaskIdeasMemory` now enforces these invariants:

1. a concept cannot remain in both success and failure memory
2. `add_structured_concept(...)` evicts the same key from failure memory before saving success
3. `add_failed_concept(...)` evicts the same key from success memory before saving failure
4. memory writes are atomic to prevent truncated JSON files

### Workflow write timing

The main workflow runner no longer writes success memory immediately after idea generation.

Current behavior:

1. generate idea
2. run workflow
3. if workflow succeeds, save to `task_ideas_memory.json`
4. if workflow fails validation, save to `task_ideas_failure_memory.json`
5. if the run aborts for environment reasons (for example quarantine / connectivity), remove the concept instead of classifying it

This prevents the old corruption pattern where one concept could be written to success memory before later being classified as failure.

### Reconstruction tool

`agents/task_ideas_memory_rebuilder.py` rebuilds concept memory from the external task folders instead of trusting stale JSON as the source of truth.

Folder truth inputs:

- `tests/game02`
- `tests/game04`
- `unsuccessful`

The tool scans task folders recursively by detecting `instruction.md`, which allows it to handle mixed layouts such as:

- flat unsuccessful entries directly under `unsuccessful/`
- nested entries like `unsuccessful/game02/<task_id>/`
- nested entries like `unsuccessful/game04/<task_id>/`

### Reconstruction phases

1. **Deterministic classification**
   - merge existing success/failure memory
   - classify concepts by task ID membership in pass/fail folders
   - send anything without enough folder evidence to unresolved

2. **Optional OpenAI reconstruction**
   - for uncovered task folders, call Azure OpenAI with structured output
   - infer `concept`, `description`, `tags`, `variations`, and `reasoning_summary`
   - merge the inferred concept back into success/failure memory using folder truth

### Reconstruction outputs

When run with `--apply`, the tool writes:

- `task_ideas_memory.json`
- `task_ideas_failure_memory.json`
- `task_ideas_unresolved_memory.json`
- `task_ideas_reconstruction_report.json`

and first creates a timestamped backup directory.

## MCP Integration

File-writing agents use [@modelcontextprotocol/server-filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) via `npx`. The runner creates two MCP tools:

- `filesystem_docs` — scoped to K8s documentation (for Idea Agent)
- `filesystem_tests` — scoped to tests root (for Generator and Fixer)

MCP tools connect lazily on first use.

## Generated Task Structure

Each task lives under `tests/<game_name>/<task_id>/`:

> Note: This `tests/...` location refers to the external K8s game repo path from `PATHS.tests_root`, not this builder repo.  
> This builder repo keeps its own unit tests under `unit_tests/`.

| File | Required | Description |
|------|----------|-------------|
| `__init__.py` | Yes | Empty package marker |
| `instruction.md` | Yes | Student-facing challenge |
| `concept.md` | Yes | Learning material (no solution code) |
| `session.json` | Yes | Template variables (plain JSON) |
| `setup.template.yaml` | Yes | Namespace + prerequisites (Jinja2) |
| `answer.template.yaml` | Yes | Complete solution (Jinja2) |
| `test_01_setup.py` | Yes | Deploy setup resources |
| `test_02_ready.py` | Yes | Wait for setup resources to be ready |
| `test_03_answer.py` | Yes | Deploy answer resources |
| `test_04_challenge.py` | No | Triggers/load generation |
| `test_05_check.py` | Yes | Validate the solution |
| `test_06_cleanup.py` | Yes | Delete namespace |

## Project Structure

```
k8s-game-rule-builder/
├── agents/
│   ├── config.py                   # Paths, Azure, validation config
│   ├── filesystem_agent.py         # MCP filesystem operations
│   ├── k8s_task_generator_agent.py # Task generation (LLM + MCP)
│   ├── k8s_task_fixer_agent.py     # Targeted task fixing (LLM + MCP)
│   ├── k8s_task_idea_agent.py      # Idea generation with memory
│   ├── k8s_task_validator.py       # Pure Python validator
│   ├── kubernetes_agent.py         # kubectl execution
│   ├── pytest_runner.py            # Pure Python test runner
│   ├── responses_agent.py          # Responses API agent for codex models
│   └── logging_middleware.py       # Function invocation logging
├── workflow/
│   ├── builder.py                  # Workflow graph construction
│   ├── executors.py                # 12 executor implementations
│   ├── models.py                   # Pydantic + dataclass models
│   ├── selectors.py                # Routing functions
│   ├── runner.py                   # Main runner (80-iteration loop)
│   └── idea_generator.py           # Idea generation logic
├── docs/
│   └── ARCHITECTURE.md             # This file
├── unit_tests/                     # Unit tests for this builder project
├── pytest.ini                      # Pytest config (collect from unit_tests/)
├── workflow.py                     # Entry point
├── launch_devui.sh                 # DevUI launcher
├── launch_devui_full.py            # DevUI setup with full workflow
├── setup.sh                        # Environment setup
├── requirements.txt                # Dependencies
├── task_ideas_memory.json          # Concept memory
├── task_ideas_failure_memory.json  # Failure memory
├── CHANGELOG.md                    # Version history
└── README.md                       # Quick start
```
