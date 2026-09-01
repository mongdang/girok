"""Refusing to move, and then moving.

"Clean" is not `git status` being empty — an unpushed commit is fine and a
build artifact nobody tracks is fine. What matters is that every file about
to move is committed, because the restore tag can only hold what was
committed.
"""
import json

import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    write(root / "STATE.md", "# 현황\n")
    write(root / "docs" / "설계.md", "# 설계\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    return root


def _mapping(files):
    return {"files": files, "gitSetup": {}, "backup": None}


def test_an_unresolved_role_blocks_everything(repo):
    mapping = _mapping([
        {"from": "STATE.md", "to": None, "role": "?", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "STATE.md" in str(excinfo.value)


def test_an_uncommitted_target_blocks(repo):
    (repo / "STATE.md").write_text("# 고침\n", encoding="utf-8")
    mapping = _mapping([
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "STATE.md" in str(excinfo.value)


def test_an_untracked_file_outside_the_plan_does_not_block(repo):
    write(repo / "scratch.log", "noise\n")
    mapping = _mapping([
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    notes_adopt.check_preconditions(repo, mapping)


def test_an_untracked_file_inside_the_plan_blocks(repo):
    write(repo / "새문서.md", "# 새\n")
    mapping = _mapping([
        {"from": "새문서.md", "to": "docs/새문서.md", "role": "doc", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "새문서.md" in str(excinfo.value)


def test_a_merge_in_progress_blocks(repo):
    (repo / ".git" / "MERGE_HEAD").write_text("deadbeef\n", encoding="utf-8")
    mapping = _mapping([])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "병합" in str(excinfo.value)


def test_moving_uses_git_so_history_follows(repo):
    mapping = _mapping([
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": notes_adopt.sha1_of(repo / "STATE.md"),
         "bytes": 1, "why": ""},
    ])

    notes_adopt.move_all(repo, mapping)

    assert (repo / "PROGRESS.md").is_file()
    assert not (repo / "STATE.md").exists()
    # move_all only stages the rename — apply commits once, after everything
    # is done — so the test commits here to check what the staged rename
    # will look like in history once that happens.
    notes_adopt.run_git(repo, "commit", "-m", "move")
    log = notes_adopt.run_git(repo, "log", "--follow", "--name-only", "--", "PROGRESS.md")
    assert "STATE.md" in log.stdout


def test_an_already_staged_rename_still_blocks_by_its_old_name(repo):
    notes_adopt.run_git(repo, "mv", "STATE.md", "PROGRESS.md")
    mapping = _mapping([
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "STATE.md" in str(excinfo.value)


def test_content_survives_the_move(repo):
    before = notes_adopt.sha1_of(repo / "docs" / "설계.md")
    mapping = _mapping([
        {"from": "docs/설계.md", "to": "docs/설계.md", "role": "doc", "merge": None,
         "sha1": before, "bytes": 1, "why": ""},
    ])

    notes_adopt.move_all(repo, mapping)

    assert notes_adopt.sha1_of(repo / "docs" / "설계.md") == before


@pytest.mark.parametrize("name,role,style,expected", [
    ("001-first.md", "adr", "adr-prefixed", "ADR-001-first.md"),
    ("ADR-001-first.md", "adr", "numbered", "001-first.md"),
    ("My Design Doc.md", "doc", "numbered", "my-design-doc.md"),
    ("2026-08-31-Backlog.md", "doc", "numbered", "2026-08-31-backlog.md"),
    ("설계 문서.md", "doc", "numbered", "설계-문서.md"),
])
def test_names_are_normalized(name, role, style, expected):
    assert notes_adopt.normalize_name(name, role, style) == expected
