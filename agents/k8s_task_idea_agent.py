"""Kubernetes Task Idea Generator Agent with Memory.

This agent reads Kubernetes documentation and generates unique task ideas
for the K8s game, using memory to avoid duplicating previously generated ideas.
"""
import asyncio
import logging
import json
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Sequence, MutableSequence, Any

from agent_framework import MCPStdioTool, ContextProvider, Context, ChatMessage
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential
from .logging_middleware import LoggingFunctionMiddleware

logging.basicConfig(level=logging.INFO)
# Suppress debug messages from agent_framework and httpx
logging.getLogger("agent_framework").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


class TaskIdeasMemory(ContextProvider):
    """Memory provider that tracks generated task ideas and injects them as context."""
    
    def __init__(self, memory_file: str = ".task_ideas_memory.json"):
        """Initialize memory provider with file-based persistence.
        
        Args:
            memory_file: Path to JSON file storing generated task ideas.
        """
        self.memory_file = Path(memory_file)
        self.generated_ideas: dict[str, dict] = {}  # Format: {task_id: {concept, description, variations, difficulty, tags}}
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
        """Lifecycle hook for automatic memory saving.
        
        NOTE: This hook is NOT called when using AzureOpenAIResponsesClient.as_agent().
        The Responses API has a different lifecycle than ChatAgent.
        Memory is saved manually in the calling code after each agent.run().
        
        See: https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/agent-memory
        The memory lifecycle hooks work with ChatAgent but not with Responses API agents.
        """
        pass
    
    def add_idea(self, task_id: str, concept: str, description: str, variations: list[str], difficulty: str, tags: list[str]) -> None:
        """Manually add a full idea to memory."""
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
    
    def extract_and_save_from_response(self, response_text: str) -> bool:
        """Extract concept from agent response and save to memory.
        
        This is used instead of invoked() hook because AzureOpenAIResponsesClient
        doesn't trigger the standard lifecycle hooks.
        
        Returns:
            True if concept was saved, False if skipped/error
        """
        import re
        
        # Extract main concept
        concept_match = re.search(r'Concept:\s*(.+?)(?:\n|$)', response_text)
        concept = concept_match.group(1).strip() if concept_match else None
        
        if concept and not self.concept_exists(concept):
            # Extract tags
            tags_match = re.search(r'Tags:\s*(.+?)(?:\n|$)', response_text)
            tags = [t.strip() for t in tags_match.group(1).split(',')] if tags_match else []
            
            # Extract description
            desc_match = re.search(r'Description:\s*(.+?)(?:\n###|$)', response_text, re.DOTALL)
            description = desc_match.group(1).strip() if desc_match else "No description"
            
            # Extract task IDs
            variation_pattern = r'Task ID:\s*\*+(\d{3}[\w_]+)\*+'
            task_ids = re.findall(variation_pattern, response_text)
            
            if not task_ids:
                variation_pattern = r'Task ID:\s*(\d{3}[\w_]+)'
                task_ids = re.findall(variation_pattern, response_text)
            
            # Save to memory
            self.add_idea(
                task_id=concept.replace(" ", "_").replace("*", "").lower(),
                concept=concept,
                description=description,
                variations=task_ids,
                difficulty="Mixed (Beginner→Intermediate→Advanced)",
                tags=tags
            )
            logging.info(f"✅ Saved: {concept} → {', '.join(task_ids)}")
            return True
        elif concept:
            logging.info(f"⚠️  Skipped: '{concept}' already exists")
            return False
        return False


