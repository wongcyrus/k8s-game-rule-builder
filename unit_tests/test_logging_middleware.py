import asyncio
import logging
from types import SimpleNamespace

from agents.logging_middleware import LoggingFunctionMiddleware, get_logging_middleware


class _DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg, *args, **kwargs):
        self.messages.append(("info", msg))

    def debug(self, msg, *args, **kwargs):
        self.messages.append(("debug", msg))

    def error(self, msg, *args, **kwargs):
        self.messages.append(("error", msg))


def test_logging_middleware_success_path():
    logger = _DummyLogger()
    middleware = LoggingFunctionMiddleware(logger=logger)
    context = SimpleNamespace(
        function=SimpleNamespace(name="save_file"),
        arguments={"path": "/tmp/a"},
        result=None,
    )

    async def call_next():
        context.result = {"ok": True}

    asyncio.run(middleware.process(context, call_next))

    assert any("Calling save_file" in m for level, m in logger.messages if level == "info")
    assert any("completed successfully" in m for level, m in logger.messages if level == "info")


def test_logging_middleware_error_path():
    logger = _DummyLogger()
    middleware = LoggingFunctionMiddleware(logger=logger)
    context = SimpleNamespace(
        function=SimpleNamespace(name="save_file"),
        arguments={},
        result=None,
    )

    async def call_next():
        raise RuntimeError("boom")

    try:
        asyncio.run(middleware.process(context, call_next))
    except RuntimeError:
        pass

    assert any("failed after" in m for level, m in logger.messages if level == "error")


def test_get_logging_middleware_returns_instance():
    instance = get_logging_middleware(logger=logging.getLogger("test"))
    assert isinstance(instance, LoggingFunctionMiddleware)
