# K8s Task Generator Agent Logic

This document explains how the Kubernetes task generator agent works, the files it produces, and the rules it enforces.

## Overview
- Agent name: K8sTaskGeneratorAgent
- Purpose: Generate fully scaffolded Kubernetes game tasks under tests/game02/XXX_descriptive_name/ (001-999 numbering)
- IO layer: Uses MCP filesystem tool (mcp-server-filesystem) to create directories and files directly on disk.
- Invocation: async context manager get_k8s_task_generator_agent() yields the agent. The __main__ block shows an example run.

## What the agent creates
For each task directory (tests/game02/XXX_descriptive_name/):
- __init__.py (empty)
- instruction.md (user-facing challenge)
- session.json (required; plain JSON variables)
- setup.template.yaml (required; at least creates the namespace)
- answer.template.yaml (required; full solution)
- test_01_setup.py (deploy_setup)
- test_03_answer.py (deploy_answer)
- test_05_check.py (validation with kubectl + JSON parsing)
- test_06_cleanup.py (delete_namespace)

Optional generated artifacts (if the harness writes them):
- setup.gen.yaml
- answer.gen.yaml

## Template and variable rules
- Template variables must use Jinja-style double braces with spaces: {{ variable }}
- session.json is pure JSON; it should not contain Jinja conditionals or loops—only variable placeholders like {{random_name()}}.
- Common variable patterns:
  - namespace: {{random_name()}}{{random_number(1,10)}}{{student_id()}}
  - other values: {{random_name()}}, {{random_number(1000, 9999)}}, {{base64_encode(random_name())}}
- setup.template.yaml must at minimum create the namespace; add any prereq resources if needed.
- answer.template.yaml should include the namespace plus all solution resources. You can use Jinja for loops/conditionals with # {% ... % } comment style if needed.

## Test file patterns (enforced)
- test_01_setup.py uses deploy_setup(json_input)
- test_03_answer.py uses deploy_answer(json_input)
- test_05_check.py imports build_kube_config and run_kubectl_command, runs kubectl with -o json, parses via json.loads(), and asserts specific fields; class name: TestCheck
- test_06_cleanup.py uses delete_namespace(json_input); class name: TestCleanup

## How TestCheck is built
- The agent instructions explicitly require a TestCheck class that:
  - Builds kubeconfig with build_kube_config(json_input[...]).
  - Runs kubectl commands via run_kubectl_command(kube_config, <cmd>).
  - Parses JSON output and asserts resource properties (namespaces, keys, values, kinds, ports, etc.).
- When generate_complete_task is used programmatically, it also synthesizes TestCheck methods from the validation_checks list (string-based generation). In MCP mode, the agent writes test_05_check.py directly according to the prompt plus the instruction rules above.

## Control flow inside the agent
1) The agent runs under an async context: async with get_k8s_task_generator_agent() as agent: ...
2) The MCP filesystem tool is attached with root /home/developer/Documents/data-disk/k8s-game-rule/tests.
3) The long instruction block tells the LLM exactly which files to create and the required content patterns.
4) On each request, the agent writes files directly via the filesystem tool; no in-memory spec is returned.

## Key files to inspect
- agents/k8s_task_generator_agent.py — agent definition, instructions, and example __main__ run.
- tests/game02/<generated_task>/ — output of a generation run (e.g., 081_create_configmap/).

## Running the agent
Activate the venv and run the module:
```bash
source .venv/bin/activate
python agents/k8s_task_generator_agent.py
```
This will generate the sample task defined in the __main__ block and write files under tests/game02/.

## Notes and troubleshooting
- If files do not appear, confirm the MCP filesystem server path and args in get_k8s_task_generator_agent().
- Ensure the venv has agent_framework and Azure identity dependencies installed.
- For custom tasks, call agent.run(...) with your prompt specifying task name, resources, variables, and validation expectations.
