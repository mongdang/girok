"""Making a folder into a repository as part of adoption.

Refusing until someone runs `git init` themselves turned a one-command fix
into a stop. The interesting part is not the init — it is everything that
must not land in the first commit, and saying out loud what was excluded so
"it is in the backup only" is a written fact rather than a surprise.
"""
import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def bare_project(tmp_path):
    """A code project that never adopted git."""
    root = tmp_path / "legacy"
    write(root / "pyproject.toml", "[project]\n")
    write(root / "STATE.md", "# 현황\n")
    write(root / "__pycache__" / "x.pyc", "junk")
    return root


def test_it_initializes_git(bare_project):
    result = notes_adopt.git_setup(bare_project)

    assert result.init
    assert (bare_project / ".git").is_dir()


def test_build_output_is_ignored(bare_project):
    notes_adopt.git_setup(bare_project)

    text = (bare_project / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in text
    assert "# girok:adopt" in text


def test_secrets_are_ignored_and_named(tmp_path):
    root = tmp_path / "p"
    write(root / "pyproject.toml", "[project]\n")
    write(root / ".env", "TOKEN=abc\n")
    write(root / "deploy.key", "-----BEGIN-----\n")

    result = notes_adopt.git_setup(root)

    assert sorted(result.secrets) == [".env", "deploy.key"]
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in text and "deploy.key" in text


def test_large_files_are_ignored_and_named(tmp_path):
    root = tmp_path / "p"
    write(root / "pyproject.toml", "[project]\n")
    big = root / "model.bin"
    big.write_bytes(b"0" * (notes_adopt.LARGE_BYTES + 1))

    result = notes_adopt.git_setup(root)

    assert result.large == ["model.bin"]


def test_an_existing_gitignore_is_kept(tmp_path):
    root = tmp_path / "p"
    write(root / "pyproject.toml", "[project]\n")
    write(root / ".gitignore", "mine/\n")
    write(root / "__pycache__" / "x.pyc", "junk")

    notes_adopt.git_setup(root)

    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("mine/\n")
    assert "__pycache__/" in text


def test_an_existing_repository_is_left_alone(tmp_path):
    root = tmp_path / "p"
    (root / ".git").mkdir(parents=True)
    write(root / "pyproject.toml", "[project]\n")

    result = notes_adopt.git_setup(root)

    assert not result.init


def test_it_refuses_a_workspace(tmp_path):
    root = tmp_path / "workspace"
    for name in ("a", "b"):
        write(root / name / "pyproject.toml", "[project]\n")

    with pytest.raises(notes_adopt.BackupFailed) as excinfo:
        notes_adopt.git_setup(root)

    assert "워크스페이스" in str(excinfo.value)


def test_a_missing_remote_is_reported_not_fatal(bare_project):
    result = notes_adopt.git_setup(bare_project)

    assert result.remote is None
