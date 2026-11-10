"""Noticing that a teammate has pushed something.

Without this the parallel-work rules have no trigger. The merge order, the
approval, the safety-first sequence - all of it begins with somebody
realizing there is something to merge, and realizing it by remembering to
look is exactly what does not happen.

Everything here is read-only. `git fetch` moves remote-tracking refs and
nothing else; no merge, no checkout, no write to the working tree. What to do
about the finding is a person's decision, and the rules say it is not made
without their approval.

Run as a script it prints the same lines, for asking again mid-session:
session start is one look, and a merge wants a fresh one.
"""
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import notes_config  # noqa: E402

# Long enough for a slow corporate remote, short enough that a session does
# not appear to hang. The SessionStart hook's own timeout is 30s.
FETCH_TIMEOUT_SEC = 12

SAFETY_NAMES = ("SAFETY_GATE.md",)
MAX_DOCUMENTS = 6

# Each branch examined costs a rev-list and a diff. A repository with a long
# tail of stale remote branches would spend the session-start budget walking
# them, so only this many are described - the newest by commit date, which is
# where a teammate's work in progress actually is.
MAX_BRANCHES = 12

# One for-each-ref answers "how far ahead of HEAD" for every remote branch.
# Asking each branch separately was a rev-list per branch, and on a machine
# where a process start takes a second that was most of the scan. The field
# is git 2.41+; an older git rejects the format and each branch is counted
# the old way.
AHEAD_FORMAT = "%(refname) %(ahead-behind:HEAD)"

WORKER_DIR = re.compile(r"(?:^|/)docs_([^/]+)/")

# A fetch that stops to ask for a password never returns: the hook has no
# terminal, and on Windows the credential manager would raise a window
# nobody asked for. Stored credentials still work; missing ones fail fast
# and are reported as a failed fetch.
NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


@dataclass
class Branch:
    name: str
    commits: int
    documents: list[str] = field(default_factory=list)
    touches_safety: bool = False
    workers: list[str] = field(default_factory=list)


@dataclass
class Incoming:
    branches: list[Branch] = field(default_factory=list)
    master_ahead: int = 0
    fetch_failed: bool = False
    remote: str | None = None
    unexamined: int = 0
    mine: str | None = None
    mine_ahead: int = 0

    @property
    def to_merge(self) -> bool:
        return bool(self.branches) or self.master_ahead > 0 or self.unexamined > 0

    @property
    def anything(self) -> bool:
        return self.to_merge or self.mine_ahead > 0


