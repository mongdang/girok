"""Safety marker scanning and gate cross-check.

Two markers, spelled exactly, so a single grep finds every one of them:

- `SAFETY-STUB` – a safety judgement (in-position, interlock, limit) that is
  temporarily allowed to pass. The default for such a stub is fail-safe, so
  this marker only appears where the stub passes instead of blocks.
- `VIRTUAL-BYPASS` – a branch that only exists for simulated runs, to be
  reviewed exhaustively before the code drives real hardware.

Both must be registered in `docs/SAFETY_GATE.md`. This script reports the
ones that are not.

> The scan reports; it never closes anything. Gate items are closed by a
> named person, and nothing here writes to the gate document.

    python marker_scan.py            # scan the working tree
    python marker_scan.py --staged   # commit-time check on staged changes
"""
import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import notes_config

MARKERS = ("SAFETY-STUB", "VIRTUAL-BYPASS")
MARKER_RE = re.compile("|".join(MARKERS))

GATE_NAME = "SAFETY_GATE.md"

SKIP_DIRS = {
    ".git", ".vs", ".idea", "__pycache__", "node_modules",
    "bin", "obj", "build", "dist", "packages", "target", ".venv",
}
SCAN_SUFFIXES = {
    ".cs", ".cpp", ".c", ".h", ".hpp", ".py", ".ts", ".js", ".java",
    ".go", ".rs", ".ps1", ".xaml", ".vb",
}


@dataclass
class Marker:
    kind: str
    path: str
    line: int
    text: str


@dataclass
class Result:
    markers: list[Marker] = field(default_factory=list)
    unregistered: list[Marker] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    skipped: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems


def _gate_path(cfg: notes_config.NotesConfig) -> Path:
    return cfg.docs_dir / GATE_NAME


def _enabled(cfg: notes_config.NotesConfig) -> bool:
    return cfg.modules.get("safetyGate", True)


def _doc_areas(cfg: notes_config.NotesConfig) -> list[Path]:
    """The folders that hold documents rather than code.

    Excluding the whole notes tree is wrong when the notes root *is* the
    repository root – that layout would exclude every source file and the
    scan would always come back empty. So the exclusion is by doc area:
    the doc roots, the decisions folder, the worker folders, `.method/`.
    """
    areas = [*cfg.doc_roots(), cfg.decisions_dir, *cfg.worker_dirs(), cfg.notes_dir / ".method"]
    if cfg.notes_dir.resolve() != cfg.repo_root.resolve():
        areas.append(cfg.notes_dir)
    return areas


def _scannable(path: Path, cfg: notes_config.NotesConfig) -> bool:
    if path.suffix.lower() not in SCAN_SUFFIXES:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    for area in _doc_areas(cfg):
        try:
            path.resolve().relative_to(area.resolve())
            return False
        except (ValueError, OSError):
            continue
    return True


def walk_files(root: Path, skip: set[str]):
    """Every file under `root`, with the skipped folders actually pruned.

    `rglob("*")` still descends into `.git` and `node_modules` and filters
    afterwards, which on a real checkout is most of the walk – and all of it
    wasted. `os.walk` can be told not to go in.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        here = Path(dirpath)
        for name in sorted(filenames):
            yield here / name


def find_markers(cfg: notes_config.NotesConfig) -> list[Marker]:
    found: list[Marker] = []
    for path in walk_files(cfg.repo_root, SKIP_DIRS):
        if not path.is_file() or not _scannable(path, cfg):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for no, line in enumerate(text.splitlines(), 1):
            for m in MARKER_RE.finditer(line):
                found.append(
                    Marker(
                        kind=m.group(0),
                        path=path.relative_to(cfg.repo_root).as_posix(),
                        line=no,
                        text=line.strip(),
                    )
                )
    return found


def gate_text(cfg: notes_config.NotesConfig) -> str | None:
    gate = _gate_path(cfg)
    if not gate.is_file():
        return None
    return gate.read_text(encoding="utf-8")


def _registered(marker: Marker, gate: str) -> bool:
    """A marker counts as registered when the gate names the file it is in.

    Matching on the file name rather than the exact line keeps the gate
    readable – an item describes a condition, not a line number that moves
    with every edit.
    """
    return Path(marker.path).name in gate


def run(start: Path | str = ".") -> Result:
    cfg = notes_config.load(start)
    result = Result()

    if not _enabled(cfg):
        result.skipped = True
        return result

    result.markers = find_markers(cfg)
    gate = gate_text(cfg)

    if gate is None:
        if result.markers:
            result.problems.append(
                f"{_gate_path(cfg)} 없음 – 마커 {len(result.markers)}건이 등재될 곳이 없다"
            )
        return result

    result.unregistered = [m for m in result.markers if not _registered(m, gate)]
    for m in result.unregistered:
        result.problems.append(f"{m.path}:{m.line} {m.kind} 가 {GATE_NAME} 에 미등재")
    return result


def check_staged(
    start: Path | str,
    added_lines: dict[str, list[str]],
    changed_paths: list[str],
) -> Result:
    """Commit-time check: a new marker and its gate entry in one commit.

    This runs when `git commit` is invoked, not when a file is edited.
    Blocking at edit time would forbid the normal order of work – write the
    marker, then register it – and would teach people to bypass the hook.
    """
    cfg = notes_config.load(start)
    result = Result()

    if not _enabled(cfg):
        result.skipped = True
        return result

    for path, lines in added_lines.items():
        for line in lines:
            for m in MARKER_RE.finditer(line):
                result.markers.append(Marker(m.group(0), path, 0, line.strip()))

    if not result.markers:
        return result

    gate_touched = any(Path(p).name == GATE_NAME for p in changed_paths)
    if not gate_touched:
        kinds = ", ".join(sorted({m.kind for m in result.markers}))
        files = ", ".join(sorted({m.path for m in result.markers}))
        result.unregistered = list(result.markers)
        result.problems.append(
            f"{kinds} 마커가 추가됐는데 같은 커밋에 {GATE_NAME} 변경이 없다 ({files}). "
            f"게이트에 항목을 등재한 뒤 다시 커밋할 것"
        )
    return result


def staged_from_git(root: Path) -> tuple[dict[str, list[str]], list[str]]:
    try:
        diff = subprocess.run(
            ["git", "diff", "--cached", "--unified=0"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout
    except OSError:
        return {}, []
    added: dict[str, list[str]] = {}
    changed: list[str] = []
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            changed.append(current)
        elif line.startswith("+") and not line.startswith("+++") and current:
            added.setdefault(current, []).append(line[1:])
    return added, changed


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--staged", action="store_true", help="스테이징된 변경만 검사 (커밋 시점)")
    args = parser.parse_args(argv)

    if args.staged:
        cfg = notes_config.load(args.root)
        added, changed = staged_from_git(cfg.repo_root)
        result = check_staged(args.root, added, changed)
    else:
        result = run(args.root)

    if result.skipped:
        print("safetyGate 모듈이 꺼져 있음 – 건너뜀")
        return 0

    for problem in result.problems:
        print(f"[차단] {problem}")

    if result.problems:
        return 1
    print(f"마커 {len(result.markers)}건, 전부 게이트에 등재됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
