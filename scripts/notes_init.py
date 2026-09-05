"""Setting a repository up for this methodology.

One approval, then everything exists: the notes skeleton, the pointers for
agents that cannot load skills, the two committed settings files, and the
`.method/` snapshot.

Nothing that already exists is overwritten. Initialization runs again on
repositories that are already half set up — a `/notes` on a repo missing one
file should add that file, not flatten the work in the others.
"""
import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import method_sync
import notes_config


def read_git_email(root: Path) -> str | None:
    """The git identity in this repository, used to fill in `workers`.

    Without it, initialization would create `docs_<id>/` and the very next
    write would be blocked for an unconfirmed worker — `/notes` would set the
    repository up and then refuse to write to it.
    """
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            cwd=root, capture_output=True, text=True,
        )
    except OSError:
        return None
    return result.stdout.strip() or None


TEMPLATES = method_sync.PLUGIN_ROOT / "templates"

GATE_BEGIN = "<!-- safety-gate:begin -->"
GATE_END = "<!-- safety-gate:end -->"


@dataclass
class InitResult:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _write(path: Path, text: str, result: InitResult, root: Path) -> None:
    rel = path.relative_to(root).as_posix()
    if path.exists():
        result.skipped.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    result.created.append(rel)


def _strip_gate_section(text: str) -> str:
    start = text.find(GATE_BEGIN)
    end = text.find(GATE_END)
    if start == -1 or end == -1:
        return text
    return text[:start].rstrip() + "\n\n" + text[end + len(GATE_END):].lstrip("\n")


def _keep_gate_section(text: str) -> str:
    return text.replace(GATE_BEGIN + "\n", "").replace(GATE_END + "\n", "")


