"""Documentation linter for the notes methodology.

Four checks, each added after the corresponding mistake reached a commit:

1. **Table of contents anchors** — a hand-written TOC drifts from the
   headings it points at, leaving links that quietly stop working.
2. **GFM table continuity** — a blank line between rows breaks the table,
   and everything after it renders as plain text while still looking like a
   table in the editor.
3. **ADR citation integrity** — citations of decisions that do not exist,
   and decision files missing from their index.
4. **Size** — documents read in full every session, measured in bytes.

The slug function only approximates GitHub's, so it cannot promise that an
anchor works on GitHub. It does reliably answer the question that matters:
do the TOC and the headings point at the same thing.

    python check_docs.py                 # the whole notes tree
    python check_docs.py docs/PROGRESS.md
"""
import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import notes_config

# Frozen at the moment they were moved, so reformatting them is out of scope.
SKIP_DIRS = {"archive", "screenshots", ".method"}

TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

# Legacy ADR-NNN alongside the date style ADR-YYMMDD-<worker>-slug. The date
# style cites the whole filename minus the extension, so two ADRs written by
# the same person on the same day stay distinguishable by their slug.
ADR_REF = re.compile(r"ADR-(\d{6}-[a-z0-9]+(?:-[a-z0-9]+)+|\d{3}(?!\d))")

# The "numbered" style: files are NNN-slug.md. Only explicit citations count
# — `decisions/015`, `ADR-015`, `ADR 015`. A bare number is not a citation
# here: every figure in the prose would look like one and the false
# positives would bury the real findings.
NUMBERED_REF = re.compile(r"(?:decisions/|ADR[- ])(\d{3})(?!\d)")
NUMBERED_FILE = re.compile(r"^(\d{3})-")

# A drive-letter or UNC path written into prose. Machines differ, so a path
# that is true here is false on a teammate's checkout. Registry keys are
# excluded: the key *is* the value, not a location on this machine.
#
# The path body is ASCII only and excludes spaces on purpose. `\w` matches
# Hangul, and with a space in the class the match ran on into the surrounding
# prose — the "path" it reported was the rest of the sentence. `C:\Program
# Files\x` is reported as `C:\Program`, which is still enough to find it.
_SEGMENT = r"[A-Za-z0-9_.$*-]"
ABSOLUTE_PATH_RE = re.compile(
    rf"(?<![\w:])(?:[A-Za-z]:(?:\\{_SEGMENT}+)+|\\\\{_SEGMENT}+(?:\\{_SEGMENT}+)+)"
)
REGISTRY_RE = re.compile(r"HK(?:EY_)?[A-Z_]*")

GATE_NAME = "SAFETY_GATE.md"
GATE_ROW_RE = re.compile(r"^\s*\|\s*\d+[a-z]?\s*\|")

# Below this a document does not benefit from a table of contents, and asking
# for one would train people to ignore the warning.
TOC_MIN_BYTES = 1500

# A decision that lives in another repository, written `repo-name`의 ADR-020
# (or, under the numbered style, `repo-name`의 decisions/020). Nothing here
# can verify it, so it is excluded rather than reported as dead.
FOREIGN_ADR = re.compile(r"`[\w.-]+`\S*\s*(?:ADR-[\w-]+|decisions/\d{3}(?!\d))")

# The same citation written with a space before the particle. Korean particles
# attach to the word before them, so this is a spacing mistake rather than a
# dead reference — and saying "존재하지 않는 … 인용" for it sent one reader
# hunting for a bug in this checker and another deleting the particle to get
# past it. Matched separately so the message can name the real cause.
FOREIGN_ADR_SPACED = re.compile(
    r"`[\w.-]+`\s+\S*\s*(?:ADR-[\w-]+|decisions/\d{3}(?!\d))"
)


@dataclass
class Problem:
    path: str
    message: str


