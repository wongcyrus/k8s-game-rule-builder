"""Script to generate the create_service task."""
import os
import json
from pathlib import Path

# Task configuration
TASK_NAME = "080_create_service"
BASE_PATH = "/home/developer/Documents/data-disk/k8s-game-rule/tests/game02"
TASK_PATH = os.path.join(BASE_PATH, TASK_NAME)

# Create directory structure
os.makedirs(TASK_PATH, exist_ok=True)

# 1. Create __init__.py
with open(os.path.join(TASK_PATH, "__init__.py"), "w") as f:
    f.write("")

# 2. Create instruction.md
instruction_content = """# Create a Kubernetes ClusterIP Service

## Difficulty Level
Beginner

## Learning Objectives
- Understand what a Kubernetes Service is and why it's needed
- Learn how to create a ClusterIP Service
- Understand how Services use label selectors to route traffic to Pods
- Learn the difference between Service ports and target ports

## Challenge Description
In this task, you will create a Kubernetes Service of type ClusterIP that exposes a deployment within the cluster. ClusterIP is the default Service type and makes your application accessible only within the cluster.

A Service provides a stable endpoint (IP address and DNS name) for accessing a group of Pods, even as Pods are created and destroyed. The Service uses label selectors to determine which Pods to route traffic to.

## Instructions
Follow the provided Kubernetes manifests to complete this task. Deploy your solution to the cluster and ensure all validation tests pass.

## Tips
- Ensure your resources are deployed in the correct namespace
- Use `kubectl get` commands to verify your deployments
- Check the Service endpoints with `kubectl get endpoints`
- Remember to clean up resources after completing the task

## Validation
Run the validation tests to check if your solution is correct:
```bash
pytest --import-mode=importlib --rootdir=. tests/game02/080_create_service/
```
"""

with open(os.path.join(TASK_PATH, "instruction.md"), "w") as f:
    f.write(instruction_content)

# 3. Create session.json
session_data = {
    "variables": {
        "namespace": "test-ns-{{random_number(1,999)}}",
        "service_name": "demo-service-{{random_number(1,100)}}"
    },
    "template_functions": {
        "random_name": "Generates random alphanumeric string",
        "random_number": "Generates random number within range",
        "student_id": "Returns current student ID",
        "base64_encode": "Encodes string to base64"
    }
}

with open(os.path.join(TASK_PATH, "session.json"), "w") as f:
    json.dump(session_data, f, indent=2)

# 4. Create answer.template.yaml
answer_template = """apiVersion: v1
kind: Service
metadata:
  name: {{ service_name }}
  namespace: {{ namespace }}
  labels:
    app: game-task
    task: service-demo
spec:
  type: ClusterIP
  selector:
    app: demo
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
"""

with open(os.path.join(TASK_PATH, "answer.template.yaml"), "w") as f:
    f.write(answer_template)

# 5. Create test_01_setup.py
setup_test = '''"""Setup test for the task."""
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)


def test_setup():
    """Test that the setup is properly configured."""
    # Load session variables
    session_file = Path(__file__).parent / "session.json"
    assert session_file.exists(), "session.json must exist"
    
    with open(session_file) as f:
        session = json.load(f)
    
    # Verify required variables are present
    assert "variables" in session, "session.json must contain 'variables' key"
    assert "namespace" in session["variables"], "namespace variable must be defined"
    assert "service_name" in session["variables"], "service_name variable must be defined"
    
    logging.info(f"Setup variables loaded: {session['variables']}")


if __name__ == "__main__":
    test_setup()
'''

with open(os.path.join(TASK_PATH, "test_01_setup.py"), "w") as f:
    f.write(setup_test)

# 6. Create test_03_answer.py
answer_test = '''"""Deploy answer test for the task."""
import json
import logging
import yaml
from pathlib import Path

logging.basicConfig(level=logging.INFO)


def load_template(filename: str) -> str:
    """Load a template file and render with session variables."""
    template_path = Path(__file__).parent / filename
    assert template_path.exists(), f"{filename} must exist"
    
    with open(template_path) as f:
        template_content = f.read()
    
    # Load session variables
    session_file = Path(__file__).parent / "session.json"
    with open(session_file) as f:
        session = json.load(f)
    
    # Simple variable substitution (replace {{ variable }} with value)
    rendered = template_content
    for key, value in session.get("variables", {}).items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", str(value))
    
    return rendered


def test_deploy_answer():
    """Test deploying the answer."""
    # Load and render the answer template
    answer_yaml = load_template("answer.template.yaml")
    
    # Parse YAML to validate
    try:
        resources = list(yaml.safe_load_all(answer_yaml))
        assert len(resources) > 0, "Answer must contain at least one resource"
        
        # Verify it's a Service
        service = resources[0]
        assert service["kind"] == "Service", "Resource must be a Service"
        assert service["spec"]["type"] == "ClusterIP", "Service type must be ClusterIP"
        
        logging.info(f"Loaded {len(resources)} resource(s)")
        logging.info(f"Service name: {service['metadata']['name']}")
        logging.info(f"Service type: {service['spec']['type']}")
    except yaml.YAMLError as e:
        raise AssertionError(f"Invalid YAML in answer.template.yaml: {e}")
    
    # Create answer.gen.yaml
    gen_path = Path(__file__).parent / "answer.gen.yaml"
    with open(gen_path, "w") as f:
        f.write(answer_yaml)
    
    logging.info("Answer deployed successfully")


if __name__ == "__main__":
    test_deploy_answer()
'''

