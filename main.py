"""Main entry point for k8s-game-rule-builder agents.

This pipeline:
1. Generates a unique K8s task idea from documentation
2. Creates the complete task structure with all required files
3. Tests the generated task to validate it works
"""
import asyncio
import logging
import json
import re
from pathlib import Path
from agents import (
    get_pytest_agent,
    get_k8s_task_generator_agent,
    get_k8s_task_idea_agent,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def parse_task_idea_from_text(text: str):
    """Parse task idea from markdown-formatted response text.
    
    Extracts task ID, concept, objective, and high-level idea from the response.
    """
    from agents.k8s_task_idea_agent import K8sTaskConcept, TaskVariation
    
    task_id = None
    concept = None
    objective = None
    what_learn = None
    high_level = None
    
    # Parse Task ID
    task_id_match = re.search(r'\*\*Task ID:\*\*.*?\*\*(\d{3}_[a-z0-9_]+)\*\*', text, re.IGNORECASE)
    if task_id_match:
        task_id = task_id_match.group(1)
    
    # Parse Concept
    concept_match = re.search(r'\*\*Concept:\*\*\s*(.+?)(?=\n\n|\*\*)', text)
    if concept_match:
        concept = concept_match.group(1).strip()
    
    # Parse Objective
    objective_match = re.search(r'\*\*Objective:\*\*\s*([\s\S]+?)(?=\n\*\*What Students|$)', text)
    if objective_match:
        objective = objective_match.group(1).strip()
    
    # Parse What Students Will Learn
    learn_match = re.search(r'\*\*What Students Will Learn:\*\*\s*([\s\S]+?)(?=\n\*\*High-Level|$)', text)
    if learn_match:
        what_learn = learn_match.group(1).strip()
    
    # Parse High-Level Task Idea
    high_level_match = re.search(r'\*\*High-Level Task Idea:\*\*\s*([\s\S]+?)$', text)
    if high_level_match:
        high_level = high_level_match.group(1).strip()
    
    # Create a basic variation from the parsed data
    if task_id and concept:
        variation = TaskVariation(
            task_id=task_id,
            difficulty="BEGINNER",
            title=concept,
            objective=objective or high_level or "Learn Kubernetes concepts",
            key_skills=["kubernetes", "operations"],
            estimated_time=45
        )
        
        return K8sTaskConcept(
            concept=concept,
            tags=["kubernetes", "operations"],
            description=objective or "A Kubernetes learning task",
            variations=[variation]
        )
    
    return None


async def main():
    """Run the complete pipeline: Idea -> Generate -> Test."""
    
    logging.info("="*80)
    logging.info("K8S TASK GENERATION PIPELINE - GENERATING 10 TASKS")
    logging.info("="*80)
    
    generated_tasks = []
    task_ids_seen = set()
    
    # Generate 3 unique tasks
    for task_num in range(1, 4):
        logging.info(f"\n{'#'*80}")
        logging.info(f"TASK {task_num}/3")
        logging.info(f"{'#'*80}")
        
        # Step 1: Generate Task Idea
        logging.info("\n[STEP 1/3] Generating unique K8s task idea from documentation...")
        logging.info("-"*80)
        
        task_info = {}
        async with get_k8s_task_idea_agent() as (idea_agent, idea_memory, idea_thread, thread_state_path):
            from agents.k8s_task_idea_agent import K8sTaskConcept
            
            idea_result = await idea_agent.run(
                "Based on the Kubernetes documentation, suggest ONE new and unique task idea "
                "for teaching Kubernetes concepts. Choose a concept that hasn't been covered yet. "
                "Provide a clear task ID in format '###_concept_name' (e.g., '050_secrets_management'). "
                "Include the objective and what students will learn.",
                thread=idea_thread,
                response_format=K8sTaskConcept,
            )
            
            # Persist thread state to disk for continuity across runs
            serialized_thread = await idea_thread.serialize()
            with open(thread_state_path, "w") as f:
                json.dump(serialized_thread, f)
            
            # Extract structured data from response
            concept = None
            
            if idea_result.value:
                concept = idea_result.value
                logging.info("✅ Got structured output directly from API")
            elif hasattr(idea_result, 'text') and idea_result.text:
                # Try to parse from markdown text
                concept = parse_task_idea_from_text(idea_result.text)
                if concept:
                    logging.info("✅ Parsed structured output from markdown text")
            
            if concept:
                logging.info(f"\n✅ Idea Generated: {concept.concept}")
                logging.info(f"   Tags: {', '.join(concept.tags)}")
                logging.info(f"   Description: {concept.description[:100]}...")
                
                # Save to memory
                idea_memory.add_structured_concept(concept)
                
                # Use the beginner task for generation
                beginner_task = concept.variations[0] if concept.variations else None
                if beginner_task:
                    task_info['task_id'] = beginner_task.task_id
                    task_info['title'] = beginner_task.title
                    task_info['description'] = beginner_task.objective
                    task_info['difficulty'] = beginner_task.difficulty.lower()
            else:
                # No structured data found - debug the response
                logging.error("No structured data found in response")
                logging.error(f"Response object type: {type(idea_result)}")
                logging.error(f"Response has .value: {hasattr(idea_result, 'value')}")
                if hasattr(idea_result, 'value'):
                    logging.error(f"Response.value is: {idea_result.value}")
                if hasattr(idea_result, 'text'):
                    print("\n" + "="*80)
                    print("FULL RESPONSE TEXT FOR DEBUG:")
                    print("="*80)
                    print(idea_result.text)
                    print("="*80 + "\n")
                raise ValueError("Failed to generate task idea - no structured data in response")
            
        if not task_info.get('task_id'):
            raise ValueError("Failed to extract task ID from idea agent response")
        
        # Ensure unique task ID
        if task_info['task_id'] in task_ids_seen:
            logging.warning(f"⚠️  Duplicate task ID detected: {task_info['task_id']}")
            # Append task number to make it unique
            task_info['task_id'] = f"{task_info['task_id']}_v{task_num}"
        
        task_ids_seen.add(task_info['task_id'])
        
        logging.info(f"\n→ Task ID: {task_info['task_id']}")
        logging.info(f"→ Difficulty: {task_info.get('difficulty', 'beginner')}")
        if task_info.get('description'):
            logging.info(f"→ Description: {task_info['description']}")
        
        # Step 2: Generate Complete Task
        logging.info("\n[STEP 2/3] Generating complete task structure...")
        logging.info("-"*80)
        
        task_directory = None
        async with get_k8s_task_generator_agent() as task_gen_agent:
            generation_prompt = (
                f"Generate a complete Kubernetes learning task with ID '{task_info['task_id']}' "
                f"at {task_info.get('difficulty', 'beginner')} difficulty level.\n\n"
                f"Task: {task_info.get('title', 'Kubernetes Learning Task')}\n"
                f"Objective: {task_info.get('description', 'Learn Kubernetes concepts')}\n\n"
                f"Create ALL required files in tests/{PATHS.game_name}/{task_info['task_id']}/:\n"
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
            logging.info(task_result.text[:500] + "..." if len(task_result.text) > 500 else task_result.text)
            
            # Extract directory path if mentioned
            task_directory = f"tests/{PATHS.game_name}/{task_info['task_id']}"
        
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
        test_summary = "PASSED" if "passed" in pytest_result.text.lower() and "failed" not in pytest_result.text.lower() else "FAILED"
        logging.info(f"Status: {test_summary}")
        
        # Track generated task
        generated_tasks.append({
            'task_id': task_info['task_id'],
            'directory': task_directory,
            'status': test_summary,
        })
    
    # Final Summary
    logging.info("\n" + "="*80)
    logging.info("PIPELINE COMPLETE - ALL 10 TASKS")
    logging.info("="*80)
    for idx, task in enumerate(generated_tasks, 1):
        logging.info(f"{idx}. {task['task_id']}: {task['status']} ({task['directory']})")
    logging.info("="*80)

if __name__ == "__main__":
    # Run all agents
    asyncio.run(main())
