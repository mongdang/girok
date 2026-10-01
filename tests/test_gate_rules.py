"""PreToolUse decisions.

Blocking is reserved for the things whose cost is not comparable to the
inconvenience of a false positive: safety, and destroying history. Anything
else warns, because a check that stops ordinary work gets disabled.

Every block returns a reason and a way out. A block the person cannot act on
just becomes a reason to turn hooks off.
"""
import pytest

import gate_rules
from conftest import write


@pytest.fixture
def repo(notes_repo):
    (notes_repo / ".claude" / "girok.json").write_text(
        """{
          "notesDir": "notes",
          "modules": {"safetyGate": true},
          "parallelMode": true,
          "workers": {"abc": "abc@example.invalid"},
          "readOnlyRepos": ["reference-repo"]
        }""",
        encoding="utf-8",
    )
    write(
        notes_repo / "notes" / "docs" / "SAFETY_GATE.md",
        """
# 안전 게이트

| # | 등급 | 항목 | 확인 방법 | 확인자 | 날짜 | 상태 |
|---|---|---|---|---|---|---|
| 1 | BLOCKER | 정위치 판정 | 실측 | | | OPEN |
""",
    )
    return notes_repo


def decide(repo, tool, tool_input, git_email="abc@example.invalid"):
    return gate_rules.decide(repo, tool, tool_input, git_email=git_email)


# --- blocks -----------------------------------------------------------------

def test_blocks_editing_the_method_snapshot(repo):
    d = decide(repo, "Edit", {"file_path": str(repo / "notes" / ".method" / "RULES.md")})

    assert d.blocked
    assert "sync" in d.reason


def test_blocks_a_force_push(repo):
    d = decide(repo, "Bash", {"command": "git push --force azure abc"})

    assert d.blocked
    assert "force" in d.reason.lower()


def test_blocks_force_with_lease_too(repo):
    d = decide(repo, "Bash", {"command": "git push --force-with-lease"})

    assert d.blocked


def test_blocks_a_push_to_a_reference_repository(repo):
    d = decide(repo, "Bash", {"command": "cd reference-repo && git push origin main"})

    assert d.blocked
    assert "reference-repo" in d.reason


def test_allows_a_push_to_the_working_repository(repo):
    d = decide(repo, "Bash", {"command": "git push azure abc"})

    assert not d.blocked


def test_blocks_filling_the_confirmer_column_of_a_gate_item(repo):
    """Gate items are closed by a named person. An agent filling that column
    is the one failure this whole design exists to prevent."""
    d = decide(
        repo,
        "Edit",
        {
            "file_path": str(repo / "notes" / "docs" / "SAFETY_GATE.md"),
            "old_string": "| 1 | BLOCKER | 정위치 판정 | 실측 | | | OPEN |",
            "new_string": "| 1 | BLOCKER | 정위치 판정 | 실측 | 김담당 | 2026-08-31 | CLOSED |",
        },
    )

    assert d.blocked
    assert "확인자" in d.reason


def test_allows_adding_a_new_open_gate_item(repo):
    d = decide(
        repo,
        "Edit",
        {
            "file_path": str(repo / "notes" / "docs" / "SAFETY_GATE.md"),
            "old_string": "| 1 | BLOCKER | 정위치 판정 | 실측 | | | OPEN |",
            "new_string": (
                "| 1 | BLOCKER | 정위치 판정 | 실측 | | | OPEN |\n"
                "| 2 | MOTION | 저속 확인 | 실측 | | | OPEN |"
            ),
        },
    )

    assert not d.blocked


def test_blocks_a_motion_command_while_a_gate_item_is_open(repo):
    d = decide(repo, "Bash", {"command": "dotnet run --project Motion -- --home-all"})

    assert d.blocked
    assert "OPEN" in d.reason


def test_allows_a_motion_command_once_every_item_is_closed(repo):
    write(
        repo / "notes" / "docs" / "SAFETY_GATE.md",
        """
# 안전 게이트

| # | 등급 | 항목 | 확인 방법 | 확인자 | 날짜 | 상태 |
|---|---|---|---|---|---|---|
| 1 | BLOCKER | 정위치 판정 | 실측 | 김담당 | 2026-08-31 | CLOSED |
""",
    )

    d = decide(repo, "Bash", {"command": "dotnet run --project Motion -- --home-all"})

    assert not d.blocked


