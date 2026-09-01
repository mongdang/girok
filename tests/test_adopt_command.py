"""The command document has to name the tool, or nobody runs it.

A script `/notes` never mentions is a script that does not exist.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMMAND = (ROOT / "commands" / "notes.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("subcommand", ["backup", "plan", "apply", "verify"])
def test_the_command_document_names_each_subcommand(subcommand):
    assert f'notes_adopt.py" {subcommand}' in COMMAND


def test_initialization_backs_up_before_it_writes():
    """Ordering is the one thing a reader must not get wrong."""
    backup_at = COMMAND.index('notes_adopt.py" backup')
    init_at = COMMAND.index("notes_init.py")

    assert backup_at < init_at


def test_the_routine_check_looks_for_unadopted_documents():
    assert 'notes_adopt.py" plan' in COMMAND
    assert "이식" in COMMAND


def test_the_version_was_bumped():
    import json
    version = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]

    assert version != "0.17.0", "새 기능은 버전을 올려야 클라이언트가 받는다"


def test_resolving_a_question_mark_names_the_role_field():
    """`apply` refuses on `role`, so telling people to fill `to` alone
    leaves every one of them blocked."""
    assert "role" in COMMAND
    assert "`role` 을 채운다" in COMMAND or "role 을 채운다" in COMMAND


def test_the_merge_field_rules_are_written_down():
    # Two ways to lose a merge silently: leaving a stale `to` beside it, and
    # naming the target by the name it had before it moved.
    assert "`merge` 를 적으면 `to` 는 `null`" in COMMAND
    assert "이동 후 경로" in COMMAND


def test_the_backup_folder_name_is_predictable_before_it_prints():
    assert "-girok-backup-" in COMMAND


def test_the_document_does_not_promise_a_single_commit():
    # A pre-existing repository gets a `.gitignore` commit first, so an
    # operator who reverts one commit reverts the wrong half.
    assert "커밋 하나로 묶" not in COMMAND


def test_byte_identity_is_not_claimed_for_documents_whose_links_changed():
    assert "바이트 단위(sha1)로 원본과" not in COMMAND


def test_adopt_does_not_know_about_read_only_repositories():
    assert "readOnlyRepos" in COMMAND


def test_the_routine_check_does_not_overwrite_the_mapping():
    assert 'notes_adopt.py" plan --dry-run' in COMMAND
