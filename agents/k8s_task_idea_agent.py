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
from typing import Sequence, MutableSequence, Any, Annotated
from pydantic import BaseModel, Field

from agent_framework import (
    MCPStdioTool,
    ContextProvider,
    Context,
    ChatMessage,
    ChatAgent,
    ChatMessageStore,
)
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import AzureCliCredential
from agents.logging_middleware import LoggingFunctionMiddleware
from agents.config import PATHS, AZURE

logging.basicConfig(level=logging.INFO)
# Suppress debug messages from agent_framework and httpx
logging.getLogger("agent_framework").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


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
        
        # Store globally for retrieval
        _last_saved_concept = concept_obj
        
        logging.info(f"✅ Saved concept via tool: {concept}")
        logging.info(f"   Tags: {', '.join(tags)}")
        logging.info(f"   Variations: {', '.join([v.task_id for v in variation_objects])}")
        
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


class TaskIdeasMemory(ContextProvider):
    """Memory provider that tracks generated task ideas and injects them as context."""
    
    def __init__(self, memory_file: str = "task_ideas_memory.json"):
        """Initialize memory provider with file-based persistence.
        
        Args:
            memory_file: Path to JSON file storing generated task ideas.
        """
        logging.info(f"Initializing TaskIdeasMemory with memory_file={memory_file}")
        # Store memory file in the project root directory
        project_root = Path(__file__).parent.parent
        self.memory_file = project_root / memory_file
        logging.info(f"Memory file path resolved to: {self.memory_file}")
        self.generated_ideas: dict[str, dict] = {}  # Format: {task_id: {concept, description, variations, difficulty, tags}}
        self._ensure_memory_file()
        self._load_ideas()
    
    def _load_ideas(self) -> None:
        """Load previously generated ideas from file."""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r") as f:
                    data = json.load(f)
                    self.generated_ideas = data.get("ideas", {})
                    logging.info(f"Loaded {len(self.generated_ideas)} previously generated task concepts")
            except Exception as e:
                logging.warning(f"Failed to load memory file: {e}")
    
    def _save_ideas(self) -> None:
        """Save current ideas to file."""
        try:
            with open(self.memory_file, "w") as f:
                json.dump({"ideas": self.generated_ideas}, f, indent=2)
        except Exception as e:
            logging.warning(f"Failed to save memory file: {e}")

    def _ensure_memory_file(self) -> None:
        """Create an empty memory file if it does not exist."""
        try:
            logging.info(f"Ensuring memory file exists at: {self.memory_file}")
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)
            if not self.memory_file.exists():
                logging.info(f"Creating new memory file: {self.memory_file}")
                with open(self.memory_file, "w") as f:
                    json.dump({"ideas": {}}, f, indent=2)
                logging.info(f"✅ Memory file created successfully")
            else:
                logging.info(f"Memory file already exists")
        except Exception as e:
            logging.error(f"❌ Unable to initialize memory file {self.memory_file}: {e}")
            import traceback
            logging.error(traceback.format_exc())
    
    async def invoking(self, messages: ChatMessage | MutableSequence[ChatMessage], **kwargs: Any) -> Context:
        """Inject previously generated concepts as context before each invocation."""
        if self.generated_ideas:
            concepts_list = "\n".join([f"- {idea['concept']}" for idea in self.generated_ideas.values()])
            instructions = (
                f"IMPORTANT: Do NOT suggest these previously covered Kubernetes concepts:\n{concepts_list}\n\n"
                f"Generate a NEW and DIFFERENT Kubernetes concept that has NOT been suggested before.\n"
                f"Provide 3 VARIATIONS of tasks for this concept (Beginner, Intermediate, Advanced)."
            )
            return Context(instructions=instructions)
        return Context()
    
    async def invoked(
        self,
        request_messages: ChatMessage | Sequence[ChatMessage],
        response_messages: ChatMessage | Sequence[ChatMessage] | None = None,
        invoke_exception: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """Lifecycle hook for automatic memory saving using structured output."""
        # Note: With structured output, we save via add_structured_concept() after agent.run
        # This hook is kept for future extensions
        pass
    
    def add_structured_concept(self, concept_data: K8sTaskConcept) -> None:
        """Add a structured concept to memory."""
        task_id = concept_data.concept.replace(" ", "_").replace("*", "").lower()
        if self.concept_exists(concept_data.concept):
            logging.info(f"⚠️  Skipped: '{concept_data.concept}' already exists")
            return
        
        self.generated_ideas[task_id] = {
            "concept": concept_data.concept,
            "description": concept_data.description,
            "variations": [v.task_id for v in concept_data.variations],
            "difficulty": "Mixed (Beginner→Intermediate→Advanced)",
            "tags": concept_data.tags,
        }
        self._save_ideas()
        logging.info(f"✅ Saved: {concept_data.concept} → {', '.join([v.task_id for v in concept_data.variations])}")
    
    def add_idea(self, task_id: str, concept: str, description: str, variations: list[str], difficulty: str, tags: list[str]) -> None:
        """Manually add a full idea to memory (legacy method)."""
        self.generated_ideas[task_id] = {
            "concept": concept,
            "description": description,
            "variations": variations,
            "difficulty": difficulty,
            "tags": tags
        }
        self._save_ideas()
        logging.info(f"Added concept to memory: {concept}")
    
    def get_ideas(self) -> list[dict]:
        """Get all recorded ideas."""
        return list(self.generated_ideas.values())
    
    def concept_exists(self, concept: str) -> bool:
        """Check if a concept has already been generated."""
        return any(idea["concept"].lower() == concept.lower() for idea in self.generated_ideas.values())
    



@asynccontextmanager
async def get_k8s_task_idea_agent():
    """Create and return a Kubernetes task idea generator agent with memory.
    
    Yields:
        An agent configured to generate unique K8s task ideas from documentation.
    """
    chat_client = AzureOpenAIChatClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=AzureCliCredential(),
    )
    
    # Create memory provider (replaces thread for context)
    memory = TaskIdeasMemory()
    
    # Connect to the official MCP filesystem server via npx for reading K8s docs
    # Use absolute path and ensure proper root directory
    docs_root = str(PATHS.k8s_docs_root)
    mcp_tool = MCPStdioTool(
        name="filesystem",
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            docs_root
        ],
        load_prompts=False  # Filesystem server doesn't support prompts
    )
    
    async with mcp_tool:
        # Use as_agent() with save_k8s_task_concept tool
        agent = chat_client.as_agent(
            name="K8sTaskIdeaAgent",
            instructions=(
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
            ),
            tools=[mcp_tool, save_k8s_task_concept],
            tool_choice="auto",
            context_providers=[memory],
            middleware=[LoggingFunctionMiddleware()],
        )

        yield agent, memory


