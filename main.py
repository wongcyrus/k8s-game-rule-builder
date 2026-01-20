"""Main entry point for k8s-game-rule-builder agents."""
import asyncio
import logging
from agents import (
    get_filesystem_agent,
    get_kubernetes_agent,
    get_pytest_agent,
    get_k8s_task_generator_agent,
)

logging.basicConfig(level=logging.INFO)


async def main():
    """Run all agents with example queries."""
    # logging.info("="*60)
    # logging.info("Running FileSystem Agent")
    # logging.info("="*60)
    
    # # Run filesystem query using agent context manager
    # async with get_filesystem_agent() as fs_agent:
    #     fs_result = await fs_agent.run(
    #         "List the files in /home/developer/Documents/data-disk/k8s-game-rule/tests/game02/001_default_namespace"
    #     )
    #     logging.info("\n=== FileSystem Agent Result ===")
    #     logging.info(fs_result.text)
    
    # logging.info("\n" + "="*60)
    # logging.info("Running Kubernetes Agent")
    # logging.info("="*60)
    
    # # Get kubernetes agent and run query
    # k8s_agent = get_kubernetes_agent()
    # k8s_result = await k8s_agent.run(
    #     "List all namespaces in the cluster"
    # )
    # logging.info("\n=== Kubernetes Agent Result ===")
    # logging.info(k8s_result.text)
    
    # logging.info("\n" + "="*60)

    
    logging.info("\n" + "="*60)
    logging.info("Running K8s Task Generator Agent")
    logging.info("="*60)
    
    # Get task generator agent and create a sample task
    async with get_k8s_task_generator_agent() as task_gen_agent:
        task_result = await task_gen_agent.run(
            "Generate a beginner-level task for creating a Kubernetes Service. "
            "The task should be named '080_create_service' and teach users how to create a "
            "ClusterIP service that exposes a deployment. Include template variables for "
            "namespace and service name."
        )
        logging.info("\n=== K8s Task Generator Agent Result ===")
        logging.info(task_result.text)


    logging.info("Running PyTest Agent")
    logging.info("="*60)
    
    # Get pytest agent and run tests
    pytest_agent = get_pytest_agent()
    pytest_result = await pytest_agent.run(
        "pytest --import-mode=importlib --rootdir=. tests/game02/080_create_service/"
    )
    logging.info("\n=== PyTest Agent Result ===")
    logging.info(pytest_result.text)

if __name__ == "__main__":
    # Run all agents
    asyncio.run(main())
