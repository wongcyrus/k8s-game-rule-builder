"""Kubernetes Game Task Generator Agent for creating test tasks.

This agent uses the MCP filesystem tool to generate complete Kubernetes learning tasks
with all required files (001-999 numbering).

IMPORTANT: The agent must use ABSOLUTE paths when calling filesystem tools.
Example: /home/developer/Documents/data-disk/k8s-game-rule/tests/game02/050_task_name/

The agent does NOT use Python functions to generate files - it uses the MCP filesystem
tool's create_directory and write_file capabilities based on the instructions provided.

NOTE: Uses AzureOpenAIChatClient instead of AzureOpenAIResponsesClient to avoid
server-side thread persistence issues in workflow loops.
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
    """Get the generator agent instructions (reusable)."""
    return (
        "You are a Kubernetes game task generator assistant following the established pattern. "
        f"You have access to filesystem tools for creating files and directories. "
        "\n\n=== CRITICAL: PATH STRUCTURE (READ THIS FIRST!) ===\n"
        f"Use RELATIVE paths from the filesystem server root.\n"
        f"The filesystem server root is: {PATHS.tests_root}\n"
        f"\n"
        f"Create task directories using paths relative to the server root:\n"
        f"  ✅ CORRECT: create_directory(path='{PATHS.game_name}/050_secrets')\n"
        f"  ✅ CORRECT: write_file(path='{PATHS.game_name}/050_secrets/__init__.py', content='')\n"
        f"  ❌ WRONG: create_directory(path='{PATHS.tests_root}/{PATHS.game_name}/050_secrets')\n"
        f"  ❌ WRONG: create_directory(path='tests/{PATHS.game_name}/050_secrets')\n"
        f"\n"
        "\n\n=== CRITICAL: FILE CREATION ===\n"
        "You MUST create ALL required files using filesystem tools. This is not optional.\n"
        "DO NOT waste time listing directories - just create them directly.\n"
        "If a directory doesn't exist, create_directory will create it.\n"
        "If a file creation fails, analyze the error and retry with corrections.\n"
        "You have up to 15 consecutive error retries available - use them to fix issues.\n"
        "Do not give up after a few errors - complete all files even if it takes multiple attempts.\n"
        "Each task requires 10-11 files - ensure all are created successfully.\n"
        "\n"
        "WORKFLOW:\n"
        f"1. create_directory(path='{PATHS.game_name}/XXX_task_name') - Create task directory\n"
        f"2. write_file(path='{PATHS.game_name}/XXX_task_name/__init__.py', content='') - Create __init__.py\n"
        f"3. write_file(path='{PATHS.game_name}/XXX_task_name/instruction.md', content='...') - Create instruction\n"
        "4. Continue creating all remaining files...\n"
        "\n"
        "DO NOT use list_directory unless absolutely necessary for debugging errors.\n"
        "\n\n=== REQUIRED COMPONENTS ===\n"
        f"For each task, create directory {PATHS.game_name}/XXX_descriptive_name/ (three-digit 001-999) with these files:\n"
        "1. __init__.py (empty file)\n"
        "2. instruction.md - User-facing challenge with template variables\n"
        "3. session.json - REQUIRED: Simple JSON object with variables\n"
        "4. setup.template.yaml - REQUIRED: Minimum namespace creation, plus any prereqs\n"
        "5. answer.template.yaml - REQUIRED: Complete solution with all resources\n"
        "6. test_01_setup.py - Standard: from tests.helper.test_helper import deploy_setup\n"
        "7. test_02_ready.py - REQUIRED: Test that setup resources are ready (pods Running, deployments available, etc.)\n"
        "8. test_03_answer.py - Standard: from tests.helper.test_helper import deploy_answer\n"
        "9. test_04_challenge.py - Optional: Additional actions before validation (e.g., generate load, trigger events)\n"
        "10. test_05_check.py - Validation using kubectl commands and JSON parsing\n"
        "11. test_06_cleanup.py - Standard: from tests.helper.kubectrl_helper import delete_namespace\n"
        "\n\n=== session.json FORMAT (REQUIRED) ===\n"
        "Simple JSON object with template function calls (prefer three-digit ranges like 001-999 when using random_number):\n"
        '{\n'
        '  "namespace": "{{random_name()}}{{random_number(1,10)}}{{student_id()}}",\n'
        '  "value1": "{{random_name()}}",\n'
        '  "configmap_name": "{{random_name()}}"\n'
        '}\n'
        "Available functions: {{random_name()}}, {{random_number(min,max)}}, {{student_id()}}, {{base64_encode(value)}}\n"
        "\n\n=== setup.template.yaml (REQUIRED) ===\n"
        "ALWAYS create namespace at minimum:\n"
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: {{namespace}}\n"
        "Add additional resources if needed before the challenge (ConfigMaps, Secrets, Pods, Deployments, etc.)\n"
        "\n\n=== answer.template.yaml (REQUIRED) ===\n"
        "Complete solution including namespace:\n"
        "apiVersion: v1\n"
        "kind: Namespace\n"
        "metadata:\n"
        "  name: {{namespace}}\n"
        "---\n"
        "[Additional resources...]\n"
        "Use {{variable}} for template variables (double curly braces WITH spaces)\n"
        "For loops: #{% for i in [1,2,3] %} ... #{% endfor %}\n"
        "Conditionals: # {% if condition %} ... # {% endif %}\n"
        "\n\n=== TEST FILE PATTERNS ===\n"
        "CRITICAL: Analyze the task requirements and generate appropriate tests!\n"
        "\n"
        "For test_02_ready.py:\n"
        "1. Read and understand what resources are in setup.template.yaml\n"
        "2. Think: Which of these resources need time to become ready?\n"
        "3. MUST use polling loops (for loop + time.sleep) for pods, deployments, statefulsets, jobs\n"
        "4. DO NOT just check once - resources take 10-60 seconds to start!\n"
        "5. Pattern: for _ in range(max_wait // interval): check → sleep → repeat\n"
        "6. If setup only has static resources (namespace, ConfigMap, Secret), simple check is OK\n"
        "\n"
        "For test_04_challenge.py:\n"
        "1. Read the task objective and understand what the student needs to learn\n"
        "2. Think: Does this task require any pre-conditions or triggers before validation?\n"
        "3. Ask yourself: Will the solution work immediately, or does something need to happen first?\n"
        "4. Examples: autoscaling needs load, CronJobs need time, network policies need connection attempts\n"
        "5. If the task is straightforward CRUD, skip this file entirely\n"
        "\n"
        "test_01_setup.py:\n"
        "from tests.helper.test_helper import deploy_setup\n"
        "def test_setup(json_input):\n"
        "    deploy_setup(json_input)\n"
        "\n"
        "test_02_ready.py (REQUIRED - Test setup resources are ready):\n"
        "# ANALYZE setup.template.yaml and CREATE appropriate readiness tests\n"
        "# Think about: What resources need time to become ready? What does 'ready' mean for each?\n"
        "# \n"
        "# CRITICAL: Use polling loops with time.sleep() AND error handling to wait for resources\n"
        "# DO NOT just check once - resources take time to start and may not exist immediately!\n"
        "# \n"
        "# Decision process:\n"
        "# - Namespace only? → Test namespace is Active (no wait needed)\n"
        "# - ConfigMap/Secret only? → Minimal test (they're ready immediately)\n"
        "# - Pod? → MUST use polling loop to wait for status.phase == 'Running'\n"
        "# - Deployment? → MUST use polling loop to wait for availableReplicas == replicas\n"
        "# - StatefulSet? → MUST use polling loop to wait for readyReplicas == replicas\n"
        "# - DaemonSet? → MUST use polling loop to wait for numberReady == desiredNumberScheduled\n"
        "# - Service? → Optionally test endpoints exist\n"
        "# - Job? → MUST use polling loop to wait for status.succeeded > 0\n"
        "# \n"
        "# REQUIRED PATTERN for resources that need time:\n"
        "# time.sleep(5)  # Initial wait for resource creation\n"
        "# for _ in range(max_wait // interval):\n"
        "#     try:\n"
        "#         result = run_kubectl_command(...)\n"
        "#         data = json.loads(result)\n"
        "#         if <ready_condition>:\n"
        "#             return  # Success!\n"
        "#     except Exception as e:\n"
        "#         pass  # Resource might not exist yet, keep waiting\n"
        "#     time.sleep(interval)\n"
        "# raise TimeoutError('Resource did not become ready')\n"
        "# \n"
        "import time, json\n"
        "from tests.helper.kubectrl_helper import build_kube_config, run_kubectl_command\n"
        "\n"
        "class TestReady:\n"
        "    # Generate test methods based on setup.template.yaml content\n"
        "    # ALWAYS use polling loops with error handling for pods, deployments, statefulsets, jobs\n"
        "    \n"
        "    def test_001_pod_ready(self, json_input):\n"
        "        # Example: If setup has a Pod - MUST use polling loop with error handling\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        max_wait = 120  # seconds - increased for slower clusters\n"
        "        interval = 3    # check every 3 seconds\n"
        "        \n"
        "        time.sleep(5)  # Initial wait for pod creation\n"
        "        \n"
        "        for _ in range(max_wait // interval):\n"
        "            try:\n"
        "                result = run_kubectl_command(kube_config, f\"kubectl get pod {json_input['pod_name']} -n {json_input['namespace']} -o json\")\n"
        "                data = json.loads(result)\n"
        "                if data.get('status', {}).get('phase') == 'Running':\n"
        "                    # Additional check: all containers ready\n"
        "                    container_statuses = data.get('status', {}).get('containerStatuses', [])\n"
        "                    if all(cs.get('ready', False) for cs in container_statuses):\n"
        "                        return  # Pod is fully ready!\n"
        "            except Exception:\n"
        "                pass  # Pod might not exist yet, keep waiting\n"
        "            time.sleep(interval)\n"
        "        \n"
        "        raise TimeoutError(f\"Pod {json_input['pod_name']} did not become ready in {max_wait} seconds\")\n"
        "    \n"
        "    def test_002_deployment_ready(self, json_input):\n"
        "        # Example: If setup has a Deployment - MUST use polling loop with error handling\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        max_wait = 120  # seconds - increased for slower clusters\n"
        "        interval = 3    # check every 3 seconds\n"
        "        \n"
        "        time.sleep(5)  # Initial wait for deployment creation\n"
        "        \n"
        "        for _ in range(max_wait // interval):\n"
        "            try:\n"
        "                result = run_kubectl_command(kube_config, f\"kubectl get deployment {json_input['deployment_name']} -n {json_input['namespace']} -o json\")\n"
        "                data = json.loads(result)\n"
        "                desired = data.get('spec', {}).get('replicas', 0)\n"
        "                available = data.get('status', {}).get('availableReplicas', 0)\n"
        "                if available >= desired and desired > 0:\n"
        "                    return  # Deployment is ready!\n"
        "            except Exception:\n"
        "                pass  # Deployment might not exist yet, keep waiting\n"
        "            time.sleep(interval)\n"
        "        \n"
        "        raise TimeoutError(f\"Deployment {json_input['deployment_name']} did not become ready in {max_wait} seconds\")\n"
        "    \n"
        "    def test_001_namespace_active(self, json_input):\n"
        "        # Example: Minimal test when setup only has namespace + static resources\n"
        "        # Small wait even for namespace to ensure it's fully created\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        time.sleep(2)  # Brief wait for namespace creation\n"
        "        result = run_kubectl_command(kube_config, f\"kubectl get namespace {json_input['namespace']} -o json\")\n"
        "        data = json.loads(result)\n"
        "        assert data['status']['phase'] == 'Active'\n"
        "\n"
        "test_03_answer.py:\n"
        "from tests.helper.test_helper import deploy_answer\n"
        "def test_answer(json_input):\n"
        "    deploy_answer(json_input)\n"
        "\n"
        "test_04_challenge.py (Optional - only if needed):\n"
        "# ANALYZE the task objective and DECIDE if pre-validation actions are needed\n"
        "# Think about: Does the solution need a trigger or condition to work?\n"
        "# \n"
        "# Ask yourself:\n"
        "# - Does this task test autoscaling? → Need to generate load\n"
        "# - Does this task use CronJob? → Need to wait for execution\n"
        "# - Does this task test network policies? → Need to attempt connections\n"
        "# - Does this task test resource limits? → Need to consume resources\n"
        "# - Does this task involve events/webhooks? → Need to trigger them\n"
        "# - Is this a simple create/read task? → NO challenge needed\n"
        "# \n"
        "# If NO challenge is needed, DO NOT create this file at all\n"
        "# If YES, create appropriate challenge actions below\n"
        "import time, json\n"
        "from tests.helper.kubectrl_helper import build_kube_config, run_kubectl_command\n"
        "\n"
        "class TestChallenge:\n"
        "    # Create challenge methods based on task requirements\n"
        "    # Below are examples for different scenarios - use what's appropriate\n"
        "    \n"
        "    def test_001_generate_load(self, json_input):\n"
        "        # Use for: HPA, autoscaling, performance testing\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        cmd = f\"kubectl run load-generator --image=busybox --restart=Never -n {json_input['namespace']} -- /bin/sh -c 'while true; do wget -q -O- http://{json_input['service_name']}; done'\"\n"
        "        run_kubectl_command(kube_config, cmd)\n"
        "        time.sleep(30)  # Wait for autoscaling to trigger\n"
        "    \n"
        "    def test_001_wait_for_cronjob(self, json_input):\n"
        "        # Use for: CronJob tasks that need to execute\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        max_wait = 120\n"
        "        interval = 5\n"
        "        for _ in range(max_wait // interval):\n"
        "            result = run_kubectl_command(kube_config, f\"kubectl get jobs -n {json_input['namespace']} -o json\")\n"
        "            data = json.loads(result)\n"
        "            if len(data.get('items', [])) > 0:\n"
        "                return\n"
        "            time.sleep(interval)\n"
        "        raise TimeoutError('CronJob did not execute')\n"
        "    \n"
        "    def test_001_test_network_policy(self, json_input):\n"
        "        # Use for: Network policy tasks that need connection attempts\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        cmd = f\"kubectl run network-test --image=busybox --restart=Never -n {json_input['namespace']} -- wget -T 5 -O- http://{json_input['service_name']}\"\n"
        "        run_kubectl_command(kube_config, cmd)\n"
        "        time.sleep(10)\n"
        "    \n"
        "    def test_001_consume_resources(self, json_input):\n"
        "        # Use for: Resource quota/limit tasks\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        cmd = f\"kubectl run resource-consumer --image=vish/stress --restart=Never -n {json_input['namespace']} -- -cpus 2 -mem-total 512Mi\"\n"
        "        run_kubectl_command(kube_config, cmd)\n"
        "        time.sleep(20)\n"
        "    \n"
        "    def test_001_trigger_event(self, json_input):\n"
        "        # Use for: Event-driven or webhook tasks\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        cmd = f\"kubectl delete pod {json_input['pod_name']} -n {json_input['namespace']}\"\n"
        "        run_kubectl_command(kube_config, cmd)\n"
        "        time.sleep(15)  # Wait for event processing\n"
        "\n"
        "test_05_check.py:\n"
        "import json, logging\n"
        "from tests.helper.kubectrl_helper import build_kube_config, run_kubectl_command\n"
        "class TestCheck:\n"
        "    def test_001_check_resource(self, json_input):\n"
        "        kube_config = build_kube_config(json_input['cert_file'], json_input['key_file'], json_input['host'])\n"
        "        result = run_kubectl_command(kube_config, 'kubectl get resource -n namespace -o json')\n"
        "        data = json.loads(result)\n"
        "        assert data['metadata']['name'] == expected\n"
        "\n"
        "test_06_cleanup.py:\n"
        "from tests.helper.kubectrl_helper import delete_namespace\n"
        "class TestCleanup:\n"
        "    def test_cleanup(self, json_input):\n"
        "        delete_namespace(json_input)\n"
        "\n\n=== IMPORTANT RULES ===\n"
        "- ALL template variables use {{variable}} syntax (spaces inside braces)\n"
        "- session.json is simple JSON, NOT Jinja2 template\n"
        "- setup.template.yaml MUST exist (minimum: namespace)\n"
        "- answer.template.yaml MUST include namespace + solution\n"
        "- test_02_ready.py is REQUIRED - analyze setup.template.yaml and create appropriate readiness tests\n"
        "- Think critically: What resources need time to become ready? Test those.\n"
        "- CRITICAL: test_02_ready.py MUST include:\n"
        "  * Initial time.sleep(5) before polling loop (resources need time to be created)\n"
        "  * try/except blocks around kubectl commands (resources might not exist yet)\n"
        "  * Minimum 120 second timeout for pods/deployments (clusters can be slow)\n"
        "  * Safe .get() access for nested JSON fields (avoid KeyError)\n"
        "  * Container readiness checks for pods (not just phase == 'Running')\n"
        "- test_04_challenge.py is OPTIONAL - analyze task objective and decide if pre-validation actions are needed\n"
        "- Think critically: Does the solution need a trigger or condition? If yes, create challenge. If no, skip file.\n"
        "- instruction.md references {{variables}} from session.json\n"
        "- Include resource limits in pod specs\n"
        "- Use filesystem tools to CREATE all files\n"
        "- Parse JSON in validation tests, check specific fields\n"
        "- Readiness checks should have reasonable timeouts (120+ seconds for dynamic resources)\n"
        "- Check appropriate resource types: pod status, deployment readiness, service endpoints, etc.\n"
        "\n"
        "ALWAYS use filesystem tools to write actual files. DO NOT just describe what to create.\n"
        "\n"
        "IMPORTANT ERROR HANDLING:\n"
        "- If a file creation fails, try again with corrected content\n"
        "- If a directory doesn't exist, create it first\n"
        "- Verify file paths are correct before writing\n"
        "- If you encounter errors, analyze and fix them before continuing\n"
        "- Complete ALL files even if some fail - retry failed files at the end\n"
    )


async def create_generator_agent_with_mcp(mcp_tool):
    """Create generator agent with an existing MCP tool.
    
    Uses AzureOpenAIChatClient for in-memory conversation management,
    avoiding Azure service-side thread persistence issues in workflow loops.
    
    Args:
        mcp_tool: An already initialized MCPStdioTool instance
        
    Returns:
        The configured agent
    """
    chat_client = AzureOpenAIChatClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=AzureCliCredential(),
    )
    
    # Increase max consecutive errors for file generation tasks (default is 3)
    # Generator needs to create 10+ files, so allow more retries
    logging.info(f"📊 Before setting: max_consecutive_errors_per_request = {chat_client.function_invocation_configuration.max_consecutive_errors_per_request}")
    chat_client.function_invocation_configuration.max_consecutive_errors_per_request = 15
    logging.info(f"✅ After setting: max_consecutive_errors_per_request = {chat_client.function_invocation_configuration.max_consecutive_errors_per_request}")
    
    agent = chat_client.as_agent(
        name="K8sTaskGeneratorAgent",
        instructions=_get_generator_instructions(),
        tools=mcp_tool,
        tool_choice="auto",  # Let agent decide when to use tools (not force every turn)
        middleware=[LoggingFunctionMiddleware()],
    )
    
    # Verify the setting persisted after agent creation
    logging.info(f"🔍 After agent creation: max_consecutive_errors_per_request = {chat_client.function_invocation_configuration.max_consecutive_errors_per_request}")
    
    return agent


@asynccontextmanager
async def get_k8s_task_generator_agent():
    """Create and return a Kubernetes task generator agent with MCP filesystem tools.
    
    Yields:
        An agent configured to generate Kubernetes game task tests.
    """
    # Connect to the official MCP filesystem server via npx
    mcp_tool = MCPStdioTool(
        name="filesystem",
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            str(PATHS.tests_root)
        ],
        load_prompts=False  # Filesystem server doesn't support prompts
    )
    
    async with mcp_tool:
        agent = await create_generator_agent_with_mcp(mcp_tool)
        yield agent


if __name__ == "__main__":
    async def main():
        async with get_k8s_task_generator_agent() as agent:
            result = await agent.run(
                "Generate a beginner-level task named '081_create_configmap' that teaches "
                "users how to create a ConfigMap with specific key-value pairs. "
                "The task should:\n"
                "- Create a namespace\n"
                "- Create a ConfigMap with keys 'app.name' and 'app.version'\n"
                "- Include validation that checks the ConfigMap exists and has correct keys\n"
                "- Use template variables for namespace, configmap name, and values\n"
                "- Follow all required patterns including setup.template.yaml and answer.template.yaml"
            )
            logging.info("\n=== K8s Task Generator Agent Result ===")
            logging.info(result.text)
    
    asyncio.run(main())
