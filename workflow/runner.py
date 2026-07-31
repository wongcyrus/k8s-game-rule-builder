"""Main workflow runner."""
import asyncio
import argparse
import importlib
import logging
import signal
import sys
from dataclasses import dataclass
from threading import current_thread, main_thread

from agent_framework import (
    MCPStdioTool,
    WorkflowViz,
)

from agents.config import PATHS
from agents.k8s_task_idea_agent import create_idea_agent_with_mcp
from workflow.idea_generator import generate_task_idea
from workflow.builder import build_workflow
from workflow.models import InitialWorkflowState
from workflow.preflight import (
    K8sConnectivityError,
    QuarantinedTaskError,
    resolve_k8s_configuration,
    run_k8s_preflight_check,
    should_manage_minikube,
)


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


class GracefulStopController:
    """Handle task-level graceful shutdown for the workflow runner."""

    def __init__(self) -> None:
        self._stop_requested = False
        self._signal_count = 0
        self._restore_handlers: list[tuple[int, signal.Handlers]] = []

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def request_stop(self, signum: int | None = None, _frame=None) -> None:
        self._signal_count += 1
        if self._signal_count == 1:
            self._stop_requested = True
            signal_name = signal.Signals(signum).name if signum is not None else "manual request"
            logging.warning(
                "Stop requested via %s. Finishing the current task before exiting. Press Ctrl+C again to abort immediately.",
                signal_name,
            )
            return

        signal_name = signal.Signals(signum).name if signum is not None else "manual request"
        logging.warning("Received %s again. Aborting immediately.", signal_name)
        raise KeyboardInterrupt("Forced workflow shutdown requested")

    def install_signal_handlers(self) -> None:
        if current_thread() is not main_thread():
            return

        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handler = signal.getsignal(signum)
            signal.signal(signum, self.request_stop)
            self._restore_handlers.append((signum, previous_handler))

    def restore_signal_handlers(self) -> None:
        while self._restore_handlers:
            signum, previous_handler = self._restore_handlers.pop()
            signal.signal(signum, previous_handler)


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


def reset_minikube(iteration: int, config: WorkflowRuntimeConfig, *, k8s_configuration=None):
    # Clean up minikube before each iteration
    import subprocess
    if not config.reset_minikube:
        logging.info(f"[ITERATION {iteration + 1}] Skipping minikube reset (config)")
        return
    if k8s_configuration is not None and not should_manage_minikube(k8s_configuration):
        logging.info(
            "[ITERATION %s] Skipping minikube reset for authoritative kubeconfig (%s)",
            iteration + 1,
            k8s_configuration.endpoint,
        )
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


async def run_workflow(
    config: WorkflowRuntimeConfig | None = None,
    *,
    stop_controller: GracefulStopController | None = None,
):
    """Run the complete K8s task generation workflow."""
    config = config or WorkflowRuntimeConfig()
    stop_controller = stop_controller or GracefulStopController()
    stop_controller.install_signal_handlers()
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
    
    try:
        async with docs_mcp_tool, tests_mcp_tool:
            num_iterations = config.iterations
            k8s_configuration = resolve_k8s_configuration()

            for iteration in range(num_iterations):
                if stop_controller.stop_requested:
                    logging.info(
                        "Graceful stop requested before iteration %s. No new task will be started.",
                        iteration + 1,
                    )
                    break

                logging.info(f"\n[ITERATION {iteration + 1}/{num_iterations}] Starting task generation...")
                reset_minikube(iteration, config, k8s_configuration=k8s_configuration)
                if iteration == 0:
                    logging.info("[PREFLIGHT] Verifying Kubernetes connectivity before task generation...")
                    preflight_output = run_k8s_preflight_check()
                    logging.info("[PREFLIGHT] Kubernetes connectivity OK:\n%s", preflight_output)

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
                try:
                    async for event in workflow.run(initial_state, stream=True):
                        if event.type == "output":
                            if event.data and isinstance(event.data, str) and event.data.strip():
                                if "successfully generated" in event.data:
                                    workflow_succeeded = True
                except QuarantinedTaskError:
                    idea_memory.remove_concept(concept.concept)
                    raise
                except K8sConnectivityError:
                    idea_memory.remove_concept(concept.concept)
                    raise
                except Exception as exc:
                    # Task-level workflow crashes are real failures for this concept, not
                    # environment invalidations, so persist them and continue iterating.
                    reason = f"Workflow execution error: {type(exc).__name__}: {exc}"
                    idea_memory.add_failed_concept(concept, reason=reason)
                    logging.exception(
                        "Workflow crashed for concept %s. Saved it to failure memory.",
                        concept.concept,
                    )
                    logging.info(f"\n[ITERATION {iteration + 1}] Complete")
                    if stop_controller.stop_requested:
                        logging.info(
                            "Graceful stop requested. Current task finished; stopping before iteration %s.",
                            iteration + 2,
                        )
                        break
                    continue

                # Update memory based on workflow outcome
                if workflow_succeeded:
                    idea_memory.add_structured_concept(concept)
                    logging.info(f"💾 Task succeeded: {concept.concept}")
                else:
                    idea_memory.add_failed_concept(concept, reason="Workflow validation failed")
                    logging.info(f"💾 Saved concept to failure memory: {concept.concept}")

                logging.info(f"\n[ITERATION {iteration + 1}] Complete")

                if stop_controller.stop_requested:
                    logging.info(
                        "Graceful stop requested. Current task finished; stopping before iteration %s.",
                        iteration + 2,
                    )
                    break

            logging.info("\n" + "="*80)
            logging.info("WORKFLOW COMPLETE")
            logging.info("="*80)
    finally:
        stop_controller.restore_signal_handlers()


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
