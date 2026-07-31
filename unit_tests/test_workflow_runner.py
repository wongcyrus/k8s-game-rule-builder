import workflow.runner as runner
from workflow.preflight import QuarantinedTaskError


class _ProcResult:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


class _FakeStopController:
    def __init__(self, requested=False):
        self.stop_requested = requested
        self.installed = False
        self.restored = False

    def install_signal_handlers(self):
        self.installed = True

    def restore_signal_handlers(self):
        self.restored = True


def test_reset_minikube_runs_delete_then_start(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return _ProcResult(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    runner.reset_minikube(0, runner.WorkflowRuntimeConfig())

    assert calls[0] == ["minikube", "delete"]
    assert calls[1][0:2] == ["minikube", "start"]


def test_reset_minikube_handles_missing_minikube(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr("subprocess.run", fake_run)
    runner.reset_minikube(0, runner.WorkflowRuntimeConfig())


def test_reset_minikube_handles_timeout(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="minikube", timeout=1)

    monkeypatch.setattr("subprocess.run", fake_run)
    runner.reset_minikube(0, runner.WorkflowRuntimeConfig())


def test_reset_minikube_skip_mode(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: calls.append(args) or _ProcResult())
    cfg = runner.WorkflowRuntimeConfig(reset_minikube=False)
    runner.reset_minikube(0, cfg)
    assert calls == []


def test_reset_minikube_skips_authoritative_kubeconfig(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: calls.append(args) or _ProcResult())
    runner.reset_minikube(
        0,
        runner.WorkflowRuntimeConfig(),
        k8s_configuration=type("Cfg", (), {"endpoint": "https://eks"})(),
    )
    assert calls == []


def test_run_workflow_executes_with_mocked_dependencies(monkeypatch, tmp_path):
    class FakeMCP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeWorkflow:
        def run(self, _state, stream=True):
            async def _gen():
                yield type("Evt", (), {"type": "output", "data": "successfully generated"})
            return _gen()

    class FakeMemory:
        def __init__(self):
            self.generated_ideas = {}
            self.failed_concepts = {}
            self.saved_successes = 0

        def add_structured_concept(self, concept):
            self.generated_ideas["c"] = {"concept": concept.concept}
            self.saved_successes += 1

        def add_failed_concept(self, concept, reason):
            self.failed_concepts["c"] = {"concept": concept.concept, "reason": reason}

    class _Var:
        task_id = "050_demo"
        difficulty = "BEGINNER"
        objective = "obj"

    class _Concept:
        concept = "ConfigMaps"
        description = "desc"
        tags = ["config"]
        variations = [_Var()]

    async def fake_create_idea_agent_with_mcp(_tool):
        return object(), FakeMemory()

    async def fake_generate_task_idea(_agent, _memory):
        return _Concept()

    async def fake_build_workflow(_tool):
        return FakeWorkflow(), object(), object()

    monkeypatch.setattr(runner, "MCPStdioTool", FakeMCP)
    monkeypatch.setattr(runner, "create_idea_agent_with_mcp", fake_create_idea_agent_with_mcp)
    monkeypatch.setattr(runner, "generate_task_idea", fake_generate_task_idea)
    monkeypatch.setattr(runner, "build_workflow", fake_build_workflow)
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "resolve_k8s_configuration",
        lambda: type("Cfg", (), {"endpoint": "https://localhost:8443"})(),
    )
    monkeypatch.setattr(runner, "run_k8s_preflight_check", lambda: "namespace/default")
    monkeypatch.setattr(runner, "WorkflowViz", lambda _workflow: type("V", (), {"save_png": lambda self, p: None})())
    monkeypatch.setattr(
        runner,
        "PATHS",
        type(
            "P",
            (),
            {
                "k8s_docs_root": tmp_path / "docs",
                "tests_root": tmp_path / "tests",
                "game_root": tmp_path / "tests/game02",
            },
        )(),
    )

    import asyncio

    stop_controller = _FakeStopController()
    asyncio.run(runner.run_workflow(runner.WorkflowRuntimeConfig(iterations=1), stop_controller=stop_controller))
    assert stop_controller.installed is True
    assert stop_controller.restored is True


def test_run_workflow_failure_path_saves_failed_concept(monkeypatch, tmp_path):
    class FakeMCP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeWorkflow:
        def run(self, _state, stream=True):
            async def _gen():
                yield type("Evt", (), {"type": "output", "data": "not successful"})
            return _gen()

    class FakeMemory:
        def __init__(self):
            self.generated_ideas = {}
            self.failed_concepts = {}
            self.saved_failures = 0

        def _save_ideas(self):
            return None

        def _save_failures(self):
            self.saved_failures += 1

        def add_structured_concept(self, concept):
            self.generated_ideas[concept.concept.lower()] = {"concept": concept.concept}

        def add_failed_concept(self, concept, reason):
            self.failed_concepts[concept.concept.lower()] = {"concept": concept.concept, "reason": reason}
            self.saved_failures += 1

    class _Var:
        task_id = "075_demo"
        difficulty = "BEGINNER"
        objective = "obj"

    class _Concept:
        concept = "StatefulSets"
        description = "desc"
        tags = ["stateful"]
        variations = [_Var()]

    memory_holder = {}

    async def fake_create_idea_agent_with_mcp(_tool):
        mem = FakeMemory()
        memory_holder["mem"] = mem
        return object(), mem

    async def fake_generate_task_idea(_agent, _memory):
        return _Concept()

    async def fake_build_workflow(_tool):
        return FakeWorkflow(), object(), object()

    monkeypatch.setattr(runner, "MCPStdioTool", FakeMCP)
    monkeypatch.setattr(runner, "create_idea_agent_with_mcp", fake_create_idea_agent_with_mcp)
    monkeypatch.setattr(runner, "generate_task_idea", fake_generate_task_idea)
    monkeypatch.setattr(runner, "build_workflow", fake_build_workflow)
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "resolve_k8s_configuration",
        lambda: type("Cfg", (), {"endpoint": "https://localhost:8443"})(),
    )
    monkeypatch.setattr(runner, "run_k8s_preflight_check", lambda: "namespace/default")
    monkeypatch.setattr(runner, "WorkflowViz", lambda _workflow: type("V", (), {"save_png": lambda self, p: None})())
    monkeypatch.setattr(
        runner,
        "PATHS",
        type(
            "P",
            (),
            {
                "k8s_docs_root": tmp_path / "docs",
                "tests_root": tmp_path / "tests",
                "game_root": tmp_path / "tests/game02",
            },
        )(),
    )

    import asyncio

    asyncio.run(runner.run_workflow(runner.WorkflowRuntimeConfig(iterations=1)))
    mem = memory_holder["mem"]
    assert mem.generated_ideas == {}
    assert "statefulsets" in mem.failed_concepts
    assert mem.saved_failures > 0


def test_run_workflow_unexpected_exception_saves_failed_concept_and_continues(monkeypatch, tmp_path):
    class FakeMCP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    workflow_calls = []

    class FakeWorkflow:
        def __init__(self, should_raise: bool):
            self.should_raise = should_raise

        def run(self, _state, stream=True):
            async def _gen():
                if self.should_raise:
                    raise RuntimeError("fixer exploded")
                yield type("Evt", (), {"type": "output", "data": "successfully generated"})
            return _gen()

    class FakeMemory:
        def __init__(self):
            self.generated_ideas = {}
            self.failed_concepts = {}
            self.saved_failures = 0
            self.saved_successes = 0

        def add_structured_concept(self, concept):
            self.generated_ideas[concept.concept.lower()] = {"concept": concept.concept}
            self.saved_successes += 1

        def add_failed_concept(self, concept, reason):
            self.failed_concepts[concept.concept.lower()] = {"concept": concept.concept, "reason": reason}
            self.saved_failures += 1

        def remove_concept(self, concept):
            self.generated_ideas.pop(concept.lower(), None)
            self.failed_concepts.pop(concept.lower(), None)

    class _VarA:
        task_id = "110_demo"
        difficulty = "BEGINNER"
        objective = "obj"

    class _ConceptA:
        concept = "Leases"
        description = "desc"
        tags = ["coordination"]
        variations = [_VarA()]

    class _VarB:
        task_id = "111_demo"
        difficulty = "BEGINNER"
        objective = "obj"

    class _ConceptB:
        concept = "DaemonSets"
        description = "desc"
        tags = ["workloads"]
        variations = [_VarB()]

    memory = FakeMemory()
    concepts = [_ConceptA(), _ConceptB()]

    async def fake_create_idea_agent_with_mcp(_tool):
        return object(), memory

    async def fake_generate_task_idea(_agent, _memory):
        return concepts.pop(0)

    async def fake_build_workflow(_tool):
        should_raise = len(workflow_calls) == 0
        workflow_calls.append("built")
        return FakeWorkflow(should_raise), object(), object()

    monkeypatch.setattr(runner, "MCPStdioTool", FakeMCP)
    monkeypatch.setattr(runner, "create_idea_agent_with_mcp", fake_create_idea_agent_with_mcp)
    monkeypatch.setattr(runner, "generate_task_idea", fake_generate_task_idea)
    monkeypatch.setattr(runner, "build_workflow", fake_build_workflow)
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "resolve_k8s_configuration",
        lambda: type("Cfg", (), {"endpoint": "https://localhost:8443"})(),
    )
    monkeypatch.setattr(runner, "run_k8s_preflight_check", lambda: "namespace/default")
    monkeypatch.setattr(runner, "WorkflowViz", lambda _workflow: type("V", (), {"save_png": lambda self, p: None})())
    monkeypatch.setattr(
        runner,
        "PATHS",
        type(
            "P",
            (),
            {
                "k8s_docs_root": tmp_path / "docs",
                "tests_root": tmp_path / "tests",
                "game_root": tmp_path / "tests/game02",
            },
        )(),
    )

    import asyncio

    asyncio.run(runner.run_workflow(runner.WorkflowRuntimeConfig(iterations=2)))

    assert workflow_calls == ["built", "built"]
    assert "leases" in memory.failed_concepts
    assert memory.failed_concepts["leases"]["reason"] == "Workflow execution error: RuntimeError: fixer exploded"
    assert "daemonsets" in memory.generated_ideas
    assert memory.saved_failures == 1
    assert memory.saved_successes == 1


