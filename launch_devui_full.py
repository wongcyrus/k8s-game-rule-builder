"""Launch DevUI with the FULL workflow including generator agent and retry loop.

This script creates the workflow programmatically and keeps the MCP context alive
for the entire DevUI session to support the workflow retry loop.

The workflow generates 1 successful task with automatic retry on failure (up to 3 attempts).
"""
import asyncio
from agent_framework import AgentExecutor, WorkflowBuilder, MCPStdioTool
from agent_framework.devui import serve

from agents import (
    get_pytest_agent,
    get_k8s_task_validator_agent,
)
from agents.k8s_task_generator_agent import create_generator_agent_with_mcp
from agents.config import PATHS

# Import executors from workflow
from workflow import (
    parse_generated_task,
    create_validation_request,
    parse_validation_result,
    create_pytest_request,
    parse_tests_and_decide,
    keep_task,
    remove_task,
    check_loop,
    retry_generation,  # Changed from generate_next
    complete_workflow,
    select_action,
    select_loop_action,
)


# Global to keep MCP tool alive
mcp_tool = None


async def create_entities():
    """Create all entities including the full workflow."""
    global mcp_tool
    
    print("Creating full workflow with generator agent and loop...")
    
    # Create MCP tool - keep it alive globally
    mcp_tool = MCPStdioTool(
        name="filesystem",
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            str(PATHS.tests_root)
        ],
        load_prompts=False
    )
    
    # Start the MCP tool
    await mcp_tool.__aenter__()
    
    # Create generator agent with persistent MCP tool (reuses agent creation logic)
    gen_agent = await create_generator_agent_with_mcp(mcp_tool)
    generator_executor = AgentExecutor(gen_agent, id="generator_agent")
    
    validator_agent = get_k8s_task_validator_agent()
    validator_executor = AgentExecutor(validator_agent, id="validator_agent")
    
    pytest_agent = get_pytest_agent()
    pytest_executor = AgentExecutor(pytest_agent, id="pytest_agent")
    
    # Build workflow with conditional logic and retry loop
    workflow = (
        WorkflowBuilder()
        .set_start_executor(generator_executor)
        .add_edge(generator_executor, parse_generated_task)
        .add_edge(parse_generated_task, create_validation_request)
        .add_edge(create_validation_request, validator_executor)
        .add_edge(validator_executor, parse_validation_result)
        .add_edge(parse_validation_result, create_pytest_request)
        .add_edge(create_pytest_request, pytest_executor)
        .add_edge(pytest_executor, parse_tests_and_decide)
        .add_multi_selection_edge_group(
            parse_tests_and_decide,
            [keep_task, remove_task],
            selection_func=select_action,
        )
        # Add retry loop edges
        .add_edge(keep_task, check_loop)
        .add_edge(remove_task, check_loop)
        .add_multi_selection_edge_group(
            check_loop,
            [retry_generation, complete_workflow],
            selection_func=select_loop_action,
        )
        # retry_generation loops back to generator
        .add_edge(retry_generation, generator_executor)
        .build()
    )
    
    # Return workflow and all individual agents
    return [workflow, gen_agent, validator_agent, pytest_agent]


def main():
    """Launch DevUI with full workflow and agents."""
    print("Launching DevUI with FULL workflow and all agents...")
    print("\nEntities:")
    print("  ✅ K8s Task Workflow (with retry loop)")
    print("  ✅ Generator Agent (with MCP filesystem)")
    print("  ✅ Validator Agent")
    print("  ✅ Pytest Agent")
    print("\nFeatures:")
    print("  - Retry loop (up to 3 attempts)")
    print("  - Topic-focused generation")
    print("  - Two decision points (keep/remove, retry/complete)")
    print("  - Shared state management")
    print("  - MCP tool stays alive for entire session")
    print("\n🌐 Opening browser to http://localhost:8081")
    
    # Create entities synchronously
    entities = asyncio.run(create_entities())
    
    print(f"\n✅ Registered {len(entities)} entities")
    print("✅ MCP filesystem tool is active and will remain alive")
    
    try:
        # Launch DevUI with the full workflow and all agents
        serve(
            entities=entities,
            port=8081,
            auto_open=True
        )
    finally:
        # Clean up MCP tool when DevUI shuts down
        if mcp_tool:
            print("\n🧹 Cleaning up MCP tool...")
            asyncio.run(mcp_tool.__aexit__(None, None, None))


if __name__ == "__main__":
    main()
