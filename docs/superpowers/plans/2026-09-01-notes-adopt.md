# notes_adopt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 저장소에 흩어져 있던 기록 문서를 하나도 잃지 않고 girok 체계로 옮기는 `notes_adopt.py` 를 만든다.

**Architecture:** `scripts/notes_adopt.py` 한 파일에 서브명령 넷(`backup`·`plan`·`apply`·`verify`)을 둔다. `method_sync.py` 의 `status/sync/verify` 와 같은 꼴이다. 판단(어느 문서를 어디로)은 `.claude/girok-adopt.json` 이라는 매핑 파일을 통해 사람·모델이 하고, 이동은 스크립트만 한다. 유실 방지는 통째 백업 + SHA-1 대조 + 병합 원문 줄 검사로 기계가 증명한다.

**Tech Stack:** Python 3.10+, 표준 라이브러리만(`argparse`·`hashlib`·`shutil`·`subprocess`·`re`·`json`·`dataclasses`). pytest. 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-09-01-notes-adopt-design.md`

## Global Constraints

- Python `>=3.10` (`pyproject.toml`). `X | None` 표기 사용 가능, `match` 는 쓰지 않는다.
- 새 서드파티 의존성 금지 — 표준 라이브러리만.
- 모든 파일 입출력은 `encoding="utf-8"`. 쓰기는 `newline="\n"` (`notes_init._write` 관례).
- 사용자에게 보이는 모든 문자열은 **한국어**. 코드 주석과 docstring은 **영어** (기존 `scripts/*.py` 관례).
- 테스트는 `tests/test_adopt_*.py`. `pyproject.toml` 의 `pythonpath = ["scripts", "hooks", "tests"]` 덕에 `import notes_adopt` 가 그냥 된다.
- `tests/conftest.py` 의 `write(path, text)` 헬퍼를 쓴다 — 부모 폴더를 만들고 앞 개행을 벗긴다.
- 기존 `notes_config._is_repository` 의 동작을 **바꾸지 않는다.** `session_report`·`check_docs`·`notes_init` 이 함께 쓰는 판정이다.
- `git mv` 만 쓴다. `shutil.move` + `git add` 조합은 금지 — 이력이 끊긴다.
- 파일 해시는 **SHA-1**, `hashlib.sha1(data).hexdigest()`, 바이트 그대로 (텍스트 정규화 없이).
- 날짜 스탬프 형식은 `YYYYMMDD` (`date.today().strftime("%Y%m%d")`).

## 목차

- [Task 1: 워크스페이스 판정](#task-1-워크스페이스-판정-is_workspace)
- [Task 2: backup](#task-2-backup--원본-통째-복사와-검증)
- [Task 3: plan](#task-3-plan--전수-목록과-role-분류)
- [Task 4: git 정비](#task-4-git-정비--init-과-gitignore)
- [Task 5: apply 사전조건과 이동](#task-5-apply-사전조건과-이동)
- [Task 6: 병합](#task-6-병합--이어붙이기)
- [Task 7: 링크 재작성](#task-7-링크-재작성)
- [Task 8: verify 와 조립](#task-8-verify-와-apply-조립)
- [Task 9: /notes 통합과 배포](#task-9-notes-통합과-배포)
- [실행 후 확인](#실행-후-확인--eq-agent-v3-실전-검증)

---

### Task 1: 워크스페이스 판정 `is_workspace`

`git init` 을 자동으로 하기 전에 "여기가 저장소 여러 개를 담은 상위 폴더인가"를 답해야 한다. 기존 `is_repository` 는 건드리지 않는다.

**Files:**
- Modify: `scripts/notes_config.py` (`_is_repository` 바로 아래에 추가)
- Test: `tests/test_adopt_workspace.py`

**Interfaces:**
- Consumes: `notes_config.SKIP_DIRS` 는 없다 — 이 함수는 자체 목록을 쓴다.
- Produces: `notes_config.is_workspace(root: Path) -> bool`

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_workspace.py`:

```python
"""Telling a project apart from a folder that merely holds projects.

`git init` run one level too high swallows every repository underneath it
into one. That is worse to undo than anything else this tool does, so it is
the one place that refuses instead of resolving.
"""
import notes_config
import pytest

from conftest import write


@pytest.fixture
def workspace(tmp_path):
    """A plain directory holding two unrelated repositories."""
    root = tmp_path / "workspace"
    for name in ("project-a", "project-b"):
        (root / name / ".git").mkdir(parents=True)
    return root


def test_a_folder_holding_two_repositories_is_a_workspace(workspace):
    assert notes_config.is_workspace(workspace)


def test_a_folder_holding_two_manifests_is_a_workspace(tmp_path):
    """Projects that do not use git still make their parent a workspace."""
    root = tmp_path / "workspace"
    write(root / "project-a" / "pyproject.toml", "[project]\n")
    write(root / "project-b" / "package.json", "{}\n")

    assert notes_config.is_workspace(root)


def test_a_single_repository_is_not_a_workspace(tmp_path):
    root = tmp_path / "solo"
    (root / ".git").mkdir(parents=True)
    write(root / "docs" / "README.md", "# 문서\n")

    assert not notes_config.is_workspace(root)


def test_a_notes_only_folder_is_not_a_workspace(tmp_path):
    """A records repository has no manifest. Requiring one would reject it."""
    root = tmp_path / "기록"
    write(root / "회의록.md", "# 회의록\n")
    write(root / "docs" / "설계.md", "# 설계\n")

    assert not notes_config.is_workspace(root)


def test_one_nested_repository_is_not_enough(tmp_path):
    """A vendored dependency does not make its parent a workspace."""
    root = tmp_path / "project"
    write(root / "pyproject.toml", "[project]\n")
    (root / "vendor" / "thirdparty" / ".git").mkdir(parents=True)

    assert not notes_config.is_workspace(root)


def test_the_repository_own_git_does_not_count(tmp_path):
    """Only *nested* repositories count, never the root's own."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "sub" / ".git").mkdir(parents=True)

    assert not notes_config.is_workspace(root)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_workspace.py -v`
Expected: FAIL — `AttributeError: module 'notes_config' has no attribute 'is_workspace'`

- [ ] **Step 3: Write minimal implementation**

`scripts/notes_config.py` 의 `_is_repository` 함수 바로 아래에 추가한다:

```python
# Files that mark a folder as a project in its own right. Used only to
# recognize a *parent* of several projects — never to require one, because a
# records repository has no manifest and rejecting those was the bug this
# replaced.
MANIFESTS = (
    "pyproject.toml", "package.json", "go.mod", "Cargo.toml",
    "pom.xml", "build.gradle", "Gemfile", "composer.json",
)

# Folders that hold other people's checkouts rather than parts of this one.
_NOT_A_SIBLING = {".git", "node_modules", ".venv", "vendor", "packages", "third_party"}


def is_workspace(root: Path) -> bool:
    """A directory that merely *contains* projects, rather than being one.

    `git init` here would swallow every repository underneath into a single
    one, which is worse to undo than anything else adoption does. Two
    children that each look like a project is the signal; one is not, since
    a vendored dependency is an ordinary thing to find inside a project.
    """
    if not root.is_dir():
        return False
    projects = 0
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if child.name in _NOT_A_SIBLING or child.name.startswith("."):
            continue
        if (child / ".git").exists() or any((child / m).is_file() for m in MANIFESTS):
            projects += 1
    return projects >= 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adopt_workspace.py -v`
Expected: 6 passed

- [ ] **Step 5: Verify nothing else broke**

Run: `python -m pytest -q`
Expected: 기존 테스트 전부 통과. 특히 `tests/test_wrong_folder.py` — `is_repository` 를 안 건드렸으므로 그대로여야 한다.

- [ ] **Step 6: Commit**

```bash
git add scripts/notes_config.py tests/test_adopt_workspace.py
git commit -m "feat: 워크스페이스 판정 is_workspace 추가

자동 git init 이 상위 폴더에서 돌면 아래 저장소를 통째로 삼킨다.
is_repository 는 세션 훅·검사기가 함께 쓰는 판정이라 건드리지 않고
목적이 다른 판정을 따로 뒀다. 매니페스트는 워크스페이스를 반증하는
신호로만 쓴다 - 기록물 저장소에는 매니페스트가 없다."
```

---

### Task 2: `backup` — 원본 통째 복사와 검증

girok 이 이 저장소에 처음 쓰기를 하기 직전에 도는 단계. 이후 모든 단계가 이것에 기댄다.

**Files:**
- Create: `scripts/notes_adopt.py`
- Test: `tests/test_adopt_backup.py`

**Interfaces:**
- Consumes: `notes_config.is_workspace` (Task 1)
- Produces:
  - `notes_adopt.BackupResult` — `path: Path`, `files: int`, `bytes: int`, `skipped: bool`
  - `notes_adopt.backup(root: Path, today: str | None = None) -> BackupResult`
  - `notes_adopt.measure(root: Path) -> tuple[int, int]` — `(파일 수, 총 바이트)`
  - `notes_adopt.BackupFailed` — 예외

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_backup.py`:

```python
"""Copying the original before anything touches it.

The whole point of adoption is that files move. The backup is what makes
that reversible, so it runs before `git init`, before the skeleton, before
anything — otherwise it captures a repository girok has already edited and
calling it "the original" is a lie.
"""
import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "eq-agent-v3"
    (root / ".git").mkdir(parents=True)
    write(root / ".git" / "HEAD", "ref: refs/heads/master\n")
    write(root / "STATE.md", "# 현황\n")
    write(root / "docs" / "설계.md", "# 설계\n")
    return root


def test_it_copies_everything_including_git(repo):
    result = notes_adopt.backup(repo, today="20260901")

    assert result.path.name == "eq-agent-v3-girok-backup-20260901"
    assert result.path.parent == repo.parent
    assert (result.path / "STATE.md").is_file()
    assert (result.path / "docs" / "설계.md").is_file()
    assert (result.path / ".git" / "HEAD").is_file()


def test_it_reports_what_it_copied(repo):
    result = notes_adopt.backup(repo, today="20260901")

    files, size = notes_adopt.measure(repo)
    assert result.files == files
    assert result.bytes == size


def test_the_copy_matches_the_original(repo):
    result = notes_adopt.backup(repo, today="20260901")

    assert notes_adopt.measure(result.path) == notes_adopt.measure(repo)


def test_running_twice_does_not_copy_again(repo):
    first = notes_adopt.backup(repo, today="20260901")
    (repo / "STATE.md").write_text("# 바뀐 현황\n", encoding="utf-8")

    second = notes_adopt.backup(repo, today="20260901")

    assert second.skipped
    assert second.path == first.path
    assert (first.path / "STATE.md").read_text(encoding="utf-8") == "# 현황\n"


def test_it_refuses_a_workspace(tmp_path):
    root = tmp_path / "workspace"
    for name in ("a", "b"):
        (root / name / ".git").mkdir(parents=True)

    with pytest.raises(notes_adopt.BackupFailed) as excinfo:
        notes_adopt.backup(root, today="20260901")

    assert "워크스페이스" in str(excinfo.value)


def test_measure_counts_bytes_not_just_files(tmp_path):
    root = tmp_path / "r"
    write(root / "a.md", "12345")
    write(root / "b" / "c.md", "678")

    assert notes_adopt.measure(root) == (2, 8)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_backup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notes_adopt'`

- [ ] **Step 3: Write minimal implementation**

`scripts/notes_adopt.py` 를 새로 만든다:

```python
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


def measure(root: Path) -> tuple[int, int]:
    """Every file under `root` and their total size, with nothing skipped.

    Counting is the verification: a copy that matches on both numbers is a
    copy. Excluding anything here would exclude it from the check too.
    """
    files = 0
    size = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += 1
            size += path.stat().st_size
    return files, size


def backup(root: Path, today: str | None = None) -> BackupResult:
    """Copy the repository whole, next to itself, before anything writes.

    Nothing is excluded — not `.git`, not build output. An exclusion list is
    a list of things that cannot be restored, and disks are cheap.
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

    shutil.copytree(root, target, symlinks=True)

    before = measure(root)
    after = measure(target)
    if before != after:
        raise BackupFailed(
            f"백업이 원본과 다르다 — 원본 {before[0]}개/{before[1]:,}바이트, "
            f"백업 {after[0]}개/{after[1]:,}바이트. 아무것도 옮기지 않았다"
        )
    return BackupResult(path=target, files=after[0], bytes=after[1])


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adopt_backup.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/notes_adopt.py tests/test_adopt_backup.py
git commit -m "feat: notes_adopt backup - 원본 통째 백업과 검증

이식은 파일을 옮기는 일이라 되돌릴 수단이 먼저 있어야 한다. 백업이
git init 이나 뼈대 생성 뒤에 있으면 담기는 것이 원본이 아니다.
제외 목록을 두지 않은 이유는 제외한 항목이 나중에 필요했을 때
되돌릴 방법이 없기 때문이다. 파일 수와 총 바이트 대조로 검증한다."
```

---

### Task 3: `plan` — 전수 목록과 role 분류

읽기 전용. 저장소의 모든 마크다운을 빠짐없이 훑어 role 초안과 SHA-1 을 붙인 매핑 파일을 만든다.

**Files:**
- Modify: `scripts/notes_adopt.py`
- Test: `tests/test_adopt_plan.py`

**Interfaces:**
- Consumes: `notes_adopt.measure` (Task 2), `notes_config.load` → `cfg.notes_dir`·`cfg.board`·`cfg.decisions_dir`·`cfg.adr_style`
- Produces:
  - `notes_adopt.Entry` — `frm: str`, `to: str | None`, `role: str`, `sha1: str`, `bytes: int`, `why: str`, `merge: str | None`
  - `notes_adopt.plan(root: Path) -> list[Entry]`
  - `notes_adopt.write_mapping(root: Path, entries: list[Entry], backup: BackupResult | None) -> Path`
  - `notes_adopt.read_mapping(root: Path) -> dict`
  - `notes_adopt.MAPPING_RELATIVE = Path(".claude") / "girok-adopt.json"`
  - `notes_adopt.sha1_of(path: Path) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_plan.py`:

```python
"""Listing every document and proposing where it goes.

Rules fill in what they are sure about and leave the rest blank. A blank is
not a failure — it is the handful of files a person or a model has to read,
and `apply` refuses while any remain. Guessing here would be worse than
asking, because a wrong guess arrives as a moved file.
"""
import json

import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def repo(tmp_path):
    """A repository shaped like eq-agent-v3 before adoption."""
    root = tmp_path / "eq-agent-v3"
    (root / ".git").mkdir(parents=True)
    write(root / ".claude" / "girok.json", json.dumps({
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "docRoots": ["docs", "decisions"], "adrStyle": "numbered",
    }))
    write(root / "STATE.md", "# 현황\n")
    write(root / "CLAUDE.md", "# 규칙\n")
    write(root / "AGENTS.md", "# 규칙\n")
    write(root / "THESIS.md", "# 논지\n")
    write(root / "decisions" / "001-first.md", "# 001 첫 결정\n")
    write(root / "decisions" / "README.md", "# 인덱스\n")
    write(root / "docs" / "design" / "2026-08-31-backlog.md", "# 백로그\n")
    write(root / "docs" / "superpowers" / "plans" / "p.md", "# 계획\n")
    write(root / "experiments" / "runs.jsonl", '{"a":1}\n')
    return root


def _by_source(entries):
    return {e.frm: e for e in entries}


def test_it_lists_every_markdown_and_nothing_else(repo):
    found = _by_source(notes_adopt.plan(repo))

    assert "STATE.md" in found
    assert "experiments/runs.jsonl" not in found


def test_the_board_is_recognized(repo):
    assert _by_source(notes_adopt.plan(repo))["STATE.md"].role == "board"


def test_rules_documents_stay_where_tools_read_them(repo):
    found = _by_source(notes_adopt.plan(repo))

    for name in ("CLAUDE.md", "AGENTS.md"):
        assert found[name].role == "rules"
        assert found[name].to is None


def test_another_tools_folder_is_left_alone(repo):
    entry = _by_source(notes_adopt.plan(repo))["docs/superpowers/plans/p.md"]

    assert entry.role == "foreign"
    assert entry.to is None


def test_a_numbered_decision_is_an_adr(repo):
    assert _by_source(notes_adopt.plan(repo))["decisions/001-first.md"].role == "adr"


def test_an_ordinary_document_is_a_doc(repo):
    entry = _by_source(notes_adopt.plan(repo))["docs/design/2026-08-31-backlog.md"]

    assert entry.role == "doc"


def test_what_the_rules_cannot_tell_is_left_blank(repo):
    found = _by_source(notes_adopt.plan(repo))

    assert found["THESIS.md"].role == "?"
    assert found["decisions/README.md"].role == "?"


def test_every_entry_carries_a_hash_of_its_content(repo):
    for entry in notes_adopt.plan(repo):
        assert len(entry.sha1) == 40
        assert entry.bytes > 0


def test_the_mapping_is_written_where_it_can_be_committed(repo):
    notes_adopt.write_mapping(repo, notes_adopt.plan(repo), None)

    data = notes_adopt.read_mapping(repo)
    assert (repo / ".claude" / "girok-adopt.json").is_file()
    assert any(f["from"] == "STATE.md" for f in data["files"])


def test_planning_moves_nothing(repo):
    before = notes_adopt.measure(repo)

    notes_adopt.plan(repo)

    assert notes_adopt.measure(repo) == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_plan.py -v`
Expected: FAIL — `AttributeError: module 'notes_adopt' has no attribute 'plan'`

- [ ] **Step 3: Write minimal implementation**

`scripts/notes_adopt.py` 에 추가한다 (`import` 에 `hashlib`·`json`·`re` 를 더한다):

```python
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
```

`main()` 의 `choices` 를 `["backup", "plan"]` 으로 넓히고 분기를 더한다:

```python
    if args.command == "plan":
        entries = plan(args.root)
        write_mapping(args.root, entries, None)
        unknown = [e for e in entries if e.role == "?"]
        for entry in entries:
            arrow = entry.to or "제자리"
            print(f"[{entry.role:>7}] {entry.frm} → {arrow}  ({entry.why})")
        print(f"문서 {len(entries)}개 — 판단 필요 {len(unknown)}개")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adopt_plan.py -v`
Expected: 10 passed

- [ ] **Step 5: Sanity-check against the real repository**

Run: `python scripts/notes_adopt.py plan --root ../eq-agent-v3`
Expected: `?` 가 `THESIS.md`·`decisions/README.md`·`docs/relay-responder-*.md` 근처로 나온다. 스펙의 예상표(§3단계 plan)와 크게 다르면 스펙 쪽이 틀렸는지 규칙이 틀렸는지 판단해 보고한다. **`git status ../eq-agent-v3` 로 아무것도 안 바뀌었는지 확인한다.**

- [ ] **Step 6: Commit**

```bash
git add scripts/notes_adopt.py tests/test_adopt_plan.py
git commit -m "feat: notes_adopt plan - 전수 목록과 role 분류

규칙이 확실히 아는 것만 채우고 나머지는 ? 로 비운다. 애매한 것을
규칙으로 추측하면 틀린 추측이 옮겨진 파일로 도착한다. 루트 고정
문서(CLAUDE.md 등)와 남의 도구 폴더(docs/superpowers)는 옮기지
않는다 - 도구가 경로로 읽기 때문이다."
```

---

### Task 4: git 정비 — `init` 과 `.gitignore`

git 이 없으면 중단하지 않고 정비를 이식의 일부로 수행한다.

**Files:**
- Modify: `scripts/notes_adopt.py`
- Test: `tests/test_adopt_gitsetup.py`

**Interfaces:**
- Consumes: `notes_config.is_workspace` (Task 1)
- Produces:
  - `notes_adopt.GitSetup` — `init: bool`, `gitignore_added: list[str]`, `secrets: list[str]`, `large: list[str]`, `remote: str | None`
  - `notes_adopt.git_setup(root: Path) -> GitSetup`
  - `notes_adopt.run_git(root: Path, *args: str) -> subprocess.CompletedProcess`
  - `notes_adopt.LARGE_BYTES = 10 * 1024 * 1024`

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_gitsetup.py`:

```python
"""Making a folder into a repository as part of adoption.

Refusing until someone runs `git init` themselves turned a one-command fix
into a stop. The interesting part is not the init — it is everything that
must not land in the first commit, and saying out loud what was excluded so
"it is in the backup only" is a written fact rather than a surprise.
"""
import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def bare_project(tmp_path):
    """A code project that never adopted git."""
    root = tmp_path / "legacy"
    write(root / "pyproject.toml", "[project]\n")
    write(root / "STATE.md", "# 현황\n")
    write(root / "__pycache__" / "x.pyc", "junk")
    return root


def test_it_initializes_git(bare_project):
    result = notes_adopt.git_setup(bare_project)

    assert result.init
    assert (bare_project / ".git").is_dir()


def test_build_output_is_ignored(bare_project):
    notes_adopt.git_setup(bare_project)

    text = (bare_project / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in text
    assert "# girok:adopt" in text


def test_secrets_are_ignored_and_named(tmp_path):
    root = tmp_path / "p"
    write(root / "pyproject.toml", "[project]\n")
    write(root / ".env", "TOKEN=abc\n")
    write(root / "deploy.key", "-----BEGIN-----\n")

    result = notes_adopt.git_setup(root)

    assert sorted(result.secrets) == [".env", "deploy.key"]
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in text and "deploy.key" in text


def test_large_files_are_ignored_and_named(tmp_path):
    root = tmp_path / "p"
    write(root / "pyproject.toml", "[project]\n")
    big = root / "model.bin"
    big.write_bytes(b"0" * (notes_adopt.LARGE_BYTES + 1))

    result = notes_adopt.git_setup(root)

    assert result.large == ["model.bin"]


def test_an_existing_gitignore_is_kept(tmp_path):
    root = tmp_path / "p"
    write(root / "pyproject.toml", "[project]\n")
    write(root / ".gitignore", "mine/\n")
    write(root / "__pycache__" / "x.pyc", "junk")

    notes_adopt.git_setup(root)

    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("mine/\n")
    assert "__pycache__/" in text


def test_an_existing_repository_is_left_alone(tmp_path):
    root = tmp_path / "p"
    (root / ".git").mkdir(parents=True)
    write(root / "pyproject.toml", "[project]\n")

    result = notes_adopt.git_setup(root)

    assert not result.init


def test_it_refuses_a_workspace(tmp_path):
    root = tmp_path / "workspace"
    for name in ("a", "b"):
        write(root / name / "pyproject.toml", "[project]\n")

    with pytest.raises(notes_adopt.BackupFailed) as excinfo:
        notes_adopt.git_setup(root)

    assert "워크스페이스" in str(excinfo.value)


def test_a_missing_remote_is_reported_not_fatal(bare_project):
    result = notes_adopt.git_setup(bare_project)

    assert result.remote is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_gitsetup.py -v`
Expected: FAIL — `AttributeError: module 'notes_adopt' has no attribute 'git_setup'`

- [ ] **Step 3: Write minimal implementation**

`scripts/notes_adopt.py` 에 추가한다 (`import subprocess` 를 더한다):

```python
LARGE_BYTES = 10 * 1024 * 1024

# Build output and caches. Committing these is not dangerous, just noise
# that makes every later diff unreadable.
JUNK_PATTERNS = (
    "__pycache__/", "*.pyc", "node_modules/", "build/", "dist/",
    ".venv/", ".pytest_cache/", "bin/", "obj/",
)

# Names that usually hold a credential. Ignoring one is cheap; committing
# one is a rotation.
SECRET_NAMES = (".env",)
SECRET_SUFFIXES = (".key", ".pem", ".p12", ".pfx")
SECRET_PREFIXES = ("credentials", "secrets", ".env.")


@dataclass
class GitSetup:
    init: bool = False
    gitignore_added: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)
    large: list[str] = field(default_factory=list)
    remote: str | None = None


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )


def _looks_secret(name: str) -> bool:
    lowered = name.lower()
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


def git_setup(root: Path) -> GitSetup:
    """Make this folder a repository, and keep the wrong things out of it.

    Everything here resolves rather than refuses, except a workspace: a
    `git init` one level too high swallows the repositories underneath, and
    that is not a thing to fix afterwards.
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

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/"):
            continue
        if _looks_secret(path.name):
            setup.secrets.append(rel)
        elif path.stat().st_size > LARGE_BYTES:
            setup.large.append(rel)

    wanted = list(JUNK_PATTERNS) + setup.secrets + setup.large
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
```

`dataclasses` 임포트에 `field` 를 더한다: `from dataclasses import dataclass, field`

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adopt_gitsetup.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/notes_adopt.py tests/test_adopt_gitsetup.py
git commit -m "feat: notes_adopt git 정비 - init 과 .gitignore

git 이 없다고 멈추면 한 명령이면 될 일이 중단이 된다. 정비를
이식의 일부로 넣되, 첫 커밋에 들어가면 안 되는 것(비밀·대용량)은
.gitignore 로 빼고 무엇을 왜 뺐는지 남긴다 - 뺀 파일은 백업
폴더에만 남으므로 말하지 않으면 나중에 사고가 된다.

워크스페이스만은 중단한다. 상위 폴더에서 git init 이 돌면 하위
저장소를 통째로 삼키고, 그건 나중에 고칠 수 있는 실수가 아니다."
```

---

### Task 5: `apply` 사전조건과 이동

**Files:**
- Modify: `scripts/notes_adopt.py`
- Test: `tests/test_adopt_apply.py`

**Interfaces:**
- Consumes: `notes_adopt.read_mapping` (Task 3), `notes_adopt.run_git` (Task 4)
- Produces:
  - `notes_adopt.Blocked` — 예외
  - `notes_adopt.check_preconditions(root: Path, mapping: dict) -> None` — 위반 시 `Blocked`
  - `notes_adopt.normalize_name(name: str, role: str, adr_style: str) -> str`
  - `notes_adopt.move_all(root: Path, mapping: dict) -> list[tuple[str, str]]` — `(from, to)` 목록

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_apply.py`:

```python
"""Refusing to move, and then moving.

"Clean" is not `git status` being empty — an unpushed commit is fine and a
build artifact nobody tracks is fine. What matters is that every file about
to move is committed, because the restore tag can only hold what was
committed.
"""
import json

import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    write(root / "STATE.md", "# 현황\n")
    write(root / "docs" / "설계.md", "# 설계\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    return root


def _mapping(files):
    return {"files": files, "gitSetup": {}, "backup": None}


def test_an_unresolved_role_blocks_everything(repo):
    mapping = _mapping([
        {"from": "STATE.md", "to": None, "role": "?", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "STATE.md" in str(excinfo.value)


def test_an_uncommitted_target_blocks(repo):
    (repo / "STATE.md").write_text("# 고침\n", encoding="utf-8")
    mapping = _mapping([
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "STATE.md" in str(excinfo.value)


def test_an_untracked_file_outside_the_plan_does_not_block(repo):
    write(repo / "scratch.log", "noise\n")
    mapping = _mapping([
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    notes_adopt.check_preconditions(repo, mapping)


def test_an_untracked_file_inside_the_plan_blocks(repo):
    write(repo / "새문서.md", "# 새\n")
    mapping = _mapping([
        {"from": "새문서.md", "to": "docs/새문서.md", "role": "doc", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "새문서.md" in str(excinfo.value)


def test_a_merge_in_progress_blocks(repo):
    (repo / ".git" / "MERGE_HEAD").write_text("deadbeef\n", encoding="utf-8")
    mapping = _mapping([])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "병합" in str(excinfo.value)


def test_moving_uses_git_so_history_follows(repo):
    mapping = _mapping([
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": notes_adopt.sha1_of(repo / "STATE.md"),
         "bytes": 1, "why": ""},
    ])

    notes_adopt.move_all(repo, mapping)

    assert (repo / "PROGRESS.md").is_file()
    assert not (repo / "STATE.md").exists()
    log = notes_adopt.run_git(repo, "log", "--follow", "--name-only", "--", "PROGRESS.md")
    assert "STATE.md" in log.stdout


def test_content_survives_the_move(repo):
    before = notes_adopt.sha1_of(repo / "docs" / "설계.md")
    mapping = _mapping([
        {"from": "docs/설계.md", "to": "docs/설계.md", "role": "doc", "merge": None,
         "sha1": before, "bytes": 1, "why": ""},
    ])

    notes_adopt.move_all(repo, mapping)

    assert notes_adopt.sha1_of(repo / "docs" / "설계.md") == before


@pytest.mark.parametrize("name,role,style,expected", [
    ("001-first.md", "adr", "adr-prefixed", "ADR-001-first.md"),
    ("ADR-001-first.md", "adr", "numbered", "001-first.md"),
    ("My Design Doc.md", "doc", "numbered", "my-design-doc.md"),
    ("2026-08-31-Backlog.md", "doc", "numbered", "2026-08-31-backlog.md"),
    ("설계 문서.md", "doc", "numbered", "설계-문서.md"),
])
def test_names_are_normalized(name, role, style, expected):
    assert notes_adopt.normalize_name(name, role, style) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_apply.py -v`
Expected: FAIL — `AttributeError: module 'notes_adopt' has no attribute 'Blocked'`

- [ ] **Step 3: Write minimal implementation**

`scripts/notes_adopt.py` 에 추가한다:

```python
class Blocked(Exception):
    """A precondition failed, so nothing moved."""


def _porcelain(root: Path) -> dict[str, str]:
    """Every path git has something to say about, mapped to its status code."""
    result = run_git(root, "status", "--porcelain")
    states = {}
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code, rel = line[:2], line[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
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
    """Move every planned document with `git mv`, so history follows."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adopt_apply.py -v`
Expected: 12 passed (파라미터 5개 포함)

- [ ] **Step 5: Commit**

```bash
git add scripts/notes_adopt.py tests/test_adopt_apply.py
git commit -m "feat: notes_adopt 사전조건과 git mv 이동

깨끗함의 기준을 git status 가 비어 있는 것이 아니라 '옮길 문서가
전부 커밋된 상태'로 잡았다. 무관한 잡파일이나 미push 로 막으면
쓸 때 걸리적거리기만 하고, 정작 막아야 하는 건 복원 태그가
담지 못하는 파일이다.

이동은 전부 git mv 다. cp 뒤 rm 은 이력을 끊는다."
```

---

### Task 6: 병합 — 이어붙이기

**Files:**
- Modify: `scripts/notes_adopt.py`
- Test: `tests/test_adopt_merge.py`

**Interfaces:**
- Consumes: `notes_adopt.run_git` (Task 4)
- Produces:
  - `notes_adopt.merge_into(root: Path, source: str, target: str, today: str | None = None) -> None`
  - `notes_adopt.missing_lines(original: str, result: str) -> list[str]`

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_merge.py`:

```python
"""Combining two documents without losing a line.

Rewriting them into one clean document reads better and cannot be checked.
Appending reads worse and can: every line of the original is either present
in the result or it is not, and that is a test. Tidying is a later,
reversible job for a person.
"""
import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    write(root / "PROGRESS.md", "# 현황판\n\n## 로컬 실행 경로\n\n돌아간다\n")
    write(root / "STATE.md", "# 상태\n\n## 지금 상태\n\n측정 중\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    return root


def test_every_line_of_the_source_survives(repo):
    original = (repo / "STATE.md").read_text(encoding="utf-8")

    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert notes_adopt.missing_lines(original, result) == []


def test_the_target_keeps_its_own_content(repo):
    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert "## 로컬 실행 경로" in result
    assert "돌아간다" in result


def test_the_source_is_marked_so_it_can_be_traced(repo):
    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert "<!-- girok:adopt 2026-09-01 · 출처 STATE.md -->" in result


def test_the_source_is_removed_with_git(repo):
    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    assert not (repo / "STATE.md").exists()
    listed = notes_adopt.run_git(repo, "ls-files").stdout
    assert "STATE.md" not in listed


def test_nothing_is_reworded(repo):
    notes_adopt.merge_into(repo, "STATE.md", "PROGRESS.md", today="2026-09-01")

    result = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert "## 지금 상태\n\n측정 중\n" in result


def test_missing_lines_reports_what_was_dropped():
    dropped = notes_adopt.missing_lines("가\n나\n다\n", "머리말\n가\n다\n")

    assert dropped == ["나"]


def test_missing_lines_ignores_blank_lines():
    assert notes_adopt.missing_lines("가\n\n\n나\n", "가\n나\n") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_merge.py -v`
Expected: FAIL — `AttributeError: module 'notes_adopt' has no attribute 'merge_into'`

- [ ] **Step 3: Write minimal implementation**

```python
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
        src.unlink(missing_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adopt_merge.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/notes_adopt.py tests/test_adopt_merge.py
git commit -m "feat: notes_adopt 병합 - 이어붙이기만 한다

재작성 병합은 결과가 깔끔한 대신 유실을 검증할 방법이 없다.
문장 하나를 흘려도 아무도 모른다. 원문을 통째로 이어붙이면
'원본의 모든 줄이 결과에 있는가'가 테스트가 된다. 다듬는 건
안전해진 뒤에 사람이 할 일이다."
```

---

### Task 7: 링크 재작성

**Files:**
- Modify: `scripts/notes_adopt.py`
- Test: `tests/test_adopt_links.py`

**Interfaces:**
- Consumes: `notes_adopt._markdown` (Task 3)
- Produces:
  - `notes_adopt.rewrite_links(root: Path, moves: list[tuple[str, str]]) -> int` — 고친 링크 수
  - `notes_adopt.broken_links(root: Path) -> list[tuple[str, str]]` — `(문서, 깨진 링크)`

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_links.py`:

```python
"""Keeping references pointing at documents that moved.

Files surviving is what the backup guarantees. Links surviving is not — a
document can be intact at its new path while every reference to it is dead,
and no hash check notices that.
"""
import notes_adopt

from conftest import write


def test_a_relative_link_follows_the_move(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "본문 [결정](decisions/001-first.md) 참고\n")

    changed = notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    assert changed == 1
    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "(docs/decisions/ADR-001-first.md)" in text


def test_an_anchor_is_kept(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[결정](decisions/001-first.md#결정)\n")

    notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "(docs/decisions/ADR-001-first.md#결정)" in text


def test_an_image_follows_too(tmp_path):
    root = tmp_path / "r"
    write(root / "docs" / "설계.md", "![그림](old/도면.md)\n")

    notes_adopt.rewrite_links(root, [("old/도면.md", "docs/도면.md")])

    text = (root / "docs" / "설계.md").read_text(encoding="utf-8")
    assert "(../docs/도면.md)" in text or "(도면.md)" in text


def test_a_reference_style_link_follows(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[결정]: decisions/001-first.md\n")

    notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "docs/decisions/ADR-001-first.md" in text


def test_a_path_inside_a_code_block_is_left_alone(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "```\ncat decisions/001-first.md\n```\n")

    changed = notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    assert changed == 0
    assert "cat decisions/001-first.md" in (root / "PROGRESS.md").read_text(encoding="utf-8")


def test_an_external_url_is_left_alone(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[집](https://example.invalid/decisions/001-first.md)\n")

    changed = notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    assert changed == 0


def test_broken_links_are_reported(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[없다](docs/없는문서.md)\n")

    assert notes_adopt.broken_links(root) == [("PROGRESS.md", "docs/없는문서.md")]


def test_a_link_that_resolves_is_not_reported(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[있다](docs/있다.md)\n")
    write(root / "docs" / "있다.md", "# 있다\n")

    assert notes_adopt.broken_links(root) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_links.py -v`
Expected: FAIL — `AttributeError: module 'notes_adopt' has no attribute 'rewrite_links'`

- [ ] **Step 3: Write minimal implementation**

```python
# Inline `[text](path)` and `![alt](path)`, plus reference definitions
# `[label]: path`. Anchors and titles are captured separately so they ride
# along unchanged.
INLINE_LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s#]+)((?:#[^)\s]*)?(?:\s+\"[^\"]*\")?\))")
REFERENCE_LINK = re.compile(r"(^\s*\[[^\]]+\]:\s+)([^\s#]+)((?:#\S*)?)", re.MULTILINE)
FENCE = re.compile(r"^\s*(```|~~~)")
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.IGNORECASE)


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

            def swap_inline(match, doc=doc_rel):
                nonlocal changed
                new = _retarget(doc, match.group(2), table)
                if new is None:
                    return match.group(0)
                changed += 1
                return f"{match.group(1)}{new}{match.group(3)}"

            def swap_reference(match, doc=doc_rel):
                nonlocal changed
                new = _retarget(doc, match.group(2), table)
                if new is None:
                    return match.group(0)
                changed += 1
                return f"{match.group(1)}{new}{match.group(3)}"

            line = INLINE_LINK.sub(swap_inline, line)
            line = REFERENCE_LINK.sub(swap_reference, line)
            lines.append(line)

        updated = "\n".join(lines)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
    return changed


def broken_links(root: Path) -> list[tuple[str, str]]:
    """Relative links that point at nothing."""
    root = Path(root).resolve()
    broken = []
    for path in _markdown(root):
        doc_rel = path.relative_to(root).as_posix()
        here = Path(doc_rel).parent
        for line, is_code in _outside_code(path.read_text(encoding="utf-8")):
            if is_code:
                continue
            for match in INLINE_LINK.finditer(line):
                link = match.group(2)
                if EXTERNAL.match(link):
                    continue
                target = Path(os.path.normpath((here / link).as_posix()))
                if not (root / target).exists():
                    broken.append((doc_rel, link))
    return broken
```

`import os` 를 파일 상단에 더한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adopt_links.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/notes_adopt.py tests/test_adopt_links.py
git commit -m "feat: notes_adopt 링크 재작성

파일이 살아남는 것은 백업이 보장하지만 링크는 아니다. 문서가 새
경로에 멀쩡히 있으면서 그것을 가리키는 참조가 전부 죽을 수 있고,
해시 검사는 그걸 못 잡는다. 코드블록 안 경로는 누가 친 명령의
기록이지 따라갈 참조가 아니라 건드리지 않는다."
```

---

### Task 8: `verify` 와 `apply` 조립

앞의 조각들을 하나의 명령으로 잇고, 유실을 증명하는 검사를 붙인다.

**Files:**
- Modify: `scripts/notes_adopt.py`
- Test: `tests/test_adopt_verify.py`

**Interfaces:**
- Consumes: 앞 Task 전부
- Produces:
  - `notes_adopt.VerifyResult` — `ok: bool`, `failures: list[str]`
  - `notes_adopt.verify(root: Path) -> VerifyResult`
  - `notes_adopt.apply(root: Path, today: str | None = None) -> list[tuple[str, str]]`

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_verify.py`:

```python
"""Proving after the fact that nothing was lost.

Every guarantee this tool makes is a claim until something re-reads the
bytes and says so. A pass here is the only reason to believe the move.
"""
import json

import notes_adopt
import pytest

from conftest import write


@pytest.fixture
def adopted(tmp_path):
    root = tmp_path / "proj"
    write(root / ".claude" / "girok.json", json.dumps({
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "adrStyle": "adr-prefixed",
    }))
    write(root / "STATE.md", "# 현황\n\n돌아간다\n")
    write(root / "decisions" / "001-first.md", "# 001\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    return root


def test_a_clean_adoption_verifies(adopted):
    notes_adopt.apply(adopted, today="20260901")

    result = notes_adopt.verify(adopted)

    assert result.ok, result.failures


def test_content_is_identical_after_adoption(adopted):
    before = notes_adopt.sha1_of(adopted / "STATE.md")

    notes_adopt.apply(adopted, today="20260901")

    assert notes_adopt.sha1_of(adopted / "PROGRESS.md") == before


def test_a_tampered_file_fails_verification(adopted):
    notes_adopt.apply(adopted, today="20260901")
    (adopted / "PROGRESS.md").write_text("# 딴것\n", encoding="utf-8")

    result = notes_adopt.verify(adopted)

    assert not result.ok
    assert any("PROGRESS.md" in f for f in result.failures)


def test_a_deleted_file_fails_verification(adopted):
    notes_adopt.apply(adopted, today="20260901")
    (adopted / "PROGRESS.md").unlink()

    result = notes_adopt.verify(adopted)

    assert not result.ok


def test_the_backup_exists_before_anything_moved(adopted):
    notes_adopt.apply(adopted, today="20260901")

    backup = adopted.parent / f"{adopted.name}-girok-backup-20260901"
    assert (backup / "STATE.md").is_file(), "백업은 이동 전 원본을 담아야 한다"


def test_the_restore_tag_is_written(adopted):
    notes_adopt.apply(adopted, today="20260901")

    tags = notes_adopt.run_git(adopted, "tag").stdout
    assert "girok-adopt-before-20260901" in tags


def test_the_mapping_is_left_for_later(adopted):
    notes_adopt.apply(adopted, today="20260901")

    data = notes_adopt.read_mapping(adopted)
    assert data["backup"]["files"] > 0
    assert any(f["to"] == "PROGRESS.md" for f in data["files"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_verify.py -v`
Expected: FAIL — `AttributeError: module 'notes_adopt' has no attribute 'apply'`

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass
class VerifyResult:
    ok: bool = True
    failures: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.failures.append(message)


def apply(root: Path, today: str | None = None) -> list[tuple[str, str]]:
    """Back up, tidy git, move, merge, and repoint — in that order.

    The order is the design. Backing up after `git init` would capture a
    repository girok had already edited, and moving before the
    preconditions would move a file the restore tag cannot bring back.
    """
    root = Path(root).resolve()
    stamp = today or date.today().strftime("%Y%m%d")

    saved = backup(root, today=stamp)
    setup = git_setup(root)

    mapping = read_mapping(root)
    mapping["gitSetup"] = {
        "init": setup.init, "gitignoreAdded": setup.gitignore_added,
        "secrets": setup.secrets, "large": setup.large, "remote": setup.remote,
    }
    mapping["backup"] = {
        "path": saved.path.name, "files": saved.files, "bytes": saved.bytes,
    }

    if setup.init or _porcelain(root):
        run_git(root, "add", "-A")
        run_git(root, "commit", "-m", "chore: girok 이식 전 상태")
    run_git(root, "tag", f"girok-adopt-before-{stamp}")

    check_preconditions(root, mapping)

    cfg = notes_config.load(root)
    for item in mapping["files"]:
        if not item.get("to"):
            continue
        parent = Path(item["to"]).parent
        name = normalize_name(Path(item["to"]).name, item["role"], cfg.adr_style)
        item["to"] = (parent / name).as_posix() if parent.as_posix() != "." else name

    merges = [i for i in mapping["files"] if i.get("merge")]
    plain = [i for i in mapping["files"] if not i.get("merge")]

    moved = move_all(root, {"files": plain})
    for item in merges:
        merge_into(root, item["from"], item["merge"], today=None)
        moved.append((item["from"], item["merge"]))

    rewrite_links(root, moved)
    _write_mapping_payload(root, mapping)
    return moved


def _write_mapping_payload(root: Path, payload: dict) -> None:
    target = Path(root).resolve() / MAPPING_RELATIVE
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def verify(root: Path) -> VerifyResult:
    """Re-read the bytes and say whether the claims hold."""
    root = Path(root).resolve()
    result = VerifyResult()
    try:
        mapping = read_mapping(root)
    except (OSError, ValueError):
        result.fail("매핑 파일이 없다 — 무엇을 옮겼는지 알 수 없으므로 검증할 수 없다")
        return result

    for item in mapping["files"]:
        landed = item.get("to") or item.get("merge") or item["from"]
        path = root / landed
        if not path.is_file():
            result.fail(f"{landed} 가 없다 (원래 {item['from']})")
            continue
        if item.get("merge"):
            continue
        if item.get("to") and sha1_of(path) != item["sha1"]:
            result.fail(f"{landed} 의 내용이 원본과 다르다")

    saved = mapping.get("backup") or {}
    if saved.get("path"):
        backup_path = root.parent / saved["path"]
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

    for doc, link in broken_links(root):
        result.fail(f"{doc} 의 링크가 깨졌다 — {link}")
    return result
```

`main()` 의 `choices` 를 `["backup", "plan", "apply", "verify"]` 로 넓히고, `apply` 는 `--confirm` 을 요구한다:

```python
    if args.command == "apply":
        root = Path(args.root).resolve()
        if args.confirm != root.name:
            print(f"[중단] `{root}` 에서 아무것도 옮기지 않았다.")
            print(f"  이식하려면 이름을 확인해 다시 실행할 것:  --confirm {root.name}")
            return 1
        try:
            moved = apply(root)
        except (BackupFailed, Blocked) as exc:
            print(f"[중단] {exc}")
            return 1
        for frm, to in moved:
            print(f"[이동] {frm} → {to}")
        print(f"{len(moved)}개 이동. 이어서 `verify` 를 돌릴 것")
        return 0

    if args.command == "verify":
        result = verify(args.root)
        for failure in result.failures:
            print(f"[실패] {failure}")
        if result.ok:
            print("이식 검증 통과 — 유실 없음")
            return 0
        stamp = date.today().strftime("%Y%m%d")
        print("복원하려면:")
        print(f"  git checkout girok-adopt-before-{stamp} -- .")
        print("  또는 백업 폴더에서 통째로 되돌릴 것")
        return 1
```

`parser.add_argument("--confirm", default=None, help="이식할 저장소의 폴더 이름")` 을 더한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adopt_verify.py -v`
Expected: 7 passed

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: 전부 통과

- [ ] **Step 6: Commit**

```bash
git add scripts/notes_adopt.py tests/test_adopt_verify.py
git commit -m "feat: notes_adopt apply/verify 조립

순서가 설계다. 백업이 git init 뒤면 담기는 것이 원본이 아니고,
이동이 사전조건 앞이면 복원 태그가 못 담는 파일이 움직인다.

verify 는 바이트를 다시 읽는다. 그 전까지 '유실 없음'은 주장이다."
```

---

### Task 9: `/notes` 통합과 배포

**Files:**
- Modify: `commands/notes.md`
- Modify: `.claude-plugin/plugin.json` (version)
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Test: `tests/test_adopt_command.py`

**Interfaces:**
- Consumes: `notes_adopt.plan` (Task 3)
- Produces: 없음 (문서와 배포)

- [ ] **Step 1: Write the failing test**

`tests/test_adopt_command.py`:

```python
"""The command document has to name the tool, or nobody runs it.

A script `/notes` never mentions is a script that does not exist.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMMAND = (ROOT / "commands" / "notes.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("subcommand", ["backup", "plan", "apply", "verify"])
def test_the_command_document_names_each_subcommand(subcommand):
    assert f"notes_adopt.py {subcommand}" in COMMAND


def test_initialization_backs_up_before_it_writes():
    """Ordering is the one thing a reader must not get wrong."""
    backup_at = COMMAND.index("notes_adopt.py backup")
    init_at = COMMAND.index("notes_init.py")

    assert backup_at < init_at


def test_the_routine_check_looks_for_unadopted_documents():
    assert "notes_adopt.py plan" in COMMAND
    assert "이식" in COMMAND


def test_the_version_was_bumped():
    import json
    version = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]

    assert version != "0.17.0", "새 기능은 버전을 올려야 클라이언트가 받는다"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adopt_command.py -v`
Expected: FAIL — `notes_adopt.py backup` 이 `commands/notes.md` 에 없다

- [ ] **Step 3: Write the documentation**

`commands/notes.md` 의 `### 2. 초기화 — 스냅샷이 없을 때` 절에서, `notes_survey.py` 실행 **앞**에 다음을 넣는다:

````markdown
**먼저 백업한다.** 이 저장소에 아무것도 쓰기 전에 원본을 통째로 남긴다. `git init` 도,
뼈대 생성도 이 뒤다 — 순서가 바뀌면 백업이 담는 것은 girok 이 이미 손댄 상태다.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/notes_adopt.py" backup
```

워크스페이스(저장소를 여러 개 담은 상위 폴더)로 보이면 여기서 멈춘다. 그때는 작업할
저장소 폴더로 옮겨 다시 켤 것.
````

같은 절의 `notes_init.py` 실행 **뒤**에 다음을 넣는다:

````markdown
### 2-1. 이식 — 기존 기록을 girok 자리로

뼈대만 만들고 끝내면 진짜 문서 옆에 빈 문서 한 벌이 남는다. 기존 기록을 옮긴다.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/notes_adopt.py" plan
```

읽기 전용이다. `.claude/girok-adopt.json` 에 전수 목록과 `role` 초안이 생긴다.

**`role` 이 `?` 인 항목은 규칙이 판단하지 못한 것이다. 그 문서를 직접 읽고 채운다** —
`to`(어디로) 와, 다른 문서에 합쳐야 하면 `merge`(어느 문서에) 를 적는다. 채운 결과를
표로 사용자에게 보여주고 승인을 받는다. `?` 가 하나라도 남으면 다음 단계가 거부한다.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/notes_adopt.py" apply --confirm <저장소 폴더 이름>
python "${CLAUDE_PLUGIN_ROOT}/scripts/notes_adopt.py" verify
```

`verify` 가 실패하면 **그 자리에서 복원 방법을 안내하고 멈춘다.** 스스로 고치려 들지
않는다 — 무엇이 어긋났는지 모르는 채로 손대면 백업이 유일한 사실이 된다.

> [!CAUTION]
> 병합은 **이어붙이기만** 한다. 원문을 요약하거나 다시 쓰지 않는다. 다듬는 것은
> `verify` 가 통과한 다음 세션에 사람이 볼 때 할 일이다.

`notesDir` 가 `"."` 인 저장소(문서가 루트에 흩어져 있는 경우)라면 **한 번 물어볼 값이
있다** — 문서를 `notes/` 아래로 모을 것인지. 이식은 기본적으로 현행 `notesDir` 를
유지한다. 바꾸면 모든 문서 경로가 달라져 링크 재작성량이 몇 배가 되고, `notesDir: "."`
는 girok 이 허용하는 정식 값이라 안 바꿔도 표준 위반이 아니다. **사람이 명시적으로
원할 때만** `.claude/girok.json` 의 `notesDir` 를 먼저 고치고 `plan` 을 다시 돌린다.
````

`### 4. 점검 — 정상일 때` 절의 명령 목록에 한 줄을 더한다:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/notes_adopt.py" plan
```

그리고 그 절의 보고 항목에 한 줄을 더한다:

```markdown
- 이식 안 된 문서 (`role` 이 `?` 이거나 제자리가 아닌 항목 수)
```

`## 하지 않는 것` 절에 두 줄을 더한다:

```markdown
- **백업 없이 파일을 옮기지 않는다.** `backup` 이 실패하면 거기서 멈춘다.
- **병합할 때 원문을 고쳐 쓰지 않는다.** 이어붙이고 출처를 남긴다.
```

- [ ] **Step 4: Bump the version and write the changelog**

`.claude-plugin/plugin.json` 의 `"version"` 을 `"0.18.0"` 으로 올린다.

`CHANGELOG.md` 맨 위에 추가한다 (기존 항목 형식을 그대로 따를 것 — 파일 상단을 먼저 읽고 맞춘다):

```markdown
## v0.18.0 — 기존 기록의 인수인계

`/notes` 는 뼈대만 만들고 이미 있던 문서는 그 자리에 두었다. 진짜 문서 옆에 빈 문서
한 벌이 남았고, 정리는 사람 몫이었다.

`notes_adopt.py` 를 더했다. `backup` 이 원본을 통째로 남기고, `plan` 이 전수 목록과
분류 초안을 만들고, `apply` 가 `git mv` 로 옮기고 링크를 다시 걸고, `verify` 가
바이트를 다시 읽어 유실이 없음을 증명한다.

- git 이 없는 폴더는 거부하지 않는다. `git init` 과 `.gitignore` 정비를 이식의
  일부로 수행하고, 첫 커밋에서 뺀 것(비밀·대용량)을 기록한다.
- 병합은 이어붙이기만 한다. 재작성은 결과가 깔끔한 대신 유실을 검증할 수 없다.
- `notes_config.is_workspace()` 를 더했다. 자동 `git init` 이 상위 폴더에서 돌면
  하위 저장소를 통째로 삼키므로, 그것만은 중단한다. 기존 `is_repository` 는
  건드리지 않았다 — 세션 훅과 검사기가 함께 쓰는 판정이다.
```

`README.md` 의 명령·스크립트 목록에 `notes_adopt.py` 를 더한다. 파일에서 `notes_survey.py` 가 언급된 곳을 찾아 그 형식에 맞춰 한 줄 넣는다.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest -q`
Expected: 전부 통과

- [ ] **Step 6: Run the linter on this repository's own docs**

Run: `python scripts/check_docs.py`
Expected: 전부 통과

- [ ] **Step 7: Commit**

```bash
git add commands/notes.md .claude-plugin/plugin.json CHANGELOG.md README.md tests/test_adopt_command.py
git commit -m "feat: /notes 에 이식 단계 통합 (v0.18.0)

명령 문서가 부르지 않는 스크립트는 없는 스크립트다. 초기화 절의
맨 앞에 backup 을 두고, 뼈대 생성 뒤에 이식 절을 넣고, 정상
점검에도 plan 을 돌려 '이식 안 된 문서'를 보고하게 했다 -
이미 girok 이 들어간 저장소는 지금 /notes 를 쳐도 정상만 나온다."
```

---

## 실행 후 확인 — `eq-agent-v3` 실전 검증

전 과제가 끝난 뒤, 실제 저장소에서 한 번 돌려본다. **이건 계획의 일부가 아니라 인수 검사다.**

- [ ] `python scripts/notes_adopt.py plan --root ../eq-agent-v3` 를 돌리고, `git status ../eq-agent-v3` 로 **아무것도 안 바뀌었음**을 확인한다
- [ ] `?` 로 남은 항목이 스펙 예상(`THESIS.md`, `decisions/README.md`, `docs/relay-responder-*.md`)과 맞는지 본다
- [ ] `apply` 는 **사용자 승인 없이 돌리지 않는다.** 다른 저장소이고, 파일이 실제로 움직인다
