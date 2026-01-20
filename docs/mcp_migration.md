# MCP Filesystem Server Migration

## Overview

This project has been migrated from a custom MCP filesystem server installation to the official [@modelcontextprotocol/server-filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) package.

## Changes Made

### 1. Agent Updates

All agents using the MCP filesystem server have been updated:

- **filesystem_agent.py** - General file operations
- **k8s_task_generator_agent.py** - Task file generation  
- **k8s_task_idea_agent.py** - Reading Kubernetes documentation

### 2. Command Configuration

**Before:**
```python
mcp_tool = MCPStdioTool(
    name="filesystem",
    command="/home/developer/Documents/data-disk/k8s-game-rule-builder/.venv/bin/mcp-server-filesystem",
    args=["/allowed/directory"]
)
```

**After:**
```python
mcp_tool = MCPStdioTool(
    name="filesystem",
    command="npx",
    args=[
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/allowed/directory"
    ],
    load_prompts=False  # Filesystem server doesn't support prompts
)
```

### 3. Key Changes

1. **No Manual Installation**: The MCP server is now automatically downloaded and run via `npx`
2. **Official Package**: Uses the official Model Context Protocol implementation
3. **Prompts Disabled**: Added `load_prompts=False` since the filesystem server doesn't support the prompts capability

## Benefits

✅ **No Manual Setup**: npx handles package management automatically  
✅ **Always Up-to-Date**: Latest version used on each run with `-y` flag  
✅ **Official Support**: Uses the maintained Model Context Protocol implementation  
✅ **Better Documentation**: Full documentation available at the official repository  
✅ **Standard Tools**: Access to all official filesystem server capabilities

## MCP Filesystem Server Features

The official server provides these tools:

### Read Operations
- `read_text_file` - Read complete file contents as text
- `read_media_file` - Read image or audio files  
- `read_multiple_files` - Read multiple files simultaneously
- `list_directory` - List directory contents
- `list_directory_with_sizes` - List with file sizes
- `directory_tree` - Get recursive tree structure
- `search_files` - Search for files matching patterns
- `get_file_info` - Get detailed file metadata

### Write Operations
- `write_file` - Create new file or overwrite existing
- `edit_file` - Make selective edits with pattern matching
- `create_directory` - Create directories
- `move_file` - Move or rename files/directories

### Tool Annotations

All tools include MCP annotations:
- `readOnlyHint` - Identifies read-only operations
- `idempotentHint` - Operations safe to retry
- `destructiveHint` - Operations that may overwrite data

## Directory Access Control

The server restricts operations to allowed directories specified via command-line arguments:

```python
args=[
    "-y",
    "@modelcontextprotocol/server-filesystem",
    "/allowed/directory1",
    "/allowed/directory2"
]
```

Operations outside these directories are blocked for security.

## Testing

To verify the migration:

```bash
source .venv/bin/activate

# Test filesystem agent
python -m agents.filesystem_agent

# Test task generator
python -m agents.k8s_task_generator_agent

# Test idea generator  
python -m agents.k8s_task_idea_agent
```

## Troubleshooting

### First Run
On first run, npx will download the package:
```
Secure MCP Filesystem Server running on stdio
Client does not support MCP Roots, using allowed directories set from server args: [...]
```

### Network Issues
If npx can't download the package, ensure network connectivity and npm registry access.

### Permission Issues
Ensure the directories specified in `args` exist and are readable/writable by the user.

## References

- [Official MCP Filesystem Server](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Agent Framework Documentation](https://github.com/Azure/agent-framework)