with open(os.path.join(TASK_PATH, "test_03_answer.py"), "w") as f:
    f.write(answer_test)

# 7. Create test_05_check.py
check_test = '''"""Validation tests for the task."""
import json
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO)


class TestCheck:
    """Validation tests for the answer."""
    
    def load_variables(self):
        """Load session variables."""
        session_file = Path(__file__).parent / "session.json"
        with open(session_file) as f:
            return json.load(f)
    
    def run_kubectl_command(self, command: str) -> str:
        """Run kubectl command and return output."""
        try:
            result = subprocess.run(
                f"kubectl {command}".split(),
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logging.error(f"kubectl command failed: {e.stderr}")
            raise
    
    def test_namespace_exists(self):
        """Test that the namespace exists."""
        session = self.load_variables()
        namespace = session.get("variables", {}).get("namespace", "default")
        
        output = self.run_kubectl_command(f"get namespace {namespace}")
        assert output, f"Namespace {namespace} not found"
        logging.info(f"✓ Namespace {namespace} exists")
    
    def test_service_exists(self):
        """Test that the Service resource exists."""
        session = self.load_variables()
        namespace = session.get("variables", {}).get("namespace", "default")
        service_name = session.get("variables", {}).get("service_name", "demo-service")
        
        output = self.run_kubectl_command(f"get service {service_name} -n {namespace}")
        assert output, f"Service {service_name} not found in namespace {namespace}"
        logging.info(f"✓ Service {service_name} exists in namespace {namespace}")
    
    def test_service_type_is_clusterip(self):
        """Test that the Service type is ClusterIP."""
        session = self.load_variables()
        namespace = session.get("variables", {}).get("namespace", "default")
        service_name = session.get("variables", {}).get("service_name", "demo-service")
        
        output = self.run_kubectl_command(
            f"get service {service_name} -n {namespace} -o jsonpath='{{.spec.type}}'"
        )
        assert output == "ClusterIP", f"Service type should be ClusterIP, got: {output}"
        logging.info(f"✓ Service type is ClusterIP")
    
    def test_service_has_correct_port(self):
        """Test that the Service has port 80 configured."""
        session = self.load_variables()
        namespace = session.get("variables", {}).get("namespace", "default")
        service_name = session.get("variables", {}).get("service_name", "demo-service")
        
        output = self.run_kubectl_command(
            f"get service {service_name} -n {namespace} -o jsonpath='{{.spec.ports[0].port}}'"
        )
        assert output == "80", f"Service port should be 80, got: {output}"
        logging.info(f"✓ Service has port 80 configured")
    
    def test_service_has_selector(self):
        """Test that the Service has the correct selector."""
        session = self.load_variables()
        namespace = session.get("variables", {}).get("namespace", "default")
        service_name = session.get("variables", {}).get("service_name", "demo-service")
        
        output = self.run_kubectl_command(
            f"get service {service_name} -n {namespace} -o jsonpath='{{.spec.selector}}'"
        )
        assert "app" in output, "Service must have 'app' selector"
        logging.info(f"✓ Service has correct selector: {output}")


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
'''

with open(os.path.join(TASK_PATH, "test_05_check.py"), "w") as f:
    f.write(check_test)

# 8. Create test_06_cleanup.py
cleanup_test = '''"""Cleanup test for the task."""
import json
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO)


def cleanup_resources():
    """Clean up all resources created by the task."""
    session_file = Path(__file__).parent / "session.json"
    with open(session_file) as f:
        session = json.load(f)
    
    namespace = session.get("variables", {}).get("namespace", "default")
    
    logging.info(f"Cleaning up namespace: {namespace}")
    
    try:
        subprocess.run(
            f"kubectl delete namespace {namespace} --ignore-not-found=true".split(),
            capture_output=True,
            check=True
        )
        logging.info(f"✓ Successfully deleted namespace {namespace}")
    except subprocess.CalledProcessError as e:
        logging.warning(f"Failed to delete namespace: {e.stderr}")


def test_cleanup():
    """Test cleanup function."""
    cleanup_resources()
    logging.info("Cleanup completed successfully")


if __name__ == "__main__":
    cleanup_resources()
'''

with open(os.path.join(TASK_PATH, "test_06_cleanup.py"), "w") as f:
    f.write(cleanup_test)

print(f"✅ Task '{TASK_NAME}' created successfully!")
print(f"📁 Location: {TASK_PATH}")
print(f"\nCreated files:")
for filename in os.listdir(TASK_PATH):
    print(f"  - {filename}")
