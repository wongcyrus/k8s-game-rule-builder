"""Kubernetes Task Idea Generator Agent with Memory.

This agent reads Kubernetes documentation and generates unique task ideas
for the K8s game, using memory to avoid duplicating previously generated ideas.
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path so this file works when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import logging
import json
from contextlib import asynccontextmanager
from typing import MutableSequence, Any, Annotated
from pydantic import BaseModel, Field

from agent_framework import (
    MCPStdioTool,
    ChatMessage,
    AgentMiddleware,
)
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import AzureCliCredential
from agents.logging_middleware import LoggingFunctionMiddleware
from agents.config import PATHS, AZURE

logging.basicConfig(level=logging.WARNING)
logging.getLogger("agent_framework").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


# Agent instructions constant (used by both standalone and workflow agents)
IDEA_AGENT_INSTRUCTIONS = (
    "You are a Kubernetes task idea generator that creates detailed task concepts with three difficulty variations. "
    "Read official K8s documentation and propose comprehensive learning concepts for a Kubernetes game. "
    "\n\nYour task:\n"
    "1. Choose ONE Kubernetes concept not yet covered (check context for existing concepts)\n"
    "2. Generate exactly 3 variations: BEGINNER, INTERMEDIATE, and ADVANCED\n"
    "3. Use 3-digit task IDs (001-999) in format: XXX_concept_name_level (e.g., 041_secrets_basic)\n"
    "4. Each variation should build on the previous one with increasing complexity\n"
    "5. Include practical, hands-on scenarios covering: Workloads, Services, Storage, Configuration, Security, Scheduling, Policies\n"
    "\n**CRITICAL**: You MUST call the save_k8s_task_concept tool to save your generated concept.\n"
    "The tool requires:\n"
    "- concept: string (core concept name)\n"
    "- tags: list of strings (e.g., ['scheduling', 'networking'])\n"
    "- description: string (general description)\n"
    "- variations: list of 3 dicts, each with:\n"
    "  - task_id: string (XXX_concept_level)\n"
    "  - difficulty: string (BEGINNER/INTERMEDIATE/ADVANCED)\n"
    "  - title: string\n"
    "  - objective: string\n"
    "  - key_skills: list of strings\n"
    "  - estimated_time: integer (minutes)\n"
    "\nAlways call save_k8s_task_concept with your generated concept."
)


class TaskVariation(BaseModel):
    """A single task variation at a specific difficulty level."""
    task_id: str = Field(description="Task ID in format XXX_concept_name (e.g., 041_secrets_basic)")
    difficulty: str = Field(description="Difficulty level: BEGINNER, INTERMEDIATE, or ADVANCED")
    title: str = Field(description="Descriptive title for the task")
    objective: str = Field(description="What students will learn")
    key_skills: list[str] = Field(description="List of skills students will acquire")
    estimated_time: int = Field(description="Estimated completion time in minutes")


class K8sTaskConcept(BaseModel):
    """Complete Kubernetes task concept with multiple difficulty variations."""
    concept: str = Field(description="Core Kubernetes concept name")
    tags: list[str] = Field(description="Relevant tags (e.g., scheduling, networking, storage)")
    description: str = Field(description="General description of the concept")
    variations: list[TaskVariation] = Field(description="Three variations: beginner, intermediate, advanced")


# Global variable to store the last saved concept (for retrieval after agent run)
_last_saved_concept: K8sTaskConcept | None = None


def save_k8s_task_concept(
    concept: Annotated[str, Field(description="Core Kubernetes concept name")],
    tags: Annotated[list[str], Field(description="Relevant tags (e.g., scheduling, networking, storage)")],
    description: Annotated[str, Field(description="General description of the concept")],
    variations: Annotated[list[dict], Field(description="Three variations with task_id, difficulty, title, objective, key_skills, estimated_time")],
) -> dict[str, Any]:
    """Save a Kubernetes task concept with multiple difficulty variations.
    
    This tool should be called to save the generated task concept.
    Returns a confirmation with the saved concept details.
    """
    global _last_saved_concept
    
    try:
        # Convert variations dicts to TaskVariation objects
        variation_objects = [TaskVariation(**v) for v in variations]
        
        # Create K8sTaskConcept object
        concept_obj = K8sTaskConcept(
            concept=concept,
            tags=tags,
            description=description,
            variations=variation_objects
        )
        
        _last_saved_concept = concept_obj
        
        return {
            "success": True,
            "message": f"Successfully saved concept: {concept}",
            "concept": concept,
            "variations_count": len(variation_objects),
            "variation_ids": [v.task_id for v in variation_objects]
        }
    except Exception as e:
        logging.error(f"❌ Failed to save concept: {e}")
        return {
            "success": False,
            "message": f"Failed to save concept: {str(e)}",
            "error": str(e)
        }


def get_last_saved_concept() -> K8sTaskConcept | None:
    """Retrieve the last saved concept from the tool call."""
    return _last_saved_concept


def clear_last_saved_concept():
    """Clear the last saved concept."""
    global _last_saved_concept
    _last_saved_concept = None


class TaskIdeasMemory:
    """Memory store for generated and failed task ideas."""
    
    def __init__(self,
                 memory_file: str = "task_ideas_memory.json",
                 failure_memory_file: str = "task_ideas_failure_memory.json"):
        """Initialize memory provider with success and failure persistence."""
        project_root = Path(__file__).parent.parent
        self.memory_file = project_root / memory_file
        self.failure_memory_file = project_root / failure_memory_file
        self.generated_ideas: dict[str, dict] = {}
        self.failed_concepts: dict[str, dict] = {}
        self._ensure_memory_file(self.memory_file)
        self._ensure_memory_file(self.failure_memory_file)
        self._load_ideas()
        self._load_failures()
    
    def _load_ideas(self) -> None:
        """Load previously generated ideas from file."""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r") as f:
                    data = json.load(f)
                    self.generated_ideas = data.get("ideas", {})
            except Exception as e:
                logging.error(f"Failed to load memory file: {e}")

    def _load_failures(self) -> None:
        """Load previously failed concepts from file."""
        if self.failure_memory_file.exists():
            try:
                with open(self.failure_memory_file, "r") as f:
                    data = json.load(f)
                    self.failed_concepts = data.get("ideas", {})
            except Exception as e:
                logging.error(f"Failed to load failure memory file: {e}")
    
    def _save_ideas(self) -> None:
        """Save current ideas to file."""
        try:
            with open(self.memory_file, "w") as f:
                json.dump({"ideas": self.generated_ideas}, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save memory file: {e}")

    def _save_failures(self) -> None:
        """Save failed concepts to file."""
        try:
            with open(self.failure_memory_file, "w") as f:
                json.dump({"ideas": self.failed_concepts}, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save failure memory file: {e}")

    def _ensure_memory_file(self, path: Path) -> None:
        """Create an empty memory file if it does not exist."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with open(path, "w") as f:
                    json.dump({"ideas": {}}, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to initialize memory file {path}: {e}")
    
class TaskIdeasMemoryMiddleware(AgentMiddleware):
    """Middleware that injects task idea memory into agent prompt reliably (Python SDK)."""
    def __init__(self, memory: TaskIdeasMemory):
        self.memory = memory

    async def process(self, context, next):
        # Always inject a baseline guard instruction (even on first run)
        blocks = [
            "You MUST generate a Kubernetes task concept that is novel, practical, and not a trivial or duplicate example."
            " Select a concept suitable for a learning game and avoid overly common demos unless memory explicitly allows them."
        ]

        # Append success-memory constraints when available
        if self.memory.generated_ideas:
            concepts_list = "\n".join(
                f"- {idea['concept']}" for idea in self.memory.generated_ideas.values()
            )
            blocks.append(
                "IMPORTANT: Do NOT suggest these previously covered Kubernetes concepts:\n"
                + concepts_list
            )

        # Append failure-memory constraints when available
        if self.memory.failed_concepts:
            failed_list = "\n".join(
                f"- {idea['concept']}" for idea in self.memory.failed_concepts.values()
            )
            blocks.append(
                "IMPORTANT: Do NOT suggest these concepts that previously FAILED validation:\n"
                + failed_list
            )

        injected = "\n\n".join(blocks)
        logging.info("✅ Injecting task ideas constraints via middleware")

        # Prepend a SYSTEM message so it reliably conditions the model
        context.messages.insert(0, ChatMessage(role="system", content=injected))

        await next(context)
    
    def add_structured_concept(self, concept_data: K8sTaskConcept) -> None:
        """Add a structured concept to memory."""
        task_id = concept_data.concept.replace(" ", "_").replace("*", "").lower()
        if self.concept_exists(concept_data.concept):
            return
        
        self.generated_ideas[task_id] = {
            "concept": concept_data.concept,
            "description": concept_data.description,
            "variations": [v.task_id for v in concept_data.variations],
            "difficulty": "Mixed (Beginner→Intermediate→Advanced)",
            "tags": concept_data.tags,
        }
        self._save_ideas()

    # --- Failure memory (backwards compatibility) ---
    def add_failed_concept(self, concept_data: K8sTaskConcept, reason: str | None = None) -> None:
        """Record a concept that failed later in the workflow."""
        task_id = concept_data.concept.replace(" ", "_").replace("*", "").lower()
        self.failed_concepts[task_id] = {
            "concept": concept_data.concept,
            "description": concept_data.description,
            "variations": [v.task_id for v in concept_data.variations],
            "reason": reason,
            "tags": concept_data.tags,
        }
        self._save_failures()

    # Compatibility API (used by workflow)
    def add_failed_concept(self, concept_data: K8sTaskConcept, reason: str | None = None) -> None:
        """Record a concept that failed later in the workflow (compatibility method)."""
        task_id = concept_data.concept.replace(" ", "_").replace("*", "").lower()
        self.failed_concepts[task_id] = {
            "concept": concept_data.concept,
            "description": concept_data.description,
            "variations": [v.task_id for v in concept_data.variations],
            "reason": reason,
            "tags": concept_data.tags,
        }
        self._save_failures()

    def add_failed_concept(self, concept_data: K8sTaskConcept, reason: str | None = None) -> None:
        """Record a concept that failed later in the workflow."""
        task_id = concept_data.concept.replace(" ", "_").replace("*", "").lower()
        self.failed_concepts[task_id] = {
            "concept": concept_data.concept,
            "description": concept_data.description,
            "variations": [v.task_id for v in concept_data.variations],
            "reason": reason,
            "tags": concept_data.tags,
        }
        self._save_failures()
    
    def get_ideas(self) -> list[dict]:
        """Get all recorded ideas."""
        return list(self.generated_ideas.values())
    
    def concept_exists(self, concept: str) -> bool:
        """Check if a concept has already been generated."""
        return any(idea["concept"].lower() == concept.lower() for idea in self.generated_ideas.values())
    



"""
NOTE:
The standalone agent factory has been removed.
Use create_idea_agent_with_mcp(mcp_tool) everywhere to ensure a single,
consistent construction path with memory injection.
"""


async def create_idea_agent_with_mcp(mcp_tool):
    """Create idea agent with an existing MCP tool.
    
    For workflow usage where MCP tool is managed externally.
    Args: mcp_tool - An already initialized MCPStdioTool instance for K8s docs
    Returns: Tuple of (agent, memory)
    """
    chat_client = AzureOpenAIChatClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=AzureCliCredential(),
    )
    
    chat_client.function_invocation_configuration.max_consecutive_errors_per_request = 10
    memory = TaskIdeasMemory()
    
    agent = chat_client.as_agent(
        name="K8sTaskIdeaAgent",
        instructions=IDEA_AGENT_INSTRUCTIONS,
        tools=[mcp_tool, save_k8s_task_concept],
        tool_choice="auto",
        middleware=[
            TaskIdeasMemoryMiddleware(memory),
            LoggingFunctionMiddleware(),
        ],
    )

    return agent, memory