def init(
    root: Path | str,
    notes_dir: str = "notes",
    repo_name: str | None = None,
    remote: str = "origin",
    safety_gate: bool = True,
    parallel_mode: bool = True,
    worker: str | None = None,
    plugin_root: Path = method_sync.PLUGIN_ROOT,
) -> InitResult:
    # Resolved so a relative --root (".") compares equal to the absolute
    # paths the config loader returns. Without this, a repository that
    # already had a config crashed on `notes_dir.relative_to(root)` — every
    # test passed because tests always hand in absolute tmp paths.
    root = Path(root).resolve()
    repo_name = repo_name or root.name
    result = InitResult()

    # A repository that already has a config has already decided where its
    # documents live. Ignoring that would scatter a second, empty skeleton
    # beside the real one — which is exactly the copy drift this exists to
    # remove.
    existing = notes_config._config_path(root)
    if existing is not None:
        cfg = notes_config.load(root)
        notes_dir = cfg.notes_dir.relative_to(root).as_posix() if cfg.notes_dir != root else "."
        safety_gate = cfg.modules.get("safetyGate", safety_gate)
        parallel_mode = cfg.parallel_mode
        board_name = cfg.board
        decisions_rel = cfg.decisions_relative
        doc_root = cfg.doc_roots_relative[0]
        adr_style = cfg.adr_style
    else:
        cfg = None
        board_name = "PROGRESS.md"
        decisions_rel = "docs/decisions"
        doc_root = "docs"
        adr_style = "adr-prefixed"

    notes = root if notes_dir == "." else root / notes_dir
    wants_archive = cfg.modules.get("archive", True) if cfg is not None else True

    # The skeleton documents describe the layout they were written into, so
    # the paths and the ADR id rule come from the config rather than being
    # spelled as the default layout — a flat repository got an index claiming
    # its board was docs/PROGRESS.md and its ids were date-style.
    board_rel = (
        board_name
        if cfg is not None and (notes / board_name).is_file()
        else f"{doc_root}/{board_name}"
    )
    # The pointer documents name paths a person will follow. Spelling the
    # default layout there sent a flat repository's CLAUDE.md pointing at a
    # docs/PROGRESS.md it does not have — the one file whose whole job is to
    # say where things are.
    notes_prefix = "" if notes_dir == "." else f"{notes_dir}/"
    fields = {
        "repoName": repo_name,
        "notesDir": notes_dir,
        "notesPrefix": notes_prefix,
        "boardFull": f"{notes_prefix}{board_rel}",
        "decisionsFull": f"{notes_prefix}{decisions_rel}/",
        "gateFull": f"{notes_prefix}{doc_root}/SAFETY_GATE.md",
        "archiveClause": (
            f", 완결 서사 `{notes_prefix}{doc_root}/archive/`" if wants_archive else ""
        ),
        "remote": remote,
        "today": date.today().isoformat(),
        "boardPath": board_rel,
        "decisionsIndex": f"{decisions_rel}/README.md",
        "archiveRef": f" · 아카이브 `{doc_root}/archive/`" if wants_archive else "",
        "adrIdRule": (
            "`NNN-slug.md`. 인용은 `decisions/NNN` 또는 `ADR-NNN` — 숫자만 적은 것은 인용이 아니다"
            if adr_style == "numbered"
            else "`ADR-YYMMDD-<작업자id>-slug.md`. 인용은 확장자 뺀 파일명 전체"
        ),
    }

    # The config comes first: everything else reads the layout from it.
    if cfg is None:
        rendered = _template("girok.json").format(
            safetyGate="true" if safety_gate else "false",
            parallelMode="true" if parallel_mode else "false",
            **fields,
        )
        if worker:
            email = read_git_email(root) or f"{worker}@example.invalid"
            data = json.loads(rendered)
            data["workers"] = {worker: email}
            data["mergeOwner"] = worker
            rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        _write(root / ".claude" / "girok.json", rendered, result, root)

    pointer = _template("CLAUDE.md.pointer").format(**fields)
    pointer = _keep_gate_section(pointer) if safety_gate else _strip_gate_section(pointer)
    _write(notes / "CLAUDE.md", pointer, result, root)

    for name in ("GEMINI.md", "AGENTS.md"):
        _write(notes / name, _template(name).format(**fields), result, root)

    board_path = (
        notes / board_name
        if cfg is not None and (notes / board_name).is_file()
        else notes / doc_root / board_name
    )
    _write(board_path, _template("PROGRESS.md").format(**fields), result, root)
    _write(
        notes / decisions_rel / "README.md",
        _template("decisions/README.md").format(**fields),
        result, root,
    )
    if safety_gate:
        _write(
            notes / doc_root / "SAFETY_GATE.md",
            _template("SAFETY_GATE.md").format(**fields),
            result, root,
        )

    archive = notes / doc_root / "archive"
    if wants_archive and not archive.exists():
        archive.mkdir(parents=True, exist_ok=True)
        (archive / ".gitkeep").write_text("", encoding="utf-8")
        result.created.append((archive / ".gitkeep").relative_to(root).as_posix())

    # Only when the notes have a folder of their own. At a repository root
    # this file would claim the folder holds no code while sitting next to
    # the source, and it would start ignoring that project's own artifacts.
    if notes.resolve() != root.resolve():
        _write(
            notes / ".gitignore",
            "# 이 폴더는 문서 전용이다 — 코드·바이너리가 섞이는 사고를 여기서 막는다\n"
            "*.exe\n*.dll\n*.pdb\n*.zip\nbin/\nobj/\n",
            result, root,
        )

    # Only a parallel repository has per-worker folders. Keying this off
    # `worker` alone gave a non-parallel repository that happened to have a
    # `workers` entry a `docs_<id>/` it had to delete by hand.
    if worker and parallel_mode:
        _init_worker(notes, worker, fields, result, root)

    # sync writes the snapshot and registers its hooks in one step. Split in
    # two, a repository could sit with the hooks committed and nothing
    # registering them -- rules present, nothing enforcing, no sign of it.
    settings = root / ".claude" / "settings.json"
    existed = settings.is_file()
    sync_result = method_sync.sync(root, plugin_root)
    result.created.append(f"{notes_dir}/.method/")

    rel = ".claude/settings.json"
    if sync_result.settings_problem:
        result.problems.append(sync_result.settings_problem)
    elif not sync_result.settings_changed:
        result.skipped.append(rel)
    elif existed:
        result.updated.append(rel)
    else:
        result.created.append(rel)
    return result


