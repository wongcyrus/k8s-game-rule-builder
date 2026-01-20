# Logging Middleware Implementation

## Overview

A Function Middleware Class for logging has been added to all agents in the project. This middleware intercepts and logs function invocations, arguments, results, execution timing, and error handling.

## Files Added

### [agents/logging_middleware.py](agents/logging_middleware.py)
- **LoggingFunctionMiddleware**: Main class extending `FunctionMiddleware`
- **get_logging_middleware()**: Factory function for creating middleware instances

## Features

- **Pre-execution logging**: Logs function name before execution
- **Argument tracking**: Logs validated arguments passed to functions
- **Execution timing**: Measures and logs function duration in seconds
- **Result logging**: Logs function return values after execution
- **Error handling**: Captures and logs exceptions with full traceback
- **Configurable logger**: Accepts custom logger instance or uses default

## Agents Updated

All agents in the project now use the logging middleware:

1. **[agents/kubernetes_agent.py](agents/kubernetes_agent.py)**
   - Logs `run_kubectl_command()` invocations

2. **[agents/pytest_agent.py](agents/pytest_agent.py)**
   - Logs `run_pytest_command()` invocations

3. **[agents/filesystem_agent.py](agents/filesystem_agent.py)**
   - Logs MCP filesystem tool operations

4. **[agents/k8s_task_idea_agent.py](agents/k8s_task_idea_agent.py)**
   - Logs task idea generation operations

5. **[agents/k8s_task_generator_agent.py](agents/k8s_task_generator_agent.py)**
   - Logs task file generation operations

## Usage

### Basic Usage

The middleware is automatically instantiated in each agent:

```python
from logging_middleware import LoggingFunctionMiddleware

agent = responses_client.as_agent(
    name="MyAgent",
    instructions="...",
    tools=my_tools,
    middleware=[LoggingFunctionMiddleware()],
)
```

### Custom Logger

You can provide a custom logger instance:

```python
import logging

custom_logger = logging.getLogger("my_app.agents")
middleware = LoggingFunctionMiddleware(logger=custom_logger)

agent = responses_client.as_agent(
    name="MyAgent",
    instructions="...",
    tools=my_tools,
    middleware=[middleware],
)
```

### Factory Function

Use the factory function for cleaner code:

```python
from logging_middleware import get_logging_middleware

agent = responses_client.as_agent(
    name="MyAgent",
    instructions="...",
    tools=my_tools,
    middleware=[get_logging_middleware()],
)
```

## Log Output Example

```
INFO:agents.logging_middleware:[Function] Calling run_kubectl_command
DEBUG:agents.logging_middleware:[Function] Arguments: {'command': 'get pods'}
INFO:agents.logging_middleware:[Function] run_kubectl_command completed successfully in 2.345s
DEBUG:agents.logging_middleware:[Function] Result: pod-1  pod-2  pod-3
```

## Integration

Import from the agents package:

```python
from agents import LoggingFunctionMiddleware, get_logging_middleware
```

Or import directly:

```python
from agents.logging_middleware import LoggingFunctionMiddleware
```

## Implementation Details

The middleware follows the Microsoft Agent Framework pattern:

- **FunctionInvocationContext**: Contains function details, arguments, result, and metadata
- **next()**: Callable that continues the middleware chain or executes the function
- **Error Handling**: Exceptions are logged with full traceback and re-raised

## Error Logging

When a function throws an exception:

```
ERROR:agents.logging_middleware:[Function] run_kubectl_command failed after 0.567s: Connection timeout
Traceback (most recent call last):
  ...
```

Errors are logged with `exc_info=True` for full stack traces and are immediately re-raised.
