"""Moving a repository's existing records into this methodology's layout.

`notes_survey` answers the other half of this question — it proposes a
config that matches whatever the repository already does, so nothing has to
move. This is the opposite direction: the repository moves to the standard
layout. Both are legitimate; which one a repository wants is a person's
call.

Files moving is the whole feature and also its whole risk, so the ordering
is defensive. `backup` runs before anything writes, `plan` writes nothing at
all, and `verify` proves after the fact that every byte survived.

    python notes_adopt.py backup
    python notes_adopt.py plan
    python notes_adopt.py apply --confirm <repo>
    python notes_adopt.py verify
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import notes_config


class BackupFailed(Exception):
    """The safety net is not in place, so nothing may move."""


@dataclass
class BackupResult:
    path: Path
    files: int
    bytes: int
    skipped: bool = False


def _size_map(root: Path) -> dict[str, int]:
    """Every file under `root`, by relative path, with its size.

    The distribution matters as much as the totals — two trees can agree on
    file count and total bytes while disagreeing on which file holds what.
    """
    sizes: dict[str, int] = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            sizes[path.relative_to(root).as_posix()] = path.stat().st_size
    return sizes


def measure(root: Path) -> tuple[int, int]:
    """Every file under `root` and their total size, with nothing skipped.

    Counting is the verification: a copy that matches on both numbers is a
    copy. Excluding anything here would exclude it from the check too.
    """
    sizes = _size_map(root)
    return len(sizes), sum(sizes.values())


def _diff_message(before: dict[str, int], after: dict[str, int]) -> str:
    """Describe how two size maps disagree, for a `BackupFailed` message."""
    missing = sorted(set(before) - set(after))
    differing = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    first = (missing + differing)[0]
    return (
        f"백업이 원본과 다르다 — 빠진 경로 {len(missing)}개, "
        f"크기가 다른 경로 {len(differing)}개, 첫 항목 `{first}`"
    )


def backup(root: Path, today: str | None = None) -> BackupResult:
    """Copy the repository whole, next to itself, before anything writes.

    Nothing is excluded — not `.git`, not build output. An exclusion list is
    a list of things that cannot be restored, and disks are cheap.

    The copy lands at a `.partial` name first and is only renamed to the
    final name once it has been measured against the original. A crash
    mid-copy must not leave a half-copied tree wearing the name that later
    runs (and people) trust as "the finished backup".
    """
    root = Path(root).resolve()
    if notes_config.is_workspace(root):
        raise BackupFailed(
            f"`{root.name}` 는 저장소가 아니라 워크스페이스로 보인다 — "
            f"하위에 프로젝트가 여럿이다. 작업할 저장소 폴더에서 다시 실행할 것"
        )

    stamp = today or date.today().strftime("%Y%m%d")
    target = root.parent / f"{root.name}-girok-backup-{stamp}"
    if target.exists():
        files, size = measure(target)
        return BackupResult(path=target, files=files, bytes=size, skipped=True)

    partial = root.parent / f"{root.name}-girok-backup-{stamp}.partial"
    if partial.exists():
        shutil.rmtree(partial)
        print(f"[백업] 지난 실행이 중간에 실패해 남아있던 {partial.name} 을 지우고 새로 시작한다")

    try:
        shutil.copytree(root, partial, symlinks=True)
    except Exception as exc:
        raise BackupFailed(
            f"백업 복사 중 오류가 났다 — {exc}. {partial.name} 에 중간 상태가 남아있으니 확인할 것"
        ) from exc

    before = _size_map(root)
    after = _size_map(partial)
    if before != after:
        raise BackupFailed(
            f"{_diff_message(before, after)}. {partial.name} 을 지우지 않았으니 확인할 것"
        )

    os.replace(partial, target)
    return BackupResult(path=target, files=len(after), bytes=sum(after.values()))


MAPPING_RELATIVE = Path(".claude") / "girok-adopt.json"

# Read by the tools themselves from the repository root. Moving one does not
# relocate a document, it hides it from the agent that needs it.
ROOT_FIXED = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "RULES.md")

# Folders another tool writes into and reads back by path.
FOREIGN_DIRS = ("docs/superpowers",)

SKIP_DIRS = {
    ".git", ".vs", ".idea", "__pycache__", "node_modules", ".pytest_cache",
    "bin", "obj", "build", "dist", "packages", "target", ".venv", ".method",
}

BOARD_HINTS = ("PROGRESS", "STATE", "STATUS", "현황")
ADR_PREFIXED = re.compile(r"^ADR-(?:\d{3}|\d{6})[-.]")
ADR_NUMBERED = re.compile(r"^\d{3}-")


@dataclass
class Entry:
    frm: str
    role: str
    sha1: str
    bytes: int
    why: str
    to: str | None = None
    merge: str | None = None

    def as_json(self) -> dict:
        return {
            "from": self.frm, "to": self.to, "role": self.role,
            "merge": self.merge, "sha1": self.sha1,
            "bytes": self.bytes, "why": self.why,
        }


def sha1_of(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _markdown(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            found.append(path)
    return found


def _classify(rel: str, cfg, decisions_prefix: str) -> tuple[str, str]:
    """The role this document plays, and why the rules think so.

    Only what the rules are certain about. `?` is the honest answer for the
    rest — it costs a person one read, where a wrong guess costs a moved
    file and a broken link.

    `decisions_prefix` is the decisions folder relative to the *repository
    root*. `cfg.decisions_dir` is an absolute Path and `decisions_relative`
    is relative to the notes folder, so neither compares against `rel`.
    """
    name = Path(rel).name
    if name in ROOT_FIXED and "/" not in rel:
        return "rules", "도구가 저장소 루트에서 읽는 파일"
    if any(rel.startswith(d + "/") for d in FOREIGN_DIRS):
        return "foreign", "다른 도구가 경로로 읽는 폴더"
    if cfg.board and name == cfg.board:
        return "board", "girok.json 의 board"
    decisions = decisions_prefix
    if decisions and rel.startswith(decisions + "/"):
        if ADR_PREFIXED.match(name) or ADR_NUMBERED.match(name):
            return "adr", "결정 기록 폴더 안의 번호 붙은 문서"
        return "?", "결정 기록 폴더 안이지만 ADR 이름 규칙에 안 맞는다"
    if ADR_PREFIXED.match(name) or ADR_NUMBERED.match(name):
        return "adr", "ADR 이름 규칙에 맞는다"
    if "/" not in rel:
        if any(hint in name.upper() or hint in name for hint in BOARD_HINTS):
            return "board", "현황판으로 보이는 이름"
        return "?", "루트에 있는 문서 — 자리를 규칙으로 정할 수 없다"
    return "doc", "일반 문서"


def _destination(entry: Entry, cfg, notes: str) -> str | None:
    """Where this document goes, as a path relative to the repository root.

    `notes` is "" when the notes folder is the repository root itself — the
    `notesDir: "."` layout, which is a supported value and stays put.
    """
    if entry.role in ("rules", "foreign", "skip", "?"):
        return None
    if entry.role == "board":
        return f"{notes}PROGRESS.md"
    if entry.role == "adr":
        return f"{notes}docs/decisions/{Path(entry.frm).name}"
    return f"{notes}docs/{Path(entry.frm).name}"


def _decisions_prefix(root: Path, cfg) -> str:
    """The decisions folder as a path relative to the repository root."""
    try:
        return cfg.decisions_dir.resolve().relative_to(root).as_posix()
    except ValueError:
        return ""


def plan(root: Path) -> list[Entry]:
    """Every markdown document, with a proposed role and destination."""
    root = Path(root).resolve()
    cfg = notes_config.load(root)
    decisions = _decisions_prefix(root, cfg)
    notes_rel = cfg.notes_dir.resolve().relative_to(root).as_posix()
    notes = "" if notes_rel == "." else notes_rel + "/"
    entries = []
    for path in _markdown(root):
        rel = path.relative_to(root).as_posix()
        role, why = _classify(rel, cfg, decisions)
        entry = Entry(
            frm=rel, role=role, sha1=sha1_of(path),
            bytes=path.stat().st_size, why=why,
        )
        entry.to = _destination(entry, cfg, notes)
        entries.append(entry)
    return entries


def write_mapping(root: Path, entries: list[Entry], backup: BackupResult | None) -> Path:
    root = Path(root).resolve()
    target = root / MAPPING_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": date.today().strftime("%Y-%m-%d"),
        "backup": None if backup is None else {
            "path": backup.path.name, "files": backup.files, "bytes": backup.bytes,
        },
        "gitSetup": {},
        "files": [e.as_json() for e in entries],
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return target


def read_mapping(root: Path) -> dict:
    target = Path(root).resolve() / MAPPING_RELATIVE
    return json.loads(target.read_text(encoding="utf-8"))


LARGE_BYTES = 10 * 1024 * 1024

# Build output and caches. Committing these is not dangerous, just noise
# that makes every later diff unreadable.
JUNK_PATTERNS = (
    "__pycache__/", "*.pyc", "node_modules/", "build/", "dist/",
    ".venv/", ".pytest_cache/", "bin/", "obj/",
)

# Names that usually hold a credential. Ignoring one is cheap; committing
# one is a rotation. The prefixes end in "." so a document like
# `secrets-policy.md` does not fall in — only `secrets.<ext>` does.
SECRET_NAMES = (".env",)
SECRET_SUFFIXES = (".key", ".pem", ".p12", ".pfx")
SECRET_PREFIXES = ("credentials.", "secrets.", ".env.")


@dataclass
class GitSetup:
    init: bool = False
    gitignore_added: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)
    large: list[str] = field(default_factory=list)
    already_tracked: list[str] = field(default_factory=list)
    remote: str | None = None


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )


def _looks_secret(name: str) -> bool:
    lowered = name.lower()
    if lowered.endswith(".md"):
        # Markdown is this methodology's own subject matter, never a secret.
        return False
    return (
        lowered in SECRET_NAMES
        or lowered.endswith(SECRET_SUFFIXES)
        or lowered.startswith(SECRET_PREFIXES)
    )


def _remote_of(root: Path) -> str | None:
    result = run_git(root, "remote")
    if result.returncode != 0:
        return None
    return (result.stdout.split() or [None])[0]


def _tracked_files(root: Path) -> set[str]:
    result = run_git(root, "ls-files")
    if result.returncode != 0:
        return set()
    return set(result.stdout.splitlines())


def _files_under(root: Path):
    """Every file under `root`, `.git` pruned before descending into it.

    `.git` holds the object database — on a repository with real history
    that is most of the tree, and `git_setup` has no business reading it.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        here = Path(dirpath)
        for name in sorted(filenames):
            yield here / name


