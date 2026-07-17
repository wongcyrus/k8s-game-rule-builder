"""Main workflow runner."""
import asyncio
import logging
import importlib
import argparse
import sys
from dataclasses import dataclass

from agent_framework import (
    MCPStdioTool,
    WorkflowViz,
)

from agents.config import PATHS
from agents.k8s_task_idea_agent import create_idea_agent_with_mcp
from workflow.idea_generator import generate_task_idea
from workflow.builder import build_workflow
from workflow.models import InitialWorkflowState


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
)
# Suppress noisy third-party loggers
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("agent_framework").setLevel(logging.WARNING)


@dataclass(frozen=True)
class WorkflowRuntimeConfig:
    iterations: int = 80
    reset_minikube: bool = True
    minikube_delete_timeout: int = 120
    minikube_start_timeout: int = 300
    max_retries: int = 3
    save_workflow_graph: bool = True


def _build_task_prompt(*, task_id: str, target_topic: str, concept, beginner_task, existing_tasks: list[str], existing_concepts: list[str]) -> str:
    return (
        f"Generate a complete Kubernetes learning task with ID '{task_id}' about '{target_topic}'. "
        f"\n\nTask Details:"
        f"\n- Concept: {concept.concept}"
        f"\n- Description: {concept.description}"
        f"\n- Difficulty: {beginner_task.difficulty}"
        f"\n- Objective: {beginner_task.objective}"
        f"\n\nEXISTING TASKS (avoid these IDs): {', '.join(existing_tasks) if existing_tasks else 'None'}"
        f"\n\nPREVIOUSLY COVERED CONCEPTS (this is a new concept): {', '.join(existing_concepts) if existing_concepts else 'None'}"
        f"\n\n✅ Directory already created: {PATHS.game_root}/{task_id}/"
        f"\nWrite all files directly into this directory. Do NOT call create_directory."
        f"\n\nCreate ALL required files including __init__.py, instruction.md, concept.md, session.json, "
        f"setup.template.yaml, answer.template.yaml, and all test files (test_01_setup.py, "
        f"test_02_ready.py, test_03_answer.py, test_05_check.py, test_06_cleanup.py). "
        f"Include test_04_challenge.py only if the task requires pre-validation actions like load generation. "
        f"test_02_ready.py must test that resources from setup.template.yaml are ready. "
        f"Use proper Jinja template variables and follow all established patterns. "
        f"Make sure all files are syntactically correct and tests will pass."
    )


def reset_minikube(iteration: int, config: WorkflowRuntimeConfig):
    # Clean up minikube before each iteration
    import subprocess
    if not config.reset_minikube:
        logging.info(f"[ITERATION {iteration + 1}] Skipping minikube reset (config)")
        return

    try:
        logging.info(f"[ITERATION {iteration + 1}] Cleaning up minikube...")
        result = subprocess.run(
            ["minikube", "delete"],
            capture_output=True,
            text=True,
            timeout=config.minikube_delete_timeout
        )
        if result.returncode == 0:
            logging.info("Minikube cleanup completed successfully")
        else:
            logging.warning(f"Minikube cleanup returned non-zero exit code: {result.returncode}")
            logging.warning(f"stderr: {result.stderr}")
    
        # Start minikube after delete
        logging.info(f"[ITERATION {iteration + 1}] Starting minikube...")
        start_result = subprocess.run(
            ["minikube", "start", "--driver=docker", "--listen-address=127.0.0.1", "--apiserver-names=localhost", "--ports=127.0.0.1:8443:8443"],
            capture_output=True,
            text=True,
            timeout=config.minikube_start_timeout
        )
        if start_result.returncode == 0:
            logging.info("Minikube started successfully")
        else:
            logging.warning(f"Minikube start returned non-zero exit code: {start_result.returncode}")
            logging.warning(f"stderr: {start_result.stderr}")
    
    except subprocess.TimeoutExpired:
        logging.error("Minikube operation timed out")
    except FileNotFoundError:
        logging.warning("minikube command not found - skipping cleanup and start")
    except Exception as e:
        logging.error(f"Error during minikube operation: {e}")