@dataclass
class Result:
    failures: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def slug(text: str) -> str:
    """Approximation of GitHub's heading slug.

    Markdown emphasis and code syntax are stripped first; letters (including
    Hangul), digits, spaces and hyphens survive; then **each** remaining
    whitespace character becomes one hyphen.

    Collapsing runs of whitespace instead would hide the mistake this check
    exists for: a header written `제목 — 부제` loses the em dash and keeps
    both spaces, so GitHub's anchor is `제목--부제` while a hand-written TOC
    almost always says `제목-부제`. The link is dead and looks fine.
    """
    t = re.sub(r"[`*]", "", text)
    t = t.lower()
    t = re.sub(r"[^\w\s\-]", "", t, flags=re.UNICODE)
    return re.sub(r"\s", "-", t.strip())


def lines_outside_fence(text: str):
    """Yield (line number, line) for lines outside fenced code blocks.

    Fence length is tracked rather than toggled: per CommonMark a closing
    fence must be at least as long as the opening one. Treating a shorter
    inner fence as the closer swallows the rest of the document.
    """
    fence_len = 0
    for no, line in enumerate(text.splitlines(), 1):
        opened = re.match(r"^\s*(`{3,}|~{3,})", line)
        if opened:
            n = len(opened.group(1))
            if fence_len == 0:
                fence_len = n
            elif n >= fence_len:
                fence_len = 0
            continue
        if fence_len > 0:
            continue
        yield no, line


def heading_slugs(text: str) -> set[str]:
    seen: dict[str, int] = {}
    slugs: set[str] = set()
    for _, line in lines_outside_fence(text):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not m:
            continue
        s = slug(m.group(2).strip())
        if s in seen:
            seen[s] += 1
            s = f"{s}-{seen[s]}"
        else:
            seen[s] = 0
        slugs.add(s)
    return slugs


def broken_tables(text: str) -> list[int]:
    """Line numbers where a run of pipe-wrapped lines lacks a separator row.

    A GFM table is a header row, a separator row and body rows with no blank
    line between them. A blank line mid-table leaves the rows after it as a
    separate run with no separator — that run is the orphan reported here.
    """
    orphans: list[int] = []
    block: list[tuple[int, str]] = []
    for no, line in list(lines_outside_fence(text)) + [(0, "")]:
        if TABLE_ROW.match(line):
            block.append((no, line))
            continue
        if block:
            if len(block) < 2 or not TABLE_SEP.match(block[1][1]):
                orphans.append(block[0][0])
            block = []
    return orphans


def _lone_carriage_returns(raw: bytes) -> int:
    """Carriage returns that are not part of a CRLF line ending.

    CRLF is normal on Windows and renders fine. A lone CR is the defect: it
    splits the line, so a table cell containing one breaks the table from
    that point on — and no editor shows it.
    """
    return raw.count(b"\r") - raw.count(b"\r\n")


def _absolute_paths(text: str) -> list[str]:
    """Drive-letter and UNC paths in prose, outside code fences.

    Fenced blocks are exempt: install instructions and command examples are
    where a real path belongs, and flagging them would train people to
    ignore this warning.
    """
    found: list[str] = []
    for _, line in lines_outside_fence(text):
        for match in ABSOLUTE_PATH_RE.finditer(line):
            before = line[: match.start()]
            if REGISTRY_RE.search(before[-24:]):
                continue
            found.append(match.group(0))
    return found


TOC_HEADING_RE = re.compile(r"^##\s+(?:목차|Contents|Table of contents)\s*$", re.M | re.I)
# The section ends at the next heading or the next horizontal rule. The
# earlier form required a blank line before one of those, so a document whose
# table of contents was the last section — or was followed by a heading with
# no blank line — read as having none: the anchors went unchecked *and* the
# document was warned for a table of contents it already had.
TOC_END_RE = re.compile(r"^(?:#{1,6}\s|-{3,}\s*$)", re.M)


def toc_anchors(text: str) -> list[str] | None:
    """Anchors used inside the `## 목차` section, or None if there is none."""
    m = TOC_HEADING_RE.search(text)
    if not m:
        return None
    rest = text[m.end():]
    end = TOC_END_RE.search(rest)
    section = rest[: end.start()] if end else rest
    return re.findall(r"\]\(#([^)]+)\)", section)


