"""Logging middleware for agent framework functions.

Provides Function Middleware Class for logging function invocations,
arguments, results, timing, and error handling across all agents.
"""
import logging
import time
from typing import Callable, Awaitable
from agent_framework import FunctionMiddleware, FunctionInvocationContext


class LoggingFunctionMiddleware(FunctionMiddleware):
    """Function middleware that logs function execution with timing and arguments.
    
    Features:
    - Pre/post execution logging
    - Argument and result logging
    - Execution timing
    - Error handling with full traceback
    - Configurable logger instance
    """

    def __init__(self, logger: logging.Logger = None):
        """Initialize the logging middleware.
        
        Args:
            logger: Optional logger instance. If None, creates a default logger.
        """
        self.logger = logger or logging.getLogger(__name__)

    async def process(
        self,
        context: FunctionInvocationContext,
        next: Callable[[FunctionInvocationContext], Awaitable[None]],
    ) -> None:
        """Process function invocation with logging.
        
        Args:
            context: The function invocation context containing function details.
            next: Callable to continue to the next middleware or function execution.
        """
        function_name = context.function.name
        start_time = time.time()

        # Pre-processing: Log before function execution
        self.logger.info(f"[Function] Calling {function_name}")
        self.logger.debug(f"[Function] Arguments: {context.arguments}")

        try:
            # Continue to next middleware or function execution
            await next(context)

            # Post-processing: Log after function execution
            elapsed_time = time.time() - start_time
            self.logger.info(
                f"[Function] {function_name} completed successfully in {elapsed_time:.3f}s"
            )
            self.logger.debug(f"[Function] Result: {context.result}")

        except Exception as e:
            # Error logging
            elapsed_time = time.time() - start_time
            self.logger.error(
                f"[Function] {function_name} failed after {elapsed_time:.3f}s: {str(e)}",
                exc_info=True,
            )
            raise


def get_logging_middleware(logger: logging.Logger = None) -> LoggingFunctionMiddleware:
    """Factory function to create a logging middleware instance.
    
    Args:
        logger: Optional logger instance. If None, creates a default logger.
        
    Returns:
        An instance of LoggingFunctionMiddleware.
    """
    return LoggingFunctionMiddleware(logger=logger)
