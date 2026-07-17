import asyncio

import workflow.builder as builder


def test_build_workflow_wires_edges_with_expected_executors(monkeypatch):
    calls = []

    async def fake_create_generator(_mcp_tool):
        return "generator-agent"

    async def fake_create_fixer(_mcp_tool):
        return "fixer-agent"

    class FakeAgentExecutor:
        def __init__(self, agent, id):
            self.agent = agent
            self.id = id

    class FakeWorkflowBuilder:
        def __init__(self, start_executor):
            calls.append(("start", getattr(start_executor, "id", start_executor)))

        def add_edge(self, src, dst):
            calls.append(("edge", getattr(src, "id", src), getattr(dst, "id", dst)))
            return self

        def add_multi_selection_edge_group(self, src, targets, selection_func):
            calls.append(
                (
                    "multi",
                    getattr(src, "id", src),
                    [getattr(t, "id", t) for t in targets],
                    selection_func.__name__,
                )
            )
            return self

        def build(self):
            return "workflow-object"

    monkeypatch.setattr(builder, "create_generator_agent_with_mcp", fake_create_generator)
    monkeypatch.setattr(builder, "create_fixer_agent_with_mcp", fake_create_fixer)
    monkeypatch.setattr(builder, "AgentExecutor", FakeAgentExecutor)
    monkeypatch.setattr(builder, "WorkflowBuilder", FakeWorkflowBuilder)

    workflow_obj, generator_executor, fixer_executor = asyncio.run(
        builder.build_workflow("mcp-tool")
    )

    assert workflow_obj == "workflow-object"
    assert generator_executor.id == "generator_agent"
    assert fixer_executor.id == "fixer_agent"
    assert any(c[0] == "multi" and c[1] == "make_decision" for c in calls)
