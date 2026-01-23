"""Task idea generation logic."""
import logging
from agents.k8s_task_idea_agent import (
    K8sTaskConcept,
    get_last_saved_concept,
    clear_last_saved_concept,
)


async def generate_task_idea(idea_agent, idea_memory) -> K8sTaskConcept:
    """Generate a unique task idea using the idea agent.
    
    Args:
        idea_agent: The idea generation agent
        idea_memory: Memory of previously generated ideas
        
    Returns:
        K8sTaskConcept with task details
        
    Raises:
        ValueError: If no concept is generated or no variations found
    """
    logging.info("\n[STEP 1] Generating unique task idea...")
    
    clear_last_saved_concept()
    
    existing_concepts = []
    if idea_memory.generated_ideas:
        existing_concepts = [idea['concept'] for idea in idea_memory.generated_ideas.values()]
    
    idea_prompt = (
        "Based on the Kubernetes documentation, suggest ONE new and unique task idea "
        "for teaching Kubernetes concepts. Choose a concept that hasn't been covered yet. "
    )
    
    if existing_concepts:
        idea_prompt += (
            f"\n\n⚠️  IMPORTANT: Do NOT suggest these previously covered concepts:\n"
            f"{chr(10).join([f'  - {c}' for c in existing_concepts])}\n"
            f"\nGenerate a DIFFERENT concept that is NOT in the list above."
        )
    
    idea_prompt += (
        "\n\nYou MUST generate exactly 3 task variations (BEGINNER, INTERMEDIATE, ADVANCED)."
        "\n\nFor the BEGINNER variation, use a task_id in format '###_concept_name' (e.g., '050_secrets_management')."
        "\nFor INTERMEDIATE and ADVANCED, you can use sequential IDs or descriptive suffixes."
        "\n\nEach variation must include:"
        "\n- task_id: string (e.g., '050_secrets_management')"
        "\n- difficulty: string - must be exactly 'BEGINNER', 'INTERMEDIATE', or 'ADVANCED'"
        "\n- title: string - descriptive title"
        "\n- objective: string - what students will learn"
        "\n- key_skills: list of strings - skills students will acquire"
        "\n- estimated_time: integer - completion time in minutes"
        "\n\nAlso provide:"
        "\n- concept: string - core concept name"
        "\n- description: string - general description of the concept"
        "\n- tags: list of strings - relevant tags (e.g., ['security', 'storage'])"
        "\n\nCall save_k8s_task_concept with ALL parameters: concept, tags, description, and variations (list of 3 dicts)."
    )
    
    await idea_agent.run(idea_prompt)
    concept = get_last_saved_concept()
    
    if not concept:
        raise ValueError("No concept saved via tool call")
    
    if not concept.variations or len(concept.variations) == 0:
        raise ValueError("No task variations found in concept")
    
    logging.info(f"✅ Generated concept: {concept.concept} (ID: {concept.variations[0].task_id})")
    
    return concept
