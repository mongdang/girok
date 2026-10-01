"""Reading an existing repository before changing anything.

`/notes` used to create the default skeleton and leave whatever was already
there sitting beside it. Choosing the right layout for the second repository
to adopt this took a person reading the repository; the plugin could not do
it, so adopting into a project with its own conventions would have produced a
second, empty set of documents next to the real ones.

This proposes a layout and reports what it noticed. It never writes. Getting
the mapping wrong is cheap while it is a proposal and expensive once it is a
file tree, so the output is something a person approves – not applies.

    python notes_survey.py            # 사람이 읽는 보고
    python notes_survey.py --json     # /notes 가 읽는 제안
"""
import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import notes_config

SKIP_DIRS = {
    ".git", ".vs", ".idea", "__pycache__", "node_modules", ".pytest_cache",
    "bin", "obj", "build", "dist", "packages", "target", ".venv", ".method",
}

# Names that suggest "the current state of this project", most specific first.
BOARD_HINTS = ("PROGRESS", "STATE", "STATUS", "현황")
BOARD_SECTION_HINTS = ("일자별", "상태 요약", "활성 위험", "열린 질문", "지금 상태", "한 줄")

DECISIONS_DIR_NAMES = ("decisions", "adr", "adrs", "decision")
GATE_NAMES = ("SAFETY_GATE.md", "SAFETY-GATE.md")
SAFETY_MARKERS = ("SAFETY-STUB", "VIRTUAL-BYPASS")
HARDWARE_HINTS = ("interlock", "인터락", "원점복귀", "homing", "emergency stop", "비상정지")

CODE_SUFFIXES = {".cs", ".cpp", ".c", ".h", ".py", ".ts", ".js", ".java", ".go", ".rs", ".ps1"}

ADR_PREFIXED = re.compile(r"^ADR-(?:\d{3}|\d{6})[-.]")
ADR_NUMBERED = re.compile(r"^\d{3}-")

NO_ARCHIVE_HINT = re.compile(r"아카이브\s*폴더를?\s*만들지\s*않는다")

# A document below this does not carry a board's worth of content.
BOARD_MIN_BYTES = 400


@dataclass
class Finding:
    message: str


@dataclass
class Survey:
    repo_root: Path
    proposal: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    configured: bool = False
    documents: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.findings.append(Finding(message))


