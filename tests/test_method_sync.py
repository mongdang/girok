"""The committed .method/ snapshot.

The snapshot is what makes a repository self-contained: clone it and the
full rule text is there, without the plugin, readable by any agent. It also
records which revision of the rules applied at each commit.

Nobody edits it by hand — that would recreate the copy drift this whole
design exists to remove — so the integrity check has to notice when someone
did.
"""
import json
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


def test_settings_sync_keeps_what_was_already_there(tmp_path):
    """Every repository that adopted girok before this already has a
    settings.json, and `_write` skips a file that exists — so the hooks would
    never arrive. Adding them must not cost the permissions someone put
    there by hand."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}), encoding="utf-8"
    )

    changed = method_sync.sync_settings(tmp_path, "notes/")

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert changed
    assert settings["permissions"]["allow"] == ["Bash(ls:*)"]
    assert "SessionStart" in settings["hooks"]


def test_settings_sync_says_nothing_changed_the_second_time(tmp_path):
    """`/notes` runs on every drift. Reporting a change each time would train
    people to ignore the one that matters."""
    method_sync.sync_settings(tmp_path, "notes/")

    assert not method_sync.sync_settings(tmp_path, "notes/")


def test_a_flat_repository_registers_hooks_at_its_root(tmp_path):
    """notesDir "." puts .method/ at the root. A path with notes/ baked in
    would register a wrapper that is not there."""
    method_sync.sync_settings(tmp_path, "")

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]

    assert "/.method/hooks/run-hook.cmd" in command
    assert "notes/" not in command


def test_verify_fails_when_the_hooks_are_not_registered(notes_repo):
    """Hooks sitting in the snapshot that nothing registers are hooks that
    never run. Inside a session the missing ready marker catches that -- but
    the marker itself comes from a hook, so something outside the session has
    to be able to see it too."""
    method_sync.sync(notes_repo)
    assert method_sync.verify(notes_repo).ok

    settings = notes_repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    del data["hooks"]
    settings.write_text(json.dumps(data), encoding="utf-8")

    result = method_sync.verify(notes_repo)

    assert not result.ok
    assert any("settings.json" in problem for problem in result.problems)


def test_verify_fails_when_a_registration_points_somewhere_else(notes_repo):
    """A stale path is worse than a missing one: the entry reads as correct
    and the hook still never runs."""
    method_sync.sync(notes_repo)
    settings = notes_repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["Stop"][0]["hooks"][0]["command"] = '"/somewhere/else/run-hook.cmd" stop'
    settings.write_text(json.dumps(data), encoding="utf-8")

    result = method_sync.verify(notes_repo)

    assert not result.ok
    assert any("Stop" in problem for problem in result.problems)


def test_a_repository_may_register_hooks_of_its_own(notes_repo):
    """Comparing the whole block would fail a repository that added a hook of
    its own, and a check that punishes ordinary use gets removed rather than
    obeyed."""
    method_sync.sync(notes_repo)
    settings = notes_repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "echo 내 훅"}]})
    settings.write_text(json.dumps(data), encoding="utf-8")

    assert method_sync.verify(notes_repo).ok


def test_the_gate_does_not_send_people_to_install_a_plugin(notes_repo):
    """The hooks run from the repository now, so a missing readiness block no
    longer means a missing plugin. Diagnosing it as one stopped work on a
    machine where everything was in fact in place, and told the person to
    install something that would have changed nothing."""
    method_sync.sync(notes_repo)

    head = (notes_repo / "notes" / ".method" / "RULES.md").read_text(encoding="utf-8")[:1800]

    assert "중단" in head
    assert "/notes" in head
    assert "플러그인 설치" not in head


def test_the_plugin_does_not_register_hooks_of_its_own(notes_repo):
    """Claude Code keeps a plugin's hooks separate from a project's, and two
    different command strings never deduplicate. Leaving hooks.json in place
    would run every check twice and double every report."""
    assert not (method_sync.PLUGIN_ROOT / "hooks" / "hooks.json").exists()


def test_sync_refuses_to_run_out_of_the_snapshot(notes_repo):
    """PLUGIN_ROOT defaults to the script's own grandparent, so running the
    snapshot's copy of this file with no plugin installed pointed sync at
    .method/ itself: it deleted the folder, then looked for the sources
    inside what it had just deleted. Every hook and linter vanished and the
    run reported success."""
    method_sync.sync(notes_repo)
    method = notes_repo / "notes" / ".method"

    with pytest.raises(method_sync.NoPluginError):
        method_sync.sync(notes_repo, plugin_root=method)

    assert (method / "hooks" / "session-start.py").is_file()
    assert (method / "scripts" / "check_docs.py").is_file()
    assert method_sync.verify(notes_repo).ok


def test_sync_refuses_before_deleting_anything(notes_repo, tmp_path):
    """The refusal has to come before the folder is removed. Refusing after
    the rmtree would report an error and still have destroyed the snapshot."""
    method_sync.sync(notes_repo)
    rules = (notes_repo / "notes" / ".method" / "RULES.md").read_text(encoding="utf-8")

    with pytest.raises(method_sync.NoPluginError):
        method_sync.sync(notes_repo, plugin_root=tmp_path / "not-a-plugin")

    assert (notes_repo / "notes" / ".method" / "RULES.md").read_text(encoding="utf-8") == rules


def test_settings_sync_keeps_hooks_the_repository_added(notes_repo):
    """verify allows a repository to register hooks of its own, so sync must
    not delete them. Replacing the whole block silently stopped somebody
    else's logging hook the first time /notes ran."""
    method_sync.sync(notes_repo)
    settings = notes_repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["UserPromptSubmit"].append(
        {"hooks": [{"type": "command", "command": "echo 내 로깅 훅"}]}
    )
    data["hooks"]["SessionEnd"] = [{"hooks": [{"type": "command", "command": "echo 끝"}]}]
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    method_sync.sync_settings(notes_repo, "notes/")

    after = json.loads(settings.read_text(encoding="utf-8"))
    commands = [
        hook.get("command", "")
        for entry in after["hooks"]["UserPromptSubmit"]
        for hook in entry.get("hooks", [])
    ]
    assert any("내 로깅 훅" in c for c in commands), commands
    assert "SessionEnd" in after["hooks"]
    assert method_sync.verify(notes_repo).ok


