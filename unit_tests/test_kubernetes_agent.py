import subprocess

import agents.kubernetes_agent as kubernetes_agent


class _ProcResult:
    def __init__(self, stdout: str = "", stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr


def test_run_kubectl_command_success(monkeypatch):
    captured = {}

    def fake_run(cmd_list, capture_output, text, check, env):
        captured["cmd_list"] = cmd_list
        captured["env"] = env
        return _ProcResult(stdout="ok")

    monkeypatch.setattr(kubernetes_agent.subprocess, "run", fake_run)

    out = kubernetes_agent.run_kubectl_command("get namespaces -o name")
    assert out == "ok"
    assert captured["cmd_list"][:2] == ["kubectl", "get"]
    assert "KUBECONFIG" in captured["env"]


def test_run_kubectl_command_returns_stderr_on_failure(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd="kubectl get pods",
            stderr="boom",
        )

    monkeypatch.setattr(kubernetes_agent.subprocess, "run", fake_run)
    out = kubernetes_agent.run_kubectl_command("get pods")
    assert out == "boom"


def test_get_kubernetes_agent_builds_agent(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def as_agent(self, **kwargs):
            return type("A", (), {"kwargs": kwargs})()

    monkeypatch.setattr(kubernetes_agent, "OpenAIChatClient", FakeClient)
    monkeypatch.setattr(
        kubernetes_agent,
        "AZURE",
        type("Cfg", (), {"endpoint": "https://example", "deployment_name": "model"})(),
    )

    agent = kubernetes_agent.get_kubernetes_agent()
    assert agent.kwargs["name"] == "KubernetesAgent"
    assert agent.kwargs["tools"][0].__name__ == "run_kubectl_command"