def test_run_workflow_runs_preflight_once(monkeypatch, tmp_path):
    class FakeMCP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeWorkflow:
        def run(self, _state, stream=True):
            async def _gen():
                yield type("Evt", (), {"type": "output", "data": "successfully generated"})
            return _gen()

    class FakeMemory:
        generated_ideas = {}
        failed_concepts = {}

        def add_structured_concept(self, _concept):
            return None

        def add_failed_concept(self, _concept, reason):
            raise AssertionError(reason)

        def remove_concept(self, _concept):
            return None

    class _Var:
        task_id = "099_demo"
        difficulty = "BEGINNER"
        objective = "obj"

    class _Concept:
        concept = "Pods"
        description = "desc"
        tags = ["workloads"]
        variations = [_Var()]

    preflight_calls = []

    async def fake_create_idea_agent_with_mcp(_tool):
        return object(), FakeMemory()

    async def fake_generate_task_idea(_agent, _memory):
        return _Concept()

    async def fake_build_workflow(_tool):
        return FakeWorkflow(), object(), object()

    monkeypatch.setattr(runner, "MCPStdioTool", FakeMCP)
    monkeypatch.setattr(runner, "create_idea_agent_with_mcp", fake_create_idea_agent_with_mcp)
    monkeypatch.setattr(runner, "generate_task_idea", fake_generate_task_idea)
    monkeypatch.setattr(runner, "build_workflow", fake_build_workflow)
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "resolve_k8s_configuration",
        lambda: type("Cfg", (), {"endpoint": "https://localhost:8443"})(),
    )
    monkeypatch.setattr(runner, "run_k8s_preflight_check", lambda: preflight_calls.append("ok") or "namespace/default")
    monkeypatch.setattr(runner, "WorkflowViz", lambda _workflow: type("V", (), {"save_png": lambda self, p: None})())
    monkeypatch.setattr(
        runner,
        "PATHS",
        type(
            "P",
            (),
            {
                "k8s_docs_root": tmp_path / "docs",
                "tests_root": tmp_path / "tests",
                "game_root": tmp_path / "tests/game02",
            },
        )(),
    )

    import asyncio

    asyncio.run(runner.run_workflow(runner.WorkflowRuntimeConfig(iterations=2)))
    assert preflight_calls == ["ok"]