def adr_ids_in_dir(d: Path, style: str = "adr-prefixed") -> set[str]:
    ids = set()
    if style == "numbered":
        for f in d.glob("[0-9][0-9][0-9]-*.md"):
            if m := NUMBERED_FILE.match(f.name):
                ids.add(m.group(1))
        return ids
    for f in d.glob("ADR-*.md"):
        if m := re.match(r"ADR-(\d{3})-", f.name):
            ids.add(m.group(1))
        elif m := re.match(r"ADR-(\d{6}-[a-z0-9]+(?:-[a-z0-9]+)+)\.md$", f.name):
            ids.add(m.group(1))
    return ids


def _citations(text: str, style: str) -> set[str]:
    if style == "numbered":
        return set(NUMBERED_REF.findall(text))
    return set(ADR_REF.findall(text))


def _is_skipped(path: Path, cfg: notes_config.NotesConfig) -> bool:
    skipped = SKIP_DIRS.union(cfg.skip_dirs)
    try:
        parts = path.relative_to(cfg.notes_dir).parts
    except ValueError:
        parts = path.parts
    return any(p in skipped for p in parts)


def documents(cfg: notes_config.NotesConfig) -> list[Path]:
    """Every document the linter is responsible for.

    Root documents are matched non-recursively: in a layout where the notes
    root is the repository root, recursing would drag in every README in the
    source tree and bury the findings that matter.
    """
    found: list[Path] = []
    for pattern in cfg.root_docs:
        found.extend(sorted(p for p in cfg.notes_dir.glob(pattern) if p.is_file()))

    for root in [*cfg.doc_roots(), *cfg.worker_dirs()]:
        if not root.is_dir():
            continue
        found.extend(sorted(p for p in root.rglob("*.md") if not _is_skipped(p, cfg)))

    # A document can match both a root pattern and a doc root; keep the
    # first occurrence so it is not linted, and reported, twice.
    return list(dict.fromkeys(found))


def adr_dirs(cfg: notes_config.NotesConfig) -> list[Path]:
    dirs = [cfg.decisions_dir]
    dirs.extend(w / "decisions" for w in cfg.worker_dirs())
    return [d for d in dirs if d.is_dir()]


def _check_toc_missing(
    path: Path, text: str, rel: str, cfg: notes_config.NotesConfig, result: Result
) -> None:
    """The rule asks every document for a `## 목차`, decisions excepted.

    Two exemptions, both from the rule itself: a decision card is short by
    design, and a note below the threshold does not benefit from one.
    Demanding a table of contents on a ten-line note would train people to
    ignore this warning, and then it protects nothing.
    """
    if any(_under(path, d) for d in adr_dirs(cfg)):
        return
    threshold = int(cfg.limits_kb.get("tocMin", TOC_MIN_BYTES / 1000) * 1000)
    if len(text.encode("utf-8")) < threshold:
        return
    result.warnings.append(
        Problem(rel, f"`## 목차` 가 없다 ({len(text.encode('utf-8')):,}바이트) — 앵커 링크가 걸린 목차를 둘 것")
    )


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def gate_table_rows(text: str):
    """Yield `(row, line)` for every gate item row, row keyed by column name.

    The header is found by its 확인자 and 상태 columns rather than by
    position, so a layout that adds a column still parses. Rows whose cell
    count does not match the header are skipped — that is a broken table, and
    the table checks report it separately.

    Nothing is yielded when no header is found. Callers that must stay
    fail-safe (the motion block) fall back to a raw line scan there.
    """
    header: list[str] | None = None
    for _, line in lines_outside_fence(text):
        cells = [c.strip() for c in line.split("|")]
        if header is None:
            if "확인자" in cells and "상태" in cells:
                header = cells
            continue
        if not GATE_ROW_RE.match(line) or len(cells) != len(header):
            continue
        yield dict(zip(header, cells)), line