def _init_worker(notes: Path, worker: str, fields: dict, result: InitResult, root: Path) -> None:
    """A personal folder for parallel work.

    The board gets a stamp: merges pick the newer copy by that line, so a
    worker board without one cannot be merged safely.
    """
    folder = notes / f"docs_{worker}"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    board = _template("PROGRESS.md").format(**{**fields, "repoName": f"{fields['repoName']} ({worker})"})
    lines = board.splitlines()
    lines.insert(1, "")
    lines.insert(2, f"> 최종 수정: {stamp} · {worker}")
    _write(folder / "PROGRESS.md", "\n".join(lines) + "\n", result, root)
    _write(folder / "decisions" / "README.md", _template("decisions/README.md").format(**fields), result, root)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--notes-dir", default="notes")
    parser.add_argument("--repo-name", default=None)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--no-safety-gate", action="store_true")
    parser.add_argument("--no-parallel", action="store_true")
    parser.add_argument("--worker", default=None)
    parser.add_argument(
        "--confirm",
        default=None,
        help="쓸 저장소의 폴더 이름. 이름이 맞지 않으면 아무것도 만들지 않는다",
    )
    args = parser.parse_args(argv)

    # A repository can be read-only by agreement rather than by permission —
    # a reference checkout, or one someone has been told not to touch.
    # Nothing inside it says so, so the caller has to name what it is about
    # to write to. This exists because a repository under exactly that
    # instruction would otherwise have been initialized on a single command.
    root = Path(args.root).resolve()

    # Claude Code has no repository picker: the folder it was started in is
    # the subject. Being started one level too high is an ordinary mistake,
    # and initializing a directory that merely contains repositories would
    # scatter a skeleton across somebody's workspace.
    if not notes_config.load(root).is_repository:
        print(f"[중단] `{root}` 는 저장소가 아니다 — `.git` 이 없다.")
        print("  둘 중 하나다:")
        print("  ① 한 단계 위에서 켰다 — Claude Code 는 켠 폴더를 대상으로 삼는다.")
        print("     작업할 저장소 폴더로 이동해 다시 실행할 것.")
        print("  ② 이 프로젝트가 아직 git 을 쓰지 않는다 — `git init` 을 먼저 할 것.")
        print("     이 방법론은 판본 추적·병합·커밋 즉시 push 를 git 에 의존한다.")
        return 1

    if args.confirm != root.name:
        print(f"[중단] `{root}` 에 아무것도 만들지 않았다.")
        print("  이 저장소에 진행기록 체계를 만들려면 이름을 확인해 다시 실행할 것:")
        print(f"    --confirm {root.name}")
        print("  참고 저장소·읽기 전용으로 합의된 저장소라면 여기서 멈추는 것이 맞다.")
        return 1

    result = init(
        args.root,
        notes_dir=args.notes_dir,
        repo_name=args.repo_name,
        remote=args.remote,
        safety_gate=not args.no_safety_gate,
        parallel_mode=not args.no_parallel,
        worker=args.worker,
    )

    for rel in result.created:
        print(f"[생성] {rel}")
    for rel in result.updated:
        print(f"[갱신] {rel}")
    for rel in result.skipped:
        print(f"[유지] {rel} — 이미 있어서 건드리지 않음")
    for problem in result.problems:
        print(f"[실패] {problem}")
    print(json.dumps({
        "created": len(result.created),
        "updated": len(result.updated),
        "kept": len(result.skipped),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
