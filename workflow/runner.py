"""Main workflow runner."""
import asyncio
import logging
import importlib
import sys

from agent_framework import (
    MCPStdioTool,
    WorkflowEvent,
    WorkflowViz,
)
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential

from agents.config import PATHS, AZURE
from agents.k8s_task_idea_agent import create_idea_agent_with_mcp
from workflow.idea_generator import generate_task_idea
from workflow.builder import build_workflow
from workflow.models import InitialWorkflowState


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


async def run_workflow():
    """Run the complete K8s task generation workflow."""
    # Force reload to pick up code changes
    if 'agents.pytest_runner' in sys.modules:
        importlib.reload(sys.modules['agents.pytest_runner'])
    
    logging.info("="*80)
    logging.info("K8S TASK GENERATION WORKFLOW")
    logging.info("="*80)
    
    credential = AzureCliCredential()
    responses_client = AzureOpenAIResponsesClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=credential,
    )
    
    # Create MCP tools
    docs_mcp_tool = MCPStdioTool(
        name="filesystem_docs",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(PATHS.k8s_docs_root)],
        load_prompts=False
    )
    
    tests_mcp_tool = MCPStdioTool(
        name="filesystem_tests",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(PATHS.tests_root.parent)],
        load_prompts=False
    )
    
    async with docs_mcp_tool, tests_mcp_tool:
        # Create agents
        idea_agent, idea_memory = await create_idea_agent_with_mcp(docs_mcp_tool)
        
        # Build workflow
        workflow, generator_executor, fixer_executor = await build_workflow(tests_mcp_tool)
        
        # Generate workflow visualization
        viz = WorkflowViz(workflow)
        print(viz.to_mermaid())
        print(viz.to_digraph())
        
        try:
            viz.save_png("workflow_graph.png")
        except Exception:
            pass
        
        # Step 1: Generate unique task idea
        concept = await generate_task_idea(idea_agent, idea_memory)
        
        beginner_task = concept.variations[0]
        target_topic = concept.concept
        task_id = beginner_task.task_id
        
        # Step 2: Run workflow
        logging.info("\n[STEP 2] Running workflow to generate task files...")
        
        # Get existing tasks
        game_dir = PATHS.game_root
        existing_tasks = []
        if game_dir.exists():
            existing_tasks = [d.name for d in game_dir.iterdir() if d.is_dir() and d.name[0].isdigit()]
        
        # Get existing concepts
        existing_concepts = []
        if idea_memory.generated_ideas:
            existing_concepts = [idea['concept'] for idea in idea_memory.generated_ideas.values()]
        
        task_prompt = (
            f"Generate a complete Kubernetes learning task with ID '{task_id}' about '{target_topic}'. "
            f"\n\nTask Details:"
            f"\n- Concept: {concept.concept}"
            f"\n- Description: {concept.description}"
            f"\n- Difficulty: {beginner_task.difficulty}"
            f"\n- Objective: {beginner_task.objective}"
            f"\n\nEXISTING TASKS (avoid these IDs): {', '.join(existing_tasks) if existing_tasks else 'None'}"
            f"\n\nPREVIOUSLY COVERED CONCEPTS (this is a new concept): {', '.join(existing_concepts) if existing_concepts else 'None'}"
            f"\n\n✅ Create directory: {PATHS.game_name}/{task_id}/"
            f"\n\nCreate ALL required files including __init__.py, instruction.md, session.json, "
            f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
            f"test_02_ready.py, test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
            f"Include test_04_challenge.py only if the task requires pre-validation actions like load generation. "
            f"test_02_ready.py must test that resources from setup.template.yaml are ready. "
            f"Use proper Jinja template variables and follow all established patterns. "
            f"Make sure all files are syntactically correct and tests will pass."
        )
        
        # Create initial state object
        initial_state = InitialWorkflowState(
            prompt=task_prompt,
            target_topic=target_topic,
            task_id=task_id,
            concept_description=concept.description,
            difficulty=beginner_task.difficulty,
            objective=beginner_task.objective,
            retry_count=0,
            max_retries=3
        )
        
        workflow_succeeded = False
        
        async for event in workflow.run_stream(initial_state):
            if isinstance(event, WorkflowEvent):
                if event.data and isinstance(event.data, str) and event.data.strip():
                    if "successfully generated" in event.data:
                        workflow_succeeded = True
        
        # Save concept to memory only if workflow succeeded
        if workflow_succeeded:
            idea_memory.add_structured_concept(concept)
            logging.info(f"\n💾 Saved concept to memory: {concept.concept}")
        
        logging.info("\n" + "="*80)
        logging.info("WORKFLOW COMPLETE")
        logging.info("="*80)


def main():
    """Entry point for the workflow."""
    asyncio.run(run_workflow())


if __name__ == "__main__":
    main()