def git_setup(root: Path) -> GitSetup:
    """Make this folder a repository, and keep the wrong things out of it.

    Everything here resolves rather than refuses, except a workspace: a
    `git init` one level too high swallows the repositories underneath, and
    that is not a thing to fix afterwards.

    This computes and returns; it does not print. `main()` is the only
    place in this module that owns stdout, so a caller reads
    `result.already_tracked` and reports it — telling the person that
    `.gitignore` cannot undo a commit that already happened.
    """
    root = Path(root).resolve()
    if notes_config.is_workspace(root):
        raise BackupFailed(
            f"`{root.name}` 는 저장소가 아니라 워크스페이스로 보인다 — "
            f"여기서 git init 을 하면 하위 저장소를 통째로 삼킨다"
        )

    setup = GitSetup()
    if not (root / ".git").exists():
        run_git(root, "init")
        setup.init = True

    tracked = _tracked_files(root)
    for path in _files_under(root):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if _looks_secret(path.name):
            (setup.already_tracked if rel in tracked else setup.secrets).append(rel)
        elif path.stat().st_size > LARGE_BYTES:
            (setup.already_tracked if rel in tracked else setup.large).append(rel)

    wanted = list(JUNK_PATTERNS) + setup.secrets + setup.large + setup.already_tracked
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    present = {line.strip() for line in existing.splitlines()}
    missing = [w for w in wanted if w not in present]
    if missing:
        stamp = date.today().strftime("%Y-%m-%d")
        block = f"\n# girok:adopt {stamp}\n" + "\n".join(missing) + "\n"
        text = existing if existing.endswith("\n") or not existing else existing + "\n"
        gitignore.write_text(text + block, encoding="utf-8", newline="\n")
        setup.gitignore_added = missing

    setup.remote = _remote_of(root)
    return setup


