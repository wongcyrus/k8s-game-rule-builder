"""Main workflow runner."""
import asyncio
import argparse
import importlib
import json
import logging
import os
import signal
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import current_thread, main_thread

from agent_framework import (
    MCPStdioTool,
    WorkflowViz,
)

from agents.config import PATHS
from agents.k8s_task_idea_agent import create_idea_agent_with_mcp
from workflow.idea_generator import generate_task_idea
from workflow.builder import build_workflow
from workflow.models import InitialWorkflowState, WorkflowStopRequested
from workflow.preflight import (
    K8sConnectivityError,
    QuarantinedTaskError,
    resolve_k8s_configuration,
    run_k8s_preflight_check,
    should_manage_minikube,
)
from workflow.reporting import archive_phase_output, append_workflow_phase_summary


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
)
# Suppress noisy third-party loggers
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("agent_framework").setLevel(logging.WARNING)


INTERRUPTED_TASK_ARTIFACT_GLOBS = (
    "*.gen.yaml",
    "test_result.txt",
    "no_answer_test_result.txt",
    "test_*.json",
)

CLUSTER_SCOPED_RESOURCE_KEYS = {
    "pv_name": "persistentvolume",
    "storageclass_name": "storageclass",
    "priorityclass_name": "priorityclass.scheduling.k8s.io",
    "gatewayclass_name": "gatewayclass.gateway.networking.k8s.io",
    "csidriver_name": "csidriver.storage.k8s.io",
}


@dataclass(frozen=True)
class WorkflowRuntimeConfig:
    iterations: int = 80
    reset_minikube: bool = True
    minikube_delete_timeout: int = 120
    minikube_start_timeout: int = 300
    max_retries: int = 3
    save_workflow_graph: bool = True
    stop_file: str | None = ".workflow-stop"
    post_iteration_stop_wait_seconds: float = 2.0


class GracefulStopController:
    """Handle task-level graceful shutdown for the workflow runner."""

    def __init__(self, stop_file: str | None = None) -> None:
        self._stop_requested = False
        self._signal_count = 0
        self._restore_handlers: list[tuple[int, signal.Handlers]] = []
        self._stop_file = Path(stop_file).resolve() if stop_file else None

    @property
    def stop_requested(self) -> bool:
        self._poll_stop_file()
        return self._stop_requested

    @property
    def stop_file(self) -> Path | None:
        return self._stop_file

    def prepare_stop_file(self) -> None:
        if self._stop_file is None:
            return
        try:
            self._stop_file.unlink(missing_ok=True)
        except Exception as exc:
            logging.warning("Failed to remove stale stop file %s: %s", self._stop_file, exc)

    def clear_stop_file(self) -> None:
        if self._stop_file is None:
            return
        try:
            self._stop_file.unlink(missing_ok=True)
        except Exception as exc:
            logging.warning("Failed to clear stop file %s: %s", self._stop_file, exc)

    def _request_active_pytest_interrupt(self) -> None:
        try:
            from agents.pytest_runner import request_pytest_interrupt
            request_pytest_interrupt()
        except Exception as exc:
            logging.warning("Failed to request pytest interruption during graceful stop: %s", exc)

    def _mark_stop_requested(self, source: str) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        self._request_active_pytest_interrupt()
        logging.warning(
            "Stop requested via %s. The workflow will stop cleanly after the current step and cleanup.",
            source,
        )

    def _poll_stop_file(self) -> None:
        if self._stop_requested or self._stop_file is None:
            return
        if self._stop_file.exists():
            self._mark_stop_requested(f"stop file {self._stop_file}")

    async def wait_for_post_iteration_stop_window(self, seconds: float) -> bool:
        if seconds <= 0:
            return self.stop_requested
        if self.stop_requested:
            return True

        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            if self.stop_requested:
                return True
            await asyncio.sleep(0.1)
        return self.stop_requested

    def request_stop(self, signum: int | None = None, _frame=None) -> None:
        self._signal_count += 1
        signal_name = signal.Signals(signum).name if signum is not None else "manual request"
        if self._signal_count == 1:
            self._mark_stop_requested(signal_name)
            return

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


