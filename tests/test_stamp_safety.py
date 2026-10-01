"""What the stamp refresh is allowed to touch.

This is the only place the plugin writes into a document a person wrote, so
it gets its own tests. It must change one line and nothing else - including
the parts of a file nobody looks at, like its line endings.
"""
import doc_followup
import pytest
from conftest import write


STAMPED = (
    "# 현황판\n"
    "\n"
    "> 최종 수정: 2020-01-01 00:00 · abc\n"
    "\n"
    "## 진행\n"
    "\n"
    "내용\n"
)


def test_only_the_stamp_line_changes(notes_repo):
    board = write(notes_repo / "notes" / "docs_abc" / "PROGRESS.md", STAMPED)

    doc_followup.refresh_stamp(board, now="2026-08-31 14:05")

    before = STAMPED.splitlines()
    after = board.read_text(encoding="utf-8").splitlines()
    assert len(before) == len(after)
    assert [i for i, (a, b) in enumerate(zip(before, after)) if a != b] == [2]


def test_crlf_line_endings_survive(notes_repo):
    """Rewriting a CRLF file as LF turns a one-line stamp update into a diff
    across the whole file, and buries the real change in review."""
    board = notes_repo / "notes" / "docs_abc" / "PROGRESS.md"
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_bytes(STAMPED.replace("\n", "\r\n").encode("utf-8"))

    doc_followup.refresh_stamp(board, now="2026-08-31 14:05")

    raw = board.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n"), "일부 줄만 LF 로 바뀌었다"


def test_lf_line_endings_stay_lf(notes_repo):
    board = notes_repo / "notes" / "docs_abc" / "PROGRESS.md"
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_bytes(STAMPED.encode("utf-8"))

    doc_followup.refresh_stamp(board, now="2026-08-31 14:05")

    assert b"\r\n" not in board.read_bytes()


def test_a_document_with_no_stamp_is_not_written_at_all(notes_repo):
    board = write(notes_repo / "notes" / "docs" / "PROGRESS.md", "# 현황판\n\n내용\n")
    before = board.stat().st_mtime_ns

    assert doc_followup.refresh_stamp(board, now="2026-08-31 14:05") is False
    assert board.stat().st_mtime_ns == before


def test_an_already_current_stamp_is_not_rewritten(notes_repo):
    board = write(
        notes_repo / "notes" / "docs_abc" / "PROGRESS.md",
        STAMPED.replace("2020-01-01 00:00", "2026-08-31 14:05"),
    )
    before = board.stat().st_mtime_ns

    doc_followup.refresh_stamp(board, now="2026-08-31 14:05")

    assert board.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    "line",
    [
        "> 최종 수정: 2020-01-01 00:00 · abc",
        ">최종 수정: 2020-01-01 00:00 · abc",
    ],
)
def test_the_worker_id_is_never_replaced(notes_repo, line):
    """The stamp says who wrote it. Rewriting that would file the work under
    whoever happened to run the hook."""
    board = write(
        notes_repo / "notes" / "docs_abc" / "PROGRESS.md",
        f"# 현황판\n\n{line}\n\n내용\n",
    )

    doc_followup.refresh_stamp(board, now="2026-08-31 14:05")

    assert "· abc" in board.read_text(encoding="utf-8")