class Blocked(Exception):
    """A precondition failed, so nothing moved."""


def _porcelain(root: Path) -> dict[str, str]:
    """Every path git has something to say about, mapped to its status code.

    `-c core.quotepath=false` keeps a Korean (or any non-ASCII) path
    readable instead of C-escaped, so it still matches a mapping entry.

    A rename (`R  old -> new`) records under both names: someone may have
    run `git mv` by hand before this ever looks, and the mapping's `from`
    still names the old path — only recording the new one would let that
    file slip past the gate and die later, inside `move_all`, on a git
    error nobody can read.

    `--untracked-files=all` asks git to list files inside a never-tracked
    directory individually. Without it git folds the whole directory into
    one `?? dir/` line, so a planned document living inside it has no entry
    here at all and reads as clean.
    """
    result = run_git(
        root, "-c", "core.quotepath=false",
        "status", "--porcelain", "--untracked-files=all",
    )
    states = {}
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code, rel = line[:2], line[3:].strip().strip('"')
        if " -> " in rel:
            old, rel = rel.split(" -> ", 1)
            states[old] = code
        states[rel] = code
    return states


def check_preconditions(root: Path, mapping: dict) -> None:
    """Refuse while anything about to move is not safely committed.

    The bar is not an empty `git status`. An unpushed commit is fine and so
    is untracked noise nobody plans to touch; what cannot be allowed is a
    file that is about to move while the restore tag has no copy of it.
    """
    root = Path(root).resolve()
    git_dir = root / ".git"
    for marker in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD"):
        if (git_dir / marker).exists():
            raise Blocked(
                "병합·리베이스가 끝나지 않았다 — 반쯤 합쳐진 파일을 옮길 수는 없다. "
                "먼저 마무리할 것"
            )

    unresolved = [f["from"] for f in mapping["files"] if f["role"] == "?"]
    if unresolved:
        listed = ", ".join(unresolved[:5])
        raise Blocked(
            f"자리가 안 정해진 문서가 {len(unresolved)}개 있다 — {listed}. "
            f"role 을 채운 뒤 다시 실행할 것"
        )

    states = _porcelain(root)
    dirty = []
    for item in mapping["files"]:
        code = states.get(item["from"])
        if code is None:
            continue
        dirty.append(f"{item['from']} ({code.strip() or '??'})")
    if dirty:
        listed = ", ".join(dirty[:5])
        raise Blocked(
            f"옮길 문서 {len(dirty)}개가 커밋되지 않았다 — {listed}. "
            f"복원 태그는 커밋된 것만 담으므로 먼저 커밋할 것"
        )


