"""Listing every document and proposing where it goes.

Rules fill in what they are sure about and leave the rest blank. A blank is
not a failure — it is the handful of files a person or a model has to read,
and `apply` refuses while any remain. Guessing here would be worse than
asking, because a wrong guess arrives as a moved file.
"""
import json

import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def repo(tmp_path):
    """A repository shaped like eq-agent-v3 before adoption."""
    root = tmp_path / "eq-agent-v3"
    (root / ".git").mkdir(parents=True)
    write(root / ".claude" / "girok.json", json.dumps({
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "docRoots": ["docs", "decisions"], "adrStyle": "numbered",
    }))
    write(root / "STATE.md", "# 현황\n")
    write(root / "CLAUDE.md", "# 규칙\n")
    write(root / "AGENTS.md", "# 규칙\n")
    write(root / "THESIS.md", "# 논지\n")
    write(root / "decisions" / "001-first.md", "# 001 첫 결정\n")
    write(root / "decisions" / "README.md", "# 인덱스\n")
    write(root / "docs" / "design" / "2026-08-31-backlog.md", "# 백로그\n")
    write(root / "docs" / "superpowers" / "plans" / "p.md", "# 계획\n")
    write(root / "experiments" / "runs.jsonl", '{"a":1}\n')
    return root


def _by_source(entries):
    return {e.frm: e for e in entries}


def test_it_lists_every_markdown_and_nothing_else(repo):
    found = _by_source(notes_adopt.plan(repo))

    assert "STATE.md" in found
    assert "experiments/runs.jsonl" not in found


def test_the_board_is_recognized(repo):
    assert _by_source(notes_adopt.plan(repo))["STATE.md"].role == "board"


def test_rules_documents_stay_where_tools_read_them(repo):
    found = _by_source(notes_adopt.plan(repo))

    for name in ("CLAUDE.md", "AGENTS.md"):
        assert found[name].role == "rules"
        assert found[name].to is None


def test_another_tools_folder_is_left_alone(repo):
    entry = _by_source(notes_adopt.plan(repo))["docs/superpowers/plans/p.md"]

    assert entry.role == "foreign"
    assert entry.to is None


def test_a_numbered_decision_is_an_adr(repo):
    assert _by_source(notes_adopt.plan(repo))["decisions/001-first.md"].role == "adr"


def test_an_ordinary_document_is_a_doc(repo):
    entry = _by_source(notes_adopt.plan(repo))["docs/design/2026-08-31-backlog.md"]

    assert entry.role == "doc"


def test_what_the_rules_cannot_tell_is_left_blank(repo):
    found = _by_source(notes_adopt.plan(repo))

    assert found["THESIS.md"].role == "?"
    assert found["decisions/README.md"].role == "?"


def test_every_entry_carries_a_hash_of_its_content(repo):
    for entry in notes_adopt.plan(repo):
        assert len(entry.sha1) == 40
        assert entry.bytes > 0


def test_the_mapping_is_written_where_it_can_be_committed(repo):
    notes_adopt.write_mapping(repo, notes_adopt.plan(repo), None)

    data = notes_adopt.read_mapping(repo)
    assert (repo / ".claude" / "girok-adopt.json").is_file()
    assert any(f["from"] == "STATE.md" for f in data["files"])


def test_planning_moves_nothing(repo):
    before = notes_adopt.measure(repo)

    notes_adopt.plan(repo)

    assert notes_adopt.measure(repo) == before
