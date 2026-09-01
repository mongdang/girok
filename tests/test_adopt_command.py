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
