"""What a PreToolUse hook blocks, and what it only warns about.

Blocking is reserved for two categories: safety, and destroying history.
Everything else warns. A check that stops ordinary work on a false positive
gets switched off, and then it protects nothing.

> These rules only cover what the agent itself runs. A person moving an axis
> from the machine's own console passes through none of this. The hook is an
> aid; it does not replace the safety rules.
"""
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import check_docs
import notes_config

CONFIG_NAME = "girok.json"
# Both spellings stay editable while a worker is unconfirmed: the answer is
# recorded in whichever config file the repository actually has, and the
# pre-rename name is still out there in repositories adopted before it.
CONFIG_NAMES = (CONFIG_NAME, "notes-method.json")

MOTION_PATTERNS = (
    r"--home-all", r"\bhome-?all\b", r"\bhoming\b", r"원점복귀",
    r"\bjog\b", r"\bmove-?abs\b", r"\bmove-?rel\b",
    r"--run-auto", r"\bauto-?test\b", r"실장비",
)
MOTION_RE = re.compile("|".join(MOTION_PATTERNS), re.IGNORECASE)

PUSH_RE = re.compile(r"git\s+push\b")

# Force in every form it comes in. The flags were caught from the start; the
# refspec form – `git push origin +master` – was not, and that is how this
# guard got bypassed on the day it mattered. A guard with a hole only its
# author knows about is worse than no guard: everyone else trusts it.
#
# The `+` counts only at the start of an argument, so a branch named
# `feature+extra` is an ordinary push.
FORCE_FLAG_RE = re.compile(r"git\s+push\b[^\n]*?(?:--force\b|\s-f\b)")
FORCE_REFSPEC_RE = re.compile(r"git\s+push\b[^\n]*?\s\+\S")

# Where one command ends and the next begins. Without this the scan ran from
# `git push` to the end of the line, so `git push origin master && rm -f tmp`
# read as `git push -f` and an ordinary command was blocked. A guard that
# stops work it was never about gets switched off, and then it guards nothing.
SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;\n|&]")


def _push_segments(command: str) -> list[str]:
    return [seg for seg in SEGMENT_SPLIT_RE.split(command or "") if PUSH_RE.search(seg)]

# The way past the guard. Deliberately a reason and not a switch: breaking
# this rule should leave a record, and `=1` leaves none. The reason is echoed
# back into the session, so it lands in the transcript next to the push.
FORCE_OVERRIDE_ENV = "GIROK_FORCE_PUSH_REASON"
FORCE_OVERRIDE_MIN_CHARS = 8


def force_push_in(command: str) -> bool:
    return any(
        FORCE_FLAG_RE.search(segment) or FORCE_REFSPEC_RE.search(segment)
        for segment in _push_segments(command)
    )


def force_push_reason() -> str | None:
    """A reason long enough to be one, or None."""
    reason = (os.environ.get(FORCE_OVERRIDE_ENV) or "").strip()
    return reason if len(reason) >= FORCE_OVERRIDE_MIN_CHARS else None


# The same patterns the linter uses. Two copies of a rule is the problem this
# whole project exists to remove, so there is one definition.
#
# The gate row pattern was in fact copied here, and the copy drifted: the
# linter learned about sub-numbered rows (`3a`) and this one did not, so an
# OPEN `3a` counted as zero open items and motion commands went through.
ABSOLUTE_PATH_RE = check_docs.ABSOLUTE_PATH_RE
GATE_ROW_RE = check_docs.GATE_ROW_RE

GATE_NAME = "SAFETY_GATE.md"


@dataclass
class Decision:
    blocked: bool = False
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


def _paths_in(tool_input: dict) -> list[Path]:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    return [Path(raw)] if raw else []


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _new_text(tool_input: dict) -> str:
    parts = [
        tool_input.get("new_string", ""),
        tool_input.get("content", ""),
    ]
    for edit in tool_input.get("edits", []) or []:
        parts.append(edit.get("new_string", ""))
    return "\n".join(p for p in parts if p)


def _old_text(tool_input: dict) -> str:
    parts = [tool_input.get("old_string", "")]
    for edit in tool_input.get("edits", []) or []:
        parts.append(edit.get("old_string", ""))
    return "\n".join(p for p in parts if p)


