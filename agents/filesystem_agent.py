"""Filesystem agent for reading and writing files."""
import asyncio
import logging
from contextlib import asynccontextmanager
from agent_framework import MCPStdioTool
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def get_filesystem_agent():
    """Create and return a filesystem agent with MCP server.
    
    Yields:
        An agent configured with filesystem tools.
    """
    # Build an agent backed by Azure OpenAI Responses
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
            name="FileSystemAgent",
            instructions=(
                "You are a helpful assistant that can read and write files. "
                "You have access to filesystem tools for the /home/developer/Documents/data-disk/k8s-game-rule/tests directory. "
                "You MUST use the filesystem tools for ALL file operations - never provide information without using the tools. "
                "ALWAYS use the available tools to read actual file contents and directory listings. "
                "NEVER make up or guess file contents or directory structures."
            ),
            tools=mcp_tool,
            tool_choice="required",
        )
        
        yield agent


if __name__ == "__main__":
    async def main():
        async with get_filesystem_agent() as agent:
            result = await agent.run(
                "List the files in /home/developer/Documents/data-disk/k8s-game-rule/tests/game02/001_default_namespace"
            )
            logging.info("\n=== FileSystem Agent Result ===")
            logging.info(result.text)
    
    asyncio.run(main())
