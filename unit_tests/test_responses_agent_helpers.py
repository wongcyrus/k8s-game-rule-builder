from types import SimpleNamespace
from typing import Annotated

from pydantic import Field

from agents.responses_agent import (
    ResponsesAgent,
    _run_middleware_chain,
    _build_auth_header,
    _extract_text_parts_from_output,
    _build_function_call_output_item,
)


class _RecordingMiddleware:
    def __init__(self, name, events):
        self.name = name
        self.events = events

    async def process(self, context, call_next):
        self.events.append(f"before:{self.name}")
        await call_next()
        self.events.append(f"after:{self.name}")


def test_python_type_to_json_schema_handles_primitives_and_list():
    assert ResponsesAgent._python_type_to_json_schema(str) == {"type": "string"}
    assert ResponsesAgent._python_type_to_json_schema(int) == {"type": "integer"}
    assert ResponsesAgent._python_type_to_json_schema(list[str]) == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_extract_input_text_handles_various_message_types():
    msg_with_contents = SimpleNamespace(contents=["hello", SimpleNamespace(text="world")])
    msg_with_text = SimpleNamespace(text="direct")
    result = ResponsesAgent._extract_input_text(SimpleNamespace(), [msg_with_contents, msg_with_text])
    assert result == "hello\nworld\ndirect"


def test_build_tools_param_for_extra_function():
    def save_thing(name: Annotated[str, Field(description="Item name")], count: int) -> dict:
        return {"ok": True}

    fake = SimpleNamespace(
        _mcp_tool=SimpleNamespace(_functions=[]),
        _extra_tools=[save_thing],
        _python_type_to_json_schema=ResponsesAgent._python_type_to_json_schema,
    )

    tools = ResponsesAgent._build_tools_param(fake)
    assert len(tools) == 1
    assert tools[0]["name"] == "save_thing"
    assert tools[0]["parameters"]["properties"]["name"]["description"] == "Item name"
    assert "count" in tools[0]["parameters"]["required"]


def test_run_middleware_chain_wraps_final_call():
    import asyncio

    events = []
    middlewares = [_RecordingMiddleware("a", events), _RecordingMiddleware("b", events)]
    context = SimpleNamespace()

    async def final_call():
        events.append("final")

    asyncio.run(_run_middleware_chain(middlewares, context, final_call))
    assert events == ["before:a", "before:b", "final", "after:b", "after:a"]


def test_build_auth_header_prefixes_token():
    header = _build_auth_header(lambda: "abc123")
    assert header["Authorization"] == "Bearer abc123"


def test_build_auth_header_accepts_existing_bearer():
    header = _build_auth_header(lambda: "Bearer abc123")
    assert header["Authorization"] == "Bearer abc123"


def test_extract_text_parts_from_output_ignores_malformed_items():
    class FakeToolCall:
        pass

    class FakeOutputMessage:
        def __init__(self):
            self.content = [SimpleNamespace(text="ok"), SimpleNamespace(other="x")]

    import agents.responses_agent as responses_agent
    tool = FakeToolCall()
    msg = FakeOutputMessage()
    monkeypatch_tool = responses_agent.ResponseFunctionToolCall
    monkeypatch_msg = responses_agent.ResponseOutputMessage
    try:
        responses_agent.ResponseFunctionToolCall = FakeToolCall
        responses_agent.ResponseOutputMessage = FakeOutputMessage
        tool_calls, text_parts = _extract_text_parts_from_output([tool, msg, object()])
        assert len(tool_calls) == 1
        assert text_parts == ["ok"]
    finally:
        responses_agent.ResponseFunctionToolCall = monkeypatch_tool
        responses_agent.ResponseOutputMessage = monkeypatch_msg


def test_build_function_call_output_item_requires_call_id():
    import pytest

    with pytest.raises(ValueError, match="missing call_id"):
        _build_function_call_output_item("", "x")
