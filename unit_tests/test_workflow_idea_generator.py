import asyncio
from types import SimpleNamespace

import workflow.idea_generator as idea_generator
from agents.k8s_task_idea_agent import K8sTaskConcept, TaskVariation


def _concept() -> K8sTaskConcept:
    return K8sTaskConcept(
        concept="ConfigMaps",
        tags=["configuration"],
        description="Learn configmaps",
        variations=[
            TaskVariation(
                task_id="050_configmaps",
                difficulty="BEGINNER",
                title="ConfigMap basics",
                objective="Create configmap",
                key_skills=["configmap"],
                estimated_time=10,
            )
        ],
    )


def test_generate_task_idea_structured_outputs_path(monkeypatch):
    concept = _concept()

    class FakeAgent:
        async def run(self, prompt, options=None):
            assert options == {"response_format": K8sTaskConcept}
            return SimpleNamespace(value=concept)

    memory = SimpleNamespace(generated_ideas={})
    result = asyncio.run(idea_generator.generate_task_idea(FakeAgent(), memory))
    assert result.concept == "ConfigMaps"


def test_generate_task_idea_tool_call_fallback(monkeypatch):
    concept = _concept()

    class FakeResponsesAgent:
        _client = object()  # triggers fallback path

        async def run(self, prompt, options=None):
            return SimpleNamespace(value=None)

    monkeypatch.setattr(idea_generator, "get_last_saved_concept", lambda: concept)
    memory = SimpleNamespace(generated_ideas={"old": {"concept": "Secrets"}})

    result = asyncio.run(idea_generator.generate_task_idea(FakeResponsesAgent(), memory))
    assert result.variations[0].task_id == "050_configmaps"


def test_generate_task_idea_raises_when_no_concept(monkeypatch):
    import pytest
    class FakeResponsesAgent:
        _client = object()

        async def run(self, prompt, options=None):
            return SimpleNamespace(value=None)

    monkeypatch.setattr(idea_generator, "get_last_saved_concept", lambda: None)
    memory = SimpleNamespace(generated_ideas={})

    with pytest.raises(ValueError, match="No concept generated"):
        asyncio.run(idea_generator.generate_task_idea(FakeResponsesAgent(), memory))