def test_run_workflow_stops_after_current_task_when_stop_requested(monkeypatch, tmp_path):
    class FakeMCP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    stop_controller = _FakeStopController()
    create_calls = []

    class FakeWorkflow:
        def run(self, _state, stream=True):
            async def _gen():
                stop_controller.stop_requested = True
                yield type("Evt", (), {"type": "output", "data": "successfully generated"})
            return _gen()

    class FakeMemory:
        def __init__(self):
            self.generated_ideas = {}
            self.failed_concepts = {}

        def add_structured_concept(self, concept):
            self.generated_ideas[concept.concept.lower()] = {"concept": concept.concept}

        def add_failed_concept(self, concept, reason):
            self.failed_concepts[concept.concept.lower()] = {"concept": concept.concept, "reason": reason}

    class _Var:
        task_id = "101_demo"
        difficulty = "BEGINNER"
        objective = "obj"

    class _Concept:
        concept = "Jobs"
        description = "desc"
        tags = ["batch"]
        variations = [_Var()]

    async def fake_create_idea_agent_with_mcp(_tool):
        create_calls.append("idea")
        return object(), FakeMemory()

    async def fake_generate_task_idea(_agent, _memory):
        return _Concept()

    async def fake_build_workflow(_tool):
        return FakeWorkflow(), object(), object()

    monkeypatch.setattr(runner, "MCPStdioTool", FakeMCP)
    monkeypatch.setattr(runner, "create_idea_agent_with_mcp", fake_create_idea_agent_with_mcp)
    monkeypatch.setattr(runner, "generate_task_idea", fake_generate_task_idea)
    monkeypatch.setattr(runner, "build_workflow", fake_build_workflow)
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "resolve_k8s_configuration",
        lambda: type("Cfg", (), {"endpoint": "https://localhost:8443"})(),
    )
    monkeypatch.setattr(runner, "run_k8s_preflight_check", lambda: "namespace/default")
    monkeypatch.setattr(runner, "WorkflowViz", lambda _workflow: type("V", (), {"save_png": lambda self, p: None})())
    monkeypatch.setattr(
        runner,
        "PATHS",
        type(
            "P",
            (),
            {
                "k8s_docs_root": tmp_path / "docs",
                "tests_root": tmp_path / "tests",
                "game_root": tmp_path / "tests/game02",
            },
        )(),
    )

    import asyncio

    asyncio.run(
        runner.run_workflow(
            runner.WorkflowRuntimeConfig(iterations=3),
            stop_controller=stop_controller,
        )
    )
    assert create_calls == ["idea"]


