"""Custom agent that uses the OpenAI Responses API.

Required for codex models (gpt-5.3-codex, gpt-5.2-codex, etc.) which
do NOT support the Chat Completions API — only the Responses API.

Implements the SupportsAgentRun protocol so it can be used with
AgentExecutor in the workflow, just like the chat-based agents.
"""
import json
import logging
import uuid
from typing import Any, Callable, Awaitable, Sequence

from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
)
from azure.identity import AzureCliCredential, get_bearer_token_provider

from agent_framework import (
    AgentResponse,
    AgentSession,
    MCPStdioTool,
    Message,
    FunctionMiddleware,
    FunctionInvocationContext,
)

logger = logging.getLogger(__name__)


def _get_token_provider(credential: AzureCliCredential):
    """Get a bearer token provider for Azure OpenAI."""
    return get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )


class _ToolCallContext:
    """Minimal context passed to middleware during tool invocation."""
    def __init__(self, function, arguments, kwargs):
        self.function = function
        self.arguments = arguments
        self.kwargs = kwargs
        self.result = None


class _FunctionRef:
    """Lightweight reference to a function for middleware context."""
    def __init__(self, name: str):
        self.name = name


async def _run_middleware_chain(
    middlewares: list[FunctionMiddleware],
    context: _ToolCallContext,
    final_call: Callable[[], Awaitable[None]],
) -> None:
    """Run a chain of FunctionMiddleware around a tool call."""
    if not middlewares:
        await final_call()
        return

    async def build_chain(index: int) -> Callable[[], Awaitable[None]]:
        if index >= len(middlewares):
            return final_call
        mw = middlewares[index]

        async def call_next():
            next_fn = await build_chain(index + 1)
            await next_fn()

        async def run():
            await mw.process(context, call_next)

        return run

    chain = await build_chain(0)
    await chain()