async def create_idea_agent_with_mcp(mcp_tool):
    """Create idea agent with an existing MCP tool.
    
    Args:
        mcp_tool: An already initialized MCPStdioTool instance for K8s docs
        
    Returns:
        Tuple of (agent, memory)
    """
    chat_client = AzureOpenAIChatClient(
        endpoint=AZURE.endpoint,
        deployment_name=AZURE.deployment_name,
        credential=AzureCliCredential(),
    )

    memory = TaskIdeasMemory()
    
    # Use as_agent() with save_k8s_task_concept tool
    agent = chat_client.as_agent(
        name="K8sTaskIdeaAgent",
        instructions=(
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
        ),
        tools=[mcp_tool, save_k8s_task_concept],
        tool_choice="auto",
        context_providers=[memory],
        middleware=[LoggingFunctionMiddleware()],
    )

    return agent, memory


if __name__ == "__main__":
    async def main():
        async with get_k8s_task_idea_agent() as (agent, memory):
            logging.info(f"\nStarting with {len(memory.generated_ideas)} existing concepts in memory\n")

            for round_num in range(3):
                logging.info(f"\n{'='*70}")
                logging.info(f"Round {round_num + 1}: Generating New Kubernetes Concept")
                logging.info(f"{'='*70}")

                # Clear previous concept
                clear_last_saved_concept()
                
                result = await agent.run(
                    "Based on Kubernetes documentation, suggest a NEW concept not yet covered. "
                    "Generate 3 task variations (Beginner, Intermediate, Advanced) with full details. "
                    "Call save_k8s_task_concept to save your concept."
                )
                
                # Get concept from tool call
                concept = get_last_saved_concept()
                
                if concept:
                    logging.info(f"\n✅ Generated Concept: {concept.concept}")
                    logging.info(f"   Tags: {', '.join(concept.tags)}")
                    logging.info(f"   Variations: {', '.join([v.task_id for v in concept.variations])}")
                    
                    # Save to memory
                    memory.add_structured_concept(concept)
                else:
                    logging.warning("⚠️  No concept saved via tool call")
                    logging.warning(f"   Agent response: {result.text[:200]}")

            logging.info(f"\n\n{'='*70}")
            logging.info("All Saved Concepts:")
            logging.info(f"{'='*70}")
            for i, idea in enumerate(memory.get_ideas(), 1):
                logging.info(f"\n{i}. {idea['concept']}")
                logging.info(f"   Description: {idea['description'][:100]}...")
                logging.info(f"   Variations: {', '.join(idea['variations'])}")
                logging.info(f"   Tags: {', '.join(idea['tags'])}")

    asyncio.run(main())
