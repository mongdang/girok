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
import os
import shutil
import sys
from dataclasses import dataclass
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


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["backup"])
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

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
