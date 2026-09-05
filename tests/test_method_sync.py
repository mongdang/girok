"""The committed .method/ snapshot.

The snapshot is what makes a repository self-contained: clone it and the
full rule text is there, without the plugin, readable by any agent. It also
records which revision of the rules applied at each commit.

Nobody edits it by hand — that would recreate the copy drift this whole
design exists to remove — so the integrity check has to notice when someone
did.
"""
import os
import subprocess

import method_sync
import pytest
from conftest import write


def test_sync_writes_the_rule_text_scripts_and_a_version(notes_repo):
    method_sync.sync(notes_repo)

    method = notes_repo / "notes" / ".method"
    assert (method / "RULES.md").is_file()
    assert (method / "VERSION").is_file()
    assert (method / "scripts" / "check_docs.py").is_file()


def test_the_rule_text_contains_every_skill(notes_repo):
    method_sync.sync(notes_repo)

    rules = (notes_repo / "notes" / ".method" / "RULES.md").read_text(encoding="utf-8")

    for skill in ("project-notes", "progress-board", "writing-adr", "doc-style", "parallel-docs"):
        assert skill in rules


def test_the_rule_text_opens_with_the_bootstrap_gate(notes_repo):
    """Agents without the plugin read this file and nothing else, so the
    check that the plugin is loaded has to be the first thing in it."""
    method_sync.sync(notes_repo)

    rules = (notes_repo / "notes" / ".method" / "RULES.md").read_text(encoding="utf-8")
    head = rules[:1500]

    assert "VERSION" in head
    assert "중단" in head


def test_version_records_the_plugin_version_and_a_content_hash(notes_repo):
    method_sync.sync(notes_repo)

    version = (notes_repo / "notes" / ".method" / "VERSION").read_text(encoding="utf-8")

    assert "girok v" in version
    assert len(method_sync.parse_version(version).content_hash) == 64


def test_verify_passes_on_a_fresh_snapshot(notes_repo):
    method_sync.sync(notes_repo)

    assert method_sync.verify(notes_repo).ok


def test_verify_fails_when_a_person_edits_the_snapshot(notes_repo):
    method_sync.sync(notes_repo)
    rules = notes_repo / "notes" / ".method" / "RULES.md"
    rules.write_text(rules.read_text(encoding="utf-8") + "\n한 줄 추가\n", encoding="utf-8")

    result = method_sync.verify(notes_repo)

    assert not result.ok
    assert any("RULES.md" in problem for problem in result.problems)


def test_verify_fails_when_a_file_is_deleted(notes_repo):
    method_sync.sync(notes_repo)
    (notes_repo / "notes" / ".method" / "scripts" / "check_docs.py").unlink()

    assert not method_sync.verify(notes_repo).ok


def test_verify_reports_a_missing_snapshot_rather_than_crashing(notes_repo):
    result = method_sync.verify(notes_repo)

    assert not result.ok
    assert any(".method" in problem for problem in result.problems)


def test_sync_is_reproducible(notes_repo):
    """Two syncs of the same plugin revision must produce the same content
    hash, or the integrity check would fail on every re-sync."""
    method_sync.sync(notes_repo)
    first = method_sync.parse_version(
        (notes_repo / "notes" / ".method" / "VERSION").read_text(encoding="utf-8")
    ).content_hash

    method_sync.sync(notes_repo)
    second = method_sync.parse_version(
        (notes_repo / "notes" / ".method" / "VERSION").read_text(encoding="utf-8")
    ).content_hash

    assert first == second


def test_sync_reports_a_stale_snapshot_before_overwriting(notes_repo):
    method_sync.sync(notes_repo)
    write(notes_repo / "notes" / ".method" / "stray.md", "사람이 넣은 파일\n")

    result = method_sync.sync(notes_repo)

    assert "stray.md" in " ".join(result.removed)
    assert method_sync.verify(notes_repo).ok


def test_status_says_whether_the_snapshot_matches_the_plugin(notes_repo, downgrade_snapshot):
    method_sync.sync(notes_repo)
    assert method_sync.status(notes_repo).in_sync

    version = notes_repo / "notes" / ".method" / "VERSION"
    downgrade_snapshot(version)

    assert not method_sync.status(notes_repo).in_sync


def test_the_snapshot_can_verify_itself_without_the_plugin(notes_repo, tmp_path, monkeypatch):
    """This is the CI case: a checkout with no plugin installed runs
    verify out of .method/. It must need nothing but the files and the
    recorded hash."""
    method_sync.sync(notes_repo)
    method = notes_repo / "notes" / ".method"

    assert (method / "scripts" / "method_sync.py").is_file()

    monkeypatch.setattr(method_sync, "PLUGIN_ROOT", tmp_path / "no-plugin-here")

    assert method_sync.verify(notes_repo).ok