def normalize_name(name: str, role: str, adr_style: str) -> str:
    """A file name that sorts and reads the same everywhere.

    Korean names are kept as they are: transliterating them would trade a
    name that means something for one that does not.
    """
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    number = None
    match = ADR_PREFIXED.match(name) or ADR_NUMBERED.match(name)
    if role == "adr" and match:
        digits = re.search(r"\d+", match.group(0))
        number = digits.group(0) if digits else None
        stem = stem[match.end():]

    stem = re.sub(r"[\s_]+", "-", stem.strip())
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    stem = "".join(c.lower() if c.isascii() else c for c in stem)

    if role == "adr" and number:
        prefix = f"ADR-{number}" if adr_style == "adr-prefixed" else number
        stem = f"{prefix}-{stem}"
    return f"{stem}.{suffix}" if suffix else stem


def move_all(root: Path, mapping: dict) -> list[tuple[str, str]]:
    """Move every planned document with `git mv`, so history follows.

    This only stages the renames. The move alone leaves links between
    documents broken — merging and link rewriting still have to happen —
    so committing here would bury that half-finished state in history
    permanently. `apply` commits once, after everything is done.
    """
    root = Path(root).resolve()
    moved = []
    for item in mapping["files"]:
        target = item.get("to")
        if not target or target == item["from"]:
            continue
        destination = root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = run_git(root, "mv", item["from"], target)
        if result.returncode != 0:
            raise Blocked(
                f"`{item['from']}` 를 옮기지 못했다 — {result.stderr.strip()}"
            )
        moved.append((item["from"], target))
    return moved


def missing_lines(original: str, result: str) -> list[str]:
    """Lines of `original` that do not appear in `result`.

    This is the whole argument for appending rather than rewriting: a
    rewrite cannot be checked this way, so a dropped sentence is invisible.
    Blank lines carry nothing and are ignored.
    """
    present = {line.strip() for line in result.splitlines()}
    return [
        line.strip() for line in original.splitlines()
        if line.strip() and line.strip() not in present
    ]