async def run_workflow(config: WorkflowRuntimeConfig | None = None):
    """Run the complete K8s task generation workflow."""
    config = config or WorkflowRuntimeConfig()
    # Force reload to pick up code changes
    if 'agents.pytest_runner' in sys.modules:
        importlib.reload(sys.modules['agents.pytest_runner'])
    
    logging.info("="*80)
    logging.info("K8S TASK GENERATION WORKFLOW")
    logging.info("="*80)
    
    
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
        num_iterations = config.iterations

        for iteration in range(num_iterations):
            logging.info(f"\n[ITERATION {iteration + 1}/{num_iterations}] Starting task generation...")
            reset_minikube(iteration, config)

            # Create a new agent and workflow for each iteration
            idea_agent, idea_memory = await create_idea_agent_with_mcp(docs_mcp_tool)
            workflow, generator_executor, fixer_executor = await build_workflow(tests_mcp_tool)

            # Generate workflow visualization only on first iteration
            if iteration == 0 and config.save_workflow_graph:
                viz = WorkflowViz(workflow)
                try:
                    viz.save_png("workflow_graph.png")
                    logging.info("Saved workflow graph to workflow_graph.png")
                except Exception:
                    pass

            # Step 1: Generate unique task idea
            concept = await generate_task_idea(idea_agent, idea_memory)

            beginner_task = concept.variations[0]
            target_topic = concept.concept
            task_id = beginner_task.task_id

            # Save concept immediately so restarts won't regenerate it
            idea_memory.add_structured_concept(concept)

            # Step 2: Run workflow
            logging.info(f"\n[STEP 2] Running workflow to generate task files for iteration {iteration + 1}...")

            # Get existing tasks
            game_dir = PATHS.game_root
            existing_tasks = []
            if game_dir.exists():
                existing_tasks = [d.name for d in game_dir.iterdir() if d.is_dir() and d.name[0].isdigit()]

            # Get existing concepts
            existing_concepts = []
            if idea_memory.generated_ideas:
                existing_concepts = [idea['concept'] for idea in idea_memory.generated_ideas.values()]

            task_prompt = _build_task_prompt(
                task_id=task_id,
                target_topic=target_topic,
                concept=concept,
                beginner_task=beginner_task,
                existing_tasks=existing_tasks,
                existing_concepts=existing_concepts,
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
                max_retries=config.max_retries
            )

            workflow_succeeded = False

            # Run workflow fresh so each retry recreates agents and Azure OpenAI clients
            async for event in workflow.run(initial_state, stream=True):
                if event.type == "output":
                    if event.data and isinstance(event.data, str) and event.data.strip():
                        if "successfully generated" in event.data:
                            workflow_succeeded = True

            # Update memory based on workflow outcome
            if workflow_succeeded:
                logging.info(f"💾 Task succeeded: {concept.concept}")
            else:
                # Move from success memory to failure memory
                idea_memory.add_failed_concept(concept, reason="Workflow validation failed")
                logging.info(f"💾 Saved concept to failure memory: {concept.concept}")

            logging.info(f"\n[ITERATION {iteration + 1}] Complete")

        logging.info("\n" + "="*80)
        logging.info("WORKFLOW COMPLETE")
        logging.info("="*80)


def main():
    """Entry point for the workflow."""
    parser = argparse.ArgumentParser(description="Run K8s task generation workflow.")
    parser.add_argument("--iterations", type=int, default=80, help="Number of workflow iterations to run.")
    parser.add_argument(
        "--reset-minikube",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable minikube reset between iterations.",
    )
    parser.add_argument(
        "--minikube-delete-timeout",
        type=int,
        default=120,
        help="Timeout seconds for 'minikube delete'.",
    )
    parser.add_argument(
        "--minikube-start-timeout",
        type=int,
        default=300,
        help="Timeout seconds for 'minikube start'.",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Fix attempts per task before giving up.")
    parser.add_argument(
        "--save-workflow-graph",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable writing workflow_graph.png on first iteration.",
    )
    args = parser.parse_args()

    runtime_config = WorkflowRuntimeConfig(
        iterations=args.iterations,
        reset_minikube=args.reset_minikube,
        minikube_delete_timeout=args.minikube_delete_timeout,
        minikube_start_timeout=args.minikube_start_timeout,
        max_retries=args.max_retries,
        save_workflow_graph=args.save_workflow_graph,
    )
    asyncio.run(run_workflow(runtime_config))


if __name__ == "__main__":
    main()
