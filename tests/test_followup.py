"""After an edit, and at the end of a session.

PostToolUse cannot block, so everything here is feedback: run the linter on
what was just written, and keep the stamp honest. The stamp is refreshed
from the system clock because a stamp written from memory once made a merge
pick the wrong copy.

Stop checks the two things people forget: a commit that never got pushed,
and the day's row on the board.
"""
import doc_followup
import session_close
from conftest import write


# --- after an edit ----------------------------------------------------------

def test_a_broken_document_comes_back_as_feedback(notes_repo):
    board = notes_repo / "notes" / "docs" / "PROGRESS.md"
    write(board, "# 현황판\n\n---\n\n## 목차\n\n- [없음](#없음)\n\n---\n\n## 있음\n\n내용\n")

    result = doc_followup.after_edit(notes_repo, board)

    assert result.messages
    assert "없음" in " ".join(result.messages)


def test_a_clean_document_produces_no_noise(notes_repo):
    result = doc_followup.after_edit(notes_repo, notes_repo / "notes" / "docs" / "PROGRESS.md")

    assert result.messages == []


def test_a_file_outside_the_notes_tree_is_ignored(notes_repo):
    source = write(notes_repo / "src" / "Motion.cs", "// code\n")

    result = doc_followup.after_edit(notes_repo, source)

    assert result.messages == []


def test_the_stamp_is_rewritten_from_the_clock(notes_repo):
    board = write(
        notes_repo / "notes" / "docs_abc" / "PROGRESS.md",
        """
# 현황판 (abc)

> 최종 수정: 2020-01-01 00:00 · abc

---

## 목차

- [진행](#진행)

---

## 진행

내용
""",
    )

    doc_followup.after_edit(notes_repo, board, now="2026-08-31 14:05")

    assert "> 최종 수정: 2026-08-31 14:05 · abc" in board.read_text(encoding="utf-8")


def test_a_document_without_a_stamp_does_not_get_one(notes_repo):
    """Only the documents that carry a stamp are stamped; adding one to
    every file would put noise into the main docs."""
    board = notes_repo / "notes" / "docs" / "PROGRESS.md"
    before = board.read_text(encoding="utf-8")

    doc_followup.after_edit(notes_repo, board, now="2026-08-31 14:05")

    assert board.read_text(encoding="utf-8") == before


def test_the_stamp_keeps_the_worker_id(notes_repo):
    board = write(
        notes_repo / "notes" / "docs_xyz" / "PROGRESS.md",
        "# 현황판\n\n> 최종 수정: 2020-01-01 00:00 · xyz\n\n내용\n",
    )

    doc_followup.after_edit(notes_repo, board, now="2026-08-31 14:05")

    assert "· xyz" in board.read_text(encoding="utf-8")


# --- end of session ---------------------------------------------------------

def test_unpushed_commits_are_reported(notes_repo):
    result = session_close.check(notes_repo, unpushed=2, today_logged=True)

    assert any("push" in m for m in result.messages)


def test_a_missing_row_for_today_is_reported(notes_repo):
    result = session_close.check(notes_repo, unpushed=0, today_logged=False)

    assert any("일자별" in m for m in result.messages)


def test_a_tidy_session_says_nothing(notes_repo):
    result = session_close.check(notes_repo, unpushed=0, today_logged=True)

    assert result.messages == []


def test_the_linter_runs_once_more_at_the_end(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        "# 현황판\n\n---\n\n## 목차\n\n- [없음](#없음)\n\n---\n\n## 있음\n\n내용\n",
    )

    result = session_close.check(notes_repo, unpushed=0, today_logged=True)

    assert any("없음" in m for m in result.messages)


def test_today_is_detected_from_the_board(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [일자별 작업 로그](#일자별-작업-로그)

---

## 일자별 작업 로그

| 날짜 | 내용 |
|---|---|
| 2026-08-31 | 무언가 함 |
""",
    )

    assert session_close.is_today_logged(notes_repo, today="2026-08-31")
    assert not session_close.is_today_logged(notes_repo, today="2026-09-01")


# --- push notification ------------------------------------------------------
#
# The setup this replaced put `Bash(git push:*)` on the permission allowlist
# and printed a line when a push actually went out. Without the second half,
# "commit then push immediately" is a rule with no feedback: you cannot tell
# from the transcript whether the push happened.

def test_a_push_is_confirmed(notes_repo):
    result = doc_followup.after_command(notes_repo, "git push azure abc")

    assert result.messages
    assert "push" in result.messages[0]


def test_an_ordinary_command_says_nothing(notes_repo):
    assert doc_followup.after_command(notes_repo, "git status").messages == []


def test_a_failed_push_is_not_reported_as_done(notes_repo):
    result = doc_followup.after_command(
        notes_repo, "git push azure abc", failed=True
    )

    assert any("실패" in m for m in result.messages)


def test_a_dry_run_is_not_reported_as_done(notes_repo):
    """A dry run pushes nothing. Saying the commit reached the remote is the
    one wrong answer here – it retires the worry the line exists for."""
    assert doc_followup.after_command(notes_repo, "git push --dry-run origin master").messages == []
    assert doc_followup.after_command(notes_repo, "git push -n origin master").messages == []
