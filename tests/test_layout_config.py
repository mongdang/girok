"""Repository layouts other than the default one.

The first repository this was built for keeps its notes in a subfolder with
`docs/PROGRESS.md` and `docs/decisions/ADR-NNN-slug.md`. The second one
keeps `STATE.md` and `decisions/NNN-slug.md` at the repository root and
cites decisions by bare number.

Renaming 52 decision files to fit the plugin would cost more than it
returns – citations spread past the documents – so the layout is
configuration, not an assumption. A methodology that only supports the
repository it was extracted from is a copy with extra steps.
"""
import json

import check_docs
import marker_scan
import notes_config
import pytest
from conftest import write


@pytest.fixture
def flat_repo(tmp_path):
    """The second layout: notes at the repository root, numbered decisions."""
    root = tmp_path / "research"
    write(
        root / ".claude" / "girok.json",
        json.dumps(
            {
                "notesDir": ".",
                "board": "STATE.md",
                "decisionsDir": "decisions",
                "docRoots": ["docs", "decisions"],
                "rootDocs": ["*.md"],
                "rulesDocs": ["CLAUDE.md", "METHOD.md"],
                "adrStyle": "numbered",
                "parallelMode": False,
                "modules": {"safetyGate": False},
            }
        ),
    )
    write(
        root / "STATE.md",
        """
# 지금 상태

---

## 목차

- [한 줄](#한-줄)

---

## 한 줄

측정 중
""",
    )
    write(root / "METHOD.md", "# 방법\n\n절차임\n")
    write(
        root / "decisions" / "README.md",
        """
# 결정 인덱스

| ID | 상태 | 결정 |
|---|---|---|
| [001](001-first.md) | accepted | 첫 결정 |
""",
    )
    write(root / "decisions" / "001-first.md", "# 001 – 첫 결정\n\n내용\n")
    return root


def test_the_board_name_comes_from_the_config(flat_repo):
    cfg = notes_config.load(flat_repo)

    assert cfg.board == "STATE.md"
    assert cfg.size_limit_bytes("STATE.md") is not None
    assert cfg.size_limit_bytes("PROGRESS.md") is None


def test_rules_documents_get_the_rules_budget(flat_repo):
    cfg = notes_config.load(flat_repo)

    assert cfg.size_limit_bytes("METHOD.md") == 20_000


def test_it_lints_root_documents_and_the_configured_doc_roots(flat_repo):
    result = check_docs.run(flat_repo)

    assert result.ok
    assert "STATE.md" in result.checked
    assert "METHOD.md" in result.checked
    assert "decisions/001-first.md" in result.checked


def test_root_documents_are_not_scanned_recursively(flat_repo):
    """The notes root is the repository root here, so recursing would drag
    in every README in the source tree."""
    write(flat_repo / "model" / "README.md", "# 모델\n\n## 목차\n\n- [없음](#없음)\n")

    result = check_docs.run(flat_repo)

    assert result.ok


def test_a_broken_anchor_in_a_root_document_is_still_caught(flat_repo):
    write(
        flat_repo / "STATE.md",
        "# 지금 상태\n\n---\n\n## 목차\n\n- [없음](#없음)\n\n---\n\n## 있음\n\n내용\n",
    )

    result = check_docs.run(flat_repo)

    assert not result.ok
    assert any("STATE.md" in f.path for f in result.failures)


def test_numbered_decisions_are_recognized(flat_repo):
    write(flat_repo / "decisions" / "002-second.md", "# 002 – 두번째\n\n내용\n")

    result = check_docs.run(flat_repo)

    assert not result.ok
    assert any("002" in f.message for f in result.failures)


def test_a_numbered_decision_listed_in_the_index_passes(flat_repo):
    write(flat_repo / "decisions" / "002-second.md", "# 002 – 두번째\n\n내용\n")
    write(
        flat_repo / "decisions" / "README.md",
        """
# 결정 인덱스

| ID | 상태 | 결정 |
|---|---|---|
| [001](001-first.md) | accepted | 첫 결정 |
| [002](002-second.md) | accepted | 두번째 |
""",
    )

    result = check_docs.run(flat_repo)

    assert result.ok


def test_bare_numbers_in_prose_are_not_treated_as_citations(flat_repo):
    """With numbered decisions, any figure in the text looks like an ID.
    Chasing those would bury the real findings, so only explicit forms
    count."""
    write(
        flat_repo / "STATE.md",
        """
# 지금 상태

---

## 목차

- [한 줄](#한-줄)

---

## 한 줄

정확도 999 건, 재현율 042 였음
""",
    )

    result = check_docs.run(flat_repo)

    assert result.ok


