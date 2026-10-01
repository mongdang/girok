import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.lstrip("\n"), encoding="utf-8")
    return path


@pytest.fixture
def notes_repo(tmp_path):
    """A minimal repository laid out the way this methodology expects.

    Returns the repo root. The notes live in <root>/notes, declared by
    <root>/.claude/girok.json, so tests exercise config discovery
    rather than a hardcoded layout.
    """
    root = tmp_path / "repo"
    write(
        root / ".claude" / "girok.json",
        json.dumps(
            {
                "notesDir": "notes",
                "workers": {"abc": "abc@example.invalid"},
                "limits": {"rulesKB": 20, "boardKB": 30},
                "parallelMode": True,
            }
        ),
    )
    write(
        root / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

> 관련 문서: 결정 기록 `docs/decisions/README.md`

---

## 목차

- [상태 요약](#상태-요약)

---

## 상태 요약

| 항목 | 상태 |
|---|---|
| a | ok |
""",
    )
    write(
        root / "notes" / "docs" / "decisions" / "README.md",
        """
# 결정 기록(ADR) 인덱스

## 목록

| ID | 상태 |
|---|---|
| [ADR-001](ADR-001-first.md) | accepted |
""",
    )
    write(
        root / "notes" / "docs" / "decisions" / "ADR-001-first.md",
        """
# ADR-001 – 첫 결정

| | |
|---|---|
| 상태 | accepted |

## 결정

무언가를 하기로 했음
""",
    )
    return root


@pytest.fixture
def current_version():
    """The plugin's own version.

    Tests read it rather than spelling it out: a release has to bump this
    (a client caches the plugin under its version directory and would
    otherwise keep serving the copy it first fetched), and a test suite
    that breaks on every bump gets its assertions weakened instead.
    """
    import method_sync

    return method_sync.plugin_version()


@pytest.fixture
def downgrade_snapshot():
    """Rewrite a snapshot's VERSION to an older release."""

    def _downgrade(version_file):
        text = version_file.read_text(encoding="utf-8")
        head, rest = text.split("/", 1)
        version_file.write_text(f"girok v0.0.1 /{rest}", encoding="utf-8")

    return _downgrade
