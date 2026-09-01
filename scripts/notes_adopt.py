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
from urllib.parse import unquote

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

# The safety gate, opened by this exact name under the docs folder by
# `check_docs`, `marker_scan` and the gate hook.
GATE_NAME = "SAFETY_GATE.md"

# Every name girok's own code looks up literally rather than by search.
# Normalizing one does not rename a document, it switches off whatever reads
# it — a `safety-gate.md` reads as "no gate", which reads as "nothing OPEN",
# which lets a real motion command through. Anything added here has to be a
# name some tool opens directly.
FIXED_NAMES = ROOT_FIXED + (GATE_NAME,)

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
        # `sha1After` is the hash `apply` leaves behind once link rewriting
        # has run. `plan` cannot know it, and `verify` needs it: a document
        # whose links were repointed is no longer byte-identical to its
        # original, and checking it against `sha1` would call a correct
        # adoption a failure.
        return {
            "from": self.frm, "to": self.to, "role": self.role,
            "merge": self.merge, "sha1": self.sha1, "sha1After": None,
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


def _classify(rel: str, cfg, decisions_prefix: str, workers: tuple = ()) -> tuple[str, str]:
    """The role this document plays, and why the rules think so.

    Only what the rules are certain about. `?` is the honest answer for the
    rest — it costs a person one read, where a wrong guess costs a moved
    file and a broken link.

    `decisions_prefix` is the decisions folder relative to the *repository
    root*. `cfg.decisions_dir` is an absolute Path and `decisions_relative`
    is relative to the notes folder, so neither compares against `rel`.

    `workers` are the parallel-mode `docs_<id>/` folders, also relative to
    the repository root.
    """
    name = Path(rel).name
    if name in ROOT_FIXED and "/" not in rel:
        return "rules", "도구가 저장소 루트에서 읽는 파일"
    # Every dot folder belongs to some tool that opens its files by path:
    # `.claude/commands`, `.github/` templates, `.superpowers/` ledgers.
    # Flattening one into `docs/` deletes the feature, not just the file.
    if rel.split("/", 1)[0].startswith("."):
        return "foreign", "점(.)으로 시작하는 도구 폴더 — 경로로 읽힌다"
    if any(rel == w or rel.startswith(w + "/") for w in workers):
        return "worker", "병행 작업 개인 폴더 — 공용 문서와 섞지 않는다"
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

    The destinations are girok's standard layout rather than whatever
    `docRoots`/`decisionsDir` currently say, because moving the repository
    onto the standard is what this command is for — `update_config` then
    rewrites the config so it describes where the files actually are.

    `keep` is a person's answer to a `?`: read it, decided it stays. It
    exists so that decision has somewhere to live besides an argument
    every check repeats.
    """
    if entry.role in ("rules", "foreign", "skip", "worker", "keep", "?"):
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
    workers = tuple(
        w.resolve().relative_to(root).as_posix() for w in cfg.worker_dirs()
    )
    entries = []
    for path in _markdown(root):
        rel = path.relative_to(root).as_posix()
        role, why = _classify(rel, cfg, decisions, workers)
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
        # `apply` fills these in: the restore tag it created, and the
        # config keys it had to correct afterwards.
        "tag": None,
        "configUpdated": {},
        "files": [e.as_json() for e in entries],
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return target


def hand_filled(existing: dict, entries: list[Entry]) -> list[str]:
    """Paths in `existing` whose hand-written answer a replan would drop.

    `plan` reads the repository, not the mapping: every entry it returns is
    built from scratch, so writing them over an existing mapping throws away
    the `role` a person resolved, every `merge` they wrote, and every
    `keep`. Those are the three things no rule can reproduce.
    """
    proposed = {entry.frm: entry.role for entry in entries}
    lost = []
    for item in existing.get("files", []):
        frm = item.get("from")
        role = item.get("role")
        if item.get("merge") or role == "keep":
            lost.append(frm)
        elif role not in (None, "?") and proposed.get(frm) == "?":
            lost.append(frm)
    return lost


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


def _read_document(path: Path, root: Path) -> str:
    """Read a markdown document, or stop with its name.

    One `.md` saved in cp949 used to end the whole run in a
    `UnicodeDecodeError` that did not say which file — at a point where a
    backup and a restore tag already exist. Anything unreadable is a
    `Blocked` naming the path, like every other refusal here.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise Blocked(
            f"`{path.relative_to(root).as_posix()}` 를 UTF-8 로 읽지 못했다 — {exc.reason}. "
            f"이 파일을 UTF-8 로 다시 저장한 뒤 다시 실행할 것"
        ) from exc
    except OSError as exc:
        raise Blocked(
            f"`{path.relative_to(root).as_posix()}` 를 읽지 못했다 — {exc}"
        ) from exc


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
    # A merge target is about to be appended to and its source deleted, so
    # the restore tag has to hold it — even when the target itself never
    # moves and so carries no `to` of its own.
    targets = {f["merge"] for f in mapping["files"] if f.get("merge")}
    dirty = []
    for item in mapping["files"]:
        # Only what adoption is about to touch. A half-finished edit to
        # `CLAUDE.md`, which never moves, is ordinary work — blocking on it
        # would make the gate about tidiness instead of about what the
        # restore tag can bring back (spec §4: "이식 대상 밖은 통과").
        if (
            not item.get("to") and not item.get("merge")
            and item["from"] not in targets
        ):
            continue
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
    name that means something for one that does not. A name girok itself
    opens literally is kept for a harder reason — see `FIXED_NAMES`.
    """
    if name in FIXED_NAMES:
        return name
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


def merge_into(
    root: Path, source: str, target: str,
    today: str | None = None, moved_to: str | None = None,
) -> None:
    """Append `source` to `target` verbatim, then drop `source`.

    Not a word is changed. Summarizing or reflowing here would be nicer to
    read and impossible to verify, and "nothing is lost" was the whole
    requirement.

    A missing target is a refusal, not an empty head. Treating it as ""
    created a brand new file at the target path holding only the source's
    body — and `verify`, which only checks that the target exists and
    contains the lines, passed. The document that was supposed to receive
    the content got nothing. `moved_to` is where the mapping says that
    document went, so the message can say what to write instead.
    """
    root = Path(root).resolve()
    src, dst = root / source, root / target
    stamp = today or date.today().strftime("%Y-%m-%d")

    if not dst.is_file():
        hint = (
            f" — 매핑을 보면 그 문서는 `{moved_to}` 로 옮겨졌다. "
            f"`merge` 에는 이동 후 경로를 적을 것"
            if moved_to else
            " — `merge` 에는 이동 후 경로를 적고, 대상 문서가 실제로 있는지 확인할 것"
        )
        raise Blocked(
            f"`{source}` 를 병합할 대상 `{target}` 가 없다{hint}. "
            f"아무것도 병합하지 않았다"
        )

    body = _read_document(src, root)
    head = _read_document(dst, root)
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


def _retarget(
    doc_rel: str, link: str, moves: dict[str, str],
    origin_rel: str | None = None, root: Path | None = None,
) -> str | None:
    """The new relative link, or None if this one needs no change.

    `link` is percent-decoded before it is matched against the moves table —
    `my%20file.md` and `my file.md` name the same file. The anchor rides
    along separately and is never touched by this.

    `origin_rel` is where the *referring* document was when this link was
    written. It matters whenever that document moved too: the link resolves
    from the old parent and has to be written relative to the new one.
    Resolving from the new parent instead looks up a path the moves table
    has never heard of, which is why link rewriting silently did nothing in
    exactly the case it exists for — `decisions/` becoming
    `docs/decisions/`.
    """
    if EXTERNAL.match(link):
        return None
    here = Path(doc_rel).parent
    origin = Path(origin_rel).parent if origin_rel else here
    try:
        target = (origin / unquote(link)).as_posix()
        target = Path(os.path.normpath(target)).as_posix()
    except ValueError:
        return None
    moved_to = moves.get(target)
    if moved_to is None:
        # The destination stayed put but this document did not, so the same
        # relative path now resolves somewhere else. Only rewrite when the
        # old path really held a file: a link that was already dead is not
        # ours to invent a destination for.
        if origin_rel is None or origin_rel == doc_rel or root is None:
            return None
        if not (root / target).exists():
            return None
        moved_to = target
    new = os.path.relpath(moved_to, here.as_posix() or ".").replace("\\", "/")
    return None if new == unquote(link) else new


def _rewrite_inline_links(
    line: str, doc_rel: str, moves: dict[str, str],
    origin_rel: str | None = None, root: Path | None = None,
) -> tuple[str, int]:
    """Rewrite every `[text](dest)` / `![alt](dest)` in a line."""
    changed = 0
    out = []
    pos = 0
    for start, end, opening, dest, anchor, title, angled in _iter_inline_links(line):
        out.append(line[pos:start])
        new_dest = _retarget(doc_rel, dest, moves, origin_rel, root)
        if new_dest is None:
            out.append(line[start:end])
        else:
            body = f"<{new_dest}>" if angled else new_dest
            out.append(f"{opening}{body}{anchor}{title})")
            changed += 1
        pos = end
    out.append(line[pos:])
    return "".join(out), changed


def _rewrite_html_attrs(
    line: str, doc_rel: str, moves: dict[str, str],
    origin_rel: str | None = None, root: Path | None = None,
) -> tuple[str, int]:
    """Rewrite `src="..."` / `href='...'` in embedded HTML."""
    changed = 0

    def swap(match):
        nonlocal changed
        new = _retarget(doc_rel, match.group(3), moves, origin_rel, root)
        if new is None:
            return match.group(0)
        changed += 1
        return f"{match.group(1)}{match.group(2)}{new}{match.group(2)}"

    return HTML_ATTR.sub(swap, line), changed


def rewrite_links(
    root: Path, moves: list[tuple[str, str]], origins: dict[str, str] | None = None,
) -> list[str]:
    """Point every relative link at where its document went.

    Returns the repository-root-relative paths of documents this actually
    wrote, sorted. The caller (`apply`) needs exactly this list to scope its
    final commit, and this function already knows it — recomputing it from
    outside by re-hashing the tree would be the same answer, done twice.
    """
    root = Path(root).resolve()
    table = dict(moves)
    # Where each moved document used to be. Its links were written from
    # there, so that is where they have to be resolved from.
    #
    # A merge belongs in `moves` (references to the source now point at the
    # target) but never in `origins`: the target did not come from the
    # source, it merely received it, and a caller that mixes the two makes
    # every link in the target resolve from the wrong folder. `apply` passes
    # the move list explicitly for that reason.
    if origins is None:
        origins = {new: old for old, new in moves}
    touched = []

    for path in _markdown(root):
        doc_rel = path.relative_to(root).as_posix()
        # A document that itself moved is already at its new path.
        origin_rel = origins.get(doc_rel, doc_rel)
        original = _read_document(path, root)
        lines = []
        changed = 0
        for line, is_code in _outside_code(original):
            if is_code:
                lines.append(line)
                continue

            line, n = _rewrite_inline_links(line, doc_rel, table, origin_rel, root)
            changed += n

            def swap_reference(match, doc=doc_rel, origin=origin_rel):
                nonlocal changed
                new = _retarget(doc, match.group(2), table, origin, root)
                if new is None:
                    return match.group(0)
                changed += 1
                return f"{match.group(1)}{new}{match.group(3)}"

            line = REFERENCE_LINK.sub(swap_reference, line)
            line, n = _rewrite_html_attrs(line, doc_rel, table, origin_rel, root)
            changed += n
            lines.append(line)

        updated = "\n".join(lines)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            touched.append(doc_rel)
    return sorted(touched)


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
        for line, is_code in _outside_code(_read_document(path, root)):
            if is_code:
                continue
            dests = [dest for _, _, _, dest, _, _, _ in _iter_inline_links(line)]
            dests += [match.group(3) for match in HTML_ATTR.finditer(line)]
            for link in dests:
                if EXTERNAL.match(link):
                    continue
                # `link` (as written in the document) is what gets reported;
                # only the existence check needs the percent-decoded path.
                target = Path(os.path.normpath((here / unquote(link)).as_posix()))
                if not (root / target).exists():
                    broken.append((doc_rel, link))
    return broken


BLANK_DEST = "·"


def link_skeleton(text: str) -> str:
    """`text` with every relative link destination blanked out.

    Two documents with the same skeleton differ only in where their links
    point, which is exactly what `apply` is allowed to change and nothing
    else. This is how the narrowed promise stays checkable: a moved
    document is no longer byte-identical to its original once a link inside
    it was repointed, but everything around those destinations still has to
    be the same text, and the untouched backup copy is what it is compared
    against. External links are left alone so a changed URL still shows up.
    """
    out = []
    for line, is_code in _outside_code(text):
        if is_code:
            out.append(line)
            continue

        blanked = []
        pos = 0
        for start, end, opening, dest, anchor, title, angled in _iter_inline_links(line):
            blanked.append(line[pos:start])
            body = dest if EXTERNAL.match(dest) else BLANK_DEST
            blanked.append(f"{opening}{f'<{body}>' if angled else body}{anchor}{title})")
            pos = end
        blanked.append(line[pos:])
        line = "".join(blanked)

        def blank_reference(match):
            if EXTERNAL.match(match.group(2)):
                return match.group(0)
            return f"{match.group(1)}{BLANK_DEST}{match.group(3)}"

        def blank_attr(match):
            if EXTERNAL.match(match.group(3)):
                return match.group(0)
            return f"{match.group(1)}{match.group(2)}{BLANK_DEST}{match.group(2)}"

        line = REFERENCE_LINK.sub(blank_reference, line)
        out.append(HTML_ATTR.sub(blank_attr, line))
    return "\n".join(out)


@dataclass
class VerifyResult:
    ok: bool = True
    failures: list[str] = field(default_factory=list)
    tag: str | None = None
    backup: str | None = None

    def fail(self, message: str) -> None:
        self.ok = False
        self.failures.append(message)


def _write_mapping_payload(root: Path, payload: dict) -> None:
    target = Path(root).resolve() / MAPPING_RELATIVE
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def update_config(root: Path, mapping: dict) -> dict:
    """Make `.claude/girok.json` describe where the documents now are.

    Without this the tool prints "성공 · 유실 없음" and girok is broken in
    that repository the same minute: the files are at `PROGRESS.md` and
    `docs/decisions/`, the config still says `STATE.md` and `decisions/`,
    and every check that reads the config reports a missing board.

    Only keys adoption actually made true are touched, and only when they
    disagree. `docRoots` gains `docs` at the front rather than being
    replaced — documents landed there, but the roots the repository already
    declared are not ours to drop.
    """
    root = Path(root).resolve()
    cfg = notes_config.load(root)
    if cfg.source is None:
        # No config file: the defaults are already the standard layout the
        # documents just moved to, and inventing a config here is
        # `notes_init`'s job, not a side effect of moving files.
        return {}

    notes_rel = cfg.notes_dir.resolve().relative_to(root).as_posix()
    notes = "" if notes_rel == "." else notes_rel + "/"
    landed = [item["to"] for item in mapping["files"] if item.get("to")]
    raw = json.loads(cfg.source.read_text(encoding="utf-8"))
    changed: dict = {}

    board = notes_config.DEFAULT_BOARD
    if f"{notes}{board}" in landed and (raw.get("board") or board) != board:
        raw["board"] = board
        changed["board"] = board

    decisions = notes_config.DEFAULT_DECISIONS_DIR
    if (
        any(t.startswith(f"{notes}{decisions}/") for t in landed)
        and (raw.get("decisionsDir") or decisions) != decisions
    ):
        raw["decisionsDir"] = decisions
        changed["decisionsDir"] = decisions

    docs = notes_config.DEFAULT_DOC_ROOTS[0]
    roots = list(raw.get("docRoots") or [])
    # `docs` has to be *first*, not merely present: `cfg.docs_dir` is
    # `doc_roots_relative[0]`, and that is where the gate hook, the linter
    # and the marker scan open `SAFETY_GATE.md` by name. A config listing
    # `["documents", "docs"]` left them reading `documents/SAFETY_GATE.md`
    # after the gate had moved to `docs/` — no gate, nothing OPEN, real
    # motion commands through, and `verify` passing.
    if (
        any(t.startswith(f"{notes}{docs}/") for t in landed)
        and roots and roots[0] != docs
    ):
        raw["docRoots"] = [docs, *(r for r in roots if r != docs)]
        changed["docRoots"] = raw["docRoots"]

    if changed:
        cfg.source.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    return changed


def apply(root: Path, today: str | None = None) -> list[tuple[str, str]]:
    """Back up, tidy git, move, merge, and repoint — in that order.

    The order is the design. Checking preconditions after committing
    everything would make the gate vacuous, and worse: in a repository that
    already existed, sweeping *everything* into that commit drags in a
    person's unrelated in-progress work. Backing up after `git init` would
    capture a repository girok had already edited, and moving before the
    preconditions would move a file the restore tag cannot bring back.
    """
    root = Path(root).resolve()
    stamp = today or date.today().strftime("%Y%m%d")

    mapping_path = root / MAPPING_RELATIVE
    if not mapping_path.is_file():
        raise Blocked(
            "매핑이 없다 — 먼저 `plan` 을 돌려 제안을 확인하고, "
            "자리가 안 정해진(`?`) 문서의 role 을 채운 뒤 다시 실행할 것"
        )
    mapping = read_mapping(root)

    unresolved = [f["from"] for f in mapping["files"] if f["role"] == "?"]
    if unresolved:
        listed = ", ".join(unresolved[:5])
        raise Blocked(
            f"자리가 안 정해진 문서가 {len(unresolved)}개 있다 — {listed}. "
            f"role 을 채운 뒤 다시 실행할 것"
        )

    if (root / ".git").exists():
        check_preconditions(root, mapping)

    saved = backup(root, today=stamp)
    setup = git_setup(root)

    if setup.init:
        run_git(root, "add", "-A")
        run_git(root, "commit", "-m", "chore: girok 이식 전 상태")
    elif setup.gitignore_added:
        # A pre-existing repository may hold unrelated, uncommitted work —
        # `git add -A` here would sweep it into our commit. Only what we
        # just wrote goes in.
        run_git(root, "add", "--", ".gitignore")
        run_git(root, "commit", "-m", "chore: girok 이식 전 상태")
    tag = f"girok-adopt-before-{stamp}"
    run_git(root, "tag", tag)

    # Recorded now rather than at the end, so a `verify` run days later —
    # or after a failure below — names the tag that exists instead of
    # rebuilding one out of today's date.
    mapping["tag"] = tag
    mapping["backup"] = {
        "path": saved.path.name, "files": saved.files, "bytes": saved.bytes,
    }
    _write_mapping_payload(root, mapping)

    # From here on, the safety net (backup folder + restore tag) already
    # exists. If anything below fails — a collision, a self-merge, a
    # `git mv`/`git rm` failure mid-move, an unreadable file, a full disk —
    # the person is mid-operation with some files possibly already moved.
    # Attaching the tag and backup name to the exception lets `main()` tell
    # them exactly how to undo it, instead of leaving them to guess whether
    # it is safe.
    try:
        cfg = notes_config.load(root)
        for item in mapping["files"]:
            target = item.get("to")
            # The board's destination ("PROGRESS.md") is this methodology's
            # own fixed name, not derived from whatever the person called
            # it — there is nothing of theirs left in it to normalize.
            if not target or item["role"] == "board":
                continue
            parent = Path(target).parent
            name = normalize_name(Path(target).name, item["role"], cfg.adr_style)
            item["to"] = (parent / name).as_posix() if parent.as_posix() != "." else name

        destinations: dict[str, list[str]] = {}
        for item in mapping["files"]:
            if item.get("to"):
                destinations.setdefault(item["to"], []).append(item["from"])
        for dest, sources in destinations.items():
            if len(sources) > 1:
                raise Blocked(
                    f"{len(sources)}개 문서가 정규화 후 같은 자리로 겹친다 — "
                    f"{', '.join(sources)} 모두 `{dest}` 가 된다. 이름을 정리하고 "
                    f"다시 실행할 것 (자동으로 번호를 붙여 해결하지 않는다)"
                )

        for item in mapping["files"]:
            if item.get("merge") and item["merge"] == item["from"]:
                raise Blocked(
                    f"`{item['from']}` 를 자기 자신에 병합할 수 없다 — 내용을 이어붙인 뒤 "
                    f"원본을 지우면 문서가 그대로 사라진다"
                )

        broken_before = broken_links(root)

        merges = [i for i in mapping["files"] if i.get("merge")]
        plain = [i for i in mapping["files"] if not i.get("merge")]

        moved = move_all(root, {"files": plain})
        origins = {to: frm for frm, to in moved}
        # Where each planned document ended up, so a `merge` written with
        # the name a person read off the mapping can be told what to say.
        landed_at = {item["from"]: item["to"] for item in plain if item.get("to")}
        for item in merges:
            merge_into(
                root, item["from"], item["merge"], today=None,
                moved_to=landed_at.get(item["merge"]),
            )
            moved.append((item["from"], item["merge"]))

        rewritten = rewrite_links(root, moved, origins)

        # The hash of what actually landed, after link rewriting. `verify`
        # checks against this; `sha1` stays as the original so the two can
        # be compared to say whether anything beyond a link changed.
        for item in mapping["files"]:
            if item.get("merge") or not item.get("to"):
                continue
            landed = root / item["to"]
            item["sha1After"] = sha1_of(landed) if landed.is_file() else None

        config_updated = update_config(root, mapping)
    except Exception as exc:
        try:
            exc.tag = tag
            exc.backup_name = saved.path.name
        except AttributeError:
            # An exception type that refuses attributes must not turn into
            # the failure that gets reported — the original error and the
            # safety net are what the person needs. `Blocked` carries both.
            blocked = Blocked(f"이식 중 오류가 났다 — {type(exc).__name__}: {exc}")
            blocked.tag = tag
            blocked.backup_name = saved.path.name
            raise blocked from exc
        raise

    mapping["gitSetup"] = {
        "init": setup.init, "gitignoreAdded": setup.gitignore_added,
        "secrets": setup.secrets, "large": setup.large,
        "alreadyTracked": setup.already_tracked, "remote": setup.remote,
    }
    mapping["brokenBefore"] = [list(pair) for pair in broken_before]
    mapping["configUpdated"] = config_updated
    _write_mapping_payload(root, mapping)

    if setup.init:
        # Nothing existed before girok touched this folder — there is no
        # unrelated work to sweep in.
        run_git(root, "add", "-A")
    else:
        touched = {MAPPING_RELATIVE.as_posix()}
        touched.update(to for _, to in moved)
        touched.update(rewritten)
        if config_updated:
            touched.add(
                notes_config.load(root).source.relative_to(root).as_posix()
            )
        run_git(root, "add", "--", *sorted(touched))
    run_git(root, "commit", "-m", "feat: girok 이식")

    return moved


def verify(root: Path) -> VerifyResult:
    """Re-read the bytes and say whether the claims hold."""
    root = Path(root).resolve()
    result = VerifyResult()
    try:
        mapping = read_mapping(root)
    except (OSError, ValueError):
        result.fail("매핑 파일이 없다 — 무엇을 옮겼는지 알 수 없으므로 검증할 수 없다")
        return result

    result.tag = mapping.get("tag")
    saved = mapping.get("backup") or {}
    result.backup = saved.get("path")
    backup_path = root.parent / saved["path"] if saved.get("path") else None
    merge_targets = {i["merge"] for i in mapping["files"] if i.get("merge")}

    for item in mapping["files"]:
        # `merge` first: an item may carry a stale `to` from before someone
        # decided to merge it instead, and that `to` names a path nothing
        # ever created.
        landed = item.get("merge") or item.get("to") or item["from"]
        path = root / landed
        if not path.is_file():
            result.fail(f"{landed} 가 없다 (원래 {item['from']})")
            continue
        if item.get("merge") or not item.get("to"):
            continue

        after = item.get("sha1After")
        expected = after or item["sha1"]
        if sha1_of(path) != expected:
            result.fail(f"{landed} 의 내용이 이식 직후와 다르다 (원래 {item['from']})")
            continue
        if not after or after == item["sha1"]:
            # Byte-identical to the original: nothing more to prove.
            continue

        # `apply` repointed a link inside this document, so it cannot be
        # byte-identical. The narrower promise — nothing but link
        # destinations changed — is checked against the untouched backup,
        # the one copy that cannot have been rewritten by anything here.
        original = backup_path / item["from"] if backup_path else None
        if original is None or not original.is_file():
            result.fail(
                f"{landed} 는 링크가 재작성돼 원본과 바이트가 다르다 — "
                f"백업의 {item['from']} 가 없어 나머지 내용이 그대로인지 대조할 수 없다"
            )
            continue
        try:
            before = link_skeleton(_read_document(original, backup_path))
            now = link_skeleton(_read_document(path, root))
        except Blocked as exc:
            # A comparison that could not be read is not a comparison that
            # passed.
            result.fail(str(exc))
            continue
        if landed in merge_targets:
            # Another document was appended into this one, so it is longer
            # than the original by design. Every original line still has to
            # be there; the appended half is checked below, against its own
            # source.
            dropped = missing_lines(before, now)
            if dropped:
                result.fail(
                    f"{landed} 에서 원본({item['from']})의 {len(dropped)}줄이 사라졌다 — "
                    f"첫 줄: {dropped[0][:40]}"
                )
        elif before != now:
            result.fail(
                f"{landed} 의 링크 목적지 밖 내용이 원본({item['from']})과 다르다"
            )

    if backup_path:
        for item in mapping["files"]:
            if not item.get("merge"):
                continue
            original = backup_path / item["from"]
            merged = root / item["merge"]
            if not (original.is_file() and merged.is_file()):
                result.fail(f"{item['from']} 의 병합 결과를 대조할 수 없다")
                continue
            dropped = missing_lines(
                original.read_text(encoding="utf-8", errors="replace"),
                merged.read_text(encoding="utf-8", errors="replace"),
            )
            if dropped:
                result.fail(
                    f"{item['from']} 의 {len(dropped)}줄이 {item['merge']} 에 없다 — "
                    f"첫 줄: {dropped[0][:40]}"
                )

    baseline = {tuple(pair) for pair in mapping.get("brokenBefore", [])}
    try:
        found = broken_links(root)
    except Blocked as exc:
        # An unreadable document is a verification that could not finish,
        # never a pass.
        result.fail(str(exc))
        found = []
    for doc, link in found:
        if (doc, link) in baseline:
            continue
        result.fail(f"{doc} 의 링크가 깨졌다 — {link}")
    return result


def restore_guidance(tag: str | None, backup_name: str | None) -> list[str]:
    """How to undo an adoption, in the order that actually works.

    The backup folder comes first because it is the only complete answer.
    `git checkout <tag> -- .` brings the old paths back but leaves the
    copies already at the new paths, so the repository ends up holding both
    and the next `apply` blocks on the leftovers.
    """
    lines = ["복원하려면:"]
    if backup_name:
        lines += [
            "  1) 지금 저장소 폴더를 다른 이름으로 옮겨둔다",
            f"  2) 백업 폴더 {backup_name} 을 원래 저장소 이름으로 되돌린다",
            "  (백업은 손대기 전 원본 전체이므로 이것이 가장 확실하다)",
        ]
    if tag:
        lines += [
            f"git 으로 되돌리려면 태그 {tag} 를 쓴다 — 옛 경로만 골라 되살리면 이미",
            "옮겨진 새 경로의 사본이 남아 문서가 둘로 갈린다. 통째로 되돌릴 것:",
            f"  git reset --hard {tag}",
            "  git clean -fd    # 새 경로에 남은 사본을 지운다. 무관한 미추적 파일도",
            "                   # 함께 지워지니 먼저 `git clean -nd` 로 확인할 것",
        ]
    else:
        lines.append("매핑에 복원 태그가 없다 — `git tag` 로 girok-adopt-before-* 를 확인할 것")
    return lines


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["backup", "plan", "apply", "verify"])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--confirm", default=None, help="이식할 저장소의 폴더 이름")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="plan: 표만 출력하고 매핑 파일은 건드리지 않는다",
    )
    parser.add_argument(
        "--reset-mapping", action="store_true",
        help="plan: 손으로 채운 값을 버리고 매핑을 처음부터 다시 만든다",
    )
    args = parser.parse_args(argv)

    if args.command == "plan":
        entries = plan(args.root)
        if not args.dry_run:
            # A routine check must not rewrite the mapping: the `?`
            # resolutions in it were filled in by hand, and in an already
            # adopted repository it is the committed record of what moved.
            try:
                existing = read_mapping(args.root)
            except (OSError, ValueError):
                existing = {}
            lost = hand_filled(existing, entries)
            if lost and not args.reset_mapping:
                listed = ", ".join(lost[:5])
                print(
                    f"[중단] 매핑을 다시 쓰지 않았다 — 사람이 손으로 채운 항목이 "
                    f"{len(lost)}개 있고, `plan` 은 저장소만 보고 매핑을 통째로 다시 "
                    f"만들기 때문에 그 답이 사라진다: {listed}"
                )
                print("  해소한 `role`·손으로 쓴 `merge`·`keep` 이 사라진다.")
                print("  표만 보려면:            plan --dry-run")
                print("  정말 처음부터 다시 하려면: plan --reset-mapping")
                return 1
            write_mapping(args.root, entries, None)
        unknown = [e for e in entries if e.role == "?"]
        for entry in entries:
            arrow = entry.to or "제자리"
            print(f"[{entry.role:>7}] {entry.frm} → {arrow}  ({entry.why})")
        print(f"문서 {len(entries)}개 — 판단 필요 {len(unknown)}개")
        return 0

    if args.command == "apply":
        root = Path(args.root).resolve()
        if args.confirm != root.name:
            print(f"[중단] `{root}` 에서 아무것도 옮기지 않았다.")
            print(f"  이식하려면 이름을 확인해 다시 실행할 것:  --confirm {root.name}")
            return 1
        try:
            moved = apply(root)
        except Exception as exc:
            # Every failure lands here, not just the recognized ones. A full
            # disk, a permission error, a file this cannot read: the person
            # still has files half-moved and a safety net they need to be
            # told about, and a traceback tells them neither.
            if isinstance(exc, (BackupFailed, Blocked)):
                print(f"[중단] {exc}")
            else:
                print(f"[중단] 예상치 못한 오류 — {type(exc).__name__}: {exc}")
            tag = getattr(exc, "tag", None)
            backup_name = getattr(exc, "backup_name", None)
            if tag and backup_name:
                # A backup and restore tag were already made before this
                # failed — some files may already be staged as moved.
                print("git mv/git rm 으로 스테이징된 이동이 인덱스에 남아 있을 수 있다.")
                for line in restore_guidance(tag, backup_name):
                    print(line)
            return 1
        for frm, to in moved:
            print(f"[이동] {frm} → {to}")

        git_info = read_mapping(root).get("gitSetup", {})
        already_tracked = git_info.get("alreadyTracked") or []
        if already_tracked:
            listed = ", ".join(already_tracked)
            print(
                "[주의] 다음 파일은 이미 git 에 커밋되어 있어 .gitignore 를 추가해도 빠지지\n"
                "않는다 — 이력을 지우려면 이력을 다시 써야 하는데 이 방법론은 그것을\n"
                "금지한다. 비밀이 들어 있다면 값을 폐기·교체하는 것이 답이다: " + listed
            )

        excluded = (git_info.get("secrets") or []) + (git_info.get("large") or [])
        if excluded:
            print(
                "[주의] 다음 파일을 비밀 또는 대용량으로 판단해 .gitignore 에 넣었다 — "
                "git 밖에 남으므로\n백업 폴더에만 존재한다. 필요한 파일이면 지금 "
                "확인할 것: " + ", ".join(excluded)
            )

        updated = read_mapping(root).get("configUpdated") or {}
        if updated:
            listed = ", ".join(f"{k} → {v}" for k, v in updated.items())
            print(f"[설정] 문서가 옮겨간 자리에 맞춰 girok.json 을 고쳤다: {listed}")

        print(f"{len(moved)}개 이동. 이어서 `verify` 를 돌릴 것")

        if git_info.get("remote") is None:
            print(
                "원격 저장소가 없다 — `git remote add origin <주소>` 뒤 "
                "`git push -u origin <브랜치> --tags` 로 커밋과 복원 태그를 함께 올릴 것"
            )
        else:
            print("push 할 때는 태그도 함께 올릴 것 — `git push --tags`")
        return 0

    if args.command == "verify":
        result = verify(args.root)
        for failure in result.failures:
            print(f"[실패] {failure}")
        if result.ok:
            print("이식 검증 통과 — 유실 없음")
            return 0
        for line in restore_guidance(result.tag, result.backup):
            print(line)
        return 1

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
