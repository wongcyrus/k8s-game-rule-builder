from pathlib import Path
from types import SimpleNamespace

import workflow.preflight as preflight


class _ProcResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_resolve_k8s_configuration_prefers_kubeconfig(tmp_path, monkeypatch):
    k8s_dir = tmp_path / "k8s-configure"
    k8s_dir.mkdir(parents=True)
    (k8s_dir / "config.yaml").write_text(
        """
apiVersion: v1
clusters:
- name: eks
  cluster:
    server: https://example.eks.amazonaws.com
contexts:
- name: ctx
  context:
    cluster: eks
current-context: ctx
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(preflight, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))

    resolved = preflight.resolve_k8s_configuration()

    assert resolved.kubeconfig_path == k8s_dir / "config.yaml"
    assert resolved.endpoint == "https://example.eks.amazonaws.com"


def test_run_k8s_preflight_check_uses_authoritative_kubeconfig(tmp_path, monkeypatch):
    k8s_dir = tmp_path / "k8s-configure"
    k8s_dir.mkdir(parents=True)
    kubeconfig_path = k8s_dir / "config.yaml"
    kubeconfig_path.write_text(
        """
apiVersion: v1
clusters:
- name: eks
  cluster:
    server: https://example.eks.amazonaws.com
contexts:
- name: ctx
  context:
    cluster: eks
current-context: ctx
""".strip(),
        encoding="utf-8",
    )

    calls = []

    def fake_run(cmd, capture_output, text, timeout, env):
        calls.append((cmd, env))
        return _ProcResult(stdout="namespace/default\n")

    monkeypatch.setattr(preflight, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))
    monkeypatch.setattr("subprocess.run", fake_run)

    output = preflight.run_k8s_preflight_check()

    assert output == "namespace/default"
    assert calls[0][0][:3] == ["kubectl", "--kubeconfig", str(kubeconfig_path)]


def test_run_k8s_preflight_check_requires_config_yaml(tmp_path, monkeypatch):
    k8s_dir = tmp_path / "k8s-configure"
    k8s_dir.mkdir(parents=True)

    monkeypatch.setattr(preflight, "PATHS", SimpleNamespace(pytest_rootdir=tmp_path))

    try:
        preflight.run_k8s_preflight_check()
        raise AssertionError("Expected K8sConnectivityError")
    except preflight.K8sConnectivityError as exc:
        assert "missing required kubeconfig file" in str(exc)


def test_should_manage_minikube_uses_kubeconfig_endpoint():
    assert preflight.should_manage_minikube(
        preflight.K8sConfiguration(endpoint="https://example.eks.amazonaws.com", kubeconfig_path=Path("/tmp/config.yaml"))
    ) is False
    assert preflight.should_manage_minikube(
        preflight.K8sConfiguration(endpoint="https://localhost:8443", kubeconfig_path=Path("/tmp/config.yaml"))
    ) is True
