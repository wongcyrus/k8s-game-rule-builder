import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

import agents.k8s_task_idea_agent as idea_agent
from agents.k8s_task_idea_agent import K8sTaskConcept, TaskVariation, TaskIdeasMemory


def _concept(name: str = "Secrets") -> K8sTaskConcept:
    return K8sTaskConcept(
        concept=name,
        tags=["security"],
        description="desc",
        variations=[
            TaskVariation(
                task_id="050_secrets",
                difficulty="BEGINNER",
                title="title",
                objective="obj",
                key_skills=["skill"],
                estimated_time=10,
            )
        ],
    )


def test_save_k8s_task_concept_and_get_clear_roundtrip():
    data = idea_agent.save_k8s_task_concept(
        concept="ConfigMaps",
        tags=["config"],
        description="desc",
        variations=[
            {
                "task_id": "051_configmaps",
                "difficulty": "BEGINNER",
                "title": "t",
                "objective": "o",
                "key_skills": ["k"],
                "estimated_time": 5,
            }
        ],
    )
    assert data["success"] is True
    assert idea_agent.get_last_saved_concept() is not None
    idea_agent.clear_last_saved_concept()
    assert idea_agent.get_last_saved_concept() is None


def test_task_ideas_memory_persists_and_loads():
    suffix = uuid.uuid4().hex
    memory_file = f"tests/.tmp_memory_{suffix}.json"
    failure_file = f"tests/.tmp_failure_{suffix}.json"
    try:
        mem = TaskIdeasMemory(memory_file=memory_file, failure_memory_file=failure_file)
        mem.generated_ideas["volumes"] = {"concept": "Volumes", "tags": ["storage"]}
        mem.failed_concepts["volumes"] = {"concept": "Volumes", "reason": "boom"}
        mem._save_ideas()
        mem._save_failures()

        loaded = TaskIdeasMemory(memory_file=memory_file, failure_memory_file=failure_file)
        assert len(loaded.generated_ideas) == 1
        assert len(loaded.failed_concepts) == 1
    finally:
        for rel in [memory_file, failure_file]:
            p = Path(__file__).resolve().parents[1] / rel
            if p.exists():
                p.unlink()


def test_task_ideas_middleware_injects_constraints():
    class FakeMemory:
        generated_ideas = {"a": {"concept": "Secrets"}}
        failed_concepts = {"b": {"concept": "Jobs"}}

        def build_constraints_blocks(self):
            return [
                "IMPORTANT: Do NOT suggest these previously covered Kubernetes concepts:\n- Secrets",
                "IMPORTANT: Do NOT suggest these concepts that previously FAILED validation:\n- Jobs",
            ]

    memory = FakeMemory()
    middleware = idea_agent.TaskIdeasMemoryMiddleware(memory)
    context = SimpleNamespace(messages=[])
    called = {"ok": False}

    async def call_next():
        called["ok"] = True

    asyncio.run(middleware.process(context, call_next))
    assert called["ok"] is True
    assert context.messages[0].role == "system"
    injected_content = context.messages[0].contents[0]
    injected = injected_content.text if hasattr(injected_content, "text") else str(injected_content)
    assert "Secrets" in injected
    assert "Jobs" in injected


def test_task_ideas_middleware_add_and_query_concepts():
    suffix = uuid.uuid4().hex
    memory_file = f"tests/.tmp_memory_{suffix}.json"
    failure_file = f"tests/.tmp_failure_{suffix}.json"
    try:
        memory = TaskIdeasMemory(memory_file=memory_file, failure_memory_file=failure_file)
        concept = _concept("CronJobs")

        memory.generated_ideas = {}
        memory.failed_concepts = {}
        memory._save_ideas = lambda: None
        memory._save_failures = lambda: None

        memory.add_structured_concept(concept)
        memory.add_failed_concept(concept, reason="validation")

        assert memory.concept_exists("cronjobs") is True
        assert len(memory.get_ideas()) == 1
    finally:
        for rel in [memory_file, failure_file]:
            p = Path(__file__).resolve().parents[1] / rel
            if p.exists():
                p.unlink()


def test_memory_build_constraints_blocks():
    suffix = uuid.uuid4().hex
    memory_file = f"tests/.tmp_memory_{suffix}.json"
    failure_file = f"tests/.tmp_failure_{suffix}.json"
    try:
        memory = TaskIdeasMemory(memory_file=memory_file, failure_memory_file=failure_file)
        memory.generated_ideas = {"a": {"concept": "Secrets"}}
        memory.failed_concepts = {"b": {"concept": "Jobs"}}
        blocks = memory.build_constraints_blocks()
        merged = "\n".join(blocks)
        assert "Secrets" in merged
        assert "Jobs" in merged
    finally:
        for rel in [memory_file, failure_file]:
            p = Path(__file__).resolve().parents[1] / rel
            if p.exists():
                p.unlink()
