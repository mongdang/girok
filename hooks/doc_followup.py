"""What happens right after a document is written.

PostToolUse cannot block, so this is feedback and one repair:

- run the linter on the file that was just written, while the reason for
  the edit is still in view;
- rewrite the `최종 수정` stamp from the system clock.

The stamp matters more than it looks. Merges pick the newer copy by that
line, and a stamp written from memory once sent a merge the wrong way - so
it is taken from the clock rather than from whatever the model believed the
time to be.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import check_docs
import notes_config

PUSH_RE = re.compile(r"git\s+push\b")
# A dry run pushes nothing. Reporting it as "the commit is on the remote" is
# the one wrong answer here: it retires the very worry the line exists for.
DRY_RUN_RE = re.compile(r"git\s+push\b[^\n;&|]*?(?:--dry-run\b|\s-n\b)")

# Horizontal whitespace only, deliberately: `\s` also matches a newline, so
# the trailing `\s*$` swallowed the blank line after the stamp and the
# replacement did not put it back. Every refresh deleted a line, and enough
# of them would have run the stamp into whatever followed it.
STAMP_RE = re.compile(
    r"^>[ \t]*최종 수정:[ \t]*[\d-]+[ \t]+[\d:]+[ \t]*·[ \t]*(\S+)[ \t]*$",
    re.M,
)


@dataclass
class Followup:
    messages: list[str] = field(default_factory=list)
    stamped: bool = False


def _is_tracked_document(path: Path, cfg: notes_config.NotesConfig) -> bool:
    if path.suffix.lower() != ".md":
        return False
    if any(_under(path, root) for root in [*cfg.doc_roots(), *cfg.worker_dirs()]):
        return True
    # Root-level documents are matched by name, not by folder: with the
    # notes root at the repository root, "is it under the notes dir" would
    # be true for every markdown file in the tree.
    return path.parent.resolve() == cfg.notes_dir.resolve() and any(
        path.match(pattern) for pattern in cfg.root_docs
    )


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def refresh_stamp(path: Path, now: str | None = None) -> bool:
    """Rewrite an existing stamp, changing one line and nothing else.

    Absent stamps are left absent - only documents that carry one are managed
    this way. This is the only place anything here writes into a document a
    person wrote, so it keeps the file's own line endings: turning a CRLF file
    into LF would make a one-line stamp update appear as a diff across the
    whole file and bury the real change in review.
    """
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")

    match = STAMP_RE.search(text)
    if not match:
        return False

    stamp_time = now or datetime.now().strftime("%Y-%m-%d %H:%M")
    updated = STAMP_RE.sub(f"> 최종 수정: {stamp_time} · {match.group(1)}", text, count=1)
    if updated != text:
        path.write_text(updated, encoding="utf-8", newline=newline)
    return True


def after_command(start: Path | str, command: str, failed: bool = False) -> Followup:
    """Say out loud when a push actually went out.

    The setup this replaced allowlisted `git push` so it needed no approval
    click, and printed a line confirming it. Without the second half,
    "commit then push immediately" is a rule with no feedback - the
    transcript does not show whether the push happened.
    """
    result = Followup()
    command = command or ""
    if not PUSH_RE.search(command) or DRY_RUN_RE.search(command):
        return result
    if failed:
        result.messages.append(
            "git push 실패 - 커밋이 이 머신에만 있다. 원격·인증을 확인하고 다시 push 할 것"
        )
    else:
        result.messages.append("git push 완료 - 커밋이 원격에 올라갔다")
    return result


def after_edit(start: Path | str, path: Path, now: str | None = None) -> Followup:
    cfg = notes_config.load(start)
    result = Followup()

    path = Path(path)
    if not path.is_file() or not _is_tracked_document(path, cfg):
        return result

    result.stamped = refresh_stamp(path, now)

    linted = check_docs.run(cfg.repo_root, targets=[path])
    for problem in linted.failures:
        result.messages.append(f"{problem.path} -> {problem.message}")
    for problem in linted.warnings:
        result.messages.append(f"{problem.path} -> {problem.message}")
    return result
