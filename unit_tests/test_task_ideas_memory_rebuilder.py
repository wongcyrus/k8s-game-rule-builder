from agents.task_ideas_memory_rebuilder import (
    FolderTruth,
    ReconstructedConcept,
    backup_memory_files,
    classify_memories,
    collect_task_ids,
    merge_reconstructed_concepts,
)


def test_classify_memories_prefers_failure_for_unsuccessful_variations():
    success = {
        "alpha": {
            "concept": "Alpha",
            "variations": ["101_alpha", "102_alpha_intermediate", "103_alpha_advanced"],
        }
    }
    failure = {}

    rebuilt_success, rebuilt_failure, unresolved = classify_memories(
        success,
        failure,
        successful_task_ids={"101_alpha", "102_alpha_intermediate", "103_alpha_advanced"},
        failed_task_ids={"102_alpha_intermediate"},
    )

    assert rebuilt_success == {}
    assert "alpha" in rebuilt_failure
    assert "unsuccessful/" in rebuilt_failure["alpha"]["reason"]
    assert unresolved == {}


def test_classify_memories_keeps_success_when_any_variation_is_in_pass_set():
    success = {
        "beta": {
            "concept": "Beta",
            "variations": ["201_beta", "202_beta_intermediate", "203_beta_advanced"],
        }
    }

    rebuilt_success, rebuilt_failure, unresolved = classify_memories(
        success,
        {},
        successful_task_ids={"201_beta"},
        failed_task_ids=set(),
    )

    assert "beta" in rebuilt_success
    assert rebuilt_failure == {}
    assert unresolved == {}


def test_classify_memories_marks_concepts_without_folder_evidence_unresolved():
    merged = {
        "gamma": {
            "concept": "Gamma",
            "variations": ["301_gamma", "302_gamma_intermediate", "303_gamma_advanced"],
        }
    }

    rebuilt_success, rebuilt_failure, unresolved = classify_memories(
        merged,
        {},
        successful_task_ids=set(),
        failed_task_ids=set(),
    )

    assert rebuilt_success == {}
    assert rebuilt_failure == {}
    assert "gamma" in unresolved


def test_collect_task_ids_recurses_through_nested_unsuccessful_layout(tmp_path):
    (tmp_path / "flat_task").mkdir()
    (tmp_path / "flat_task" / "instruction.md").write_text("x", encoding="utf-8")
    (tmp_path / "game02" / "nested_task").mkdir(parents=True)
    (tmp_path / "game02" / "nested_task" / "instruction.md").write_text("x", encoding="utf-8")

    task_ids = collect_task_ids(tmp_path)

    assert task_ids == {"flat_task", "nested_task"}


def test_merge_reconstructed_concepts_routes_by_folder_truth():
    inferred = [
        ReconstructedConcept(
            concept="Priority Classes",
            description="desc",
            tags=["scheduling"],
            variations=["201_priorityclass_non_preempting"],
            reasoning_summary="based on task files",
        ),
        ReconstructedConcept(
            concept="Gateway Filters",
            description="desc",
            tags=["networking"],
            variations=["742_gateway_api_backend_lb_policy_beginner"],
            reasoning_summary="based on task files",
        ),
    ]

    success, failure, unresolved = merge_reconstructed_concepts(
        {},
        {},
        inferred,
        FolderTruth(
            successful_task_ids={"201_priorityclass_non_preempting"},
            failed_task_ids={"742_gateway_api_backend_lb_policy_beginner"},
            task_dirs_by_id={},
        ),
    )

    assert "priority_classes" in success
    assert "gateway_filters" in failure
    assert unresolved == {}


def test_backup_memory_files_copies_existing_inputs(tmp_path):
    success = tmp_path / "task_ideas_memory.json"
    failure = tmp_path / "task_ideas_failure_memory.json"
    success.write_text('{"ideas":{}}', encoding="utf-8")
    failure.write_text('{"ideas":{}}', encoding="utf-8")

    backup_dir = backup_memory_files(tmp_path, success, failure)

    assert backup_dir.exists()
    assert (backup_dir / success.name).exists()
    assert (backup_dir / failure.name).exists()
