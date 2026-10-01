"""End-of-session checks.

Three things people forget, in the order they cost: a commit that never got
pushed (the work exists only on one machine), the day's row on the board
(the session leaves no trace), and a document that was left broken.

None of these stop anything. They are reminders at the one moment when
acting on them is still cheap.
"""
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import check_docs
import notes_config

LOG_HEADINGS = ("일자별 작업 로그", "일자별 로그")


@dataclass
class CloseReport:
    messages: list[str] = field(default_factory=list)


def unpushed_count(root: Path) -> int:
    """Commits on the current branch that the remote has not seen.

    A missing upstream returns 0 rather than raising: a branch that was
    never pushed is reported by the push rule itself, and a hook that dies
    here would take the rest of the checks with it.
    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"],
            cwd=root, capture_output=True, text=True,
        )
    except OSError:
        return 0
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _boards(cfg: notes_config.NotesConfig) -> list[Path]:
    return [p for p in cfg.board_paths() if p.is_file()]


def is_today_logged(start: Path | str, today: str | None = None) -> bool:
    cfg = notes_config.load(start)
    stamp = today or date.today().isoformat()
    for board in _boards(cfg):
        text = board.read_text(encoding="utf-8")
        for heading in LOG_HEADINGS:
            m = re.search(rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)", text, re.S | re.M)
            if m and stamp in m.group(1):
                return True
    return False


def check(
    start: Path | str = ".",
    unpushed: int | None = None,
    today_logged: bool | None = None,
) -> CloseReport:
    """`unpushed` and `today_logged` are injectable so tests can state the
    situation instead of building a git history to imply it."""
    cfg = notes_config.load(start)
    report = CloseReport()
    today_logged_flag = today_logged

    pending = unpushed if unpushed is not None else unpushed_count(cfg.repo_root)
    if pending:
        report.messages.append(
            f"미push 커밋 {pending}건 – 커밋과 push 는 한 묶음이다. 지금 자기 브랜치를 push 할 것"
        )

    logged = today_logged_flag if today_logged_flag is not None else is_today_logged(cfg.repo_root)
    if not logged:
        report.messages.append(
            "현황판 일자별 작업 로그에 오늘 행이 없다 – 그날 최종적으로 남은 결과 한 줄을 남길 것"
        )

    linted = check_docs.run(cfg.repo_root)
    for problem in linted.failures:
        report.messages.append(f"{problem.path} -> {problem.message}")
    for problem in linted.warnings:
        report.messages.append(f"{problem.path} -> {problem.message}")

    return report
