import asyncio
from types import SimpleNamespace

import agents.filesystem_agent as filesystem_agent
import agents.k8s_task_fixer_agent as fixer_agent
import agents.k8s_task_generator_agent as generator_agent
import agents.k8s_task_idea_agent as idea_agent


class _FakeMCPTool:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self._functions = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeChatClient:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.function_invocation_configuration = {}

    def as_agent(self, **kwargs):
        return SimpleNamespace(kind="agent", kwargs=kwargs)


def test_filesystem_agent_context_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(filesystem_agent, "MCPStdioTool", _FakeMCPTool)
    monkeypatch.setattr(filesystem_agent, "OpenAIChatClient", _FakeChatClient)
    monkeypatch.setattr(
        filesystem_agent,
        "PATHS",
        SimpleNamespace(tests_root=tmp_path / "tests", game_root=tmp_path / "tests/game02"),
    )
    monkeypatch.setattr(
        filesystem_agent,
        "AZURE",
        SimpleNamespace(endpoint="https://example", deployment_name="model"),
    )

    async def run():
        async with filesystem_agent.get_filesystem_agent() as agent:
            assert agent.kwargs["name"] == "FileSystemAgent"
            assert agent.kwargs["default_options"]["tool_choice"] == "required"

    asyncio.run(run())


def test_generator_agent_factory_chat_completions_branch(monkeypatch):
    monkeypatch.setattr(generator_agent, "OpenAIChatCompletionClient", _FakeChatClient)
    monkeypatch.setattr(
        generator_agent,
        "AZURE",
        SimpleNamespace(
            use_responses_api=False,
            endpoint="https://example",
            deployment_name="gpt-4o",
        ),
    )

    agent = asyncio.run(generator_agent.create_generator_agent_with_mcp("mcp"))
    assert agent.kwargs["name"] == "K8sTaskGeneratorAgent"
    assert "filesystem tools" in agent.kwargs["instructions"]


def test_fixer_agent_factory_chat_completions_branch(monkeypatch):
    monkeypatch.setattr(fixer_agent, "OpenAIChatCompletionClient", _FakeChatClient)
    monkeypatch.setattr(
        fixer_agent,
        "AZURE",
        SimpleNamespace(
            use_responses_api=False,
            endpoint="https://example",
            deployment_name="gpt-4o",
        ),
    )

    agent = asyncio.run(fixer_agent.create_fixer_agent_with_mcp("mcp"))
    assert agent.kwargs["name"] == "K8sTaskFixerAgent"
    assert "FIX existing failed tasks" in agent.kwargs["instructions"]


def test_idea_agent_factory_chat_completions_branch(monkeypatch):
    monkeypatch.setattr(idea_agent, "OpenAIChatCompletionClient", _FakeChatClient)
    monkeypatch.setattr(
        idea_agent,
        "AZURE",
        SimpleNamespace(
            use_responses_api=False,
            endpoint="https://example",
            deployment_name="gpt-4o",
        ),
    )

    agent, memory = asyncio.run(idea_agent.create_idea_agent_with_mcp("mcp"))
    assert agent.kwargs["name"] == "K8sTaskIdeaAgent"
    assert isinstance(memory.generated_ideas, dict)


def test_generator_agent_factory_responses_branch(monkeypatch):
    monkeypatch.setattr("agent_framework.openai.OpenAIChatClient", _FakeChatClient)
    monkeypatch.setattr(
        generator_agent,
        "AZURE",
        SimpleNamespace(
            use_responses_api=True,
            endpoint="https://example",
            deployment_name="gpt-5.3-codex",
        ),
    )

    agent = asyncio.run(generator_agent.create_generator_agent_with_mcp("mcp"))
    assert agent.kwargs["name"] == "K8sTaskGeneratorAgent"


def test_fixer_agent_factory_responses_branch(monkeypatch):
    monkeypatch.setattr("agent_framework.openai.OpenAIChatClient", _FakeChatClient)
    monkeypatch.setattr(
        fixer_agent,
        "AZURE",
        SimpleNamespace(
            use_responses_api=True,
            endpoint="https://example",
            deployment_name="gpt-5.3-codex",
        ),
    )

    agent = asyncio.run(fixer_agent.create_fixer_agent_with_mcp("mcp"))
    assert agent.kwargs["name"] == "K8sTaskFixerAgent"


def test_generator_and_fixer_context_managers(monkeypatch, tmp_path):
    monkeypatch.setattr(generator_agent, "MCPStdioTool", _FakeMCPTool)
    monkeypatch.setattr(fixer_agent, "MCPStdioTool", _FakeMCPTool)
    monkeypatch.setattr(generator_agent, "create_generator_agent_with_mcp", lambda _m: _fake_agent("gen"))
    monkeypatch.setattr(fixer_agent, "create_fixer_agent_with_mcp", lambda _m: _fake_agent("fix"))
    monkeypatch.setattr(generator_agent, "PATHS", SimpleNamespace(tests_root=tmp_path / "tests"))
    monkeypatch.setattr(fixer_agent, "PATHS", SimpleNamespace(tests_root=tmp_path / "tests"))

    async def run():
        async with generator_agent.get_k8s_task_generator_agent() as gen:
            assert gen.kind == "gen"
        async with fixer_agent.get_k8s_task_fixer_agent() as fix:
            assert fix.kind == "fix"

    asyncio.run(run())


def test_idea_agent_factory_responses_branch_with_constraints(monkeypatch):
    class FakeMemory:
        def __init__(self):
            self.generated_ideas = {"a": {"concept": "Secrets"}}
            self.failed_concepts = {"b": {"concept": "Jobs"}}

    monkeypatch.setattr("agent_framework.openai.OpenAIChatClient", _FakeChatClient)
    monkeypatch.setattr(idea_agent, "TaskIdeasMemory", FakeMemory)
    monkeypatch.setattr(
        idea_agent,
        "AZURE",
        SimpleNamespace(
            use_responses_api=True,
            endpoint="https://example",
            deployment_name="gpt-5.3-codex",
        ),
    )

    agent, _memory = asyncio.run(idea_agent.create_idea_agent_with_mcp("mcp"))
    instructions = agent.kwargs["instructions"]
    assert "Do NOT suggest these previously covered Kubernetes concepts" in instructions
    assert "Secrets" in instructions
    assert "Jobs" in instructions


async def _fake_agent(kind):
    return SimpleNamespace(kind=kind)