def open_gate_items(cfg: notes_config.NotesConfig) -> int:
    """How many gate items are still OPEN.

    Counted from the 상태 column, so an item whose description happens to
    contain the word does not read as open. When the table has no header this
    can recognize, it falls back to scanning the whole line: over-counting
    blocks motion, under-counting lets it through, and only one of those is
    a safe direction to be wrong in.
    """
    gate = cfg.docs_dir / GATE_NAME
    if not gate.is_file():
        return 0
    text = gate.read_text(encoding="utf-8")

    rows = list(check_docs.gate_table_rows(text))
    if rows:
        return sum(1 for row, _ in rows if "OPEN" in row.get("상태", ""))
    return sum(
        1 for line in text.splitlines() if GATE_ROW_RE.match(line) and "OPEN" in line
    )


def _gate_confirmer_filled(tool_input: dict) -> bool:
    """Did this edit fill in the confirmer or date of an existing gate row?

    Adding a new row is normal work. Changing a row that already exists so
    that its confirmer column stops being empty is the agent closing a gate
    item, which it must never do.
    """
    old_rows = [l for l in _old_text(tool_input).splitlines() if GATE_ROW_RE.match(l)]
    new_rows = [l for l in _new_text(tool_input).splitlines() if GATE_ROW_RE.match(l)]
    if not old_rows or not new_rows:
        return False

    def key(row: str) -> str:
        return row.split("|")[1].strip()

    new_by_key = {key(r): r for r in new_rows}
    for old in old_rows:
        new = new_by_key.get(key(old))
        if new is None or new == old:
            continue
        old_cells = [c.strip() for c in old.split("|")]
        new_cells = [c.strip() for c in new.split("|")]
        if len(old_cells) != len(new_cells):
            continue
        # The confirmer and date columns sit between the method and status
        # columns; treat any empty-to-filled transition there as a closure.
        for before, after in zip(old_cells, new_cells):
            if before == "" and after != "":
                return True
    return False


def read_git_email(root: Path) -> str | None:
    """The git identity here, or None.

    A machine with no git on PATH raises rather than returns, and this runs
    inside a PreToolUse hook – every tool call would report a failed check.
    An absent identity is the same situation as an unmatched one, which the
    caller already handles.
    """
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            cwd=root, capture_output=True, text=True,
        )
    except OSError:
        return None
    return result.stdout.strip() or None


def worker_of(cfg: notes_config.NotesConfig, email: str | None) -> str | None:
    """The worker this email belongs to, or None if that is not settled.

    Confirmation is the mapping existing in the config. Defining it that way
    keeps the state checkable at any moment instead of living inside a
    session nobody can inspect afterwards.
    """
    matches = [wid for wid, mail in cfg.workers.items() if mail and mail == email]
    return matches[0] if len(matches) == 1 else None


def _unconfirmed_worker_reason(cfg: notes_config.NotesConfig, email: str | None) -> str:
    folders = sorted(p.name[len("docs_"):] for p in cfg.worker_dirs())
    listed = ", ".join(folders) if folders else "(없음)"
    return (
        f"작업자가 확정되지 않았다 – git user.email `{email or '미설정'}` 이 "
        f"`.claude/{CONFIG_NAME}` 의 workers 에 없다. 잘못된 id 로 기록되면 병합 때 남의 "
        f"기록에 섞인다. 등록된 작업자: {listed}. "
        f'해소: workers 에 `"<본인 id>": "{email or "<본인 git user.email>"}"` 를 추가하면 '
        f"그 순간부터 확정된다 (그 파일과 안전 게이트는 지금도 편집할 수 있다)."
    )


def _is_record(path: Path, cfg: notes_config.NotesConfig) -> bool:
    """Is this a document that becomes part of the record?

    Source files are not: the rule exists so records are not filed under the
    wrong name, and blocking ordinary code edits would spend the rule's
    credibility on something it was never about.
    """
    if path.suffix.lower() != ".md":
        return False
    if any(_under(path, root) for root in cfg.doc_roots()):
        return True
    # Worker folders are matched by name rather than by listing them: the
    # folder for a worker who has not been confirmed yet does not exist, and
    # that is exactly the case this has to catch.
    for parent in [path.parent, *path.parents]:
        if parent.name.startswith("docs_") and parent.parent.resolve() == cfg.notes_dir.resolve():
            return True
    return path.parent.resolve() == cfg.notes_dir.resolve() and any(
        path.match(pattern) for pattern in cfg.root_docs
    )