def test_a_sub_numbered_open_item_still_blocks_motion(repo):
    """`3a` is a gate item. The linter knew that and this guard did not – the
    row pattern had been copied instead of shared, and the copy drifted. An
    OPEN item that counts as zero open items is the worst possible direction
    for this particular check to be wrong in."""
    write(
        repo / "notes" / "docs" / "SAFETY_GATE.md",
        """
# 안전 게이트

| # | 등급 | 항목 | 확인 방법 | 확인자 | 날짜 | 상태 |
|---|---|---|---|---|---|---|
| 1 | BLOCKER | 정위치 판정 | 실측 | 김담당 | 2026-08-31 | CLOSED |
| 3a | BLOCKER | 인터락 배선 | 실측 |  |  | OPEN |
""",
    )

    d = decide(repo, "Bash", {"command": "dotnet run -- --home-all"})

    assert d.blocked


def test_open_in_another_column_is_not_an_open_item(repo):
    """The count comes from the 상태 column. An item that merely describes an
    open condition is closed if its status says so."""
    write(
        repo / "notes" / "docs" / "SAFETY_GATE.md",
        """
# 안전 게이트

| # | 등급 | 항목 | 확인 방법 | 확인자 | 날짜 | 상태 |
|---|---|---|---|---|---|---|
| 1 | BLOCKER | 도어 OPEN 시 정지 | 실측 | 김담당 | 2026-08-31 | CLOSED |
""",
    )

    d = decide(repo, "Bash", {"command": "dotnet run -- --home-all"})

    assert not d.blocked


def test_a_gate_table_with_no_recognizable_header_still_blocks(repo):
    """Falling back to a raw line scan. A table this code cannot parse must
    read as "something is open", never as "nothing is"."""
    write(
        repo / "notes" / "docs" / "SAFETY_GATE.md",
        "# 게이트\n\n| # | 항목 | 진행 |\n|---|---|---|\n| 1 | 정위치 | OPEN |\n",
    )

    assert decide(repo, "Bash", {"command": "dotnet run -- --home-all"}).blocked


def test_the_safety_module_can_be_turned_off(notes_repo):
    (notes_repo / ".claude" / "girok.json").write_text(
        '{"notesDir": "notes", "modules": {"safetyGate": false}}', encoding="utf-8"
    )

    d = gate_rules.decide(notes_repo, "Bash", {"command": "run --home-all"})

    assert not d.blocked


# --- warnings ---------------------------------------------------------------

def test_warns_when_writing_to_the_frozen_main_docs_during_parallel_work(repo):
    d = decide(repo, "Write", {"file_path": str(repo / "notes" / "docs" / "PROGRESS.md")})

    assert not d.blocked
    assert d.warnings


def test_the_gate_document_is_exempt_from_the_freeze(repo):
    """Safety information must not wait for a merge."""
    d = decide(
        repo,
        "Edit",
        {
            "file_path": str(repo / "notes" / "docs" / "SAFETY_GATE.md"),
            "old_string": "OPEN |",
            "new_string": "OPEN |\n| 2 | LATER | 표시 | 실측 | | | OPEN |",
        },
    )

    assert not d.warnings


def test_a_worker_folder_is_the_normal_place_to_write(repo):
    d = decide(repo, "Write", {"file_path": str(repo / "notes" / "docs_abc" / "PROGRESS.md")})

    assert not d.blocked
    assert not d.warnings


def test_warns_about_a_new_local_absolute_path_in_a_document(repo):
    d = decide(
        repo,
        "Edit",
        {
            "file_path": str(repo / "notes" / "docs_abc" / "PROGRESS.md"),
            "old_string": "내용",
            "new_string": r"코드는 D:\Work\Solution 에 있음",
        },
    )

    assert not d.blocked
    assert any("경로" in w for w in d.warnings)


def test_does_not_warn_about_an_absolute_path_in_code(repo):
    d = decide(
        repo,
        "Edit",
        {
            "file_path": str(repo / "src" / "Config.cs"),
            "old_string": "a",
            "new_string": r'var p = @"D:\Work";',
        },
    )

    assert not d.warnings


