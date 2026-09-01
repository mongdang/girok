"""The doc linter: table of contents anchors, GFM table continuity, ADR
citation integrity, and size limits.

Each test states the failure it guards against, because every check here
exists in response to a mistake that actually reached a commit.
"""
import pytest

import check_docs
from conftest import write


def run(root):
    return check_docs.run(root)


def test_passes_on_a_well_formed_repo(notes_repo):
    result = run(notes_repo)

    assert result.ok
    assert result.failures == []


def test_reports_a_toc_anchor_that_no_heading_matches(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [없는 절](#없는-절)

---

## 상태 요약

내용
""",
    )

    result = run(notes_repo)

    assert not result.ok
    assert any("없는-절" in f.message for f in result.failures)


def test_a_header_with_a_spaced_separator_breaks_its_own_anchor(notes_repo):
    """` — ` in a header makes the linter's slug and GitHub's real anchor
    disagree on hyphen count, so the TOC link silently stops working."""
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [상태 요약 — 개요](#상태-요약-개요)

---

## 상태 요약 — 개요

내용
""",
    )

    result = run(notes_repo)

    assert not result.ok


def test_reports_a_table_split_by_a_blank_line(notes_repo):
    """GFM needs header, separator and body rows adjacent. A blank line
    turns everything after it into plain text that still looks like a table
    in the editor."""
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [상태 요약](#상태-요약)

---

## 상태 요약

| 항목 | 상태 |
|---|---|
| a | ok |

| b | ok |
""",
    )

    result = run(notes_repo)

    assert not result.ok
    assert any("표" in f.message or "table" in f.message.lower() for f in result.failures)


def test_ignores_tables_and_headings_inside_fenced_code(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [상태 요약](#상태-요약)

---

## 상태 요약

```markdown
## 이건 헤더가 아님

| a |

| b |
```
""",
    )

    result = run(notes_repo)

    assert result.ok


def test_a_longer_fence_does_not_close_a_shorter_one(notes_repo):
    """A ``` inside a ```` block used to be read as the closing fence, which
    swallowed the rest of the document."""
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [상태 요약](#상태-요약)

---

## 상태 요약

````markdown
```
| a |
```
````

| 항목 | 상태 |
|---|---|
| a | ok |
""",
    )

    result = run(notes_repo)

    assert result.ok


def test_reports_a_citation_of_an_adr_that_does_not_exist(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [상태 요약](#상태-요약)

---

## 상태 요약

배경은 ADR-999 참고
""",
    )

    result = run(notes_repo)

    assert not result.ok
    assert any("999" in f.message for f in result.failures)


def test_accepts_a_date_style_adr_id(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "decisions" / "ADR-260821-abc-parallel.md",
        "# ADR-260821-abc-parallel — 병행\n",
    )
    write(
        notes_repo / "notes" / "docs" / "decisions" / "README.md",
        """
# 결정 기록(ADR) 인덱스

## 목록

| ID | 상태 |
|---|---|
| [ADR-001](ADR-001-first.md) | accepted |
| [ADR-260821-abc-parallel](ADR-260821-abc-parallel.md) | accepted |
""",
    )

    result = run(notes_repo)

    assert result.ok


def test_reports_an_adr_missing_from_its_index(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "decisions" / "ADR-002-second.md",
        "# ADR-002 — 두번째\n",
    )

    result = run(notes_repo)

    assert not result.ok
    assert any("002" in f.message for f in result.failures)


def test_does_not_chase_an_adr_belonging_to_another_repository(notes_repo):
    """`other-repo`의 ADR-020 cites a decision that lives elsewhere; the
    linter has no way to check it and must not claim it is dead."""
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [상태 요약](#상태-요약)

---

## 상태 요약

형식은 `other-repo`의 ADR-020 을 이식한 것
""",
    )

    result = run(notes_repo)

    assert result.ok


def test_checks_a_parallel_worker_folder_with_the_same_rules(notes_repo):
    write(
        notes_repo / "notes" / "docs_abc" / "PROGRESS.md",
        """
# 현황판 (abc)

> 최종 수정: 2026-08-31 10:00 · abc

---

## 목차

- [없는 절](#없는-절)

---

## 진행

내용
""",
    )

    result = run(notes_repo)

    assert not result.ok
    assert any("docs_abc" in f.path for f in result.failures)


def test_size_limit_is_a_warning_not_a_failure(notes_repo):
    board = notes_repo / "notes" / "docs" / "PROGRESS.md"
    board.write_text(board.read_text(encoding="utf-8") + "\n" + "가" * 20_000, encoding="utf-8")

    result = run(notes_repo)

    assert result.ok
    assert any("PROGRESS.md" in w.message for w in result.warnings)


def test_size_limit_comes_from_the_config(notes_repo):
    config = notes_repo / ".claude" / "girok.json"
    config.write_text(
        '{"notesDir": "notes", "limits": {"boardKB": 1}}', encoding="utf-8"
    )
    board = notes_repo / "notes" / "docs" / "PROGRESS.md"
    board.write_text(board.read_text(encoding="utf-8") + "\n" + "가" * 2_000, encoding="utf-8")

    result = run(notes_repo)

    assert any("PROGRESS.md" in w.message for w in result.warnings)


def test_finds_the_notes_folder_without_a_config(tmp_path):
    """Other agents clone the repo without the plugin and run the linter
    straight out of .method/; it has to work with no config present."""
    root = tmp_path / "bare"
    write(
        root / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [없는 절](#없는-절)

---

## 상태

내용
""",
    )

    result = run(root)

    assert not result.ok


def test_a_document_without_a_toc_is_skipped_not_failed(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "NOTES.md",
        "# 그냥 메모\n\n목차 없는 문서임\n",
    )

    result = run(notes_repo)

    assert result.ok


def test_a_toc_that_is_the_last_section_is_still_a_toc(notes_repo):
    """The section used to be recognized only when a blank line and a `---`
    or a `##` followed it. A table of contents at the end of a document read
    as no table of contents at all: the anchors went unchecked, and the
    document was warned for missing the thing it had."""
    write(
        notes_repo / "notes" / "docs" / "END.md",
        "# 문서\n\n" + "본문임\n" * 200 + "\n## 목차\n\n- [없는 절](#없는-절)\n",
    )

    result = run(notes_repo)

    assert any("#없는-절" in p.message for p in result.failures)
    assert not any("`## 목차` 가 없다" in p.message for p in result.warnings)


def test_a_toc_followed_by_a_heading_with_no_blank_line(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "TIGHT.md",
        "# 문서\n\n## 목차\n- [본문](#본문)\n- [없는 절](#없는-절)\n## 본문\n내용임\n",
    )

    result = run(notes_repo)

    assert any("#없는-절" in p.message for p in result.failures)
    assert not any("#본문" in p.message for p in result.failures)


@pytest.mark.parametrize("name", ["archive", "screenshots"])
def test_archive_is_not_linted(notes_repo, name):
    """Archived narratives are frozen at the moment they were moved; the
    linter must not demand that they be reformatted."""
    write(
        notes_repo / "notes" / "docs" / name / "old.md",
        """
# 옛 서사

## 목차

- [없는 절](#없는-절)

---

| a |

| b |
""",
    )

    result = run(notes_repo)

    assert result.ok


def test_reports_a_local_absolute_path_in_a_document(notes_repo):
    """The edit-time hook warns about these, but a path that arrives any
    other way — someone without the plugin, a web edit, a file written before
    adoption — was never caught. The linter is the backstop."""
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        r"""
# 현황판

---

## 목차

- [상태](#상태)

---

## 상태

코드는 D:\Work\Solution 에 있음
""",
    )

    result = run(notes_repo)

    assert result.ok, "차단이 아니라 경고여야 한다"
    assert any("절대경로" in w.message for w in result.warnings)
    assert any(r"D:\Work\Solution" in w.message for w in result.warnings)


def test_a_unc_path_counts_too(notes_repo):
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        "# 현황판\n\n---\n\n## 목차\n\n- [상태](#상태)\n\n---\n\n## 상태\n\n\\\\server\\share\\build 참고\n",
    )

    result = run(notes_repo)

    assert any("절대경로" in w.message for w in result.warnings)