def _check_gate_rows(text: str, rel: str, result: Result) -> None:
    """A CLOSED gate item must name who confirmed it and when.

    This is the check the whole design exists for. An item marked CLOSED with
    an empty confirmer column is an unverified condition that reads as
    verified — and the next person reads the badge, not the blank cell.
    """
    for row, _line in gate_table_rows(text):
        if "CLOSED" not in row.get("상태", ""):
            continue
        number = row.get("#", "?")
        if not row.get("확인자"):
            result.failures.append(
                Problem(rel, f"게이트 #{number} 가 CLOSED 인데 확인자가 비어 있다 — 확인되지 않은 항목이 확인된 것으로 읽힌다")
            )
        if not row.get("날짜"):
            result.failures.append(
                Problem(rel, f"게이트 #{number} 가 CLOSED 인데 날짜가 비어 있다 — 언제 확인했는지 되짚을 수 없다")
            )


def check_document(
    path: Path,
    cfg: notes_config.NotesConfig,
    result: Result,
    texts: dict[Path, str] | None = None,
) -> None:
    rel = _rel(path, cfg)
    # One read per document. The bytes are decoded here rather than read a
    # second time through `read_text`, and handed to the citation pass so a
    # full-tree run does not read every file twice.
    raw = path.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if texts is not None:
        texts[path] = text
    result.checked.append(rel)

    # A carriage return that is not part of a CRLF line ending. Found
    # twice in real documents, both inside a table cell holding a Windows
    # path whose backslash-r was written as an actual CR. It splits the
    # line and breaks the table, and no editor shows it.
    lone_cr = _lone_carriage_returns(raw)
    if lone_cr > 0:
        result.failures.append(
            Problem(
                rel,
                f"줄바꿈이 아닌 캐리지 리턴이 {lone_cr}개 있다 — 줄이 쪼개져 표가 끊긴다. "
                "편집기에는 보이지 않으니 경로에 이스케이프가 실제 문자로 들어갔는지 확인할 것",
            )
        )

    # GitHub reads a leading `---` as Jekyll front matter and the page fails
    # to render at all. The rule says put the title first; nothing checked it.
    if text.lstrip("﻿").startswith("---"):
        result.failures.append(
            Problem(
                rel,
                "문서가 `---` 로 시작한다 — GitHub 이 Jekyll front matter 로 오인해 "
                "렌더링이 깨진다. `# 제목` 을 먼저 둘 것",
            )
        )

    for line_no in broken_tables(text):
        result.failures.append(
            Problem(rel, f"표가 빈 줄로 끊김 — {line_no}번째 줄부터의 행이 표 밖 텍스트로 렌더링됨")
        )

    if path.name == GATE_NAME and cfg.modules.get("safetyGate", True):
        _check_gate_rows(text, rel, result)

    anchors = toc_anchors(text)
    if anchors is None:
        _check_toc_missing(path, text, rel, cfg, result)
    else:
        valid = heading_slugs(text)
        for bad in [a for a in anchors if a not in valid]:
            hint = ""
            if bad.replace("-", "") in {v.replace("-", "") for v in valid}:
                hint = " — 헤더의 공백으로 감싼 구분 문자(` — `·` · `)가 앵커에 빈 하이픈을 남김. 앞 단어에 붙여 쓸 것"
            result.failures.append(Problem(rel, f"목차 앵커 `#{bad}` 에 대응하는 헤더가 없음{hint}"))

    for found in _absolute_paths(text):
        result.warnings.append(
            Problem(
                rel,
                f"문서에 로컬 절대경로가 있다 ({found}) — 머신마다 달라진다. "
                f"저장소를 가리킬 땐 저장소 이름만 쓸 것",
            )
        )

    limit = cfg.size_limit_bytes(path.name)
    if limit is not None:
        size = path.stat().st_size
        if size > limit:
            result.warnings.append(
                Problem(rel, f"{path.name} {size:,}바이트 (기준 {limit:,} 초과) — 완결된 서사를 archive/ 로 옮길 것")
            )