def _walk(root: Path):
    """Every folder and file under `root`, with skipped folders pruned.

    `rglob("*")` walks into `.git` and `node_modules` and discards them
    afterwards – on a real checkout that is most of the traversal, and this
    runs before anything else `/notes` does.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        here = Path(dirpath)
        for name in dirnames:
            yield here / name
        for name in sorted(filenames):
            yield here / name


def _markdown(root: Path) -> list[Path]:
    return sorted(p for p in _walk(root) if p.is_file() and p.suffix.lower() == ".md")


def _notes_dir(root: Path) -> Path:
    """Where the documentation tree lives.

    Prefer a folder that holds both a `docs/` subfolder and its own rule file
    – that is the shape of a notes folder beside the source. Otherwise the
    repository root.
    """
    for path in sorted(_walk(root)):
        if not path.is_dir() or path.name in SKIP_DIRS:
            continue
        if (path / "docs").is_dir() and any(
            (path / name).is_file() for name in ("CLAUDE.md", "RULES.md", "AGENTS.md")
        ):
            return path
    return root


def _doc_roots(notes_dir: Path) -> list[str]:
    """Folders under the notes dir that actually hold documents and no code."""
    roots = []
    for child in sorted(p for p in notes_dir.iterdir() if p.is_dir()):
        if child.name in SKIP_DIRS or child.name.startswith("docs_"):
            continue
        files = [p for p in _walk(child) if p.is_file()]
        if not files:
            continue
        md = [p for p in files if p.suffix.lower() == ".md"]
        code = [p for p in files if p.suffix.lower() in CODE_SUFFIXES]
        if md and not code:
            roots.append(child.name)
    return roots or ["docs"]


def _board(
    notes_dir: Path, doc_roots: list[str], survey: Survey, decision_homes: set[Path]
) -> str | None:
    """The file that reads as "the current state of this project".

    Decision folders are excluded: a decision named
    `041-screen-shows-state-we-were-not-reading.md` matched on "state" and was
    proposed as the board the first time this ran for real.
    """
    places = [notes_dir] + [notes_dir / r for r in doc_roots]
    candidates: list[tuple[int, Path]] = []

    for place in places:
        if not place.is_dir() or place.resolve() in decision_homes:
            continue
        for path in sorted(place.glob("*.md")):
            if path.resolve().parent in decision_homes:
                continue
            score = 0
            stem = path.stem.upper()
            for rank, hint in enumerate(BOARD_HINTS):
                if hint in stem or hint in path.stem:
                    score += 10 - rank
            if score == 0:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text.encode("utf-8")) < BOARD_MIN_BYTES:
                continue
            score += sum(2 for hint in BOARD_SECTION_HINTS if hint in text)
            candidates.append((score, path))

    if not candidates:
        survey.note(
            "현황판으로 볼 문서를 찾지 못했다 – 지금 상태를 담는 문서가 없거나 이름이 "
            "다르다. 어느 파일이 현황판인지 알려주거나, 새로 만들 것"
        )
        return None

    candidates.sort(key=lambda c: (-c[0], c[1].name))
    best_score, best_path = candidates[0]

    # Any second candidate is worth naming. Picking silently between two files
    # that both look like the board is the one guess whose cost lands on
    # somebody else: every later session reads the wrong document.
    if len(candidates) > 1:
        others = ", ".join(p.name for _, p in candidates[1:])
        survey.note(
            f"현황판 후보가 여럿이다 – `{best_path.name}` 을 골랐고 다른 후보는 {others} 다. "
            f"틀렸으면 알려줄 것"
        )
    return best_path.name


def _decisions(notes_dir: Path, survey: Survey) -> tuple[str | None, str]:
    for path in sorted(_walk(notes_dir)):
        if not path.is_dir() or path.name.lower() not in DECISIONS_DIR_NAMES:
            continue
        files = sorted(p.name for p in path.glob("*.md"))
        prefixed = [n for n in files if ADR_PREFIXED.match(n)]
        numbered = [n for n in files if ADR_NUMBERED.match(n)]
        # A folder holding only an index still counts: the decisions may have
        # drifted out of it, which is exactly what the stray check is for.
        if not prefixed and not numbered and "README.md" not in files:
            continue

        rel = path.relative_to(notes_dir).as_posix()
        if not (path / "README.md").is_file():
            survey.note(
                f"`{rel}/` 에 결정이 {len(prefixed) + len(numbered)}건 있는데 "
                f"인덱스(`README.md`)가 없다 – 다른 문서가 ID로 인용할 근거가 없다"
            )
        style = "numbered" if len(numbered) > len(prefixed) else "adr-prefixed"
        return rel, style

    return None, "adr-prefixed"


def _decision_homes(notes_dir: Path, decisions_rel: str | None) -> set[Path]:
    """Every folder where a decision legitimately lives.

    During parallel work a decision belongs in `docs_<id>/decisions/` – the
    rules say so. Treating those as strays flagged eight correctly placed
    files the first time this ran on a real repository.
    """
    homes = set()
    if decisions_rel:
        homes.add((notes_dir / decisions_rel).resolve())
    for worker in notes_dir.glob("docs_*"):
        if worker.is_dir():
            homes.add((worker / "decisions").resolve())
    return homes


def _strays(notes_dir: Path, decisions_rel: str | None, survey: Survey) -> None:
    """Decision-shaped files sitting outside every decisions folder."""
    if decisions_rel is None:
        return
    homes = _decision_homes(notes_dir, decisions_rel)
    for path in _markdown(notes_dir):
        if path.resolve().parent in homes:
            continue
        if ADR_PREFIXED.match(path.name):
            survey.note(
                f"`{path.name}` 가 결정 기록처럼 보이는데 `{decisions_rel}/` 밖에 있다 – "
                f"인덱스에 없으면 아무도 찾지 못한다"
            )


def _safety(root: Path, notes_dir: Path, doc_roots: list[str], survey: Survey) -> bool:
    for place in [notes_dir] + [notes_dir / r for r in doc_roots]:
        for name in GATE_NAMES:
            if (place / name).is_file():
                return True

    for path in _walk(root):
        if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for marker in SAFETY_MARKERS:
            if marker in text:
                survey.note(
                    f"코드에 `{marker}` 가 있는데 안전 게이트 문서가 없다 – 등재되지 않은 "
                    f"안전 우회다. 안전 모듈을 켜고 게이트에 등재할 것"
                )
                return True
        lowered = text.lower()
        if any(hint in lowered for hint in HARDWARE_HINTS):
            survey.note(
                "코드에 인터락·모션 관련 표현이 있다 – 실장비를 제어하는 프로젝트라면 "
                "안전 모듈을 켜는 쪽을 권한다"
            )
            return True
    return False


def _workers(root: Path, notes_dir: Path) -> dict:
    """Worker ids from existing `docs_<id>/` folders, emails from git."""
    ids = sorted(p.name[len("docs_"):] for p in notes_dir.glob("docs_*") if p.is_dir())
    emails = _git_authors(root)
    workers = {}
    for worker in ids:
        match = next((e for e in emails if e.split("@")[0].lower() == worker.lower()), None)
        workers[worker] = match or f"{worker}@example.invalid"
    return workers


def _git_authors(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "log", "--format=%ae", "-n", "400"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    seen: dict[str, None] = {}
    for line in result.stdout.split():
        seen.setdefault(line.strip(), None)
    return list(seen)


def _archive(notes_dir: Path, doc_roots: list[str], markdown: list[Path], survey: Survey) -> bool:
    for path in markdown:
        text = path.read_text(encoding="utf-8", errors="replace")
        if NO_ARCHIVE_HINT.search(text):
            survey.note(
                f"`{path.name}` 가 아카이브 폴더를 만들지 않는다고 못 박아 뒀다 – "
                f"그 관례를 따라 archive 모듈을 끈다"
            )
            return False
    for place in [notes_dir] + [notes_dir / r for r in doc_roots]:
        if (place / "archive").is_dir():
            return True
    return True


def _sizes(notes_dir: Path, board: str | None, markdown: list[Path], survey: Survey) -> None:
    limits = {"board": 30_000, "rules": 20_000}
    for path in markdown:
        limit = None
        if board and path.name == board:
            limit = limits["board"]
        elif path.name in ("CLAUDE.md", "RULES.md", "METHOD.md"):
            limit = limits["rules"]
        if limit is None:
            continue
        size = path.stat().st_size
        if size > limit:
            survey.note(
                f"`{path.name}` 크기가 {size:,}바이트로 기준({limit:,})을 넘는다 – "
                f"완결된 서사를 아카이브로 옮길 때다"
            )


def run(start: Path | str = ".") -> Survey:
    cfg = notes_config.load(start)
    root = cfg.repo_root
    survey = Survey(repo_root=root)

    markdown = _markdown(root)
    survey.documents = [p.relative_to(root).as_posix() for p in markdown]

    notes_dir = _notes_dir(root)
    doc_roots = _doc_roots(notes_dir)
    decisions_rel, adr_style = _decisions(notes_dir, survey)
    homes = _decision_homes(notes_dir, decisions_rel)
    board = _board(notes_dir, doc_roots, survey, homes)
    _strays(notes_dir, decisions_rel, survey)
    safety = _safety(root, notes_dir, doc_roots, survey)
    workers = _workers(root, notes_dir)
    archive = _archive(notes_dir, doc_roots, markdown, survey)
    _sizes(notes_dir, board, markdown, survey)

    notes_rel = "." if notes_dir.resolve() == root.resolve() else notes_dir.relative_to(root).as_posix()
    root_docs = sorted(p.name for p in notes_dir.glob("*.md"))

    survey.proposal = {
        "notesDir": notes_rel,
        "repoName": root.name,
        "remote": _remote(root),
        "board": board,
        "decisionsDir": decisions_rel or "docs/decisions",
        "docRoots": doc_roots,
        "rootDocs": root_docs or ["CLAUDE.md", "RULES.md"],
        "rulesDocs": [n for n in root_docs if n in ("CLAUDE.md", "RULES.md", "METHOD.md")]
        or ["CLAUDE.md", "RULES.md"],
        "adrStyle": adr_style,
        "workers": workers,
        "mergeOwner": next(iter(workers), None),
        "modules": {"safetyGate": safety, "archive": archive},
        # Worker folders only. Several author emails is not evidence of several
        # people – one person on a laptop, a desktop and a notebook runtime
        # produces four. Turning parallel mode on for that would block every
        # write until `workers` named identities that are all the same person.
        "parallelMode": bool(workers),
        "readOnlyRepos": [],
    }

    authors = _git_authors(root)
    if not workers and len(authors) > 1:
        survey.note(
            f"커밋 이메일이 {len(authors)}개다 ({', '.join(authors[:4])}) – 사람이 여럿이면 "
            f"병행 작업을 켜고 `workers` 를 채울 것. 한 사람이 여러 머신을 쓰는 것이라면 "
            f"지금대로 끈 채 두면 된다"
        )

    survey.configured = cfg.source is not None
    if survey.configured:
        _compare(cfg, survey)

    return survey


def _remote(root: Path) -> str:
    try:
        names = subprocess.run(
            ["git", "remote"], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        ).stdout.split()
    except OSError:
        return "origin"
    if not names:
        return "origin"
    return "origin" if "origin" in names else names[0]


def _compare(cfg: notes_config.NotesConfig, survey: Survey) -> None:
    """A configured repository has already decided. Say whether the decision
    still matches what is on disk rather than proposing it again."""
    checks = (
        ("notesDir", cfg.notes_dir.name if cfg.notes_dir != cfg.repo_root else "."),
        ("board", cfg.board),
        ("adrStyle", cfg.adr_style),
    )
    for key, current in checks:
        proposed = survey.proposal.get(key)
        if proposed and current != proposed:
            survey.note(
                f"설정의 {key} 는 `{current}` 인데 저장소에서 보이는 것은 `{proposed}` 다 – "
                f"둘 중 하나가 낡았다"
            )

    # A module choice that was right at adoption can stop being right. The
    # safety module in particular: a research project grows hardware control
    # and nothing revisits the flag.
    for module, proposed in survey.proposal["modules"].items():
        current = cfg.modules.get(module, True)
        if current == proposed:
            continue
        survey.note(
            f"설정의 modules.{module} 는 `{'켬' if current else '끔'}` 인데 저장소를 보면 "
            f"`{'켬' if proposed else '끔'}` 쪽이다 – 도입 시점의 판단이 아직 맞는지 "
            f"확인할 것"
        )


def report(survey: Survey) -> list[str]:
    p = survey.proposal
    lines = [
        f"저장소: {survey.repo_root.name} · 문서 {len(survey.documents)}건",
        "",
        "제안하는 설정:",
        f"  진행기록 위치  {p['notesDir']}",
        f"  현황판        {p['board'] or '(찾지 못함)'}",
        f"  결정 기록      {p['decisionsDir']} ({p['adrStyle']})",
        f"  검사할 폴더    {', '.join(p['docRoots'])}",
        f"  안전 게이트    {'켬' if p['modules']['safetyGate'] else '끔'}",
        f"  아카이브       {'켬' if p['modules']['archive'] else '끔'}",
        f"  병행 작업      {'켬' if p['parallelMode'] else '끔'}"
        + (f" (작업자: {', '.join(p['workers'])})" if p["workers"] else ""),
    ]
    if survey.findings:
        lines += ["", f"살펴볼 것 {len(survey.findings)}건:"]
        lines += [f"  - {f.message}" for f in survey.findings]
    else:
        lines += ["", "살펴볼 것: 없음"]
    lines += [
        "",
        "이건 제안이다 – 아무것도 쓰지 않았다. 사람이 확인한 뒤 초기화할 것.",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true", help="제안을 JSON 으로")
    args = parser.parse_args(argv)

    survey = run(args.root)

    if args.json:
        print(json.dumps(
            {
                "proposal": survey.proposal,
                "findings": [f.message for f in survey.findings],
                "configured": survey.configured,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    for line in report(survey):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
