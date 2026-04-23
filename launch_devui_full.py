"""Launch DevUI with the FULL workflow including generator agent and retry loop.

This script creates the workflow programmatically and registers entities with
DevUI. MCP tools use lazy initialization and connect automatically on first use
inside the DevUI event loop — do NOT use ``async with`` or ``__aenter__`` here.

The workflow generates 1 successful task with automatic retry on failure (up to 3 attempts).
"""
import asyncio
from agent_framework import AgentExecutor, WorkflowBuilder, MCPStdioTool
from agent_framework.devui import serve

from agents.k8s_task_generator_agent import create_generator_agent_with_mcp
from agents.config import PATHS

# Import executors from workflow
from workflow import (
    initialize_retry,
    parse_generated_task,
    run_validation,
    run_pytest,
    make_decision,
    keep_task,
    remove_task,
    check_loop,
    retry_generation,
    complete_workflow,
    select_action,
    select_loop_action,
)


async def create_entities():
    """Create all entities including the full workflow.

    MCP tools connect lazily on first use — no ``async with`` needed here.
    See: https://learn.microsoft.com/agent-framework/devui/security#best-practices
    """
    print("Creating full workflow with generator agent and loop...")

    # Create MCP tool — do NOT enter async context; DevUI handles lifecycle
    mcp_tool = MCPStdioTool(
        name="filesystem",
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            str(PATHS.tests_root),
        ],
        load_prompts=False,
    )

    # Create generator agent (MCP tool is passed by reference, connected lazily)
    gen_agent = await create_generator_agent_with_mcp(mcp_tool)
    generator_executor = AgentExecutor(gen_agent, id="generator_agent")

    # Build workflow matching the structure in workflow/builder.py.
    # initialize_retry is the start executor — it wraps raw input into a
    # proper AgentExecutorRequest before forwarding to the generator agent.
    workflow = (
        WorkflowBuilder(start_executor=initialize_retry)
        .add_edge(initialize_retry, generator_executor)
        .add_edge(generator_executor, parse_generated_task)
        .add_edge(parse_generated_task, run_validation)
        .add_edge(run_validation, run_pytest)
        .add_edge(run_pytest, make_decision)
        .add_multi_selection_edge_group(
            make_decision,
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

    return [workflow, gen_agent]


def main():
    """Launch DevUI with full workflow and agents."""
    print("Launching DevUI with FULL workflow and all agents...")
    print("\nEntities:")
    print("  ✅ K8s Task Workflow (with retry loop)")
    print("  ✅ Generator Agent (with MCP filesystem)")
    print("  ✅ Validator (direct Python - no LLM)")
    print("  ✅ Pytest Runner (direct Python - no LLM)")
    print("\nFeatures:")
    print("  - Retry loop (up to 3 attempts)")
    print("  - Topic-focused generation")
    print("  - Two decision points (keep/remove, retry/complete)")
    print("  - Shared state management")
    print("  - MCP tool connects lazily on first agent run")
    print("\n🌐 Opening browser to http://localhost:8081")

    # Create entities — MCP tool is constructed but not connected yet
    entities = asyncio.run(create_entities())

    print(f"\n✅ Registered {len(entities)} entities")

    # Launch DevUI — MCP tool will connect automatically when the agent runs
    serve(
        entities=entities,
        port=8081,
        auto_open=True,
    )


if __name__ == "__main__":
    main()