@asynccontextmanager
async def get_k8s_task_idea_agent():
    """Create and return a Kubernetes task idea generator agent with memory.
    
    Yields:
        An agent configured to generate unique K8s task ideas from documentation.
    """
    responses_client = AzureOpenAIResponsesClient(
        endpoint="https://cyrus-me23xi26-eastus2.openai.azure.com/",
        deployment_name="gpt-5.2-chat",
        credential=AzureCliCredential(),
    )
    
    # Create memory provider
    memory = TaskIdeasMemory()
    
    # Connect to the MCP filesystem server for reading K8s docs
    # Use absolute path and ensure proper root directory
    docs_root = "/home/developer/Documents/data-disk/website/content/en/docs/concepts"
    mcp_tool = MCPStdioTool(
        name="filesystem",
        command="/home/developer/Documents/data-disk/k8s-game-rule-builder/.venv/bin/mcp-server-filesystem",
        args=[docs_root]
    )
    
    async with mcp_tool:
        agent = responses_client.as_agent(
            name="K8sTaskIdeaAgent",
            instructions=(
                "You are a Kubernetes task idea generator that creates RICH, DETAILED task concepts with MULTIPLE VARIATIONS. "
                "Read official K8s documentation and propose comprehensive learning concepts for a Kubernetes game. "
                "\n\n=== YOUR ROLE ===\n"
                "1. Choose ONE Kubernetes concept not yet covered\n"
                "2. Generate 3 VARIATIONS of tasks for this concept:\n"
                "   - BEGINNER (easy, basic understanding)\n"
                "   - INTERMEDIATE (moderate difficulty, real-world scenario)\n"
                "   - ADVANCED (challenging, complex configuration)\n"
                "3. For each variation, provide full details and learning outcomes\n"
                "\n\n=== RESPONSE FORMAT ===\n"
                "Concept: [Core K8s Concept]\n"
                "Tags: [tag1, tag2, tag3]\n"
                "Description: [General description of the concept]\n"
                "\n### Variation 1: BEGINNER\n"
                "Task ID: 0XX_concept_name_basic\n"
                "Title: [Task Title]\n"
                "Objective: [What students will learn]\n"
                "Key Skills: [Skills acquired]\n"
                "Estimated Time: [minutes]\n"
                "\n### Variation 2: INTERMEDIATE\n"
                "Task ID: 0XX_concept_name_intermediate\n"
                "[same fields as above]\n"
                "\n### Variation 3: ADVANCED\n"
                "Task ID: 0XX_concept_name_advanced\n"
                "[same fields as above]\n"
                "\n\n=== CONCEPT REQUIREMENTS ===\n"
                "- Cover: Workloads, Services, Storage, Configuration, Security, Scheduling, Policies\n"
                "- Be specific and actionable\n"
                "- Each variation should build on the previous one\n"
                "- Include practical, hands-on scenarios\n"
                "- Reference actual K8s resources (use 3-digit IDs like 001-999)\n"
                "\n\n=== IMPORTANT ===\n"
                "- Generate MULTIPLE task variations (Beginner → Intermediate → Advanced)\n"
                "- Provide full descriptions, objectives, and skills for EACH variation\n"
                "- Do NOT duplicate concepts from memory\n"
                "- Create progression paths (learners advance through difficulty levels)\n"
                "- Be detailed and specific, not just task names!"
            ),
            tools=mcp_tool,
            context_providers=[memory],
            tool_choice="required",
            middleware=[LoggingFunctionMiddleware()],
        )
        
        yield agent, memory


if __name__ == "__main__":
    async def main():
        async with get_k8s_task_idea_agent() as (agent, memory):
            logging.info(f"\nStarting with {len(memory.generated_ideas)} existing concepts in memory\n")
            
            # Generate 3 concept rounds
            # Memory saves after each via extract_and_save_from_response()
            for round_num in range(3):
                logging.info(f"\n{'='*70}")
                logging.info(f"Round {round_num + 1}: Generating New Kubernetes Concept")
                logging.info(f"{'='*70}")
                
                result = await agent.run(
                    "Based on Kubernetes documentation, suggest a NEW concept not yet covered. "
                    "Generate 3 task variations (Beginner, Intermediate, Advanced) with full details."
                )
                logging.info("\n=== Generated Concept with Variations ===")
                logging.info(result.text)
                
                # Extract and save using helper method (replaces invoked() hook)
                memory.extract_and_save_from_response(result.text)
            
            logging.info(f"\n\n{'='*70}")
            logging.info("All Saved Concepts:")
            logging.info(f"{'='*70}")
            for i, idea in enumerate(memory.get_ideas(), 1):
                logging.info(f"\n{i}. {idea['concept']}")
                logging.info(f"   Description: {idea['description'][:100]}...")
                logging.info(f"   Variations: {', '.join(idea['variations'])}")
                logging.info(f"   Tags: {', '.join(idea['tags'])}")
    
    asyncio.run(main())
