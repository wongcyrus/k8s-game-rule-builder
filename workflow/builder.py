"""Workflow builder for K8s task generation."""
import logging
from agent_framework import (
    AgentExecutor,
    WorkflowBuilder,
    MCPStdioTool,
)

from agents.config import PATHS
from agents.k8s_task_generator_agent import create_generator_agent_with_mcp
from agents.k8s_task_fixer_agent import create_fixer_agent_with_mcp
from workflow.executors import (
    initialize_retry,
    parse_generated_task,
    run_validation,
    run_pytest,
    make_decision,
    keep_task,
    remove_task,
    check_loop,
    retry_generation,
    fix_task,
    run_pytest_skip_answer,
    complete_workflow,
)
from workflow.selectors import select_action, select_loop_action, select_skip_answer_action


async def build_workflow(tests_mcp_tool: MCPStdioTool):
    """Build the K8s task generation workflow.
    
    Args:
        tests_mcp_tool: MCP tool for filesystem access to tests
        
    Returns:
        Tuple of (workflow, generator_executor, fixer_executor)
    """
    logging.info("Building workflow...")
    
    generator_agent = await create_generator_agent_with_mcp(tests_mcp_tool)
    generator_executor = AgentExecutor(generator_agent, id="generator_agent")
    
    fixer_agent = await create_fixer_agent_with_mcp(tests_mcp_tool)
    fixer_executor = AgentExecutor(fixer_agent, id="fixer_agent")
    
    workflow = (
        WorkflowBuilder()
        .set_start_executor(initialize_retry)
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
        .add_edge(keep_task, run_pytest_skip_answer)
        .add_edge(remove_task, check_loop)
        .add_multi_selection_edge_group(
            run_pytest_skip_answer,
            [check_loop, complete_workflow],
            selection_func=select_skip_answer_action,
        )
        .add_multi_selection_edge_group(
            check_loop,
            [fix_task, complete_workflow],
            selection_func=select_loop_action,
        )
        .add_edge(fix_task, fixer_executor)
        .add_edge(fixer_executor, parse_generated_task)
        .build()
    )
    
    return workflow, generator_executor, fixer_executor
