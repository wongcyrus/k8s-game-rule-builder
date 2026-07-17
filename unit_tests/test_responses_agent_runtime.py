import asyncio
import json
from types import SimpleNamespace

import agents.responses_agent as responses_agent
from agents.responses_agent import ResponsesAgent


class _FakeToolCall:
    def __init__(self, name, arguments, call_id="c1"):
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class _FakeMessage:
    def __init__(self, text):
        self.content = [SimpleNamespace(text=text)]


class _FakeClient:
    def __init__(self, responses):
        self.responses = responses


class _FakeResponsesAPI:
    def __init__(self, outputs):
        self._outputs = outputs
        self._i = 0

    async def create(self, **kwargs):
        out = self._outputs[self._i]
        self._i += 1
        return out


def _new_agent():
    agent = object.__new__(ResponsesAgent)
    agent.id = "id"
    agent.name = "name"
    agent.description = "desc"
    agent._instructions = "inst"
    agent._model = "model"
    agent._extra_tools = []
    agent._middleware = []
    agent._max_tool_rounds = 3
    agent._max_consecutive_errors = 2
    agent._mcp_tool = SimpleNamespace(_functions=[], connect=_noop_async, call_tool=_noop_tool)
    agent._token_provider = lambda: "token"
    agent._final_response = None
    return agent


async def _noop_async():
    return None


async def _noop_tool(*args, **kwargs):
    return ""


def test_execute_tool_call_invalid_json():
    agent = _new_agent()
    result = asyncio.run(agent._execute_tool_call(_FakeToolCall("x", "{bad json")))
    assert "Invalid JSON arguments" in result


def test_execute_tool_call_extra_function_success():
    agent = _new_agent()

    def save_thing(name: str):
        return {"saved": name}

    agent._extra_tools = [save_thing]
    result = asyncio.run(
        agent._execute_tool_call(_FakeToolCall("save_thing", json.dumps({"name": "demo"})))
    )
    assert '"saved": "demo"' in result


def test_execute_tool_call_mcp_tool_success():
    agent = _new_agent()
    agent._mcp_tool = SimpleNamespace(
        _functions=[SimpleNamespace(name="list_dir", additional_properties={})],
        connect=_noop_async,
        call_tool=_fake_call_tool,
    )
    result = asyncio.run(
        agent._execute_tool_call(_FakeToolCall("list_dir", json.dumps({"path": "/tmp"})))
    )
    assert "OK:/tmp" in result


async def _fake_call_tool(name, **kwargs):
    return f"OK:{kwargs['path']}"


def test_run_non_streaming_finishes_with_text_response(monkeypatch):
    monkeypatch.setattr(responses_agent, "ResponseFunctionToolCall", _FakeToolCall)
    monkeypatch.setattr(responses_agent, "ResponseOutputMessage", _FakeMessage)

    agent = _new_agent()
    response = SimpleNamespace(id="r1", output=[_FakeMessage("done")])
    agent._client = _FakeClient(_FakeResponsesAPI([response]))

    final = asyncio.run(agent._run_non_streaming("hello"))
    assert final.messages[0].contents[0].text == "done"


def test_run_stream_updates_handles_tool_then_text(monkeypatch):
    monkeypatch.setattr(responses_agent, "ResponseFunctionToolCall", _FakeToolCall)
    monkeypatch.setattr(responses_agent, "ResponseOutputMessage", _FakeMessage)

    agent = _new_agent()
    agent._execute_tool_call = _fake_execute_tool
    response_1 = SimpleNamespace(id="r1", output=[_FakeToolCall("tool", "{}")])
    response_2 = SimpleNamespace(id="r2", output=[_FakeMessage("final")])
    agent._client = _FakeClient(_FakeResponsesAPI([response_1, response_2]))

    async def collect():
        updates = []
        async for item in agent._run_stream_updates("hello"):
            updates.append(item)
        return updates

    updates = asyncio.run(collect())
    assert len(updates) == 1
    assert agent._final_response.messages[0].contents[0].text == "final"


def test_run_stream_updates_raises_when_token_provider_fails(monkeypatch):
    monkeypatch.setattr(responses_agent, "ResponseFunctionToolCall", _FakeToolCall)
    monkeypatch.setattr(responses_agent, "ResponseOutputMessage", _FakeMessage)

    agent = _new_agent()
    agent._max_consecutive_errors = 1
    agent._token_provider = lambda: ""
    agent._client = _FakeClient(_FakeResponsesAPI([]))

    import pytest

    with pytest.raises(RuntimeError, match="invalid token"):
        asyncio.run(agent._run_non_streaming("hello"))


def test_run_stream_updates_hits_max_tool_rounds(monkeypatch):
    monkeypatch.setattr(responses_agent, "ResponseFunctionToolCall", _FakeToolCall)
    monkeypatch.setattr(responses_agent, "ResponseOutputMessage", _FakeMessage)

    agent = _new_agent()
    agent._max_tool_rounds = 2
    agent._execute_tool_call = _fake_execute_tool
    tool_only = SimpleNamespace(id="r1", output=[_FakeToolCall("tool", "{}", call_id="c1")])
    agent._client = _FakeClient(_FakeResponsesAPI([tool_only, tool_only]))

    asyncio.run(agent._run_non_streaming("hello"))
    assert agent._final_response.messages[0].contents[0].text == "Max tool rounds reached."


def test_run_stream_updates_handles_malformed_output_items(monkeypatch):
    monkeypatch.setattr(responses_agent, "ResponseFunctionToolCall", _FakeToolCall)
    monkeypatch.setattr(responses_agent, "ResponseOutputMessage", _FakeMessage)

    agent = _new_agent()
    malformed_response = SimpleNamespace(id="r1", output=[object()])
    agent._client = _FakeClient(_FakeResponsesAPI([malformed_response]))
    final = asyncio.run(agent._run_non_streaming("hello"))
    assert final.messages[0].contents[0].text == ""


async def _fake_execute_tool(_tool_call):
    return "ok"
