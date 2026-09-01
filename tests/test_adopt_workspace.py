"""Telling a project apart from a folder that merely holds projects.

`git init` run one level too high swallows every repository underneath it
into one. That is worse to undo than anything else this tool does, so it is
the one place that refuses instead of resolving.
"""
import notes_config
import pytest

from conftest import write


@pytest.fixture
def workspace(tmp_path):
    """A plain directory holding two unrelated repositories."""
    root = tmp_path / "workspace"
    for name in ("project-a", "project-b"):
        (root / name / ".git").mkdir(parents=True)
    return root


def test_a_folder_holding_two_repositories_is_a_workspace(workspace):
    assert notes_config.is_workspace(workspace)


def test_a_folder_holding_two_manifests_is_a_workspace(tmp_path):
    """Projects that do not use git still make their parent a workspace."""
    root = tmp_path / "workspace"
    write(root / "project-a" / "pyproject.toml", "[project]\n")
    write(root / "project-b" / "package.json", "{}\n")

    assert notes_config.is_workspace(root)


def test_a_single_repository_is_not_a_workspace(tmp_path):
    root = tmp_path / "solo"
    (root / ".git").mkdir(parents=True)
    write(root / "docs" / "README.md", "# 문서\n")

    assert not notes_config.is_workspace(root)


def test_a_notes_only_folder_is_not_a_workspace(tmp_path):
    """A records repository has no manifest. Requiring one would reject it."""
    root = tmp_path / "기록"
    write(root / "회의록.md", "# 회의록\n")
    write(root / "docs" / "설계.md", "# 설계\n")

    assert not notes_config.is_workspace(root)


def test_one_nested_repository_is_not_enough(tmp_path):
    """A vendored dependency does not make its parent a workspace."""
    root = tmp_path / "project"
    write(root / "pyproject.toml", "[project]\n")
    (root / "vendor" / "thirdparty" / ".git").mkdir(parents=True)

    assert not notes_config.is_workspace(root)


def test_the_repository_own_git_does_not_count(tmp_path):
    """Only *nested* repositories count, never the root's own."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "sub" / ".git").mkdir(parents=True)

    assert not notes_config.is_workspace(root)