def test_an_explicit_citation_of_a_missing_decision_is_caught(flat_repo):
    write(
        flat_repo / "STATE.md",
        """
# 지금 상태

---

## 목차

- [한 줄](#한-줄)

---

## 한 줄

배경은 `decisions/099` 참고
""",
    )

    result = check_docs.run(flat_repo)

    assert not result.ok
    assert any("099" in f.message for f in result.failures)


def test_marker_scan_still_sees_code_when_notes_live_at_the_root(flat_repo):
    """With notesDir '.', excluding the notes tree would exclude the whole
    repository and the scan would always find nothing."""
    write(flat_repo / "agent" / "control.py", "# SAFETY-STUB\n")
    (flat_repo / ".claude" / "girok.json").write_text(
        json.dumps(
            {
                "notesDir": ".",
                "board": "STATE.md",
                "decisionsDir": "decisions",
                "docRoots": ["docs", "decisions"],
                "modules": {"safetyGate": True},
            }
        ),
        encoding="utf-8",
    )

    result = marker_scan.run(flat_repo)

    assert len(result.markers) == 1
    assert "agent/control.py" in result.markers[0].path


def test_a_foreign_numbered_decision_is_not_chased(flat_repo):
    """`eq-agent`의 decisions/051 cites a decision in another repository; the
    linter cannot verify it and must not report it as dead."""
    write(
        flat_repo / "STATE.md",
        """
# 지금 상태

---

## 목차

- [한 줄](#한-줄)

---

## 한 줄

배경은 `eq-agent`의 decisions/051 참고
""",
    )

    result = check_docs.run(flat_repo)

    assert result.ok, [f.message for f in result.failures]


def test_skip_dirs_from_the_config_are_left_alone(flat_repo):
    """Frozen process artifacts (imported plan transcripts, generated
    histories) predate the rules; linting them buries the real findings."""
    write(flat_repo / "docs" / "superpowers" / "old-plan.md", "# 계획\n\n배경은 `decisions/099` 참고\n")
    config = flat_repo / ".claude" / "girok.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    data["skipDirs"] = ["superpowers"]
    config.write_text(json.dumps(data), encoding="utf-8")

    result = check_docs.run(flat_repo)

    assert result.ok, [f.message for f in result.failures]


def test_the_toc_threshold_can_be_raised_per_repository(flat_repo):
    """A repository whose own rule caps documents at 8KB should not be nagged
    for a table of contents on every 3KB note."""
    body = "\n".join(f"## {i}절\n\n짧은 설명 문단.\n" for i in range(1, 40))
    write(flat_repo / "docs" / "OPERATIONS.md", f"# 운영\n\n{body}")
    config = flat_repo / ".claude" / "girok.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    data["limits"] = {"tocMinKB": 100}
    config.write_text(json.dumps(data), encoding="utf-8")

    result = check_docs.run(flat_repo)

    assert not any("목차" in w.message for w in result.warnings)


def test_the_pre_rename_config_filename_still_works(tmp_path):
    """Repositories adopted before the girok rename carry
    `.claude/notes-method.json`. Refusing to read it would turn a rename
    into a breaking change for every one of them."""
    root = tmp_path / "old-adopter"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "notes-method.json").write_text(
        '{"notesDir": ".", "board": "STATE.md"}', encoding="utf-8"
    )

    cfg = notes_config.load(root)

    assert cfg.source is not None
    assert cfg.board == "STATE.md"


def test_the_new_config_filename_wins_over_the_legacy_one(tmp_path):
    root = tmp_path / "renamed"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "girok.json").write_text('{"board": "NEW.md"}', encoding="utf-8")
    (root / ".claude" / "notes-method.json").write_text('{"board": "OLD.md"}', encoding="utf-8")

    assert notes_config.load(root).board == "NEW.md"


def test_a_half_edited_config_falls_back_instead_of_crashing(tmp_path):
    """A key present but empty is a config somebody was in the middle of
    editing. An empty `docRoots` left `docs_dir` indexing an empty tuple, so
    every check died with an IndexError rather than reporting anything."""
    root = tmp_path / "halfedited"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "girok.json").write_text(
        '{"docRoots": [], "rootDocs": [], "rulesDocs": [], "board": "", "remote": null}',
        encoding="utf-8",
    )

    cfg = notes_config.load(root)

    assert cfg.doc_roots_relative == notes_config.DEFAULT_DOC_ROOTS
    assert cfg.board == notes_config.DEFAULT_BOARD
    assert cfg.remote == "origin"
    assert cfg.docs_dir.name == "docs"
    assert check_docs.run(root) is not None


def test_the_default_layout_still_works(notes_repo):
    """The original repository's layout must keep working untouched."""
    cfg = notes_config.load(notes_repo)

    assert cfg.board == "PROGRESS.md"
    assert cfg.decisions_dir.name == "decisions"
    assert check_docs.run(notes_repo).ok
