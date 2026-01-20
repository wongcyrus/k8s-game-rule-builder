"""Main entry point for k8s-game-rule-builder agents.

This pipeline:
1. Generates a unique K8s task idea from documentation
2. Creates the complete task structure with all required files
3. Tests the generated task to validate it works
"""
import asyncio
import logging
import re
from agents import (
    get_pytest_agent,
    get_k8s_task_generator_agent,
    get_k8s_task_idea_agent,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def extract_task_info(idea_text: str) -> dict:
    """Extract task information from idea agent result.
    
    Args:
        idea_text: The text output from the idea agent
        
    Returns:
        dict with 'task_id', 'title', 'description', 'difficulty'
    """
    task_info = {
        'task_id': None,
        'title': None,
        'description': None,
        'difficulty': 'beginner'
    }
    
    # Try to extract task ID patterns like: 001_concept_name or XXX_concept_name
    task_id_match = re.search(r'(?:Task ID:|Task:)\s*(\d{3}_\w+)', idea_text)
    if task_id_match:
        task_info['task_id'] = task_id_match.group(1)
    
    # Extract title
    title_match = re.search(r'(?:Title:|Task:)\s*([^\n]+)', idea_text)
    if title_match and not task_info['task_id']:
        # If we got a title but no ID, check if title has the pattern
        title_text = title_match.group(1).strip()
        id_in_title = re.search(r'(\d{3}_\w+)', title_text)
        if id_in_title:
            task_info['task_id'] = id_in_title.group(1)
        task_info['title'] = title_text
    
    # Extract difficulty
    if 'ADVANCED' in idea_text.upper() or 'advanced' in idea_text.lower():
        task_info['difficulty'] = 'advanced'
    elif 'INTERMEDIATE' in idea_text.upper() or 'intermediate' in idea_text.lower():
        task_info['difficulty'] = 'intermediate'
    
    # Extract description/objective
    desc_match = re.search(r'(?:Description:|Objective:)\s*([^\n]+)', idea_text)
    if desc_match:
        task_info['description'] = desc_match.group(1).strip()
    
    return task_info


async def main():
    """Run the complete pipeline: Idea -> Generate -> Test."""
    
    logging.info("="*80)
    logging.info("K8S TASK GENERATION PIPELINE")
    logging.info("="*80)
    
    # Step 1: Generate Task Idea
    logging.info("\n[STEP 1/3] Generating unique K8s task idea from documentation...")
    logging.info("-"*80)
    
    task_info = {}
    async with get_k8s_task_idea_agent() as (idea_agent, idea_memory):
        idea_result = await idea_agent.run(
            "Based on the Kubernetes documentation, suggest ONE new and unique task idea "
            "for teaching Kubernetes concepts. Choose a concept that hasn't been covered yet. "
            "Provide a clear task ID in format '###_concept_name' (e.g., '050_secrets_management'). "
            "Include the objective and what students will learn."
        )
        
        logging.info("\n✓ Idea Generated:")
        logging.info(idea_result.text)
        
        # Extract task information
        task_info = extract_task_info(idea_result.text)
        
    if not task_info['task_id']:
        logging.error("Failed to extract task ID from idea. Using fallback.")
        task_info['task_id'] = "099_fallback_task"
    
    logging.info(f"\n→ Task ID: {task_info['task_id']}")
    logging.info(f"→ Difficulty: {task_info['difficulty']}")
    if task_info['description']:
        logging.info(f"→ Description: {task_info['description']}")
    
    # Step 2: Generate Complete Task
    logging.info("\n[STEP 2/3] Generating complete task structure...")
    logging.info("-"*80)
    
    task_directory = None
    async with get_k8s_task_generator_agent() as task_gen_agent:
        generation_prompt = (
            f"Generate a complete Kubernetes learning task with ID '{task_info['task_id']}' "
            f"at {task_info['difficulty']} difficulty level.\n\n"
            f"Based on this concept:\n{idea_result.text}\n\n"
            f"Create ALL required files in tests/game02/{task_info['task_id']}/:\n"
            f"- __init__.py (empty)\n"
            f"- instruction.md (user-facing challenge with Jinja variables)\n"
            f"- session.json (JSON with template variables)\n"
            f"- setup.template.yaml (at minimum creates namespace)\n"
            f"- answer.template.yaml (complete solution)\n"
            f"- test_01_setup.py (uses deploy_setup)\n"
            f"- test_03_answer.py (uses deploy_answer)\n"
            f"- test_05_check.py (validation with kubectl + JSON parsing)\n"
            f"- test_06_cleanup.py (uses delete_namespace)\n\n"
            f"Use proper Jinja template variables like {{{{random_name()}}}}, {{{{student_id()}}}}, etc."
        )
        
        task_result = await task_gen_agent.run(generation_prompt)
        
        logging.info("\n✓ Task Generated:")
        logging.info(task_result.text)
        
        # Extract directory path if mentioned
        task_directory = f"tests/game02/{task_info['task_id']}"
    
    logging.info(f"\n→ Task created at: {task_directory}")
    
    # Step 3: Run Tests on Generated Task
    logging.info("\n[STEP 3/3] Testing generated task...")
    logging.info("-"*80)
    
    pytest_agent = get_pytest_agent()
    pytest_result = await pytest_agent.run(
        f"Run all tests in {task_directory}/ to validate the generated task. "
        f"Show test results and any failures."
    )
    
    logging.info("\n✓ Test Results:")
    logging.info(pytest_result.text)
    
    # Final Summary
    logging.info("\n" + "="*80)
    logging.info("PIPELINE COMPLETE")
    logging.info("="*80)
    logging.info(f"Task ID: {task_info['task_id']}")
    logging.info(f"Location: {task_directory}")
    logging.info(f"Status: Check test results above")
    logging.info("="*80)

if __name__ == "__main__":
    # Run all agents
    asyncio.run(main())
