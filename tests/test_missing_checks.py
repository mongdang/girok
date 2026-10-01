"""Rules that were written down but never checked.

Each of these is in the rule text – some since the beginning – and the
linter said nothing about them. A rule nobody checks is a rule that drifts,
which is the failure this whole project is about; finding five of them in
its own linter is the same mistake one level up.
"""
import check_docs
import pytest
from conftest import write

BOARD = """
# 현황판

---

## 목차

- [상태](#상태)

---

## 상태

내용
"""


def run(root):
    return check_docs.run(root)


# --- a document must carry a table of contents -------------------------------
#
# The rule: every docs/*.md and the rule file get a `## 목차` with anchor
# links, ADRs and the archive excepted. The linter printed "목차 없음
# (건너뜀)" and moved on, so the one thing it could enforce, it did not.

def test_a_document_with_no_toc_is_reported(notes_repo):
    body = "\n".join(f"## {i}절\n\n운영 절차 설명 문단입니다.\n" for i in range(1, 40))
    write(notes_repo / "notes" / "docs" / "OPERATIONS.md", f"# 운영\n\n{body}")

    result = run(notes_repo)

    assert any("목차" in w.message for w in result.warnings)
    assert any("OPERATIONS.md" in w.path for w in result.warnings)


def test_an_adr_needs_no_toc(notes_repo):
    """A decision card is short by design; the rule excepts it."""
    write(
        notes_repo / "notes" / "docs" / "decisions" / "ADR-002-second.md",
        "# ADR-002 – 두번째\n\n## 결정\n\n내용\n",
    )
    write(
        notes_repo / "notes" / "docs" / "decisions" / "README.md",
        "# 인덱스\n\n| ID | 상태 |\n|---|---|\n"
        "| [ADR-001](ADR-001-first.md) | accepted |\n"
        "| [ADR-002](ADR-002-second.md) | accepted |\n",
    )

    result = run(notes_repo)

    assert not any("목차" in w.message for w in result.warnings)


def test_a_short_note_is_not_nagged(notes_repo):
    """Demanding a table of contents on a ten-line note would train people
    to ignore the warning."""
    write(notes_repo / "notes" / "docs" / "NOTE.md", "# 메모\n\n한 줄\n")

    result = run(notes_repo)

    assert not any("목차" in w.message for w in result.warnings)


# --- a document must not open with `---` --------------------------------------

def test_a_document_starting_with_a_rule_is_reported(notes_repo):
    """GitHub reads a leading `---` as Jekyll front matter and the page fails
    to render. The rule says so; nothing checked it."""
    write(notes_repo / "notes" / "docs" / "PROGRESS.md", "---\n\n# 현황판\n\n내용\n")

    result = run(notes_repo)

    assert not result.ok
    assert any("front matter" in f.message or "frontmatter" in f.message for f in result.failures)


# --- a closed gate item needs a confirmer and a date -------------------------
#
# This is the one the whole design exists for: an item marked CLOSED with an
# empty confirmer column is an unverified condition that reads as verified.

@pytest.fixture
def gated(notes_repo):
    def _write(rows: str):
        write(
            notes_repo / "notes" / "docs" / "SAFETY_GATE.md",
            "# 안전 게이트\n\n---\n\n## 목차\n\n- [1. 게이트 항목](#1-게이트-항목)\n\n---\n\n"
            "## 1. 게이트 항목\n\n"
            "| # | 등급 | 항목 | 확인 방법 | 확인자 | 날짜 | 상태 |\n"
            "|---|---|---|---|---|---|---|\n" + rows,
        )
    return _write


def test_a_closed_item_without_a_confirmer_is_a_failure(notes_repo, gated):
    gated("| 1 | BLOCKER | 정위치 | 실측 | | | CLOSED |\n")

    result = run(notes_repo)

    assert not result.ok
    assert any("확인자" in f.message for f in result.failures)


def test_a_closed_item_without_a_date_is_a_failure(notes_repo, gated):
    gated("| 1 | BLOCKER | 정위치 | 실측 | 김담당 | | CLOSED |\n")

    result = run(notes_repo)

    assert not result.ok
    assert any("날짜" in f.message for f in result.failures)


def test_a_properly_closed_item_passes(notes_repo, gated):
    gated("| 1 | BLOCKER | 정위치 | 실측 | 김담당 | 2026-08-31 | CLOSED |\n")

    assert run(notes_repo).ok


def test_an_open_item_needs_neither(notes_repo, gated):
    gated("| 1 | BLOCKER | 정위치 | 실측 | | | OPEN |\n")

    assert run(notes_repo).ok


def test_the_check_is_skipped_when_the_module_is_off(notes_repo, gated):
    gated("| 1 | BLOCKER | 정위치 | 실측 | | | CLOSED |\n")
    (notes_repo / ".claude" / "girok.json").write_text(
        '{"notesDir": "notes", "modules": {"safetyGate": false}}', encoding="utf-8"
    )

    assert run(notes_repo).ok


# --- a supersede must point at something -------------------------------------

def test_a_supersede_pointing_nowhere_is_reported(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "decisions" / "ADR-001-first.md",
        "# ADR-001 – 첫 결정\n\n| | |\n|---|---|\n| 상태 | superseded-by-ADR-099 |\n\n## 결정\n\n내용\n",
    )

    result = run(notes_repo)

    assert not result.ok
    assert any("099" in f.message for f in result.failures)


def test_a_supersede_pointing_at_a_real_decision_passes(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "decisions" / "ADR-001-first.md",
        "# ADR-001 – 첫 결정\n\n| | |\n|---|---|\n| 상태 | superseded-by-ADR-002 |\n\n## 결정\n\n내용\n",
    )
    write(
        notes_repo / "notes" / "docs" / "decisions" / "ADR-002-second.md",
        "# ADR-002 – 두번째\n\n## 결정\n\n내용\n",
    )
    write(
        notes_repo / "notes" / "docs" / "decisions" / "README.md",
        "# 인덱스\n\n| ID | 상태 |\n|---|---|\n"
        "| [ADR-001](ADR-001-first.md) | superseded-by-ADR-002 |\n"
        "| [ADR-002](ADR-002-second.md) | accepted |\n",
    )

    assert run(notes_repo).ok


# --- a stray carriage return ------------------------------------------------
#
# Found twice in real documents, both times inside a table cell holding a
# Windows path: the `\r` of `scripts\run-x.ps1` was written as an actual
# carriage return. It splits the line, breaks the table, and is invisible in
# every editor – the only way anyone finds it is a checker that looks.

def test_a_lone_carriage_return_is_reported(notes_repo):
    board = notes_repo / "notes" / "docs" / "PROGRESS.md"
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_bytes(
        "# 현황판\n\n---\n\n## 목차\n\n- [상태](#상태)\n\n---\n\n## 상태\n\n| a | b |\n|---|---|\n| `x\rrun.ps1` | c |\n".encode()
    )

    result = run(notes_repo)

    assert not result.ok
    assert any("캐리지 리턴" in f.message for f in result.failures)


def test_crlf_line_endings_are_not_reported(notes_repo):
    """A CRLF file is normal on Windows and renders fine. Only a CR that is
    not part of a line ending is the defect."""
    board = notes_repo / "notes" / "docs" / "PROGRESS.md"
    board.write_bytes(BOARD.lstrip("\n").replace("\n", "\r\n").encode())

    result = run(notes_repo)

    assert not any("캐리지 리턴" in f.message for f in result.failures)