def test_run_workflow_does_not_start_new_task_when_stop_already_requested(monkeypatch, tmp_path):
    class FakeMCP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    stop_controller = _FakeStopController(requested=True)
    create_calls = []
    preflight_calls = []
    reset_calls = []

    async def fake_create_idea_agent_with_mcp(_tool):
        create_calls.append("idea")
        raise AssertionError("should not start new task")

    monkeypatch.setattr(runner, "MCPStdioTool", FakeMCP)
    monkeypatch.setattr(runner, "create_idea_agent_with_mcp", fake_create_idea_agent_with_mcp)
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config, **_kwargs: reset_calls.append("reset"))
    monkeypatch.setattr(
        runner,
        "resolve_k8s_configuration",
        lambda: type("Cfg", (), {"endpoint": "https://localhost:8443"})(),
    )
    monkeypatch.setattr(runner, "run_k8s_preflight_check", lambda: preflight_calls.append("ok") or "namespace/default")
    monkeypatch.setattr(
        runner,
        "PATHS",
        type(
            "P",
            (),
            {
                "k8s_docs_root": tmp_path / "docs",
                "tests_root": tmp_path / "tests",
                "game_root": tmp_path / "tests/game02",
            },
        )(),
    )

    import asyncio

    asyncio.run(
        runner.run_workflow(
            runner.WorkflowRuntimeConfig(iterations=2, save_workflow_graph=False),
            stop_controller=stop_controller,
        )
    )
    assert create_calls == []
    assert preflight_calls == []
    assert reset_calls == []


