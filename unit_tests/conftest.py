from pathlib import Path
import os
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("K8S_RULE_TESTS_ROOT", "/tmp/k8s-game-rule/tests")
os.environ.setdefault("K8S_RULE_GAME_NAME", "game02")
os.environ.setdefault("K8S_RULE_PYTEST_ROOTDIR", "/tmp/k8s-game-rule")
os.environ.setdefault("K8S_RULE_K8S_DOCS_ROOT", "/tmp/k8s-docs")
os.environ.setdefault("K8S_RULE_UNSUCCESSFUL_ROOT", "/tmp/k8s-game-rule/unsuccessful")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5.3-codex")
