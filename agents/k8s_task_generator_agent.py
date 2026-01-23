"""Kubernetes Game Task Generator Agent for creating test tasks.

This agent uses the MCP filesystem tool to generate complete Kubernetes learning tasks.
The LLM is smart enough to figure out file operations - just provide clear requirements.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from agent_framework import MCPStdioTool
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import AzureCliCredential
from .logging_middleware import LoggingFunctionMiddleware
from .config import PATHS, AZURE

logging.basicConfig(level=logging.INFO)


def _get_generator_instructions():
    """Get the generator agent instructions."""
    return (
        "You are a Kubernetes task generator with filesystem tools.\n"
        "\n"
        f"=== PATHS ===\n"
        f"Filesystem root: {PATHS.tests_root}\n"
        f"Create tasks in: {PATHS.game_name}/XXX_task_name/\n"
        f"Example: {PATHS.game_name}/050_secrets/instruction.md\n"
        "\n"
        f"=== REQUIRED FILES ===\n"
        f"Create directory {PATHS.game_name}/XXX_descriptive_name/ with:\n"
        "\n"
        "1. __init__.py - Empty\n"
        "2. instruction.md - Challenge description with {{variables}}\n"
        "3. session.json - Variables (format below)\n"
        "4. setup.template.yaml - Namespace + prerequisites\n"
        "5. answer.template.yaml - Complete solution\n"
        "6. test_01_setup.py - Deploy setup\n"
        "7. test_02_ready.py - Wait for setup resources (REQUIRED)\n"
        "8. test_03_answer.py - Deploy answer\n"
        "9. test_04_challenge.py - Optional: triggers/load\n"
        "10. test_05_check.py - Validate solution\n"
        "11. test_06_cleanup.py - Delete namespace\n"
        "\n"
        "=== session.json ===\n"
        '{\n'
        '  "namespace": "{{random_name()}}{{random_number(100,999)}}{{student_id()}}",\n'
        '  "pod_name": "{{random_name()}}",\n'
        '  "configmap_name": "{{random_name()}}"\n'
        '}\n'
        "Functions: {{random_name()}}, {{random_number(min,max)}}, {{student_id()}}, {{base64_encode(value)}}\n"
        "\n"
        "=== YAML TEMPLATES ===\n"
        "Variables: {{variable}} (spaces inside braces)\n"
        "Loops: #{% for i in [1,2,3] %} ... #{% endfor %}\n"
        "Conditionals: # {% if x %} ... # {% endif %}\n"
        "\n"
        "setup.template.yaml must include namespace:\n"
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: {{namespace}}\n"
        "\n"
        "answer.template.yaml must include namespace + solution resources\n"
        "\n"
        "=== TEST PATTERNS ===\n"
        "\n"
        "test_01_setup.py:\n"
        "from tests.helper.test_helper import deploy_setup\n"
        "def test_setup(json_input):\n"
        "    deploy_setup(json_input)\n"
        "\n"
        "test_02_ready.py - ANALYZE setup.template.yaml and generate appropriate tests:\n"
        "\n"
        "⚠️  CRITICAL: test_02_ready.py checks resources from setup.template.yaml, NOT answer.template.yaml!\n"
        "\n"
        "Test flow:\n"
        "1. test_01_setup.py deploys setup.template.yaml\n"
        "2. test_02_ready.py waits for setup.template.yaml resources to be ready\n"
        "3. test_03_answer.py deploys answer.template.yaml\n"
        "4. test_05_check.py validates answer.template.yaml resources\n"
        "\n"
        "Decision tree:\n"
        "- Only namespace/ConfigMap/Secret in setup.template.yaml? → Simple namespace check\n"
        "- Has Pod in setup.template.yaml? → Poll for phase='Running' AND all containers ready\n"
        "- Has Deployment? → Poll for availableReplicas >= replicas\n"
        "- Has StatefulSet? → Poll for readyReplicas >= replicas\n"
        "- Has Job? → Poll for succeeded > 0\n"
        "\n"
        "import time, json\n"
        "from tests.helper.kubectrl_helper import build_kube_config, run_kubectl_command\n"
        "\n"
        "class TestReady:\n"
        "    # For static resources (namespace only):\n"
        "    def test_001_namespace_active(self, json_input):\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        time.sleep(2)\n"
        "        result = run_kubectl_command(kube_config, f\"kubectl get namespace {json_input['namespace']} -o json\")\n"
        "        print(f\"\\nDEBUG kubectl output:\\n{result}\")\n"
        "        data = json.loads(result)\n"
        "        print(f\"DEBUG: Namespace {data.get('metadata', {}).get('name')} is {data.get('status', {}).get('phase')}\")\n"
        "        assert data['status']['phase'] == 'Active'\n"
        "    \n"
        "    # For Pods:\n"
        "    def test_001_pod_ready(self, json_input):\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        max_wait = 60  # 1 minute max\n"
        "        interval = 15  # Check every 15 seconds\n"
        "        time.sleep(5)\n"
        "        \n"
        "        for attempt in range(max_wait // interval):\n"
        "            try:\n"
        "                result = run_kubectl_command(kube_config, f\"kubectl get pod {json_input['pod_name']} -n {json_input['namespace']} -o json\")\n"
        "                print(f\"\\nDEBUG [Attempt {attempt+1}] kubectl output:\\n{result}\")\n"
        "                data = json.loads(result)\n"
        "                phase = data.get('status', {}).get('phase', 'Unknown')\n"
        "                print(f\"DEBUG: Pod phase: {phase}\")\n"
        "                if phase == 'Running':\n"
        "                    container_statuses = data.get('status', {}).get('containerStatuses', [])\n"
        "                    ready_count = sum(1 for cs in container_statuses if cs.get('ready', False))\n"
        "                    total_count = len(container_statuses)\n"
        "                    print(f\"DEBUG: Containers ready: {ready_count}/{total_count}\")\n"
        "                    if all(cs.get('ready', False) for cs in container_statuses):\n"
        "                        print(f\"DEBUG: Pod ready - {data.get('metadata', {}).get('name')}\")\n"
        "                        return\n"
        "            except Exception as e:\n"
        "                print(f\"DEBUG [Attempt {attempt+1}] Exception: {e}\")\n"
        "            time.sleep(interval)\n"
        "        raise TimeoutError(f\"Pod not ready in {max_wait}s\")\n"
        "    \n"
        "    # For Deployments:\n"
        "    def test_001_deployment_ready(self, json_input):\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        max_wait = 60  # 1 minute max\n"
        "        interval = 15  # Check every 15 seconds\n"
        "        time.sleep(5)\n"
        "        \n"
        "        for attempt in range(max_wait // interval):\n"
        "            try:\n"
        "                result = run_kubectl_command(kube_config, f\"kubectl get deployment {json_input['deployment_name']} -n {json_input['namespace']} -o json\")\n"
        "                print(f\"\\nDEBUG [Attempt {attempt+1}] kubectl output:\\n{result}\")\n"
        "                data = json.loads(result)\n"
        "                desired = data.get('spec', {}).get('replicas', 0)\n"
        "                available = data.get('status', {}).get('availableReplicas', 0)\n"
        "                print(f\"DEBUG: Deployment replicas: {available}/{desired}\")\n"
        "                if available >= desired and desired > 0:\n"
        "                    print(f\"DEBUG: Deployment ready - {available}/{desired} replicas\")\n"
        "                    return\n"
        "            except Exception as e:\n"
        "                print(f\"DEBUG [Attempt {attempt+1}] Exception: {e}\")\n"
        "            time.sleep(interval)\n"
        "        raise TimeoutError(f\"Deployment not ready in {max_wait}s\")\n"
        "\n"
        "test_03_answer.py:\n"
        "from tests.helper.test_helper import deploy_answer\n"
        "def test_answer(json_input):\n"
        "    deploy_answer(json_input)\n"
        "\n"
        "test_04_challenge.py - Optional (skip for simple CRUD tasks):\n"
        "Only create if task needs triggers:\n"
        "- Autoscaling? Generate load\n"
        "- CronJob? Wait for execution\n"
        "- Network policies? Test connections\n"
        "- Simple CRUD? Skip this file\n"
        "\n"
        "test_05_check.py - Parse JSON and validate specific fields:\n"
        "import json\n"
        "from tests.helper.kubectrl_helper import build_kube_config, run_kubectl_command\n"
        "\n"
        "class TestCheck:\n"
        "    # For ConfigMap:\n"
        "    def test_001_configmap_exists(self, json_input):\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        result = run_kubectl_command(kube_config, f\"kubectl get configmap {json_input['configmap_name']} -n {json_input['namespace']} -o json\")\n"
        "        print(f\"\\nDEBUG kubectl output:\\n{result}\")\n"
        "        data = json.loads(result)\n"
        "        assert data['metadata']['name'] == json_input['configmap_name']\n"
        "        assert 'key1' in data.get('data', {})\n"
        "    \n"
        "    # For Pod:\n"
        "    def test_001_pod_exists(self, json_input):\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        result = run_kubectl_command(kube_config, f\"kubectl get pod {json_input['pod_name']} -n {json_input['namespace']} -o json\")\n"
        "        print(f\"\\nDEBUG kubectl output:\\n{result}\")\n"
        "        data = json.loads(result)\n"
        "        assert data['metadata']['name'] == json_input['pod_name']\n"
        "        assert data['spec']['containers'][0]['image'] == 'nginx:latest'\n"
        "    \n"
        "    # For Service:\n"
        "    def test_001_service_exists(self, json_input):\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        result = run_kubectl_command(kube_config, f\"kubectl get service {json_input['service_name']} -n {json_input['namespace']} -o json\")\n"
        "        print(f\"\\nDEBUG kubectl output:\\n{result}\")\n"
        "        data = json.loads(result)\n"
        "        assert data['spec']['type'] == 'ClusterIP'\n"
        "        assert data['spec']['ports'][0]['port'] == 80\n"
        "\n"
        "test_06_cleanup.py:\n"
        "from tests.helper.kubectrl_helper import delete_namespace\n"
        "class TestCleanup:\n"
        "    def test_cleanup(self, json_input):\n"
        "        delete_namespace(json_input)\n"
        "\n"
        "=== KEY RULES ===\n"
        "- session.json is plain JSON, NOT Jinja template\n"
        "- test_02_ready.py is REQUIRED - analyze setup.template.yaml and choose appropriate pattern\n"
        "- MUST use polling loops (60s timeout, 15s interval) for pods/deployments/statefulsets/jobs\n"
        "- MUST use try/except around kubectl commands (resources may not exist yet)\n"
        "- MUST use safe .get() for nested JSON fields to avoid KeyError\n"
        "- CRITICAL: ALWAYS print FULL kubectl result on EVERY attempt: print(f\"\\nDEBUG [Attempt {attempt+1}] kubectl output:\\n{result}\")\n"
        "- CRITICAL: ALWAYS print exceptions: except Exception as e: print(f\"DEBUG [Attempt {attempt+1}] Exception: {e}\")\n"
        "- CRITICAL: Print status on every check (phase, replicas, etc.) so we can see progress\n"
        "- Use 'for attempt in range(max_wait // interval):' to track attempt numbers\n"
        "- test_04_challenge.py is optional - only if task needs triggers\n"
        "- test_05_check.py must validate specific fields from JSON output\n"
        "- Include resource limits in pod specs\n"
        "- Use three-digit task numbers (001-999)\n"
    )


async def create_generator_agent_with_mcp(mcp_tool):
    """Create generator agent with MCP tool."""
    chat_client = AzureOpenAIChatClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=AzureCliCredential(),
    )
    
    # Allow more retries for file generation (10+ files)
    chat_client.function_invocation_configuration.max_consecutive_errors_per_request = 15
    
    agent = chat_client.as_agent(
        name="K8sTaskGeneratorAgent",
        instructions=_get_generator_instructions(),
        tools=mcp_tool,
        tool_choice="auto",
        middleware=[LoggingFunctionMiddleware()],
    )
    
    return agent


@asynccontextmanager
async def get_k8s_task_generator_agent():
    """Create and return a Kubernetes task generator agent with MCP filesystem tools."""
    mcp_tool = MCPStdioTool(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(PATHS.tests_root)],
        load_prompts=False
    )
    
    async with mcp_tool:
        agent = await create_generator_agent_with_mcp(mcp_tool)
        yield agent


if __name__ == "__main__":
    async def main():
        async with get_k8s_task_generator_agent() as agent:
            result = await agent.run(
                "Generate task '081_create_configmap' teaching ConfigMap creation. "
                "Include namespace, ConfigMap with keys 'app.name' and 'app.version', "
                "validation checking the ConfigMap exists with correct keys."
            )
            logging.info("\n=== Result ===")
            logging.info(result.text)
    
    asyncio.run(main())