def test_says_nothing_about_an_unrelated_tool(repo):
    d = decide(repo, "Read", {"file_path": str(repo / "notes" / "docs" / "PROGRESS.md")})

    assert not d.blocked
    assert not d.warnings


# --- worker confirmation ----------------------------------------------------
#
# "확인 전에는 어떤 작업도 진행하지 않는다" was previously only injected as text
# for the model to obey. Text is not enforcement: nothing stopped a write.
#
# Confirmation is defined as the mapping existing in the config, so the state
# is checkable at any moment instead of living in a session nobody can inspect.

def test_an_unmapped_worker_cannot_write_a_document(repo):
    d = decide(
        repo,
        "Write",
        {"file_path": str(repo / "notes" / "docs_abc" / "PROGRESS.md")},
        git_email="nobody@example.invalid",
    )

    assert d.blocked
    assert "workers" in d.reason


def test_the_block_names_the_email_so_the_fix_is_obvious(repo):
    d = decide(
        repo,
        "Write",
        {"file_path": str(repo / "notes" / "docs_abc" / "PROGRESS.md")},
        git_email="nobody@example.invalid",
    )

    assert "nobody@example.invalid" in d.reason


def test_a_mapped_worker_writes_freely(repo):
    (repo / ".claude" / "girok.json").write_text(
        '{"notesDir": "notes", "parallelMode": true,'
        ' "workers": {"abc": "abc@example.invalid"}}',
        encoding="utf-8",
    )

    d = decide(
        repo,
        "Write",
        {"file_path": str(repo / "notes" / "docs_abc" / "PROGRESS.md")},
        git_email="abc@example.invalid",
    )

    assert not d.blocked


def test_the_config_itself_stays_writable(repo):
    """Blocking the file that records the answer would make the block
    unresolvable from inside the session."""
    d = decide(
        repo,
        "Edit",
        {"file_path": str(repo / ".claude" / "girok.json")},
        git_email="nobody@example.invalid",
    )

    assert not d.blocked


def test_the_safety_gate_stays_writable(repo):
    """Safety information does not wait for anything, including this."""
    d = decide(
        repo,
        "Edit",
        {
            "file_path": str(repo / "notes" / "docs" / "SAFETY_GATE.md"),
            "old_string": "OPEN |",
            "new_string": "OPEN |\n| 2 | LATER | 표시 | 실측 | | | OPEN |",
        },
        git_email="nobody@example.invalid",
    )

    assert not d.blocked


def test_code_edits_are_not_blocked_by_an_unmapped_worker(repo):
    """The rule exists so records are not filed under the wrong name. A
    source file is not a record."""
    d = decide(
        repo,
        "Edit",
        {"file_path": str(repo / "src" / "Motion.cs"), "old_string": "a", "new_string": "b"},
        git_email="nobody@example.invalid",
    )

    assert not d.blocked


def test_an_unmapped_worker_cannot_commit(repo):
    d = decide(repo, "Bash", {"command": "git commit -m '작업'"}, git_email="nobody@example.invalid")

    assert d.blocked


def test_an_unmapped_worker_cannot_push(repo):
    d = decide(repo, "Bash", {"command": "git push origin abc"}, git_email="nobody@example.invalid")

    assert d.blocked


def test_a_folder_that_never_adopted_this_is_not_blocked(tmp_path):
    """parallelMode defaults to true, so a repository with no config at all –
    one that never adopted the methodology, or a session started outside a
    repository – was blocked from committing for an "unconfirmed worker"
    nobody was ever asked to configure."""
    plain = tmp_path / "unrelated"
    (plain / ".git").mkdir(parents=True)

    d = gate_rules.decide(
        plain, "Bash", {"command": "git commit -m 'x'"}, git_email="anyone@example.invalid"
    )

    assert not d.blocked


def test_none_of_this_applies_outside_parallel_mode(notes_repo):
    (notes_repo / ".claude" / "girok.json").write_text(
        '{"notesDir": "notes", "parallelMode": false}', encoding="utf-8"
    )

    d = gate_rules.decide(
        notes_repo,
        "Write",
        {"file_path": str(notes_repo / "notes" / "docs" / "PROGRESS.md")},
        git_email="nobody@example.invalid",
    )

    assert not d.blocked
