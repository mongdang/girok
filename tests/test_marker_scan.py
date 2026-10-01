"""Safety marker scanning.

A `SAFETY-STUB` marks a place where a safety judgement (in-position,
interlock, limit) is temporarily allowed to pass. A `VIRTUAL-BYPASS` marks a
branch that only exists for simulated runs. Both must be findable by a
single grep and registered in the gate document, because the gate is the
only record of what is still unverified before the code drives real
hardware.
"""
import pytest

import marker_scan
from conftest import write


GATE_WITH_ONE_ITEM = """
# 실장비 투입 전 안전 게이트

---

## 목차

- [1. 게이트 항목](#1-게이트-항목)

---

## 1. 게이트 항목

| # | 등급 | 항목 | 확인 방법 | 확인자 | 날짜 | 상태 |
|---|---|---|---|---|---|---|
| 1 | BLOCKER | 정위치 판정 스텁 (`Motion.cs` HomeCheck) | 실측 | | | OPEN |
"""


@pytest.fixture
def hardware_repo(notes_repo):
    write(notes_repo / "notes" / "docs" / "SAFETY_GATE.md", GATE_WITH_ONE_ITEM)
    return notes_repo


def test_finds_no_markers_in_a_clean_tree(hardware_repo):
    write(hardware_repo / "src" / "Motion.cs", "public bool HomeCheck() => _sensor.Ok;\n")

    result = marker_scan.run(hardware_repo)

    assert result.markers == []
    assert result.ok


def test_finds_a_safety_stub_and_reports_its_location(hardware_repo):
    write(
        hardware_repo / "src" / "Motion.cs",
        "// SAFETY-STUB 정위치 판정 임시 통과\npublic bool HomeCheck() => true;\n",
    )

    result = marker_scan.run(hardware_repo)

    assert len(result.markers) == 1
    marker = result.markers[0]
    assert marker.kind == "SAFETY-STUB"
    assert marker.line == 1
    assert marker.path.endswith("src/Motion.cs")


def test_finds_a_virtual_bypass(hardware_repo):
    write(
        hardware_repo / "src" / "Io.cs",
        "if (_virtual) // VIRTUAL-BYPASS\n    return true;\n",
    )

    result = marker_scan.run(hardware_repo)

    assert [m.kind for m in result.markers] == ["VIRTUAL-BYPASS"]


def test_a_marker_registered_in_the_gate_is_not_a_failure(hardware_repo):
    write(
        hardware_repo / "src" / "Motion.cs",
        "// SAFETY-STUB\npublic bool HomeCheck() => true;\n",
    )

    result = marker_scan.run(hardware_repo)

    assert result.ok
    assert result.unregistered == []


def test_a_marker_in_a_file_the_gate_never_names_is_reported(hardware_repo):
    write(
        hardware_repo / "src" / "Gripper.cs",
        "// SAFETY-STUB 인터락 무시\npublic bool Safe() => true;\n",
    )

    result = marker_scan.run(hardware_repo)

    assert not result.ok
    assert len(result.unregistered) == 1
    assert "Gripper.cs" in result.unregistered[0].path


def test_marker_spelling_is_exact(hardware_repo):
    """Lowercase or underscored variants are not markers. The whole point is
    that one grep finds every one of them."""
    write(
        hardware_repo / "src" / "Motion.cs",
        "// safety-stub\n// SAFETY_STUB\n// SAFETYSTUB\n",
    )

    result = marker_scan.run(hardware_repo)

    assert result.markers == []


def test_the_notes_folder_itself_is_not_scanned(hardware_repo):
    """The gate document names the markers in prose; that is not code."""
    result = marker_scan.run(hardware_repo)

    assert result.markers == []


def test_build_output_is_not_scanned(hardware_repo):
    for folder in ("bin", "obj", "node_modules", ".git"):
        write(
            hardware_repo / "src" / folder / "Copy.cs",
            "// SAFETY-STUB\n",
        )

    result = marker_scan.run(hardware_repo)

    assert result.markers == []


def test_reports_nothing_when_the_module_is_off(notes_repo):
    """A project with no hardware turns modules.safetyGate off; scanning
    then has no gate to check against and must stay quiet."""
    (notes_repo / ".claude" / "girok.json").write_text(
        '{"notesDir": "notes", "modules": {"safetyGate": false}}', encoding="utf-8"
    )
    write(notes_repo / "src" / "a.cs", "// SAFETY-STUB\n")

    result = marker_scan.run(notes_repo)

    assert result.ok
    assert result.skipped


def test_a_missing_gate_document_is_a_failure_not_silence(notes_repo):
    """Turning the module on without the gate document means every marker is
    unregistered by definition - say so instead of passing."""
    write(notes_repo / "src" / "a.cs", "// SAFETY-STUB\n")

    result = marker_scan.run(notes_repo)

    assert not result.ok
    assert any("SAFETY_GATE" in problem for problem in result.problems)


def test_staged_mode_passes_when_a_new_marker_arrives_with_its_gate_entry(hardware_repo):
    """The commit-time check: a marker and its registration belong in the
    same commit."""
    result = marker_scan.check_staged(
        hardware_repo,
        added_lines={"src/Gripper.cs": ["// SAFETY-STUB 그리퍼 인터락"]},
        changed_paths=["src/Gripper.cs", "notes/docs/SAFETY_GATE.md"],
    )

    assert result.ok


def test_staged_mode_blocks_a_new_marker_with_no_gate_change(hardware_repo):
    result = marker_scan.check_staged(
        hardware_repo,
        added_lines={"src/Gripper.cs": ["// SAFETY-STUB 그리퍼 인터락"]},
        changed_paths=["src/Gripper.cs"],
    )

    assert not result.ok
    assert any("SAFETY-STUB" in problem for problem in result.problems)


def test_staged_mode_ignores_a_commit_that_adds_no_marker(hardware_repo):
    result = marker_scan.check_staged(
        hardware_repo,
        added_lines={"src/Gripper.cs": ["public bool Safe() => _sensor.Ok;"]},
        changed_paths=["src/Gripper.cs"],
    )

    assert result.ok
