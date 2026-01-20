# K8s Task Idea Agent with Memory

## Overview
The `k8s_task_idea_agent` is a new agent that generates unique Kubernetes learning task ideas by reading official K8s documentation. It uses **Agent Memory** to track previously generated ideas and prevent duplicates.

## Key Features

### 1. Memory Management
- **TaskIdeasMemory** context provider implements persistent memory
- Stores generated task ideas in `.task_ideas_memory.json`
- Automatically loads previous ideas on startup
- Injects "do not duplicate" instructions before each generation

### 2. Memory Types Used
From the Microsoft Agent Framework documentation, this agent implements:

#### Context Providers (Dynamic Memory)
- `TaskIdeasMemory` extends `ContextProvider`
- **invoking()**: Injects previously generated ideas as context before each call
- **invoked()**: Extracts and stores new task ideas from agent responses
- Ensures agent stays aware of what's already been suggested

#### File-Based Persistence
- `_load_ideas()`: Reads from `.task_ideas_memory.json` on init
- `_save_ideas()`: Persists ideas after each generation
- Survives application restarts

### 3. How It Works

```
1. K8s Task Idea Agent reads Kubernetes documentation
   ↓
2. Memory context is injected: "Do NOT suggest these ideas: [list]"
   ↓
3. Agent generates NEW unique task idea (e.g., "001_create_namespace")
   ↓
4. Memory captures the response and stores it
   ↓
5. Next generation gets full list of previously generated ideas
```

## Usage

### In main.py (Integrated Workflow)
```python
async with get_k8s_task_idea_agent() as (idea_agent, idea_memory):
    # Generate unique task idea
    idea_result = await idea_agent.run(
        "Based on Kubernetes docs, suggest a new task idea"
    )
    
    # Extract task name and pass to generator
    task_name = idea_result.text.split("Task:")[1].split("\n")[0].strip()
```

### Standalone (Generate Multiple Ideas)
```bash
python -m agents.k8s_task_idea_agent
```

This will generate 5 unique task ideas, each time pulling from memory to avoid duplicates.

## File Structure
- **agents/k8s_task_idea_agent.py** - Agent definition with memory
- **.task_ideas_memory.json** - Persistent storage of generated ideas (auto-created)

## Memory Persistence

Ideas are stored as JSON:
```json
{
  "ideas": [
    "001_create_namespace",
    "002_deploy_pod",
    "003_create_service",
    "004_configure_configmap"
  ]
}
```

## Integration with Task Generator

The workflow is now:
1. **Idea Agent** → generates unique task concept
2. **Task Generator Agent** → creates full task with templates and tests
3. **Pytest Agent** → validates the generated task

## Benefits

✅ **No Duplicate Ideas** - Memory tracks all suggestions  
✅ **Persistent** - Ideas survive application restarts  
✅ **Scalable** - Can generate 100+ unique tasks without repetition  
✅ **Context-Aware** - Uses real K8s docs as inspiration  
✅ **Framework-Native** - Uses official Agent Framework memory patterns  

## Next Steps

- Extend memory to track task difficulty levels
- Add memory for topics already covered
- Integrate with database for production scale
- Use Mem0 for advanced memory capabilities

## References

- Microsoft Agent Framework: [Agent Memory & History](https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/agent-memory?pivots=programming-language-python)
- Memory Types: Context Providers, Persistent Stores, Thread Serialization
