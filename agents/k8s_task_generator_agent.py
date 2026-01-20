"""Kubernetes Game Task Generator Agent for creating test tasks.

This agent uses the MCP filesystem tool to generate complete Kubernetes learning tasks
under tests/game02/XXX_descriptive_name/ with all required files (001-999 numbering).

The agent does NOT use Python functions to generate files - it uses the MCP filesystem
tool's create_directory and write_file capabilities based on the instructions provided.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from agent_framework import MCPStdioTool
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def get_k8s_task_generator_agent():
    """Create and return a Kubernetes task generator agent with MCP filesystem tools.
    
    Yields:
        An agent configured to generate Kubernetes game task tests.
    """
    responses_client = AzureOpenAIResponsesClient(
        endpoint="https://cyrus-me23xi26-eastus2.openai.azure.com/",
        deployment_name="gpt-5.2-chat",
        credential=AzureCliCredential(),
    )
    
    # Connect to the MCP filesystem server
    mcp_tool = MCPStdioTool(
        name="filesystem",
        command="/home/developer/Documents/data-disk/k8s-game-rule-builder/.venv/bin/mcp-server-filesystem",
        args=["/home/developer/Documents/data-disk/k8s-game-rule/tests"]
    )
    
    async with mcp_tool:
        agent = responses_client.as_agent(
            name="K8sTaskGeneratorAgent",
            instructions=(
                "You are a Kubernetes game task generator assistant following the established pattern. "
                "You have access to filesystem tools for /home/developer/Documents/data-disk/k8s-game-rule/tests directory. "
                "\n\n=== REQUIRED COMPONENTS ===\n"
                "For each task, create directory tests/game02/XXX_descriptive_name/ (three-digit 001-999) with these files:\n"
                "1. __init__.py (empty file)\n"
                "2. instruction.md - User-facing challenge with template variables\n"
                "3. session.json - REQUIRED: Simple JSON object with variables\n"
                "4. setup.template.yaml - REQUIRED: Minimum namespace creation, plus any prereqs\n"
                "5. answer.template.yaml - REQUIRED: Complete solution with all resources\n"
                "6. test_01_setup.py - Standard: from tests.helper.test_helper import deploy_setup\n"
                "7. test_03_answer.py - Standard: from tests.helper.test_helper import deploy_answer\n"
                "8. test_05_check.py - Validation using kubectl commands and JSON parsing\n"
                "9. test_06_cleanup.py - Standard: from tests.helper.kubectrl_helper import delete_namespace\n"
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
                "Add additional resources if needed before the challenge (ConfigMaps, Secrets, etc.)\n"
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
                "test_01_setup.py:\n"
                "from tests.helper.test_helper import deploy_setup\n"
                "def test_setup(json_input):\n"
                "    deploy_setup(json_input)\n"
                "\n"
                "test_03_answer.py:\n"
                "from tests.helper.test_helper import deploy_answer\n"
                "def test_answer(json_input):\n"
                "    deploy_answer(json_input)\n"
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
                "- instruction.md references {{variables}} from session.json\n"
                "- Include resource limits in pod specs\n"
                "- Use filesystem tools to CREATE all files\n"
                "- Parse JSON in validation tests, check specific fields\n"
                "\n"
                "ALWAYS use filesystem tools to write actual files. DO NOT just describe what to create."
            ),
            tools=mcp_tool,
            tool_choice="required",
        )
        
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