def test_a_path_inside_a_code_fence_is_left_alone(notes_repo):
    """Install instructions and command examples live in fences, and there a
    path is the point."""
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        r"""
# 현황판

---

## 목차

- [상태](#상태)

---

## 상태

```bash
cd D:\Work\Solution
```
""",
    )

    result = run(notes_repo)

    assert not any("절대경로" in w.message for w in result.warnings)


def test_an_equipment_registry_path_is_not_a_file_path(notes_repo):
    """A registry key is the value itself, not a location on this machine."""
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        "# 현황판\n\n---\n\n## 목차\n\n- [상태](#상태)\n\n---\n\n## 상태\n\n설정은 `HKCU\\Software\\Vendor\\App` 에 있음\n",
    )

    result = run(notes_repo)

    assert not any("절대경로" in w.message for w in result.warnings)


def test_says_so_when_a_foreign_citation_detaches_its_particle(notes_repo):
    """`other-repo` 의 ADR-020 — with a space before the particle — is the same
    citation written with a Korean spacing mistake: a particle attaches to the
    word before it. The linter has to name that, because reporting it as a dead
    reference sent one reader looking for a bug in the linter and another
    deleting the particle to get past it.
    """
    write(
        notes_repo / "notes" / "docs" / "PROGRESS.md",
        """
# 현황판

---

## 목차

- [상태 요약](#상태-요약)

---

## 상태 요약

형식은 `other-repo` 의 ADR-020 을 이식한 것
""",
    )

    result = run(notes_repo)

    assert not result.ok
    assert any("조사" in f.message for f in result.failures)
    assert not any("존재하지 않는" in f.message for f in result.failures)
