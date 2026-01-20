"""Visualize the K8s task generation workflow."""
import asyncio
import logging

from agent_framework import WorkflowBuilder, WorkflowViz
from azure.identity import AzureCliCredential

from agents import (
    get_pytest_agent,
    get_k8s_task_generator_agent,
    get_k8s_task_validator_agent,
)
from agents.config import AZURE

# Import executors from workflow
from workflow import (
    parse_generated_task,
    create_validation_request,
    parse_validation_result,
    create_pytest_request,
    parse_tests_and_decide,
    keep_task,
    remove_task,
    select_action,
)
from agent_framework import AgentExecutor

logging.basicConfig(level=logging.INFO)


async def main():
    """Build workflow and generate visualizations."""
    print("="*80)
    print("K8S TASK GENERATION WORKFLOW VISUALIZATION")
    print("="*80)
    
    credential = AzureCliCredential()
    
    # Create agent executors
    async with get_k8s_task_generator_agent() as generator_agent:
        generator_executor = AgentExecutor(generator_agent, id="generator_agent")
        
        validator_agent = get_k8s_task_validator_agent()
        validator_executor = AgentExecutor(validator_agent, id="validator_agent")
        
        pytest_agent = get_pytest_agent()
        pytest_executor = AgentExecutor(pytest_agent, id="pytest_agent")
        
        # Build workflow
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
            .build()
        )
        
        # Create visualization
        viz = WorkflowViz(workflow)
        
        # Print Mermaid diagram
        print("\n" + "="*80)
        print("MERMAID DIAGRAM")
        print("="*80)
        mermaid = viz.to_mermaid()
        print(mermaid)
        
        # Print DiGraph
        print("\n" + "="*80)
        print("DIGRAPH (DOT FORMAT)")
        print("="*80)
        digraph = viz.to_digraph()
        print(digraph)
        
        # Export to files
        print("\n" + "="*80)
        print("EXPORTING TO FILES")
        print("="*80)
        
        try:
            svg_file = viz.save_svg("workflow_graph.svg")
            print(f"✅ SVG exported to: {svg_file}")
        except Exception as e:
            print(f"❌ Could not export SVG: {e}")
        
        try:
            png_file = viz.save_png("workflow_graph.png")
            print(f"✅ PNG exported to: {png_file}")
        except Exception as e:
            print(f"❌ Could not export PNG: {e}")
        
        try:
            pdf_file = viz.save_pdf("workflow_graph.pdf")
            print(f"✅ PDF exported to: {pdf_file}")
        except Exception as e:
            print(f"❌ Could not export PDF: {e}")
        
        print("\n" + "="*80)
        print("VISUALIZATION COMPLETE")
        print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