def test_running_the_snapshot_scripts_does_not_break_its_own_hash(notes_repo):
    """CI runs verify out of .method/, and Python writes __pycache__ next to
    the scripts it imports. Counting that bytecode would make the gate fail
    on its own side effect."""
    method_sync.sync(notes_repo)
    cache = notes_repo / "notes" / ".method" / "scripts" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "check_docs.cpython-312.pyc").write_bytes(b"\x00compiled\x00")

    result = method_sync.verify(notes_repo)

    assert result.ok, result.problems


def test_the_snapshot_ignores_its_own_bytecode(notes_repo):
    method_sync.sync(notes_repo)

    ignore = (notes_repo / "notes" / ".method" / ".gitignore").read_text(encoding="utf-8")

    assert "__pycache__" in ignore


def test_sync_refuses_to_delete_a_method_folder_that_is_not_ours(notes_repo):
    """sync rebuilds .method/ by deleting it first. A repository that happens
    to keep something else at that path would lose it, so the folder has to
    identify itself as this plugin's before anything is removed."""
    stranger = notes_repo / "notes" / ".method"
    stranger.mkdir(parents=True)
    (stranger / "somebody-elses-data.txt").write_text("소중한 것", encoding="utf-8")

    with pytest.raises(method_sync.NotOursError):
        method_sync.sync(notes_repo)

    assert (stranger / "somebody-elses-data.txt").is_file()


def test_sync_replaces_a_folder_it_recognizes(notes_repo):
    method_sync.sync(notes_repo)
    method_sync.sync(notes_repo)

    assert method_sync.verify(notes_repo).ok


def test_sync_still_recognizes_a_pre_rename_snapshot(notes_repo):
    """Snapshots written before the girok rename identify themselves with the
    old plugin name, which is deliberately not spelled anywhere anymore. They
    are recognized by the stamp's shape — the 64-hex content hash — so an
    adopted repository's first re-sync after the rename still runs."""
    method_sync.sync(notes_repo)
    version = notes_repo / "notes" / ".method" / "VERSION"
    version.write_text(
        version.read_text(encoding="utf-8").replace("girok", "old-plugin-name"),
        encoding="utf-8",
    )

    result = method_sync.sync(notes_repo)

    assert result.version is not None
    assert method_sync.verify(notes_repo).ok


def test_status_does_not_die_when_the_plugin_is_not_installed(notes_repo, tmp_path):
    """The snapshot carries the hooks now, so a session runs on machines with
    no plugin at all. Raising here took the whole session-start report down
    with it — a repository that was fully set up reported nothing."""
    method_sync.sync(notes_repo)

    state = method_sync.status(notes_repo, tmp_path / "no-plugin-here")

    assert state.plugin_version is None
    assert state.snapshot_version is not None
    assert not state.in_sync


def test_sync_writes_the_hooks_too(notes_repo):
    """Hooks that live only inside the plugin are hooks that do not run on a
    machine without it. The snapshot is what a clone gets, so the enforcement
    has to travel in it alongside the rule text."""
    method_sync.sync(notes_repo)
    hooks = notes_repo / "notes" / ".method" / "hooks"

    for name in ("session-start.py", "pre-tool-use.py", "hook_io.py", "run-hook.cmd"):
        assert (hooks / name).is_file(), name


def test_editing_a_hook_changes_the_snapshot_hash(notes_repo):
    """Hook code outside the content hash is hook code CI cannot vouch for --
    the one file that decides what gets blocked would be the one file anyone
    could quietly rewrite."""
    method_sync.sync(notes_repo)
    hook = notes_repo / "notes" / ".method" / "hooks" / "hook_io.py"
    hook.write_text(hook.read_text(encoding="utf-8") + "\n# 한 줄\n", encoding="utf-8")

    result = method_sync.verify(notes_repo)

    assert not result.ok
    assert any("hook_io.py" in problem for problem in result.problems)


def test_verify_fails_when_a_hook_is_deleted(notes_repo):
    method_sync.sync(notes_repo)
    (notes_repo / "notes" / ".method" / "hooks" / "stop.py").unlink()

    assert not method_sync.verify(notes_repo).ok


def test_the_wrapper_is_committed_executable(notes_repo):
    """copyfile drops the execute bit, and git on Windows adds new files as
    100644 with no way to say otherwise. Either way the wrapper reaches a
    Linux checkout unexecutable: registered, and silently never running --
    a session that looks supervised and is not."""
    subprocess.run(["git", "init", "-q"], cwd=notes_repo, check=True)

    method_sync.sync(notes_repo)

    listed = subprocess.run(
        ["git", "ls-files", "-s", "notes/.method/hooks/run-hook.cmd"],
        cwd=notes_repo, capture_output=True, text=True, check=True,
    ).stdout
    assert listed.startswith("100755"), listed or "(인덱스에 없다)"


@pytest.mark.skipif(os.name == "nt", reason="Windows 파일에는 실행 비트가 없다")
def test_the_wrapper_is_executable_on_disk(notes_repo):
    method_sync.sync(notes_repo)

    wrapper = notes_repo / "notes" / ".method" / "hooks" / "run-hook.cmd"

    assert os.stat(wrapper).st_mode & 0o111
