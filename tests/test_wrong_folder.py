"""Being launched somewhere that is not a repository.

Claude Code has no repository picker: the folder it was started in is the
subject. Starting it one level too high – in a directory that merely
*contains* repositories – used to resolve the notes folder to whichever
sibling happened to have a `docs/`, i.e. a different project entirely.

Walking *up* from a subfolder is fine and expected. Wandering *down* into a
sibling is not.
"""
import json

import check_docs
import notes_config
import notes_init
import pytest
import session_report


@pytest.fixture
def workspace(tmp_path):
    """A plain directory holding two unrelated repositories."""
    root = tmp_path / "workspace"
    for name in ("project-a", "some-plugin"):
        repo = root / name
        (repo / ".git").mkdir(parents=True)
        (repo / "docs").mkdir(parents=True)
        (repo / "docs" / "README.md").write_text("# 문서\n", encoding="utf-8")
    return root


def test_a_directory_that_only_contains_repositories_is_not_one(workspace):
    cfg = notes_config.load(workspace)

    assert not cfg.is_repository


def test_it_does_not_adopt_a_sibling_repository_as_its_notes_folder(workspace):
    cfg = notes_config.load(workspace)

    assert cfg.notes_dir == workspace


def test_a_repository_is_recognized(workspace):
    cfg = notes_config.load(workspace / "project-a")

    assert cfg.is_repository
    assert cfg.repo_root == workspace / "project-a"


def test_a_subfolder_resolves_up_to_its_repository(workspace):
    deep = workspace / "project-a" / "src" / "nested"
    deep.mkdir(parents=True)

    cfg = notes_config.load(deep)

    assert cfg.repo_root == workspace / "project-a"


def test_initialization_refuses_outside_a_repository(workspace, capsys):
    code = notes_init.main(["--root", str(workspace), "--confirm", workspace.name])

    assert code == 1
    assert not (workspace / ".claude").exists()
    out = capsys.readouterr().out
    assert "저장소" in out


def test_the_session_says_it_is_in_the_wrong_place(workspace):
    """Reporting "the snapshot is missing" here would invite initializing a
    directory that is not a project."""
    report = session_report.build(workspace)

    assert not report.ready
    assert "저장소" in report.text
    assert "초기화" not in report.text


def test_the_linter_says_so_too_instead_of_passing_vacuously(workspace):
    result = check_docs.run(workspace)

    assert not result.ok
    assert any("저장소" in f.message for f in result.failures)


def test_a_configured_directory_is_a_repository_even_without_git(tmp_path):
    """A worktree or an exported checkout may have no .git directory. The
    config is the stronger signal, so it wins."""
    root = tmp_path / "exported"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "girok.json").write_text(
        json.dumps({"notesDir": "notes"}), encoding="utf-8"
    )

    assert notes_config.load(root).is_repository


def test_the_message_offers_both_readings(workspace, capsys):
    """Two different situations produce this: started one level too high, or
    a project that genuinely is not under git yet. The second one has a
    different answer – `git init` – and the methodology depends on git for
    version tracking, merging and the commit-then-push rule, so saying so is
    the useful part."""
    notes_init.main(["--root", str(workspace), "--confirm", workspace.name])

    out = capsys.readouterr().out
    assert "git init" in out
    assert "저장소 폴더" in out


def test_the_session_message_offers_both_readings_too(workspace):
    text = session_report.build(workspace).text

    assert "git init" in text
