"""Combining two documents without losing a line.

Rewriting them into one clean document reads better and cannot be checked.
Appending reads worse and can: every line of the original is either present
in the result or it is not, and that is a test. Tidying is a later,
reversible job for a person.
"""
import subprocess

import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    write(root / "PROGRESS.md", "# 현황판\n\n## 로컬 실행 경로\n\n돌아간다\n")
    write(root / "STATE.md", "# 상태\n\n## 지금 상태\n\n측정 중\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    return root


def test_every_line_of_the_source_survives(repo):
    original = (repo / "STATE.md").read_text(encoding="utf-8")

    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert notes_adopt.missing_lines(original, result) == []


def test_the_target_keeps_its_own_content(repo):
    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert "## 로컬 실행 경로" in result
    assert "돌아간다" in result


def test_the_source_is_marked_so_it_can_be_traced(repo):
    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert "<!-- girok:adopt 2026-09-01 · 출처 STATE.md -->" in result


def test_the_source_is_removed_with_git(repo):
    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    assert not (repo / "STATE.md").exists()
    listed = notes_adopt.run_git(repo, "ls-files").stdout
    assert "STATE.md" not in listed


def test_nothing_is_reworded(repo):
    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert "## 지금 상태\n\n측정 중\n" in result


def test_missing_lines_reports_what_was_dropped():
    dropped = notes_adopt.missing_lines("가\n나\n다\n", "머리말\n가\n다\n")

    assert dropped == ["나"]


def test_missing_lines_ignores_blank_lines():
    assert notes_adopt.missing_lines("가\n\n\n나\n", "가\n나\n") == []


def test_untracked_source_falls_back_to_plain_delete(repo):
    # Never `git add`-ed, so `git rm` cannot find it in the index — this is
    # the normal, harmless reason `git rm` fails.
    write(repo / "DRAFT.md", "# 초안\n\n버려질 예정\n")

    notes_adopt.merge_into(repo, "DRAFT.md", "PROGRESS.md", today="2026-09-01")

    assert not (repo / "DRAFT.md").exists()
    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert "버려질 예정" in result


def test_tracked_source_blocks_instead_of_silently_deleting(repo, monkeypatch):
    # A tracked source whose `git rm` fails for some other reason (a lock,
    # a permission error, a broken .git) must not be deleted out from under
    # git's index — that would leave the working tree and the index
    # disagreeing about whether the file exists.
    real_run_git = notes_adopt.run_git

    def failing_rm(root, *args):
        if args and args[0] == "rm":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="fatal: unable to lock")
        return real_run_git(root, *args)

    monkeypatch.setattr(notes_adopt, "run_git", failing_rm)

    with pytest.raises(notes_adopt.Blocked):
        notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    assert (repo / "STATE.md").exists()
