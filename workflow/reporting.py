"""Workflow CSV reporting helpers."""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from agents.config import PATHS


SUMMARY_HEADERS = (
    "recorded_at",
    "workflow_started_at",
    "iteration",
    "task_id",
    "target_topic",
    "difficulty",
    "phase",
    "attempt",
    "status",
    "is_valid",
    "reason",
    "task_directory",
    "artifact_path",
)


def _fallback_reports_root() -> Path:
    game_root = getattr(PATHS, "game_root", None)
    if game_root is not None:
        return Path(game_root).parents[1] / "reports"

    unsuccessful_game_root = getattr(PATHS, "unsuccessful_game_root", None)
    if unsuccessful_game_root is not None:
        return Path(unsuccessful_game_root).parents[1] / "reports"

    unsuccessful_root = getattr(PATHS, "unsuccessful_root", None)
    if unsuccessful_root is not None:
        return Path(unsuccessful_root).parent / "reports"

    return Path.cwd() / "reports"


def reports_root(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir) / "reports"

    pytest_rootdir = getattr(PATHS, "pytest_rootdir", None)
    if pytest_rootdir is not None:
        return Path(pytest_rootdir) / "reports"
    return _fallback_reports_root()


def workflow_phase_summary_csv(base_dir: Path | None = None) -> Path:
    return reports_root(base_dir) / "workflow_phase_summary.csv"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "artifact"


def _relativize(path: Path, base_dir: Path | None = None) -> str:
    root = reports_root(base_dir).parent
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def archive_phase_output(
    *,
    task_id: str,
    phase: str,
    attempt: int | None,
    status: str,
    content: str,
    reports_base_dir: Path | None = None,
) -> str:
    """Persist detailed phase output and return a portable path string."""
    if not content:
        return ""

    task_reports_dir = reports_root(reports_base_dir) / "tasks" / task_id
    task_reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    attempt_suffix = f"attempt_{attempt:02d}_" if attempt is not None else ""
    artifact_path = task_reports_dir / f"{timestamp}_{attempt_suffix}{_slugify(phase)}_{_slugify(status)}.txt"
    artifact_path.write_text(content, encoding="utf-8")
    return _relativize(artifact_path, reports_base_dir)


def append_workflow_phase_summary(
    *,
    workflow_started_at: str,
    iteration: int | str | None,
    task_id: str,
    target_topic: str,
    difficulty: str,
    phase: str,
    attempt: int | None,
    status: str,
    is_valid: bool | None,
    reason: str,
    task_directory: str,
    artifact_path: str = "",
    reports_base_dir: Path | None = None,
) -> Path:
    """Append a single workflow phase row to the CSV summary."""
    csv_path = workflow_phase_summary_csv(reports_base_dir)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()

    row = {
        "recorded_at": _now_iso(),
        "workflow_started_at": workflow_started_at,
        "iteration": "" if iteration is None else str(iteration),
        "task_id": task_id,
        "target_topic": target_topic,
        "difficulty": difficulty,
        "phase": phase,
        "attempt": "" if attempt is None else str(attempt),
        "status": status,
        "is_valid": "" if is_valid is None else str(is_valid),
        "reason": reason,
        "task_directory": task_directory,
        "artifact_path": artifact_path,
    }

    with open(csv_path, "a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return csv_path
