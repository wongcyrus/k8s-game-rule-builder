"""Rebuild task idea memory from folder truth, with optional OpenAI inference."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CONTEXT_FILES = (
    "instruction.md",
    "concept.md",
    "session.json",
    "setup.template.yaml",
    "answer.template.yaml",
)


@dataclass
class ReconstructedConcept:
    """Structured reconstruction result for a single uncovered task family."""

    concept: str
    description: str
    tags: list[str]
    variations: list[str]
    reasoning_summary: str

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ReconstructedConcept":
        return cls(
            concept=str(data["concept"]),
            description=str(data["description"]),
            tags=[str(item) for item in data.get("tags", [])],
            variations=[str(item) for item in data.get("variations", [])],
            reasoning_summary=str(data.get("reasoning_summary", "")),
        )

    def model_dump(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "description": self.description,
            "tags": list(self.tags),
            "variations": list(self.variations),
            "reasoning_summary": self.reasoning_summary,
        }


@dataclass(frozen=True)
class FolderTruth:
    successful_task_ids: set[str]
    failed_task_ids: set[str]
    task_dirs_by_id: dict[str, Path]


def iter_task_dirs(root: Path) -> Iterable[Path]:
    """Yield task directories recursively by detecting instruction.md."""
    if not root.exists():
        return
    seen: set[Path] = set()
    for instruction_path in root.rglob("instruction.md"):
        task_dir = instruction_path.parent
        if task_dir not in seen:
            seen.add(task_dir)
            yield task_dir


def collect_task_ids(*roots: Path) -> set[str]:
    task_ids: set[str] = set()
    for root in roots:
        for task_dir in iter_task_dirs(root):
            task_ids.add(task_dir.name)
    return task_ids


def build_task_dir_index(*roots: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for root in roots:
        for task_dir in iter_task_dirs(root):
            index[task_dir.name] = task_dir
    return index


def classify_memories(
    success_ideas: dict[str, dict[str, Any]],
    failure_ideas: dict[str, dict[str, Any]],
    successful_task_ids: set[str],
    failed_task_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    rebuilt_success: dict[str, dict[str, Any]] = {}
    rebuilt_failure: dict[str, dict[str, Any]] = {}
    unresolved: dict[str, dict[str, Any]] = {}

    merged: dict[str, dict[str, Any]] = {}
    merged.update(success_ideas)
    merged.update(failure_ideas)

    for key, value in merged.items():
        variations = set(value.get("variations", []))
        if not variations:
            unresolved[key] = value
            continue

        if variations & failed_task_ids:
            failed_entry = dict(value)
            failed_entry["reason"] = (
                "Rebuilt from folder classification because one or more variations "
                "exist under unsuccessful/"
            )
            rebuilt_failure[key] = failed_entry
            continue

        if variations & successful_task_ids:
            success_entry = dict(value)
            success_entry.pop("reason", None)
            rebuilt_success[key] = success_entry
            continue

        unresolved[key] = value

    return rebuilt_success, rebuilt_failure, unresolved


def _load_ideas(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    ideas = data.get("ideas", {})
    if not isinstance(ideas, dict):
        raise ValueError(f"{path} does not contain an object under 'ideas'")
    return ideas


def _write_ideas(path: Path, ideas: dict[str, dict[str, Any]]) -> None:
    path.write_text(json.dumps({"ideas": ideas}, indent=2) + "\n", encoding="utf-8")


def _default_game_rule_root() -> Path:
    candidates = [
        Path("/home/developer/Documents/data-disk/k8s/k8s-game-platform/k8s-game-rule"),
        Path(__file__).resolve().parents[2] / "k8s" / "k8s-game-platform" / "k8s-game-rule",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not infer k8s-game-rule root. Pass --game-rule-root explicitly.")


def _concept_key(concept: str) -> str:
    return concept.replace(" ", "_").replace("*", "").lower()


def backup_memory_files(project_root: Path, *paths: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = project_root / f"memory-backups-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path in paths:
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def _read_task_context(task_dir: Path, *, max_chars_per_file: int = 6000) -> str:
    lines = [f"TASK_DIR: {task_dir}"]
    for file_name in CONTEXT_FILES:
        path = task_dir / file_name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if len(text) > max_chars_per_file:
            text = text[:max_chars_per_file] + "\n...[truncated]..."
        lines.append(f"\n## {file_name}\n{text}")
    return "\n".join(lines)


def _related_task_candidates(task_id: str, all_task_ids: set[str]) -> list[str]:
    suffix = task_id.split("_", 1)[1] if "_" in task_id else task_id
    tokens = tuple(
        part for part in suffix.split("_")
        if part not in {"basic", "basics", "beginner", "intermediate", "advanced"}
    )
    matches: list[str] = []
    for candidate in sorted(all_task_ids):
        candidate_suffix = candidate.split("_", 1)[1] if "_" in candidate else candidate
        if candidate == task_id:
            continue
        if candidate_suffix == suffix:
            matches.append(candidate)
            continue
        candidate_tokens = tuple(
            part for part in candidate_suffix.split("_")
            if part not in {"basic", "basics", "beginner", "intermediate", "advanced"}
        )
        if tokens and candidate_tokens and candidate_tokens == tokens:
            matches.append(candidate)
    return matches[:12]


def merge_reconstructed_concepts(
    base_success: dict[str, dict[str, Any]],
    base_failure: dict[str, dict[str, Any]],
    inferred: list[ReconstructedConcept],
    folder_truth: FolderTruth,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    merged_success = {key: dict(value) for key, value in base_success.items()}
    merged_failure = {key: dict(value) for key, value in base_failure.items()}
    unresolved: dict[str, dict[str, Any]] = {}

    grouped: dict[str, dict[str, Any]] = {}
    for item in inferred:
        key = _concept_key(item.concept)
        current = grouped.setdefault(
            key,
            {
                "concept": item.concept,
                "description": item.description,
                "variations": [],
                "tags": [],
                "reasoning_summary": item.reasoning_summary,
            },
        )
        current["variations"] = sorted(set(current["variations"]) | set(item.variations))
        current["tags"] = sorted(set(current["tags"]) | set(item.tags))
        if not current.get("description"):
            current["description"] = item.description

    for key, value in grouped.items():
        variations = set(value["variations"])
        if variations & folder_truth.failed_task_ids:
            entry = dict(value)
            entry["reason"] = "Reconstructed by OpenAI agent from task folders under unsuccessful/"
            merged_success.pop(key, None)
            merged_failure[key] = entry
        elif variations & folder_truth.successful_task_ids:
            entry = dict(value)
            entry.pop("reason", None)
            merged_failure.pop(key, None)
            merged_success[key] = entry
        else:
            unresolved[key] = dict(value)

    return merged_success, merged_failure, unresolved


async def infer_missing_concepts(
    missing_task_ids: list[str],
    task_dirs_by_id: dict[str, Path],
    all_task_ids: set[str],
) -> list[ReconstructedConcept]:
    if not missing_task_ids:
        return []

    from pydantic import BaseModel, Field
    from agent_framework.openai import OpenAIChatCompletionClient
    from azure.identity import AzureCliCredential
    from agents.config import AZURE

    class ReconstructionResponse(BaseModel):
        concept: str = Field(description="Canonical concept name for the task family")
        description: str = Field(description="Short concept description")
        tags: list[str] = Field(description="Relevant concept tags")
        variations: list[str] = Field(description="Task IDs that belong to this concept family")
        reasoning_summary: str = Field(description="Short explanation of how the concept was inferred")

    client = OpenAIChatCompletionClient(
        azure_endpoint=AZURE.endpoint,
        model=AZURE.deployment_name,
        credential=AzureCliCredential(),
    )
    agent = client.as_agent(
        name="TaskIdeaMemoryReconstructionAgent",
        instructions=(
            "You reconstruct Kubernetes task idea memory from existing task folders.\n"
            "Infer the canonical concept, short description, tags, and concept family variations.\n"
            "Only include task IDs explicitly provided in the prompt. Never invent new task IDs.\n"
            "Prefer concise, normalized concept names that match the educational Kubernetes feature.\n"
            "If you are unsure about sibling tasks, return only the target task ID."
        ),
    )

    results: list[ReconstructedConcept] = []
    for task_id in missing_task_ids:
        task_dir = task_dirs_by_id[task_id]
        related = _related_task_candidates(task_id, all_task_ids)
        prompt = (
            "Reconstruct a memory entry for the following Kubernetes task folder.\n\n"
            f"TARGET_TASK_ID: {task_id}\n"
            f"ALLOWED_TASK_IDS: {', '.join([task_id, *related])}\n"
            "Return a single reconstructed concept entry.\n"
            "If related task IDs are clearly the same concept family, include them in variations.\n"
            "Otherwise include only the target task ID.\n\n"
            f"{_read_task_context(task_dir)}"
        )
        response = await agent.run(prompt, options={"response_format": ReconstructionResponse})
        if not response.value:
            raise ValueError(f"Agent returned no structured concept for {task_id}")
        results.append(ReconstructedConcept.from_mapping(response.value.model_dump()))
    return results


def _print_summary(
    *,
    success_before: int,
    failure_before: int,
    success_after: int,
    failure_after: int,
    unresolved_count: int,
    missing_task_ids: list[str],
    inferred_count: int,
) -> None:
    print(f"success_before={success_before}")
    print(f"failure_before={failure_before}")
    print(f"success_after={success_after}")
    print(f"failure_after={failure_after}")
    print(f"unresolved={unresolved_count}")
    print(f"missing_task_ids={len(missing_task_ids)}")
    print(f"inferred_concepts={inferred_count}")
    if missing_task_ids:
        print("missing_task_id_list=" + ",".join(missing_task_ids))


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild task idea memory from folder classification.")
    parser.add_argument(
        "--game-rule-root",
        default="",
        help="Path to k8s-game-rule repository. Defaults to the local sibling checkout when found.",
    )
    parser.add_argument(
        "--success-dir",
        action="append",
        default=[],
        help="Success task directory relative to game-rule-root. Repeat for multiple directories.",
    )
    parser.add_argument(
        "--failure-dir",
        action="append",
        default=[],
        help="Failure task directory relative to game-rule-root. Repeat for multiple directories.",
    )
    parser.add_argument(
        "--memory-file",
        default="task_ideas_memory.json",
        help="Success memory filename relative to the builder repo root.",
    )
    parser.add_argument(
        "--failure-memory-file",
        default="task_ideas_failure_memory.json",
        help="Failure memory filename relative to the builder repo root.",
    )
    parser.add_argument(
        "--infer-missing",
        action="store_true",
        help="Use an OpenAI structured-output agent to reconstruct concepts for uncovered current task folders.",
    )
    parser.add_argument(
        "--limit-missing",
        type=int,
        default=0,
        help="Optional cap on how many uncovered task folders to infer.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write rebuilt memories back to disk. Without this flag, print a dry-run summary only.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    game_rule_root = Path(args.game_rule_root).resolve() if args.game_rule_root else _default_game_rule_root()
    success_dirs = args.success_dir or ["tests/game02", "tests/game04"]
    failure_dirs = args.failure_dir or ["unsuccessful"]

    success_roots = [game_rule_root / rel for rel in success_dirs]
    failure_roots = [game_rule_root / rel for rel in failure_dirs]
    success_task_ids = collect_task_ids(*success_roots)
    failure_task_ids = collect_task_ids(*failure_roots)
    task_dirs_by_id = build_task_dir_index(*success_roots, *failure_roots)
    folder_truth = FolderTruth(
        successful_task_ids=success_task_ids,
        failed_task_ids=failure_task_ids,
        task_dirs_by_id=task_dirs_by_id,
    )

    success_path = project_root / args.memory_file
    failure_path = project_root / args.failure_memory_file
    unresolved_path = project_root / "task_ideas_unresolved_memory.json"
    success_ideas = _load_ideas(success_path)
    failure_ideas = _load_ideas(failure_path)

    rebuilt_success, rebuilt_failure, unresolved = classify_memories(
        success_ideas, failure_ideas, success_task_ids, failure_task_ids
    )

    covered_task_ids: set[str] = set()
    for store in (rebuilt_success, rebuilt_failure):
        for value in store.values():
            covered_task_ids.update(value.get("variations", []))

    current_task_ids = success_task_ids | failure_task_ids
    missing_task_ids = sorted(current_task_ids - covered_task_ids)
    if args.limit_missing > 0:
        missing_task_ids = missing_task_ids[: args.limit_missing]

    inferred_concepts: list[ReconstructedConcept] = []
    inferred_unresolved: dict[str, dict[str, Any]] = {}
    if args.infer_missing and missing_task_ids:
        inferred_concepts = asyncio.run(
            infer_missing_concepts(missing_task_ids, task_dirs_by_id, current_task_ids)
        )
        rebuilt_success, rebuilt_failure, inferred_unresolved = merge_reconstructed_concepts(
            rebuilt_success, rebuilt_failure, inferred_concepts, folder_truth
        )
        unresolved.update(inferred_unresolved)

    _print_summary(
        success_before=len(success_ideas),
        failure_before=len(failure_ideas),
        success_after=len(rebuilt_success),
        failure_after=len(rebuilt_failure),
        unresolved_count=len(unresolved),
        missing_task_ids=missing_task_ids,
        inferred_count=len(inferred_concepts),
    )

    if args.apply:
        backup_dir = backup_memory_files(project_root, success_path, failure_path, unresolved_path)
        _write_ideas(success_path, rebuilt_success)
        _write_ideas(failure_path, rebuilt_failure)
        _write_ideas(unresolved_path, unresolved)
        report_path = project_root / "task_ideas_reconstruction_report.json"
        report = {
            "generated_at": datetime.now().isoformat(),
            "game_rule_root": str(game_rule_root),
            "success_dirs": success_dirs,
            "failure_dirs": failure_dirs,
            "backup_dir": str(backup_dir),
            "success_before": len(success_ideas),
            "failure_before": len(failure_ideas),
            "success_after": len(rebuilt_success),
            "failure_after": len(rebuilt_failure),
            "unresolved_after": len(unresolved),
            "missing_task_ids": missing_task_ids,
            "inferred_concepts": [item.model_dump() for item in inferred_concepts],
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"backup_dir={backup_dir}")
        print(f"report_file={report_path}")
        print(f"unresolved_file={unresolved_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
