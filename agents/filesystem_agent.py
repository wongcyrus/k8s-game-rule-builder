"""Filesystem agent for reading and writing files."""
import asyncio
import logging
from contextlib import asynccontextmanager
from agent_framework import MCPStdioTool
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential
from .logging_middleware import LoggingFunctionMiddleware
from .config import PATHS, AZURE

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def get_filesystem_agent():
    """Create and return a filesystem agent with MCP server.
    
    Yields:
        An agent configured with filesystem tools.
    """
    # Build an agent backed by Azure OpenAI Responses
    responses_client = AzureOpenAIResponsesClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=AzureCliCredential(),
    )
    
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
        agent = responses_client.as_agent(
            name="FileSystemAgent",
            instructions=(
                "You are a helpful assistant that can read and write files. "
                f"You have access to filesystem tools for the {PATHS.tests_root} directory. "
                "You MUST use the filesystem tools for ALL file operations - never provide information without using the tools. "
                "ALWAYS use the available tools to read actual file contents and directory listings. "
                "NEVER make up or guess file contents or directory structures."
            ),
            tools=mcp_tool,
            tool_choice="required",
            middleware=[LoggingFunctionMiddleware()],
        )
        
        yield agent


if __name__ == "__main__":
    async def main():
        async with get_filesystem_agent() as agent:
            result = await agent.run(
                f"List the files in {PATHS.game_root}/001_default_namespace"
            )
            logging.info("\n=== FileSystem Agent Result ===")
            logging.info(result.text)
    
    asyncio.run(main())