def merge_into(root: Path, source: str, target: str, today: str | None = None) -> None:
    """Append `source` to `target` verbatim, then drop `source`.

    Not a word is changed. Summarizing or reflowing here would be nicer to
    read and impossible to verify, and "nothing is lost" was the whole
    requirement.
    """
    root = Path(root).resolve()
    src, dst = root / source, root / target
    stamp = today or date.today().strftime("%Y-%m-%d")

    body = src.read_text(encoding="utf-8")
    head = dst.read_text(encoding="utf-8") if dst.is_file() else ""
    if head and not head.endswith("\n"):
        head += "\n"

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        f"{head}\n<!-- girok:adopt {stamp} · 출처 {source} -->\n{body}",
        encoding="utf-8", newline="\n",
    )

    result = run_git(root, "rm", "-q", "--", source)
    if result.returncode != 0:
        if source in _tracked_files(root):
            # git knows this file and refused to drop it (lock, permission,
            # a broken .git) — its content is already appended into `target`,
            # so deleting it now would desync the index from the working
            # tree. Stop and let a person sort out git's state.
            raise Blocked(
                f"`{source}` 를 git에서 지우지 못했다 — {result.stderr.strip()}\n"
                f"내용은 이미 `{target}` 에 이어붙었으니, `{source}` 상태를 확인한 뒤 직접 정리할 것"
            )
        # Never tracked, so git has nothing to lose track of — its content
        # is already in `target`, so a plain filesystem delete is safe.
        src.unlink(missing_ok=True)


# `[text](` / `![alt](` — only the opening. The destination itself is
# hand-scanned by `_parse_dest` because it may be wrapped in `<...>`, hold a
# literal space, or nest one level of parens: shapes no single character
# class captures without either missing them or truncating them.
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(")
# Reference-style definitions `[label]: path` — destinations here are never
# angle-wrapped or spaced in practice, so a plain character class is enough.
REFERENCE_LINK = re.compile(r"(^\s*\[[^\]]+\]:\s+)([^\s#]+)((?:#\S*)?)", re.MULTILINE)
FENCE = re.compile(r"^\s*(```|~~~)")
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.IGNORECASE)
# `<img src="...">` / `<a href='...'>`. The quotes bound the value, so
# unlike a bare markdown destination there is nothing to hand-scan here.
HTML_ATTR = re.compile(r'((?:src|href)=)(["\'])([^"\']*)\2', re.IGNORECASE)


def _outside_code(text: str):
    """Yield (line, is_code) so rewriting can skip fenced blocks.

    A shell command in a code block that happens to name a moved file is
    documentation of what someone typed, not a reference to follow.
    """
    fenced = False
    for line in text.split("\n"):
        if FENCE.match(line):
            fenced = not fenced
            yield line, True
            continue
        yield line, fenced


def _parse_dest(text: str, pos: int):
    """Parse a link destination starting at `text[pos]`, right after `](`.

    Returns `(dest, anchor, title, angled, end)` — `end` is the index just
    past the closing `)`. Returns `None` if no closing `)` is found; a
    destination this can't close is one it can't vouch for either, so the
    caller must not report it as a link at all, let alone a broken one.
    """
    angled = False
    if pos < len(text) and text[pos] == "<":
        close = text.find(">", pos + 1)
        if close == -1:
            return None
        angled = True
        dest = text[pos + 1:close]
        scan_from = close + 1
    else:
        dest = None
        scan_from = pos

    # Find the ')' that closes the whole link, allowing one level of
    # nested parens in a bare (unangled) destination such as `file(1).md`.
    depth = 0
    i = scan_from
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        i += 1
    else:
        return None
    end = i + 1
    body = text[scan_from:i]

    title_match = re.search(r'\s+"[^"]*"$', body)
    title = title_match.group(0) if title_match else ""
    rest = body[:title_match.start()] if title_match else body

    if angled:
        anchor = rest
    else:
        hash_idx = rest.find("#")
        if hash_idx == -1:
            dest, anchor = rest, ""
        else:
            dest, anchor = rest[:hash_idx], rest[hash_idx:]

    return dest, anchor, title, angled, end


def _iter_inline_links(line: str):
    """Find every `[text](dest)` / `![alt](dest)` in a line.

    Yields `(start, end, opening, dest, anchor, title, angled)` so a
    caller can replace `line[start:end]`. A destination `_parse_dest`
    cannot close is skipped rather than guessed at.
    """
    pos = 0
    while True:
        match = INLINE_LINK.search(line, pos)
        if match is None:
            return
        parsed = _parse_dest(line, match.end())
        if parsed is None:
            pos = match.end()
            continue
        dest, anchor, title, angled, end = parsed
        yield match.start(), end, match.group(0), dest, anchor, title, angled
        pos = end