def decide(
    start: Path | str,
    tool_name: str,
    tool_input: dict,
    git_email: str | None = None,
) -> Decision:
    cfg = notes_config.load(start)
    decision = Decision()
    safety_on = cfg.modules.get("safetyGate", True)

    email = git_email if git_email is not None else read_git_email(cfg.repo_root)
    # Worker confirmation only applies where the methodology was actually
    # adopted – a config file exists. parallel_mode defaults to true, so
    # without this a `git commit` in any folder with no config (a repository
    # that never adopted this, or a session started outside one) was blocked
    # for an "unconfirmed worker" nobody was ever asked to configure.
    worker_unknown = (
        cfg.source is not None and cfg.parallel_mode and worker_of(cfg, email) is None
    )

    if tool_name == "Bash":
        command = tool_input.get("command", "")

        if force_push_in(command):
            reason = force_push_reason()
            if reason is None:
                return Decision(
                    blocked=True,
                    reason=(
                        "force push 금지 – 변경 이력 자체가 결정 기록이라 되돌리기 어렵다. "
                        "이력 정리가 필요하면 트리 불변 커밋(`-s ours` 조상 연결 등)으로 할 것. "
                        f"그래도 해야 한다면 `{FORCE_OVERRIDE_ENV}` 에 이유를 담아 실행할 것 – "
                        f"스위치가 아니라 이유다({FORCE_OVERRIDE_MIN_CHARS}자 이상). 그 이유는 "
                        f"세션에 그대로 남는다"
                    ),
                )
            decision.warnings.append(
                f"force push 를 이유와 함께 허용했다 – \"{reason}\". "
                f"되돌리려면 지워질 커밋을 미리 태그나 브랜치로 붙잡아 둘 것"
            )
            return decision

        if PUSH_RE.search(command):
            for repo in cfg.read_only_repos:
                if re.search(rf"\b{re.escape(repo)}\b", command):
                    return Decision(
                        blocked=True,
                        reason=(
                            f"`{repo}` 는 참고 저장소라 push 금지 – 대조·이식 출처로만 쓴다. "
                            f"고칠 것이 있으면 작업 저장소에 반영하고 ADR·게이트로 기록할 것"
                        ),
                    )

        if safety_on and MOTION_RE.search(command):
            open_items = open_gate_items(cfg)
            if open_items:
                return Decision(
                    blocked=True,
                    reason=(
                        f"{GATE_NAME} 에 OPEN 항목이 {open_items}건 남아 있어 실장비 모션 명령을 "
                        f"실행하지 않는다. 항목은 사람 확인자만 닫을 수 있다 – 확인자가 게이트를 "
                        f"닫은 뒤 다시 시도할 것"
                    ),
                )

        if worker_unknown and re.search(r"git\s+(commit|push)\b", command):
            return Decision(blocked=True, reason=_unconfirmed_worker_reason(cfg, email))
        return decision

    if tool_name not in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        return decision

    for path in _paths_in(tool_input):
        if _under(path, cfg.notes_dir / ".method"):
            return Decision(
                blocked=True,
                reason=(
                    ".method/ 는 플러그인이 생성하는 동결 사본이라 직접 고치지 않는다 "
                    "(고치면 사본이 다시 갈라진다). 개정은 플러그인 원본에서 하고 "
                    "`/notes` 로 sync 할 것"
                ),
            )

        is_gate = path.name == GATE_NAME

        # The config records the answer and the gate carries safety
        # information, so neither may be blocked by a missing answer –
        # otherwise the block has no way out from inside the session.
        if worker_unknown and not is_gate and path.name not in CONFIG_NAMES and _is_record(path, cfg):
            return Decision(blocked=True, reason=_unconfirmed_worker_reason(cfg, email))

        if safety_on and is_gate and _gate_confirmer_filled(tool_input):
            return Decision(
                blocked=True,
                reason=(
                    "게이트 항목의 확인자 칸은 에이전트가 채우지 않는다 – 실장비 검증을 "
                    "대신할 수 없기 때문이다. 사람 담당자가 실명으로 채운다"
                ),
            )

        if cfg.parallel_mode and _under(path, cfg.docs_dir) and not is_gate:
            decision.warnings.append(
                f"병행 기간에 메인 docs/ 는 동결이다 – {path.name} 변경은 자기 "
                f"docs_<id>/ 에 하거나, 기계적 정합화라면 그 사실을 커밋 메시지에 남길 것"
            )

        if path.suffix.lower() == ".md":
            added = _new_text(tool_input)
            removed = _old_text(tool_input)
            new_paths = set(ABSOLUTE_PATH_RE.findall(added)) - set(
                ABSOLUTE_PATH_RE.findall(removed)
            )
            if new_paths:
                decision.warnings.append(
                    f"문서에 로컬 절대경로를 새로 적었다 ({', '.join(sorted(new_paths))}) – "
                    f"머신마다 달라진다. 저장소를 가리킬 땐 저장소 이름만 쓸 것"
                )

    return decision