def check_adr_citations(
    cfg: notes_config.NotesConfig, result: Result, texts: dict[Path, str] | None = None
) -> None:
    dirs = adr_dirs(cfg)
    if not dirs:
        return
    style = cfg.adr_style
    label = "" if style == "numbered" else "ADR-"
    existing = set().union(*(adr_ids_in_dir(d, style) for d in dirs))
    texts = texts if texts is not None else {}

    for path in documents(cfg):
        raw_text = texts.get(path)
        if raw_text is None:
            raw_text = path.read_text(encoding="utf-8")
        text = FOREIGN_ADR.sub("", raw_text)
        # Citations that survive only because the particle was written apart
        # from the repository name. Those get a message about the spacing.
        forgiving = _citations(FOREIGN_ADR_SPACED.sub("", text), style)
        for ref in sorted(_citations(text, style) - existing):
            if ref not in forgiving:
                message = (
                    f"{label}{ref} 인용의 조사가 저장소명에서 떨어져 있다 — "
                    f"`저장소명`의 처럼 붙여 쓸 것"
                )
            else:
                message = f"존재하지 않는 {label}{ref} 인용"
            result.failures.append(Problem(_rel(path, cfg), message))

    for d in dirs:
        readme = d / "README.md"
        if not readme.is_file():
            continue
        # The index links each decision, so read ids from the links rather
        # than from prose: under the numbered style a citation regex over
        # the whole file would also match the dates and counts in the table.
        indexed = {m.group(1) or m.group(2) or m.group(3) for m in re.finditer(
            r"\((?:\./)?(?:ADR-(\d{3})-|ADR-(\d{6}-[a-z0-9]+(?:-[a-z0-9]+)+)|(\d{3})-)[^)]*\)",
            readme.read_text(encoding="utf-8"),
        )}
        for missing in sorted(adr_ids_in_dir(d, style) - indexed):
            result.failures.append(
                Problem(_rel(readme, cfg), f"{label}{missing} 가 인덱스에 미등재")
            )


def _rel(path: Path, cfg: notes_config.NotesConfig) -> str:
    try:
        return path.relative_to(cfg.repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def run(start: Path | str = ".", targets: list[Path] | None = None) -> Result:
    cfg = notes_config.load(start)
    result = Result()

    # Otherwise this passes with nothing checked, which reads as "the
    # documents are fine" when in fact none were found.
    if not cfg.is_repository and targets is None:
        result.failures.append(
            Problem(
                cfg.repo_root.as_posix(),
                "여기는 저장소가 아니다 — `.git` 이 없다. 검사한 문서가 0개다. "
                "켠 폴더가 한 단계 위가 아닌지 확인하고, 아직 git 을 안 쓰는 "
                "프로젝트라면 `git init` 을 먼저 할 것",
            )
        )
        return result

    paths = targets if targets else documents(cfg)
    texts: dict[Path, str] = {}
    for path in paths:
        if not path.is_file():
            result.warnings.append(Problem(str(path), "파일 없음 — 건너뜀"))
            continue
        check_document(path, cfg, result, texts)

    if targets is None:
        check_adr_citations(cfg, result, texts)
    return result


def _force_utf8_output() -> None:
    """Windows consoles default to a legacy code page (cp949 on Korean
    installs) that cannot encode the em dashes and Hangul in these messages,
    and the linter would die on its own output. Reconfiguring is enough;
    errors="replace" keeps a redirected pipe from crashing either.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="검사할 파일 (생략하면 전체)")
    parser.add_argument("--root", type=Path, default=Path("."), help="탐색 시작 경로")
    args = parser.parse_args(argv)

    result = run(args.root, args.files or None)

    for problem in result.failures:
        print(f"[실패] {problem.path} -> {problem.message}")
    for problem in result.warnings:
        print(f"[주의] {problem.path} -> {problem.message}")

    if result.failures:
        print(f"\n{len(result.checked)}개 문서 검사, {len(result.failures)}건 실패")
        return 1
    print(f"\n{len(result.checked)}개 문서 검사, 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
