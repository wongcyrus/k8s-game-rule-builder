import workflow.runner as runner


class _ProcResult:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


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

        def add_structured_concept(self, concept):
            self.generated_ideas["c"] = {"concept": concept.concept}

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
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config: None)
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
    monkeypatch.setattr(runner, "reset_minikube", lambda _iteration, _config: None)
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
    assert "statefulsets" in mem.failed_concepts
    assert mem.saved_failures > 0