def _retarget(doc_rel: str, link: str, moves: dict[str, str]) -> str | None:
    """The new relative link, or None if this one does not point at a move."""
    if EXTERNAL.match(link):
        return None
    here = Path(doc_rel).parent
    try:
        target = (here / link).as_posix()
        target = Path(os.path.normpath(target)).as_posix()
    except ValueError:
        return None
    moved_to = moves.get(target)
    if moved_to is None:
        return None
    return os.path.relpath(moved_to, here.as_posix() or ".").replace("\\", "/")


def _rewrite_inline_links(line: str, doc_rel: str, moves: dict[str, str]) -> tuple[str, int]:
    """Rewrite every `[text](dest)` / `![alt](dest)` in a line."""
    changed = 0
    out = []
    pos = 0
    for start, end, opening, dest, anchor, title, angled in _iter_inline_links(line):
        out.append(line[pos:start])
        new_dest = _retarget(doc_rel, dest, moves)
        if new_dest is None:
            out.append(line[start:end])
        else:
            body = f"<{new_dest}>" if angled else new_dest
            out.append(f"{opening}{body}{anchor}{title})")
            changed += 1
        pos = end
    out.append(line[pos:])
    return "".join(out), changed


def _rewrite_html_attrs(line: str, doc_rel: str, moves: dict[str, str]) -> tuple[str, int]:
    """Rewrite `src="..."` / `href='...'` in embedded HTML."""
    changed = 0

    def swap(match):
        nonlocal changed
        new = _retarget(doc_rel, match.group(3), moves)
        if new is None:
            return match.group(0)
        changed += 1
        return f"{match.group(1)}{match.group(2)}{new}{match.group(2)}"

    return HTML_ATTR.sub(swap, line), changed


def rewrite_links(root: Path, moves: list[tuple[str, str]]) -> int:
    """Point every relative link at where its document went."""
    root = Path(root).resolve()
    table = dict(moves)
    changed = 0

    for path in _markdown(root):
        doc_rel = path.relative_to(root).as_posix()
        # A document that itself moved is already at its new path.
        original = path.read_text(encoding="utf-8")
        lines = []
        for line, is_code in _outside_code(original):
            if is_code:
                lines.append(line)
                continue

            line, n = _rewrite_inline_links(line, doc_rel, table)
            changed += n

            def swap_reference(match, doc=doc_rel):
                nonlocal changed
                new = _retarget(doc, match.group(2), table)
                if new is None:
                    return match.group(0)
                changed += 1
                return f"{match.group(1)}{new}{match.group(3)}"

            line = REFERENCE_LINK.sub(swap_reference, line)
            line, n = _rewrite_html_attrs(line, doc_rel, table)
            changed += n
            lines.append(line)

        updated = "\n".join(lines)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
    return changed


def broken_links(root: Path) -> list[tuple[str, str]]:
    """Relative links that point at nothing.

    A destination `_parse_dest` could not close is skipped, not reported —
    a false "broken" kills the signal `verify` depends on.
    """
    root = Path(root).resolve()
    broken = []
    for path in _markdown(root):
        doc_rel = path.relative_to(root).as_posix()
        here = Path(doc_rel).parent
        for line, is_code in _outside_code(path.read_text(encoding="utf-8")):
            if is_code:
                continue
            dests = [dest for _, _, _, dest, _, _, _ in _iter_inline_links(line)]
            dests += [match.group(3) for match in HTML_ATTR.finditer(line)]
            for link in dests:
                if EXTERNAL.match(link):
                    continue
                target = Path(os.path.normpath((here / link).as_posix()))
                if not (root / target).exists():
                    broken.append((doc_rel, link))
    return broken


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["backup", "plan"])
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    if args.command == "plan":
        entries = plan(args.root)
        write_mapping(args.root, entries, None)
        unknown = [e for e in entries if e.role == "?"]
        for entry in entries:
            arrow = entry.to or "제자리"
            print(f"[{entry.role:>7}] {entry.frm} → {arrow}  ({entry.why})")
        print(f"문서 {len(entries)}개 — 판단 필요 {len(unknown)}개")
        return 0

    try:
        result = backup(args.root)
    except BackupFailed as exc:
        print(f"[중단] {exc}")
        return 1

    verb = "이미 있음" if result.skipped else "생성"
    print(f"[백업/{verb}] {result.path.name} — {result.files:,}개 파일 / {result.bytes:,}바이트")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
