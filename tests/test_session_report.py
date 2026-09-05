"""What a session is told before it starts working.

The goal is that the first response already knows the state of the
repository, so the only thing left for a person is judgement. Two things
must always be in the output: the readiness marker, because the CLAUDE.md
gate keys off it, and the safety summary, because a skill that fails to load
disappears silently and nobody finds out.
"""
import method_sync
import session_report
from conftest import write


def build(root, **kw):
    return session_report.build(root, **kw)


def test_a_ready_marker_carries_the_version(notes_repo, current_version):
    method_sync.sync(notes_repo)

    report = build(notes_repo)

    assert f"[girok] ready v{current_version}" in report.text


def test_no_ready_marker_without_a_snapshot(notes_repo):
    """The CLAUDE.md gate stops work when this marker is absent, so emitting
    it while the snapshot is missing would defeat the gate."""
    report = build(notes_repo)

    assert "[girok] ready" not in report.text
    assert "초기화" in report.text


def test_a_stale_snapshot_is_reported_but_does_not_stop_the_session(notes_repo, downgrade_snapshot):
    method_sync.sync(notes_repo)
    version = notes_repo / "notes" / ".method" / "VERSION"
    downgrade_snapshot(version)

    report = build(notes_repo)

    assert "sync" in report.text
    assert report.ready


def test_the_worker_is_resolved_from_the_git_email_without_asking(notes_repo):
    method_sync.sync(notes_repo)

    report = build(notes_repo, git_email="abc@example.invalid")

    assert "abc" in report.text
    assert not report.needs_worker_answer


def test_an_unknown_email_is_the_one_case_that_asks(notes_repo):
    method_sync.sync(notes_repo)

    report = build(notes_repo, git_email="nobody@example.invalid")

    assert report.needs_worker_answer
    assert "누구" in report.text


def test_the_worker_folders_are_listed_when_asking(notes_repo):
    method_sync.sync(notes_repo)
    write(notes_repo / "notes" / "docs_abc" / "PROGRESS.md", "# abc\n")
    write(notes_repo / "notes" / "docs_xyz" / "PROGRESS.md", "# xyz\n")

    report = build(notes_repo, git_email="nobody@example.invalid")

    assert "abc" in report.text and "xyz" in report.text


def test_the_safety_summary_is_always_present_when_the_module_is_on(notes_repo):
    """Rules delivered only as a lazily loaded skill can silently fail to
    load. The safety ones are injected instead."""
    method_sync.sync(notes_repo)
    write(
        notes_repo / "notes" / "docs" / "SAFETY_GATE.md",
        """
# 안전 게이트

| # | 등급 | 항목 | 확인 방법 | 확인자 | 날짜 | 상태 |
|---|---|---|---|---|---|---|
| 1 | BLOCKER | 정위치 | 실측 | | | OPEN |
| 2 | MOTION | 저속 | 실측 | | | OPEN |
| 3 | LATER | 표시 | 실측 | 김담당 | 2026-08-31 | CLOSED |
""",
    )

    report = build(notes_repo)

    assert "OPEN 2" in report.text
    assert "확인자" in report.text


def test_no_safety_section_when_the_module_is_off(notes_repo):
    (notes_repo / ".claude" / "girok.json").write_text(
        '{"notesDir": "notes", "modules": {"safetyGate": false}}', encoding="utf-8"
    )
    method_sync.sync(notes_repo)

    report = build(notes_repo)

    assert "안전 게이트" not in report.text


def test_the_board_summary_carries_open_risks_and_questions(notes_repo):
    method_sync.sync(notes_repo)
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [활성 위험](#활성-위험)
- [열린 질문](#열린-질문)

---

## 활성 위험

| # | 위험 |
|---|---|
| 1 | 축 간섭 |
| 2 | 통신 끊김 |

## 열린 질문

| # | 질문 |
|---|---|
| 1 | 정본이 무엇인가 |
""",
    )

    report = build(notes_repo)

    assert "활성 위험 2" in report.text
    assert "열린 질문 1" in report.text


def test_a_missing_board_is_said_out_loud(notes_repo):
    method_sync.sync(notes_repo)
    (notes_repo / "notes" / "docs" / "PROGRESS.md").unlink()

    report = build(notes_repo)

    assert "PROGRESS.md" in report.text


def test_the_report_is_short(notes_repo):
    """This goes into every session, so it stays a summary. Detail lives in
    the documents it points at."""
    method_sync.sync(notes_repo)

    report = build(notes_repo, git_email="abc@example.invalid")

    assert len(report.text.encode("utf-8")) < 2000


def test_the_ready_marker_survives_a_missing_plugin(notes_repo, tmp_path):
    """The marker says the rules are in this repository, not that a plugin is
    on this machine. Reading it off the installed plugin made a fully set up
    repository look unsupervised the moment the plugin was absent."""
    method_sync.sync(notes_repo)

    report = build(notes_repo, plugin_root=tmp_path / "no-plugin-here")

    assert report.ready
    assert "[girok] ready v" in report.text
    assert "낡았을 수 있다" not in report.text


def test_a_corrupt_snapshot_does_not_get_a_ready_marker(notes_repo):
    """The gate keys off this marker, so emitting it for a snapshot whose
    stamp is unreadable is worse than emitting nothing: the session reports
    itself supervised on the strength of a file nobody could parse."""
    method_sync.sync(notes_repo)
    version = notes_repo / "notes" / ".method" / "VERSION"
    version.write_text("corrupt data\n", encoding="utf-8")

    report = build(notes_repo)

    assert not report.ready
    assert "[girok] ready" not in report.text
