"""Initializing a repository.

One approval, then the skeleton exists and passes its own linter. The parts
that matter: the bootstrap gate lands in CLAUDE.md (without it a repo cloned
before the plugin arrives is worked on with no rules), the other agents get
pointers rather than copies of the rules, and nothing already written is
overwritten.
"""
import json

import check_docs
import notes_init
import pytest


@pytest.fixture
def empty_repo(tmp_path):
    root = tmp_path / "fresh"
    (root / ".git").mkdir(parents=True)
    return root


def test_creates_the_skeleton(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    for rel in (
        "notes/CLAUDE.md",
        "notes/GEMINI.md",
        "notes/AGENTS.md",
        "notes/docs/PROGRESS.md",
        "notes/docs/decisions/README.md",
        "notes/.method/RULES.md",
        "notes/.method/VERSION",
        ".claude/settings.json",
        ".claude/girok.json",
    ):
        assert (empty_repo / rel).is_file(), rel


def test_the_skeleton_passes_its_own_linter(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    result = check_docs.run(empty_repo)

    assert result.ok, [f"{p.path}: {p.message}" for p in result.failures]


def test_claude_md_carries_the_bootstrap_gate(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    text = (empty_repo / "notes" / "CLAUDE.md").read_text(encoding="utf-8")

    assert "작업 전 필수 확인" in text
    assert "notes/.method/VERSION" in text
    assert "ready v" in text


def test_the_other_agents_get_a_pointer_not_a_copy(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    for name in ("GEMINI.md", "AGENTS.md"):
        text = (empty_repo / "notes" / name).read_text(encoding="utf-8")
        assert "notes/.method/RULES.md" in text
        assert len(text) < 1200, f"{name} 이 규칙 사본으로 자라고 있음"


def test_settings_declare_the_marketplace_and_the_plugin(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    settings = json.loads((empty_repo / ".claude" / "settings.json").read_text(encoding="utf-8"))

    assert "mongdang" in settings["extraKnownMarketplaces"]
    assert settings["enabledPlugins"]["girok@mongdang"] is True


def test_the_config_records_the_choices(empty_repo):
    notes_init.init(
        empty_repo, notes_dir="기록", repo_name="fresh", remote="azure", safety_gate=False
    )

    config = json.loads((empty_repo / ".claude" / "girok.json").read_text(encoding="utf-8"))

    assert config["notesDir"] == "기록"
    assert config["remote"] == "azure"
    assert config["modules"]["safetyGate"] is False


def test_the_gate_document_appears_only_when_the_module_is_on(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh", safety_gate=False)

    assert not (empty_repo / "notes" / "docs" / "SAFETY_GATE.md").exists()
    assert "안전 게이트" not in (empty_repo / "notes" / "CLAUDE.md").read_text(encoding="utf-8")


def test_the_gate_document_is_written_when_the_module_is_on(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh", safety_gate=True)

    assert (empty_repo / "notes" / "docs" / "SAFETY_GATE.md").is_file()


def test_it_never_overwrites_what_is_already_there(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")
    board = empty_repo / "notes" / "docs" / "PROGRESS.md"
    board.write_text("# 내가 쓴 현황판\n", encoding="utf-8")

    result = notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    assert board.read_text(encoding="utf-8") == "# 내가 쓴 현황판\n"
    assert any("PROGRESS.md" in s for s in result.skipped)


def test_a_relative_root_works_with_an_existing_config(tmp_path, monkeypatch):
    """`/notes` runs the CLI with --root . — a relative path — while the
    config loader returns absolute paths. Comparing the two crashed init on
    every repository that already had a config; tests never saw it because
    they always pass absolute tmp paths."""
    root = tmp_path / "configured"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "girok.json").write_text(
        json.dumps({"notesDir": ".", "board": "STATE.md", "modules": {"safetyGate": False}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(root)

    code = notes_init.main(["--root", ".", "--confirm", "configured"])

    assert code == 0
    assert (root / ".method" / "VERSION").is_file()


def test_the_snapshot_verifies_right_after_init(empty_repo):
    import method_sync

    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    assert method_sync.verify(empty_repo).ok


def test_a_worker_folder_is_created_when_asked(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh", worker="abc")

    assert (empty_repo / "notes" / "docs_abc" / "PROGRESS.md").is_file()
    assert (empty_repo / "notes" / "docs_abc" / "decisions" / "README.md").is_file()


def test_the_worker_board_carries_a_stamp(empty_repo):
    """Merges pick the newer copy by this line, so a worker board without
    one cannot be merged safely."""
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh", worker="abc")

    text = (empty_repo / "notes" / "docs_abc" / "PROGRESS.md").read_text(encoding="utf-8")

    assert "최종 수정:" in text
    assert "· abc" in text


def test_it_respects_a_layout_that_is_already_configured(tmp_path):
    """A repository that already has a config has already decided where its
    documents live. Initializing with the defaults would scatter a second,
    empty skeleton beside the real one."""
    import json

    root = tmp_path / "research"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "girok.json").write_text(
        json.dumps(
            {
                "notesDir": ".",
                "board": "STATE.md",
                "decisionsDir": "decisions",
                "docRoots": ["docs", "decisions"],
                "parallelMode": False,
                "modules": {"safetyGate": False},
            }
        ),
        encoding="utf-8",
    )
    (root / "STATE.md").write_text("# 지금 상태\n\n측정 중\n", encoding="utf-8")

    notes_init.init(root)

    assert (root / "STATE.md").read_text(encoding="utf-8") == "# 지금 상태\n\n측정 중\n"
    assert not (root / "notes").exists()
    assert not (root / "docs" / "PROGRESS.md").exists()
    assert (root / ".method" / "VERSION").is_file()


def test_the_pointer_names_the_layout_this_repository_actually_has(tmp_path):
    """`CLAUDE.md` exists to say where things are. It used to spell the
    default layout regardless, so a flat repository was handed a pointer to a
    `docs/PROGRESS.md` it does not have — wrong in the one document whose
    whole job is being right about paths."""
    root = tmp_path / "research"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "girok.json").write_text(
        json.dumps(
            {
                "notesDir": ".",
                "board": "STATE.md",
                "decisionsDir": "decisions",
                "docRoots": ["docs"],
                "parallelMode": False,
                "modules": {"safetyGate": True, "archive": False},
            }
        ),
        encoding="utf-8",
    )

    notes_init.init(root)

    pointer = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "`docs/STATE.md`" in pointer
    assert "`decisions/`" in pointer
    assert "`.method/RULES.md`" in pointer
    assert "`docs/SAFETY_GATE.md`" in pointer
    # The archive module is off, so the pointer must not send anyone to a
    # folder this repository decided not to have.
    assert "archive" not in pointer
    assert "notes/" not in pointer


def test_it_does_not_add_a_gate_document_when_the_module_is_off_in_config(tmp_path):
    import json

    root = tmp_path / "research"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "girok.json").write_text(
        json.dumps({"notesDir": ".", "board": "STATE.md", "modules": {"safetyGate": False}}),
        encoding="utf-8",
    )

    notes_init.init(root)

    assert not (root / "docs" / "SAFETY_GATE.md").exists()


def test_the_archive_folder_can_be_declined(tmp_path):
    """One repository's rule is 'no archive folder — what was deleted is in
    git history'. Creating one anyway would have this plugin breaking the
    convention of the repository it was invited into."""
    import json

    root = tmp_path / "research"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "girok.json").write_text(
        json.dumps({"notesDir": ".", "modules": {"archive": False, "safetyGate": False}}),
        encoding="utf-8",
    )

    notes_init.init(root)

    assert not (root / "docs" / "archive").exists()


def test_the_archive_folder_is_created_by_default(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    assert (empty_repo / "notes" / "docs" / "archive").is_dir()


def test_the_cli_refuses_to_write_without_naming_the_repository(tmp_path, capsys):
    """A repository can be read-only by agreement rather than by permission —
    a reference checkout, or one someone has been told not to touch. Nothing
    in the repository says so, so the caller has to name what it is about to
    write to."""
    root = tmp_path / "reference-repo"
    (root / ".git").mkdir(parents=True)

    code = notes_init.main(["--root", str(root)])

    assert code == 1
    assert not (root / "notes").exists()
    out = capsys.readouterr().out
    assert "reference-repo" in out
    assert "--confirm" in out


def test_a_mismatched_confirmation_is_refused(tmp_path, capsys):
    root = tmp_path / "reference-repo"
    (root / ".git").mkdir(parents=True)

    code = notes_init.main(["--root", str(root), "--confirm", "some-other-repo"])

    assert code == 1
    assert not (root / "notes").exists()


def test_naming_the_repository_lets_it_through(tmp_path):
    root = tmp_path / "my-repo"
    (root / ".git").mkdir(parents=True)

    code = notes_init.main(["--root", str(root), "--confirm", "my-repo"])

    assert code == 0
    assert (root / "notes" / "CLAUDE.md").is_file()


def test_the_documents_only_gitignore_is_not_written_at_a_repository_root(tmp_path):
    """That .gitignore says "this folder holds documents, not code" and blocks
    binaries. At the repository root of a code project it is simply false, and
    it would sit next to the source it claims cannot be there."""
    root = tmp_path / "FlatRepo"
    (root / ".git").mkdir(parents=True)

    notes_init.init(root, notes_dir=".", repo_name="FlatRepo")

    assert not (root / ".gitignore").exists()


def test_it_is_written_when_the_notes_live_in_their_own_folder(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    text = (empty_repo / "notes" / ".gitignore").read_text(encoding="utf-8")
    assert "문서 전용" in text


def test_naming_a_worker_records_their_email_too(tmp_path, monkeypatch):
    """Otherwise initialization creates docs_<id>/ and the very next action
    is blocked for an unconfirmed worker — /notes would set the repository up
    and then refuse to write to it."""
    import gate_rules

    root = tmp_path / "my-repo"
    (root / ".git").mkdir(parents=True)
    monkeypatch.setattr(gate_rules, "read_git_email", lambda _root: "kdh@example.invalid")
    monkeypatch.setattr(notes_init, "read_git_email", lambda _root: "kdh@example.invalid")

    notes_init.init(root, notes_dir="notes", repo_name="my-repo", worker="kdh")

    config = json.loads((root / ".claude" / "girok.json").read_text(encoding="utf-8"))
    assert config["workers"] == {"kdh": "kdh@example.invalid"}
    assert config["mergeOwner"] == "kdh"


def test_a_worker_with_no_git_email_configured_is_still_recorded(tmp_path, monkeypatch):
    root = tmp_path / "my-repo"
    (root / ".git").mkdir(parents=True)
    monkeypatch.setattr(notes_init, "read_git_email", lambda _root: None)

    notes_init.init(root, notes_dir="notes", repo_name="my-repo", worker="kdh")

    config = json.loads((root / ".claude" / "girok.json").read_text(encoding="utf-8"))
    assert "kdh" in config["workers"]


def test_no_worker_named_leaves_the_mapping_empty(empty_repo):
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    config = json.loads((empty_repo / ".claude" / "girok.json").read_text(encoding="utf-8"))
    assert config["workers"] == {}


def test_no_worker_folder_when_parallel_work_is_off(empty_repo):
    """A repository with `parallelMode: false` has no per-worker folders, so
    creating one leaves a stray board nobody merges. Initialization used to
    key this off `--worker` alone, and a non-parallel repository that had a
    `workers` entry got a `docs_<id>/` it then had to delete by hand.
    """
    notes_init.init(
        empty_repo, notes_dir="notes", repo_name="fresh",
        worker="abc", parallel_mode=False,
    )

    assert not (empty_repo / "notes" / "docs_abc").exists()
    assert (empty_repo / "notes" / "docs" / "PROGRESS.md").is_file()


def test_the_repository_registers_the_hooks_itself(empty_repo):
    """Registration through the plugin only reaches machines that installed
    it. The repository is what every machine has, so it is what registers."""
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")

    settings = json.loads((empty_repo / ".claude" / "settings.json").read_text(encoding="utf-8"))

    assert set(settings["hooks"]) == {
        "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop",
    }
    command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "CLAUDE_PROJECT_DIR" in command
    assert "notes/.method/hooks/run-hook.cmd" in command
    assert "session-start" in command


def test_the_registered_wrapper_is_actually_there(empty_repo):
    """A command naming a path that does not exist registers a hook that
    never runs, and nothing reports it — the failure this whole change is
    against."""
    notes_init.init(empty_repo, notes_dir="notes", repo_name="fresh")
    settings = json.loads((empty_repo / ".claude" / "settings.json").read_text(encoding="utf-8"))

    command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    tail = command.split("}", 1)[1].split('"')[0].lstrip("/")

    assert (empty_repo / tail).is_file(), tail