class ResponsesAgent:
    """Agent using the OpenAI Responses API for codex models.

    Implements SupportsAgentRun so it works with AgentExecutor.
    Handles the tool-call loop internally (call model → execute tools → feed
    results back → repeat until the model produces a text response).
    """

    def __init__(
        self,
        *,
        name: str,
        instructions: str,
        azure_endpoint: str,
        model: str,
        credential: AzureCliCredential,
        mcp_tool: MCPStdioTool,
        extra_tools: list[Callable] | None = None,
        middleware: list[FunctionMiddleware] | None = None,
        max_tool_rounds: int = 30,
        max_consecutive_errors: int = 15,
    ):
        self.id = f"responses-{name}"
        self.name = name
        self.description = f"Responses API agent: {name}"
        self._instructions = instructions
        self._model = model
        self._mcp_tool = mcp_tool
        self._extra_tools: list[Callable] = extra_tools or []
        self._middleware = middleware or []
        self._max_tool_rounds = max_tool_rounds
        self._max_consecutive_errors = max_consecutive_errors

        token_provider = _get_token_provider(credential)
        # The Responses API v1 requires base_url ending in /openai/v1/
        # AsyncAzureOpenAI doesn't construct this correctly, so we use
        # AsyncOpenAI with an explicit base_url and token-based auth.
        from openai import AsyncOpenAI

        base = azure_endpoint.rstrip("/")
        self._client = AsyncOpenAI(
            base_url=f"{base}/openai/v1/",
            api_key="unused",  # overridden by default_headers
            default_headers={
                "Authorization": "",  # placeholder, replaced per-request
            },
        )
        self._token_provider = token_provider

    def _build_tools_param(self) -> list[dict[str, Any]]:
        """Convert MCP tools + extra callables into Responses API tool defs."""
        tools = []

        # MCP filesystem tools
        for func_tool in self._mcp_tool._functions:
            # Use parameters() which returns the cached JSON Schema from the MCP server
            schema = func_tool.parameters()
            if not schema or not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            tools.append({
                "type": "function",
                "name": func_tool.name,
                "description": func_tool.description or "",
                "parameters": schema,
            })

        # Extra callable tools (like save_k8s_task_concept)
        for fn in self._extra_tools:
            import inspect
            from typing import get_type_hints, Annotated, get_args, get_origin

            hints = get_type_hints(fn, include_extras=True)
            sig = inspect.signature(fn)
            properties = {}
            required = []

            for param_name, param in sig.parameters.items():
                hint = hints.get(param_name)
                desc = ""
                if get_origin(hint) is Annotated:
                    args = get_args(hint)
                    hint = args[0]
                    for meta in args[1:]:
                        if hasattr(meta, "description"):
                            desc = meta.description

                prop = self._python_type_to_json_schema(hint)
                if desc:
                    prop["description"] = desc
                properties[param_name] = prop

                if param.default is inspect.Parameter.empty:
                    required.append(param_name)

            tools.append({
                "type": "function",
                "name": fn.__name__,
                "description": (fn.__doc__ or "").split("\n")[0],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })

        return tools

    @staticmethod
    def _python_type_to_json_schema(hint) -> dict[str, Any]:
        """Convert a Python type hint to a JSON Schema fragment."""
        from typing import get_origin, get_args

        if hint is str:
            return {"type": "string"}
        if hint is int:
            return {"type": "integer"}
        if hint is bool:
            return {"type": "boolean"}
        if hint is float:
            return {"type": "number"}
        if hint is dict:
            return {"type": "object"}

        origin = get_origin(hint)
        if origin is list:
            args = get_args(hint)
            if args:
                return {"type": "array", "items": ResponsesAgent._python_type_to_json_schema(args[0])}
            return {"type": "array", "items": {}}

        # Fallback
        return {"type": "string"}

    async def _execute_tool_call(
        self, tool_call: ResponseFunctionToolCall
    ) -> str:
        """Execute a single tool call and return the result string."""
        name = tool_call.name
        try:
            args = json.loads(tool_call.arguments) if tool_call.arguments else {}
        except json.JSONDecodeError:
            return f"Error: Invalid JSON arguments: {tool_call.arguments}"

        logger.debug(f"Tool call: {name}, args keys: {list(args.keys())}, raw: {tool_call.arguments[:200] if tool_call.arguments else 'None'}")

        # Check if it's an extra callable tool
        for fn in self._extra_tools:
            if fn.__name__ == name:
                ctx = _ToolCallContext(_FunctionRef(name), args, {})

                async def call_fn():
                    import asyncio
                    if asyncio.iscoroutinefunction(fn):
                        ctx.result = await fn(**args)
                    else:
                        ctx.result = fn(**args)

                await _run_middleware_chain(self._middleware, ctx, call_fn)
                result = ctx.result
                return json.dumps(result) if not isinstance(result, str) else result

        # Otherwise it's an MCP tool — find the matching FunctionTool
        for func_tool in self._mcp_tool._functions:
            if func_tool.name == name:
                ctx = _ToolCallContext(_FunctionRef(name), args, {})

                async def call_mcp():
                    remote_name = func_tool.additional_properties.get(
                        "_mcp_remote_name", name
                    )
                    ctx.result = await self._mcp_tool.call_tool(remote_name, **args)

                await _run_middleware_chain(self._middleware, ctx, call_mcp)
                result = ctx.result
                if isinstance(result, list):
                    # list[Content] → join text parts
                    parts = []
                    for item in result:
                        if hasattr(item, "text"):
                            parts.append(item.text)
                        else:
                            parts.append(str(item))
                    return "\n".join(parts)
                return str(result) if result is not None else ""

        return f"Error: Unknown tool '{name}'"

    def run(
        self,
        messages=None,
        *,
        stream: bool = False,
        session: AgentSession | None = None,
        **kwargs,
    ):
        """Run the agent using the Responses API with tool-call loop.

        When stream=False, returns an awaitable AgentResponse.
        When stream=True, returns a ResponseStream that the framework can
        iterate for AgentResponseUpdate items and finalize via
        get_final_response().
        """
        if stream:
            from agent_framework import ResponseStream
            return ResponseStream(
                stream=self._run_stream_updates(messages),
                finalizer=self._stream_finalizer,
            )
        return self._run_non_streaming(messages)

    async def _stream_finalizer(self, updates) -> AgentResponse:
        """Produce the final AgentResponse after streaming completes."""
        return self._final_response

    async def _run_non_streaming(self, messages) -> AgentResponse:
        """Non-streaming execution — returns final AgentResponse."""
        async for _ in self._run_stream_updates(messages):
            pass
        return self._final_response

    async def _run_stream_updates(self, messages):
        """Async generator that drives the Responses API tool loop.

        Yields AgentResponseUpdate (empty) after each tool-call round so the
        framework knows the agent is still working.  Sets self._final_response
        when the model produces its final text output.
        """
        from agent_framework import AgentResponseUpdate

        # Ensure MCP tool is connected (lazy init for DevUI compatibility)
        if not self._mcp_tool._functions:
            logger.info("MCP tool not yet connected — connecting lazily...")
            await self._mcp_tool.connect()
            logger.info(f"MCP tool connected: {len(self._mcp_tool._functions)} functions loaded")

        input_text = self._extract_input_text(messages)
        tools = self._build_tools_param()
        consecutive_errors = 0
        previous_response_id = None

        for round_num in range(self._max_tool_rounds):
            try:
                call_kwargs = {
                    "model": self._model,
                    "instructions": self._instructions,
                    "tools": tools,
                    "tool_choice": "auto",
                }

                if previous_response_id:
                    call_kwargs["previous_response_id"] = previous_response_id
                    call_kwargs["input"] = self._pending_input
                else:
                    call_kwargs["input"] = input_text

                response: Response = await self._client.responses.create(
                    extra_headers={"Authorization": f"Bearer {self._token_provider()}"},
                    **call_kwargs,
                )
                previous_response_id = response.id

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Responses API call failed (attempt {consecutive_errors}): {e}")
                if consecutive_errors >= self._max_consecutive_errors:
                    raise
                continue

            # Process output items
            tool_calls = []
            text_parts = []

            for item in response.output:
                if isinstance(item, ResponseFunctionToolCall):
                    tool_calls.append(item)
                elif isinstance(item, ResponseOutputMessage):
                    for content in item.content:
                        if hasattr(content, "text"):
                            text_parts.append(content.text)

            # If no tool calls, we're done
            if not tool_calls:
                final_text = "\n".join(text_parts) if text_parts else ""
                self._final_response = AgentResponse(
                    messages=[Message(role="assistant", contents=[final_text])],
                    response_id=response.id,
                )
                return

            # Execute tool calls and build input for next round
            self._pending_input = []
            for tc in tool_calls:
                try:
                    result = await self._execute_tool_call(tc)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(
                        f"Tool {tc.name} failed ({consecutive_errors}/{self._max_consecutive_errors}): {e}"
                    )
                    result = f"Error: {e}"
                    if consecutive_errors >= self._max_consecutive_errors:
                        raise

                self._pending_input.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": result,
                })

            # Yield a heartbeat so the framework knows we're still working
            yield AgentResponseUpdate()

        # Exhausted tool rounds
        logger.warning(f"Agent {self.name} hit max tool rounds ({self._max_tool_rounds})")
        self._final_response = AgentResponse(
            messages=[Message(role="assistant", contents=["Max tool rounds reached."])],
            response_id=previous_response_id or "",
        )

    def _extract_input_text(self, messages) -> str:
        """Convert various message formats to a plain text string."""
        if isinstance(messages, str):
            return messages
        elif isinstance(messages, list):
            parts = []
            for msg in messages:
                if isinstance(msg, str):
                    parts.append(msg)
                elif hasattr(msg, "contents"):
                    for c in msg.contents:
                        if isinstance(c, str):
                            parts.append(c)
                        elif hasattr(c, "text"):
                            parts.append(c.text)
                elif hasattr(msg, "text"):
                    parts.append(msg.text)
            return "\n".join(parts)
        elif messages is None:
            return ""
        return str(messages)

    def create_session(self, *, session_id: str | None = None) -> AgentSession:
        return AgentSession(session_id=session_id)

    def get_session(self, service_session_id: str, *, session_id: str | None = None) -> AgentSession:
        return AgentSession(service_session_id=service_session_id, session_id=session_id)