def _git(
    root: Path, *args: str, timeout: int | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    """Run a read-only git command. A missing git is a non-zero result, not
    an exception: this runs at session start and must not take the rest of
    the report down with it."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except OSError:
        return subprocess.CompletedProcess(args=["git", *args], returncode=1, stdout="", stderr="")


def _remote_name(root: Path, configured: str | None) -> str | None:
    names = _git(root, "remote").stdout.split()
    if not names:
        return None
    if configured in names:
        return configured
    return "origin" if "origin" in names else names[0]


def _remote_refs(root: Path, remote: str) -> list[tuple[str, int | None]]:
    """Every branch of the remote, newest first, with how far it is ahead of
    HEAD - or None where this git cannot say in one call.

    The full refname is read and shortened here. `%(refname:short)` turns
    `refs/remotes/origin/HEAD` into plain `origin`, which no `/HEAD` filter
    catches, and the pointer was then reported as one more branch.
    """
    base = ("for-each-ref", "--sort=-committerdate")
    scope = f"refs/remotes/{remote}"
    listed = _git(root, *base, f"--format={AHEAD_FORMAT}", scope)
    if listed.returncode != 0:
        listed = _git(root, *base, "--format=%(refname)", scope)

    refs = []
    for line in listed.stdout.splitlines():
        parts = line.split()
        if not parts or parts[0].endswith("/HEAD"):
            continue
        name = parts[0].removeprefix("refs/remotes/")
        refs.append((name, int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None))
    return refs


def _upstream(root: Path) -> str | None:
    found = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    return (found.stdout.strip() or None) if found.returncode == 0 else None


def scan(
    start: Path | str = ".",
    worker: str | None = None,
    fetch: bool = True,
) -> Incoming:
    cfg = notes_config.load(start)
    root = cfg.repo_root
    result = Incoming()

    if not cfg.is_repository:
        return result

    remote = _remote_name(root, cfg.remote)
    if remote is None:
        return result
    result.remote = remote

    if fetch:
        try:
            fetched = _git(
                root, "fetch", "--quiet", remote,
                timeout=FETCH_TIMEOUT_SEC, env={**os.environ, **NO_PROMPT},
            )
            result.fetch_failed = fetched.returncode != 0
        except (subprocess.TimeoutExpired, OSError):
            result.fetch_failed = True
        if result.fetch_failed:
            # Offline is ordinary. The refs already on disk are still worth
            # comparing, but they may be stale, so nothing is claimed.
            return result

    refs = _remote_refs(root, remote)
    names = [name for name, _ in refs]
    ahead = dict(refs)

    def count(ref: str) -> int:
        known = ahead.get(ref)
        return known if known is not None else _count(root, ref)

    default = next((f"{remote}/{c}" for c in ("master", "main") if f"{remote}/{c}" in names), None)

    # Mine is what this branch tracks, and the branch named after the worker.
    # It is not a teammate's work, but it is not nothing either: commits
    # there that HEAD lacks are what I pushed from the other machine.
    candidates = (_upstream(root), f"{remote}/{worker}" if worker else None)
    mine = [ref for ref in candidates if ref in names and ref != default]
    for ref in mine:
        if count(ref) > result.mine_ahead:
            result.mine, result.mine_ahead = ref, count(ref)

    others = [name for name in names if name not in mine and name != default]
    result.unexamined = max(0, len(others) - MAX_BRANCHES)
    for ref in others[:MAX_BRANCHES]:
        commits = count(ref)
        if commits:
            result.branches.append(_describe(root, ref, commits))

    if default:
        result.master_ahead = count(default)

    return result


def _count(root: Path, ref: str) -> int:
    counted = _git(root, "rev-list", "--count", f"HEAD..{ref}")
    try:
        return int(counted.stdout.strip())
    except ValueError:
        return 0


def _describe(root: Path, ref: str, commits: int) -> Branch:
    branch = Branch(name=ref, commits=commits)

    changed = _git(root, "diff", "--name-only", f"HEAD...{ref}").stdout.split("\n")
    paths = [p.strip() for p in changed if p.strip()]

    branch.touches_safety = any(Path(p).name in SAFETY_NAMES for p in paths)
    branch.documents = [p for p in paths if p.lower().endswith(".md")][:MAX_DOCUMENTS]
    branch.workers = sorted({m.group(1) for p in paths for m in WORKER_DIR.finditer(p)})
    return branch


def summary(result: Incoming) -> list[str]:
    """One or two lines for the session-start block.

    It states what arrived and asks; it does not merge. The rules put the
    approval before the merge, and the safety-related part of the incoming
    work before the rest.
    """
    if result.fetch_failed:
        return [
            f"[주의] `{result.remote}` fetch 실패 - 오프라인이거나 인증 문제다. "
            f"상대 작업자의 새 내용이 있는지 확인하지 못했다"
        ]
    if not result.anything:
        return []

    lines = []
    # First, because pulling it changes everything below: until then every
    # branch that already contains my own commits counts them as new.
    if result.mine_ahead:
        lines.append(
            f"[반입] 내 브랜치 {result.mine} 에 지금 HEAD 에 없는 커밋 {result.mine_ahead}건 - "
            f"다른 PC 에서 올린 작업이면 먼저 pull 할 것"
        )
    for branch in result.branches:
        bits = [f"{branch.name} 새 커밋 {branch.commits}건"]
        if branch.touches_safety:
            bits.append("**안전 게이트 변경 포함 - 이것부터 본다**")
        if branch.workers:
            bits.append("작업자 " + ", ".join(branch.workers) + " 의 기록 변경")
        if branch.documents:
            bits.append("문서: " + ", ".join(branch.documents))
        lines.append("[반입] " + " · ".join(bits))

    if result.master_ahead:
        lines.append(f"[반입] {result.remote} 기본 브랜치가 {result.master_ahead}건 앞서 있다")

    # Said out loud rather than passed over: "nothing arrived" and "I looked
    # at the newest 12 branches" are different statements, and only one of
    # them is true here.
    if result.unexamined:
        lines.append(
            f"[주의] 원격 브랜치가 많아 최근 {MAX_BRANCHES}개만 봤다 "
            f"({result.unexamined}개 미확인) - 오래된 브랜치에 반입분이 있으면 직접 확인할 것"
        )

    if result.to_merge:
        lines.append(
            "병합은 승인 없이 하지 않는다 - 요약을 제시하고 진행 여부를 확인할 것. "
            "미루기로 하면 그 사실을 자기 현황판에 한 줄 남긴다"
        )
    return lines


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    cfg = notes_config.load(".")
    email = _git(cfg.repo_root, "config", "user.email").stdout.strip()
    matches = [wid for wid, mail in cfg.workers.items() if mail and mail == email]

    result = scan(".", worker=matches[0] if len(matches) == 1 else None)
    if result.remote is None:
        print("원격이 없다 - 반입을 확인할 곳이 없다")
    else:
        print("\n".join(summary(result)) or f"반입 없음 - `{result.remote}` 에 가져올 새 커밋이 없다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
