"""Kubernetes connectivity checks for workflow startup and quarantine decisions."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

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


@dataclass(frozen=True)
class K8sConfiguration:
    """Resolved Kubernetes connection details from k8s-configure."""

    endpoint: str
    kubeconfig_path: Path


def _k8s_configure_dir() -> Path:
    return PATHS.pytest_rootdir / "k8s-configure"


def _kubeconfig_path(k8s_dir: Path) -> Path:
    return k8s_dir / "config.yaml"


def _extract_kubeconfig_endpoint(kubeconfig_path: Path) -> str:
    try:
        kubeconfig = yaml.safe_load(kubeconfig_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise K8sConnectivityError(
            message=f"Kubernetes preflight failed: unable to parse kubeconfig {kubeconfig_path}",
            output=str(exc),
        ) from exc

    clusters = {
        entry.get("name"): (entry.get("cluster") or {})
        for entry in kubeconfig.get("clusters", [])
        if entry.get("name")
    }
    contexts = {
        entry.get("name"): (entry.get("context") or {})
        for entry in kubeconfig.get("contexts", [])
        if entry.get("name")
    }

    current_context_name = kubeconfig.get("current-context")
    context = contexts.get(current_context_name)
    if context is None and contexts:
        context = next(iter(contexts.values()))

    cluster_name = (context or {}).get("cluster")
    cluster = clusters.get(cluster_name)
    if cluster is None and clusters:
        cluster = next(iter(clusters.values()))

    endpoint = (cluster or {}).get("server", "").strip()
    if not endpoint:
        raise K8sConnectivityError(
            message=(
                f"Kubernetes preflight failed: kubeconfig {kubeconfig_path} "
                "does not define a cluster server"
            )
        )

    return endpoint


def resolve_k8s_configuration() -> K8sConfiguration:
    """Resolve k8s-configure using config.yaml only."""
    k8s_dir = _k8s_configure_dir()
    kubeconfig_path = _kubeconfig_path(k8s_dir)
    if not kubeconfig_path.exists():
        raise K8sConnectivityError(
            message=(
                "Kubernetes preflight failed: missing required kubeconfig file "
                f"{kubeconfig_path}"
            )
        )
    return K8sConfiguration(
        endpoint=_extract_kubeconfig_endpoint(kubeconfig_path),
        kubeconfig_path=kubeconfig_path,
    )


def should_manage_minikube(configuration: K8sConfiguration) -> bool:
    """Whether the workflow should reset/start minikube for this configuration."""
    hostname = urlparse(configuration.endpoint).hostname or ""
    return (
        hostname == "localhost"
        or hostname.startswith("127.")
        or hostname.startswith("192.168.49.")
    )


def run_k8s_preflight_check(timeout_seconds: int = 15) -> str:
    """Verify the configured cluster endpoint and credentials are usable."""
    configuration = resolve_k8s_configuration()
    command = ["kubectl", "--kubeconfig", str(configuration.kubeconfig_path)]
    command.extend(["get", "namespaces", "-o", "name", f"--request-timeout={timeout_seconds}s"])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raise K8sConnectivityError(
            message=(
                f"Kubernetes preflight timed out after {timeout_seconds}s "
                f"against {configuration.endpoint}"
            ),
            command=" ".join(command),
        ) from exc

    output = (result.stdout or "").strip()
    error_output = (result.stderr or "").strip()
    if result.returncode != 0:
        raise K8sConnectivityError(
            message=f"Kubernetes preflight failed against {configuration.endpoint}",
            command=" ".join(command),
            output=error_output or output,
        )

    return output