def _run_best_effort_kubectl(args: list[str]) -> None:
    env = {**os.environ, "KUBECONFIG": os.environ.get("KUBECONFIG", "/home/developer/.kube/config")}
    try:
        result = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        logging.warning("kubectl command not found during interrupted task cleanup")
        return
    except Exception as exc:
        logging.warning("Interrupted task cleanup command failed to start %s: %s", args, exc)
        return

    if result.returncode != 0 and result.stderr.strip():
        logging.warning("Interrupted task cleanup command failed %s: %s", args, result.stderr.strip())


def _load_interrupted_task_runtime_contexts(task_dir: Path) -> list[dict[str, object]]:
    contexts: list[dict[str, object]] = []
    for path in sorted(task_dir.glob("test_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logging.warning("Failed to parse runtime context %s: %s", path, exc)
            continue
        if isinstance(data, dict):
            contexts.append(data)
    return contexts


def _cleanup_interrupted_cluster_resources(task_dir: Path) -> None:
    for manifest_name in ("answer.gen.yaml", "setup.gen.yaml"):
        manifest_path = task_dir / manifest_name
        if manifest_path.exists():
            _run_best_effort_kubectl(["delete", "-f", str(manifest_path), "--ignore-not-found=true"])

    contexts = _load_interrupted_task_runtime_contexts(task_dir)
    seen_namespaces: set[str] = set()
    seen_cluster_scoped: set[tuple[str, str]] = set()
    for context in contexts:
        namespace = context.get("namespace")
        if isinstance(namespace, str) and namespace and namespace not in seen_namespaces:
            seen_namespaces.add(namespace)
            _run_best_effort_kubectl(["delete", "namespace", namespace, "--ignore-not-found=true", "--wait=false"])

        for key, resource_type in CLUSTER_SCOPED_RESOURCE_KEYS.items():
            name = context.get(key)
            if isinstance(name, str) and name:
                resource_ref = (resource_type, name)
                if resource_ref not in seen_cluster_scoped:
                    seen_cluster_scoped.add(resource_ref)
                    _run_best_effort_kubectl(["delete", resource_type, name, "--ignore-not-found=true"])


def _cleanup_interrupted_local_artifacts(task_dir: Path, *, task_dir_preexisting: bool) -> None:
    if not task_dir.exists():
        return

    if not task_dir_preexisting:
        shutil.rmtree(task_dir, ignore_errors=True)
        return

    for pattern in INTERRUPTED_TASK_ARTIFACT_GLOBS:
        for path in task_dir.glob(pattern):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            except Exception as exc:
                logging.warning("Failed to remove interrupted artifact %s: %s", path, exc)

    for pycache_dir in task_dir.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache_dir, ignore_errors=True)
        except Exception as exc:
            logging.warning("Failed to remove interrupted cache dir %s: %s", pycache_dir, exc)


def _cleanup_interrupted_task(*, task_id: str, task_dir: Path, task_dir_preexisting: bool) -> None:
    logging.info("Cleaning interrupted task artifacts for %s", task_id)
    _cleanup_interrupted_cluster_resources(task_dir)
    _cleanup_interrupted_local_artifacts(task_dir, task_dir_preexisting=task_dir_preexisting)


def _reports_base_dir() -> Path:
    pytest_rootdir = getattr(PATHS, "pytest_rootdir", None)
    if pytest_rootdir is not None:
        return Path(pytest_rootdir)

    game_root = getattr(PATHS, "game_root", None)
    if game_root is not None:
        return Path(game_root).parents[1]

    tests_root = getattr(PATHS, "tests_root", None)
    if tests_root is not None:
        return Path(tests_root).parent

    return Path.cwd()


def _task_directory_string(task_id: str) -> str:
    game_name = getattr(PATHS, "game_name", Path(PATHS.game_root).name)
    return f"tests/{game_name}/{task_id}"


async def _wait_for_post_iteration_stop_window(stop_controller, seconds: float) -> bool:
    if hasattr(stop_controller, "wait_for_post_iteration_stop_window"):
        return await stop_controller.wait_for_post_iteration_stop_window(seconds)
    if seconds <= 0:
        return bool(getattr(stop_controller, "stop_requested", False))

    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        if bool(getattr(stop_controller, "stop_requested", False)):
            return True
        await asyncio.sleep(0.1)
    return bool(getattr(stop_controller, "stop_requested", False))


async def run_workflow(
    config: WorkflowRuntimeConfig | None = None,
    *,
    stop_controller: GracefulStopController | None = None,
):
    """Run the complete K8s task generation workflow."""
    config = config or WorkflowRuntimeConfig()
    stop_controller = stop_controller or GracefulStopController(config.stop_file)
    if hasattr(stop_controller, "prepare_stop_file"):
        stop_controller.prepare_stop_file()
    previous_stop_file_env = os.environ.get("K8S_BUILDER_STOP_FILE")
    if getattr(stop_controller, "stop_file", None):
        os.environ["K8S_BUILDER_STOP_FILE"] = str(stop_controller.stop_file)
    else:
        os.environ.pop("K8S_BUILDER_STOP_FILE", None)
    stop_controller.install_signal_handlers()
    # Force reload to pick up code changes
    if 'agents.pytest_runner' in sys.modules:
        importlib.reload(sys.modules['agents.pytest_runner'])
    
    logging.info("="*80)
    logging.info("K8S TASK GENERATION WORKFLOW")
    logging.info("="*80)
    workflow_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    
    
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

    current_concept = None
    current_task_id: str | None = None
    current_task_dir: Path | None = None
    current_task_dir_preexisting = False
    current_idea_memory = None
    
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
                if stop_controller.stop_requested:
                    logging.info(
                        "Graceful stop requested during iteration %s setup. Stopping before task generation.",
                        iteration + 1,
                    )
                    break
                if iteration == 0:
                    logging.info("[PREFLIGHT] Verifying Kubernetes connectivity before task generation...")
                    preflight_output = run_k8s_preflight_check()
                    logging.info("[PREFLIGHT] Kubernetes connectivity OK:\n%s", preflight_output)
                    if stop_controller.stop_requested:
                        logging.info(
                            "Graceful stop requested during preflight for iteration %s. Stopping before task generation.",
                            iteration + 1,
                        )
                        break

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
                task_dir = PATHS.game_root / task_id
                task_dir_preexisting = task_dir.exists()
                current_concept = concept
                current_task_id = task_id
                current_task_dir = task_dir
                current_task_dir_preexisting = task_dir_preexisting
                current_idea_memory = idea_memory

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
                    max_retries=config.max_retries,
                    iteration_number=iteration + 1,
                    workflow_started_at=workflow_started_at,
                    stop_requested_callback=lambda: stop_controller.stop_requested,
                    task_dir_preexisting=task_dir_preexisting,
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
                except WorkflowStopRequested:
                    idea_memory.remove_concept(concept.concept)
                    if current_task_dir is not None:
                        _cleanup_interrupted_task(
                            task_id=task_id,
                            task_dir=current_task_dir,
                            task_dir_preexisting=current_task_dir_preexisting,
                        )
                    logging.info(
                        "Workflow interrupted for concept %s. Removed it from memory and stopped cleanly.",
                        concept.concept,
                    )
                    append_workflow_phase_summary(
                        workflow_started_at=workflow_started_at,
                        iteration=iteration + 1,
                        task_id=task_id,
                        target_topic=target_topic,
                        difficulty=beginner_task.difficulty,
                        phase="workflow_complete",
                        attempt=None,
                        status="interrupted",
                        is_valid=None,
                        reason="Workflow stopped gracefully before task completion",
                        task_directory=_task_directory_string(task_id),
                        reports_base_dir=_reports_base_dir(),
                    )
                    break
                except Exception as exc:
                    # Task-level workflow crashes are real failures for this concept, not
                    # environment invalidations, so persist them and continue iterating.
                    reason = f"Workflow execution error: {type(exc).__name__}: {exc}"
                    idea_memory.add_failed_concept(concept, reason=reason)
                    artifact_path = archive_phase_output(
                        task_id=task_id,
                        phase="workflow_complete",
                        attempt=None,
                        status="execution_error",
                        content="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                        reports_base_dir=_reports_base_dir(),
                    )
                    append_workflow_phase_summary(
                        workflow_started_at=workflow_started_at,
                        iteration=iteration + 1,
                        task_id=task_id,
                        target_topic=target_topic,
                        difficulty=beginner_task.difficulty,
                        phase="workflow_complete",
                        attempt=None,
                        status="execution_error",
                        is_valid=False,
                        reason=reason,
                        task_directory=_task_directory_string(task_id),
                        artifact_path=artifact_path,
                        reports_base_dir=_reports_base_dir(),
                    )
                    logging.exception(
                        "Workflow crashed for concept %s. Saved it to failure memory.",
                        concept.concept,
                    )
                    logging.info(f"\n[ITERATION {iteration + 1}] Complete")
                    current_concept = None
                    current_task_id = None
                    current_task_dir = None
                    current_task_dir_preexisting = False
                    current_idea_memory = None
                    if await _wait_for_post_iteration_stop_window(
                        stop_controller,
                        config.post_iteration_stop_wait_seconds
                    ):
                        logging.info(
                            "Graceful stop requested. Current task finished; stopping before iteration %s.",
                            iteration + 2,
                        )
                        break
                    continue

                if stop_controller.stop_requested:
                    idea_memory.remove_concept(concept.concept)
                    if current_task_dir is not None:
                        _cleanup_interrupted_task(
                            task_id=task_id,
                            task_dir=current_task_dir,
                            task_dir_preexisting=current_task_dir_preexisting,
                        )
                    logging.info(
                        "Workflow stop was requested during concept %s. Removed it from memory and exited cleanly.",
                        concept.concept,
                    )
                    append_workflow_phase_summary(
                        workflow_started_at=workflow_started_at,
                        iteration=iteration + 1,
                        task_id=task_id,
                        target_topic=target_topic,
                        difficulty=beginner_task.difficulty,
                        phase="workflow_complete",
                        attempt=None,
                        status="interrupted",
                        is_valid=None,
                        reason="Workflow stopped gracefully before task completion",
                        task_directory=_task_directory_string(task_id),
                        reports_base_dir=_reports_base_dir(),
                    )
                    break

                # Update memory based on workflow outcome
                if workflow_succeeded:
                    idea_memory.add_structured_concept(concept)
                    logging.info(f"💾 Task succeeded: {concept.concept}")
                else:
                    idea_memory.add_failed_concept(concept, reason="Workflow validation failed")
                    logging.info(f"💾 Saved concept to failure memory: {concept.concept}")

                logging.info(f"\n[ITERATION {iteration + 1}] Complete")
                current_concept = None
                current_task_id = None
                current_task_dir = None
                current_task_dir_preexisting = False
                current_idea_memory = None

                if await _wait_for_post_iteration_stop_window(
                    stop_controller,
                    config.post_iteration_stop_wait_seconds
                ):
                    logging.info(
                        "Graceful stop requested. Current task finished; stopping before iteration %s.",
                        iteration + 2,
                    )
                    break

            logging.info("\n" + "="*80)
            logging.info("WORKFLOW COMPLETE")
            logging.info("="*80)
    finally:
        if previous_stop_file_env is None:
            os.environ.pop("K8S_BUILDER_STOP_FILE", None)
        else:
            os.environ["K8S_BUILDER_STOP_FILE"] = previous_stop_file_env
        if hasattr(stop_controller, "clear_stop_file"):
            stop_controller.clear_stop_file()
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
    parser.add_argument(
        "--stop-file",
        default=".workflow-stop",
        help="Path to a sentinel file that requests a graceful stop when created. Use an empty string to disable.",
    )
    parser.add_argument(
        "--post-iteration-stop-wait-seconds",
        type=float,
        default=2.0,
        help="Seconds to poll for a stop request after each completed iteration before starting the next one.",
    )
    args = parser.parse_args()

    runtime_config = WorkflowRuntimeConfig(
        iterations=args.iterations,
        reset_minikube=args.reset_minikube,
        minikube_delete_timeout=args.minikube_delete_timeout,
        minikube_start_timeout=args.minikube_start_timeout,
        max_retries=args.max_retries,
        save_workflow_graph=args.save_workflow_graph,
        stop_file=args.stop_file.strip() or None,
        post_iteration_stop_wait_seconds=args.post_iteration_stop_wait_seconds,
    )
    asyncio.run(run_workflow(runtime_config))


if __name__ == "__main__":
    main()