def test_run_workflow_quarantine_stops_without_failure_memory(monkeypatch, tmp_path):
    class FakeMCP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeWorkflow:
        def run(self, _state, stream=True):
            async def _gen():
                raise QuarantinedTaskError(
                    task_id="100_demo",
                    quarantine_path=tmp_path / "environment_failed/game02/100_demo",
                    cause=runner.K8sConnectivityError("k8s down"),
                )
                yield  # pragma: no cover
            return _gen()

    class FakeMemory:
        def __init__(self):
            self.generated_ideas = {}
            self.failed_concepts = {}
            self.removed = []
            self.saved_failures = 0

        def add_structured_concept(self, concept):
            self.generated_ideas[concept.concept.lower()] = {"concept": concept.concept}

        def add_failed_concept(self, concept, reason):
            self.saved_failures += 1
            self.failed_concepts[concept.concept.lower()] = {"concept": concept.concept, "reason": reason}

        def remove_concept(self, concept):
            self.removed.append(concept)

    class _Var:
        task_id = "100_demo"
        difficulty = "BEGINNER"
        objective = "obj"

    class _Concept:
        concept = "Ingress"
        description = "desc"
        tags = ["networking"]
        variations = [_Var()]

    memory_holder = {}

    async def fake_create_idea_agent_with_mcp(_tool):
        mem = FakeMemory()
        memory_holder["mem"] = mem
        return object(), mem

    async def fake_generate_task_idea(_agent, _memory):
        return _Concept()

    async def fake_build_workflow(_tool):
        return FakeWorkflow(), object(), object()

    monkeypatch.setattr(runner, "MCPStdioTool", FakeMCP)
    monkeypatch.setattr(runner, "create_idea_agent_with_mcp", fake_create_idea_agent_with_mcp)
    monkeypatch.setattr(runner, "generate_task_idea", fake_generate_task_idea)
    monkeypatch.setattr(runner, "build_workflow", fake_build_workflow)
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "resolve_k8s_configuration",
        lambda: type("Cfg", (), {"endpoint": "https://localhost:8443"})(),
    )
    monkeypatch.setattr(runner, "run_k8s_preflight_check", lambda: "namespace/default")
    monkeypatch.setattr(runner, "WorkflowViz", lambda _workflow: type("V", (), {"save_png": lambda self, p: None})())
    monkeypatch.setattr(
        runner,
        "PATHS",
        type(
            "P",
            (),
            {
                "k8s_docs_root": tmp_path / "docs",
                "tests_root": tmp_path / "tests",
                "game_root": tmp_path / "tests/game02",
            },
        )(),
    )

    import asyncio
    import pytest

    with pytest.raises(QuarantinedTaskError):
        asyncio.run(runner.run_workflow(runner.WorkflowRuntimeConfig(iterations=1)))

    mem = memory_holder["mem"]
    assert mem.removed == ["Ingress"]
    assert mem.saved_failures == 0
