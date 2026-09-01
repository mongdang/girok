"""Copying the original before anything touches it.

The whole point of adoption is that files move. The backup is what makes
that reversible, so it runs before `git init`, before the skeleton, before
anything — otherwise it captures a repository girok has already edited and
calling it "the original" is a lie.
"""
import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "eq-agent-v3"
    (root / ".git").mkdir(parents=True)
    write(root / ".git" / "HEAD", "ref: refs/heads/master\n")
    write(root / "STATE.md", "# 현황\n")
    write(root / "docs" / "설계.md", "# 설계\n")
    return root


def test_it_copies_everything_including_git(repo):
    result = notes_adopt.backup(repo, today="20260901")

    assert result.path.name == "eq-agent-v3-girok-backup-20260901"
    assert result.path.parent == repo.parent
    assert (result.path / "STATE.md").is_file()
    assert (result.path / "docs" / "설계.md").is_file()
    assert (result.path / ".git" / "HEAD").is_file()


def test_it_reports_what_it_copied(repo):
    result = notes_adopt.backup(repo, today="20260901")

    files, size = notes_adopt.measure(repo)
    assert result.files == files
    assert result.bytes == size


def test_the_copy_matches_the_original(repo):
    result = notes_adopt.backup(repo, today="20260901")

    assert notes_adopt.measure(result.path) == notes_adopt.measure(repo)


def test_running_twice_does_not_copy_again(repo):
    first = notes_adopt.backup(repo, today="20260901")
    (repo / "STATE.md").write_text("# 바뀐 현황\n", encoding="utf-8")

    second = notes_adopt.backup(repo, today="20260901")

    assert second.skipped
    assert second.path == first.path
    assert (first.path / "STATE.md").read_text(encoding="utf-8") == "# 현황\n"


def test_it_refuses_a_workspace(tmp_path):
    root = tmp_path / "workspace"
    for name in ("a", "b"):
        (root / name / ".git").mkdir(parents=True)

    with pytest.raises(notes_adopt.BackupFailed) as excinfo:
        notes_adopt.backup(root, today="20260901")

    assert "워크스페이스" in str(excinfo.value)


def test_measure_counts_bytes_not_just_files(tmp_path):
    root = tmp_path / "r"
    write(root / "a.md", "12345")
    write(root / "b" / "c.md", "678")

    assert notes_adopt.measure(root) == (2, 8)
