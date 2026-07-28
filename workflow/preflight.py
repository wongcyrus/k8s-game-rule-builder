"""Kubernetes connectivity checks for workflow startup and quarantine decisions."""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agents.config import PATHS


@dataclass(frozen=True)
class K8sConnectivityError(RuntimeError):
    """Raised when the workflow cannot reach the configured Kubernetes API."""

    message: str
    command: str = ""
    output: str = ""

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class QuarantinedTaskError(RuntimeError):
    """Raised when a task is quarantined because the Kubernetes environment failed."""

    task_id: str
    quarantine_path: Path
    cause: K8sConnectivityError

    def __str__(self) -> str:
        return (
            f"Task {self.task_id} quarantined due to Kubernetes connectivity failure. "
            f"Quarantine path: {self.quarantine_path}. Cause: {self.cause}"
        )


def _k8s_configure_dir() -> Path:
    return PATHS.pytest_rootdir / "k8s-configure"


def _build_kubeconfig(endpoint: str, cert_path: Path, key_path: Path, ca_path: Path) -> str:
    return f"""apiVersion: v1
kind: Config
clusters:
- name: workflow-cluster
  cluster:
    server: {endpoint}
    certificate-authority: {ca_path}
contexts:
- name: workflow-context
  context:
    cluster: workflow-cluster
    user: workflow-user
current-context: workflow-context
users:
- name: workflow-user
  user:
    client-certificate: {cert_path}
    client-key: {key_path}
"""


def run_k8s_preflight_check(timeout_seconds: int = 15) -> str:
    """Verify the configured cluster endpoint and credentials are usable."""
    k8s_dir = _k8s_configure_dir()
    endpoint_path = k8s_dir / "endpoint.txt"
    cert_path = k8s_dir / "client.crt"
    key_path = k8s_dir / "client.key"
    ca_path = k8s_dir / "ca.crt"

    required_files = {
        "endpoint.txt": endpoint_path,
        "client.crt": cert_path,
        "client.key": key_path,
        "ca.crt": ca_path,
    }
    missing = [name for name, path in required_files.items() if not path.exists()]
    if missing:
        raise K8sConnectivityError(
            message=(
                "Kubernetes preflight failed: missing required k8s-configure files: "
                + ", ".join(missing)
            )
        )

    endpoint = endpoint_path.read_text(encoding="utf-8").strip()
    if not endpoint:
        raise K8sConnectivityError("Kubernetes preflight failed: endpoint.txt is empty")

    command = ["kubectl", "get", "namespaces", "-o", "name", f"--request-timeout={timeout_seconds}s"]
    kubeconfig_contents = _build_kubeconfig(endpoint, cert_path, key_path, ca_path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as temp_config:
        temp_config.write(kubeconfig_contents)
        temp_config_path = Path(temp_config.name)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ, "KUBECONFIG": str(temp_config_path)},
        )
    except subprocess.TimeoutExpired as exc:
        raise K8sConnectivityError(
            message=f"Kubernetes preflight timed out after {timeout_seconds}s against {endpoint}",
            command=" ".join(command),
        ) from exc
    finally:
        temp_config_path.unlink(missing_ok=True)

    output = (result.stdout or "").strip()
    error_output = (result.stderr or "").strip()
    if result.returncode != 0:
        raise K8sConnectivityError(
            message=f"Kubernetes preflight failed against {endpoint}",
            command=" ".join(command),
            output=error_output or output,
        )

    return output