def test_settings_sync_replaces_only_its_own_entry(notes_repo):
    """A stale girok entry from an older layout must go, or the repository
    would keep a registration pointing at a wrapper that is not there."""
    method_sync.sync(notes_repo)
    settings = notes_repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["Stop"] = [
        {"hooks": [{"type": "command", "command": '"old/.method/hooks/run-hook.cmd" stop'}]}
    ]
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    method_sync.sync_settings(notes_repo, "notes/")

    after = json.loads(settings.read_text(encoding="utf-8"))
    commands = [
        hook.get("command", "")
        for entry in after["hooks"]["Stop"]
        for hook in entry.get("hooks", [])
    ]
    assert not any("old/.method" in c for c in commands), commands
    assert method_sync.verify(notes_repo).ok


def test_verify_rejects_a_registration_that_only_looks_right(notes_repo):
    """Matching the wrapper as a substring passed a path that merely ends the
    same way. The entry reads as correct in the file and the hook never runs
    -- the exact failure this check exists to catch."""
    method_sync.sync(notes_repo)
    settings = notes_repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["Stop"][0]["hooks"][0]["command"] = (
        '"$CLAUDE_PROJECT_DIR/vendor.notes/.method/hooks/run-hook.cmd" stop'
    )
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = method_sync.verify(notes_repo)

    assert not result.ok
    assert any("Stop" in problem for problem in result.problems)


def test_a_corrupt_version_is_not_read_as_a_version(notes_repo):
    """parse_version takes the last word of the stamp, so a VERSION holding
    "corrupt data" reported the snapshot version as "data" -- and the session
    then announced `ready vdata` for a snapshot nobody had checked."""
    method_sync.sync(notes_repo)
    version = notes_repo / "notes" / ".method" / "VERSION"
    version.write_text("corrupt data\n", encoding="utf-8")

    assert method_sync.status(notes_repo).snapshot_version is None


def test_the_settings_template_can_still_be_rendered():
    """The template goes through str.format, so a single unescaped brace in
    it raises where the hooks are written. It is the one file whose breakage
    leaves a repository with no registration at all."""
    assert method_sync._default_settings(method_sync.PLUGIN_ROOT).get("enabledPlugins")


def test_a_broken_settings_file_is_reported_not_silently_kept(notes_repo):
    """Refusing to overwrite half-edited JSON is right; saying nothing about
    it is not. The snapshot lands, the hooks do not register, and the run
    reads as a clean success."""
    method_sync.sync(notes_repo)
    settings = notes_repo / ".claude" / "settings.json"
    settings.write_text("{ 이건 JSON 이 아니다", encoding="utf-8")

    result = method_sync.sync(notes_repo)

    assert result.settings_problem
    assert "settings.json" in result.settings_problem


def test_settings_sync_keeps_a_hook_that_only_names_the_wrapper(notes_repo):
    """Recognizing our own entry matched the wrapper anywhere in the command
    while verify matched it at a path boundary. A hook that passes the path
    as an argument -- rather than running it -- read as girok leftovers and
    was deleted."""
    method_sync.sync(notes_repo)
    settings = notes_repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "python tools/audit.py --skip .method/hooks/run-hook.cmd"}]}
    )
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    method_sync.sync_settings(notes_repo, "notes/")

    after = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h.get("command", "") for e in after["hooks"]["Stop"] for h in e.get("hooks", [])]
    assert any("tools/audit.py" in c for c in commands), commands
    assert method_sync.verify(notes_repo).ok


def test_a_version_hash_that_is_not_a_hash_is_not_read_as_a_version(notes_repo):
    """status measured the hash's length and sync also measured its
    characters, so a stamp carrying 64 non-hex characters was a snapshot to
    the gate and a foreign folder to sync. The gate announced it ready."""
    method_sync.sync(notes_repo)
    version = notes_repo / "notes" / ".method" / "VERSION"
    version.write_text("other v1.2.3 / 2026-01-01 / abc1234 / " + "z" * 64 + "\n", encoding="utf-8")

    assert method_sync.status(notes_repo).snapshot_version is None


def test_a_sync_that_fails_partway_leaves_the_snapshot_it_had(notes_repo, monkeypatch):
    """sync deleted the folder and then wrote twenty files into it. A failure
    in between left a half-built snapshot that the next run refuses to touch,
    so the repository sits unsupervised until someone deletes it by hand."""
    method_sync.sync(notes_repo)
    method = notes_repo / "notes" / ".method"
    before = sorted(p.relative_to(method).as_posix() for p in method.rglob("*") if p.is_file())

    real = method_sync.shutil.copyfile
    copied = []

    def fails_once_it_is_underway(src, dst, *args, **kwargs):
        copied.append(dst)
        if len(copied) > 3:
            raise OSError("디스크가 가득 찼다")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(method_sync.shutil, "copyfile", fails_once_it_is_underway)

    with pytest.raises(OSError):
        method_sync.sync(notes_repo)

    after = sorted(p.relative_to(method).as_posix() for p in method.rglob("*") if p.is_file())
    assert after == before
    assert method_sync.verify(notes_repo).ok
