"""Proving after the fact that nothing was lost.

Every guarantee this tool makes is a claim until something re-reads the
bytes and says so. A pass here is the only reason to believe the move.
"""
import json

import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def adopted(tmp_path):
    root = tmp_path / "proj"
    write(root / ".claude" / "girok.json", json.dumps({
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "adrStyle": "adr-prefixed",
    }))
    write(root / "STATE.md", "# 현황\n\n돌아간다\n")
    write(root / "decisions" / "001-first.md", "# 001\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    return root


def test_a_clean_adoption_verifies(adopted):
    notes_adopt.apply(adopted, today="20260901")

    result = notes_adopt.verify(adopted)

    assert result.ok, result.failures


def test_content_is_identical_after_adoption(adopted):
    before = notes_adopt.sha1_of(adopted / "STATE.md")

    notes_adopt.apply(adopted, today="20260901")

    assert notes_adopt.sha1_of(adopted / "PROGRESS.md") == before


def test_a_tampered_file_fails_verification(adopted):
    notes_adopt.apply(adopted, today="20260901")
    (adopted / "PROGRESS.md").write_text("# 딴것\n", encoding="utf-8")

    result = notes_adopt.verify(adopted)

    assert not result.ok
    assert any("PROGRESS.md" in f for f in result.failures)


def test_a_deleted_file_fails_verification(adopted):
    notes_adopt.apply(adopted, today="20260901")
    (adopted / "PROGRESS.md").unlink()

    result = notes_adopt.verify(adopted)

    assert not result.ok


def test_the_backup_exists_before_anything_moved(adopted):
    notes_adopt.apply(adopted, today="20260901")

    backup = adopted.parent / f"{adopted.name}-girok-backup-20260901"
    assert (backup / "STATE.md").is_file(), "백업은 이동 전 원본을 담아야 한다"


def test_the_restore_tag_is_written(adopted):
    notes_adopt.apply(adopted, today="20260901")

    tags = notes_adopt.run_git(adopted, "tag").stdout
    assert "girok-adopt-before-20260901" in tags


def test_the_mapping_is_left_for_later(adopted):
    notes_adopt.apply(adopted, today="20260901")

    data = notes_adopt.read_mapping(adopted)
    assert data["backup"]["files"] > 0
    assert any(f["to"] == "PROGRESS.md" for f in data["files"])


def test_apply_does_not_sweep_unrelated_work_into_its_commit(adopted):
    # A pre-existing repository has other in-progress, uncommitted work
    # that has nothing to do with adoption. `apply` must never `git add -A`
    # in that case — only its own scoped changes (.gitignore, moved files).
    write(adopted / "unrelated.txt", "손대지 않은 작업\n")

    notes_adopt.apply(adopted, today="20260901")

    status = notes_adopt.run_git(adopted, "status", "--porcelain", "unrelated.txt").stdout
    assert "unrelated.txt" in status, "무관한 미완성 작업이 커밋에 쓸려 들어가면 안 된다"


def test_destination_collisions_are_blocked_not_auto_resolved(tmp_path):
    root = tmp_path / "proj"
    write(root / ".claude" / "girok.json", json.dumps({
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "adrStyle": "adr-prefixed",
    }))
    write(root / "docs" / "My Notes.md", "# a\n")
    write(root / "docs" / "my-notes.md", "# b\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.apply(root, today="20260901")

    message = str(excinfo.value)
    assert "my-notes.md" in message


def test_verify_ignores_links_broken_before_adoption(adopted):
    write(adopted / "docs" / "이미깨짐.md", "[없는 문서](없는파일.md)\n")
    notes_adopt.run_git(adopted, "add", "-A")
    notes_adopt.run_git(adopted, "commit", "-m", "pre-existing dead link")

    notes_adopt.apply(adopted, today="20260901")

    result = notes_adopt.verify(adopted)

    assert result.ok, result.failures


def test_verify_still_catches_newly_broken_links(adopted):
    notes_adopt.apply(adopted, today="20260901")
    (adopted / "PROGRESS.md").write_text("[깨짐](없는것.md)\n", encoding="utf-8")

    result = notes_adopt.verify(adopted)

    assert not result.ok
    assert any("없는것.md" in f for f in result.failures)


def test_merging_a_document_into_itself_is_blocked(adopted):
    mapping = notes_adopt.read_mapping(adopted) if (adopted / notes_adopt.MAPPING_RELATIVE).is_file() else None
    if mapping is None:
        notes_adopt.write_mapping(adopted, notes_adopt.plan(adopted), None)
        mapping = notes_adopt.read_mapping(adopted)
    for item in mapping["files"]:
        if item["from"] == "decisions/001-first.md":
            item["merge"] = item["from"]
    notes_adopt._write_mapping_payload(adopted, mapping)

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.apply(adopted, today="20260901")

    assert "decisions/001-first.md" in str(excinfo.value)
