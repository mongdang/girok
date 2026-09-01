"""Refusing to move, and then moving.

"Clean" is not `git status` being empty — an unpushed commit is fine and a
build artifact nobody tracks is fine. What matters is that every file about
to move is committed, because the restore tag can only hold what was
committed.
"""
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


def test_an_untracked_file_inside_a_new_directory_blocks(repo):
    # Git folds a never-tracked directory into one `?? newdir/` line unless
    # asked to list it in full — a planned document inside it must still
    # be caught, not hidden behind the folded line.
    write(repo / "newdir" / "doc.md", "# 새\n")
    mapping = _mapping([
        {"from": "newdir/doc.md", "to": "docs/doc.md", "role": "doc", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "newdir/doc.md" in str(excinfo.value)


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
    # move_all only stages the rename — apply commits once, after everything
    # is done — so the test commits here to check what the staged rename
    # will look like in history once that happens.
    notes_adopt.run_git(repo, "commit", "-m", "move")
    log = notes_adopt.run_git(repo, "log", "--follow", "--name-only", "--", "PROGRESS.md")
    assert "STATE.md" in log.stdout


def test_an_already_staged_rename_still_blocks_by_its_old_name(repo):
    notes_adopt.run_git(repo, "mv", "STATE.md", "PROGRESS.md")
    mapping = _mapping([
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "STATE.md" in str(excinfo.value)


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


def test_an_uncommitted_document_that_is_not_moving_does_not_block(repo):
    # Editing `CLAUDE.md` is ordinary work. It never moves, so the restore
    # tag not holding this edit costs adoption nothing.
    (repo / "CLAUDE.md").write_text("# 규칙\n", encoding="utf-8")
    mapping = _mapping([
        {"from": "CLAUDE.md", "to": None, "role": "rules", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
        {"from": "STATE.md", "to": "PROGRESS.md", "role": "board", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    notes_adopt.check_preconditions(repo, mapping)


def _adoptable(tmp_path, name="proj", config=None):
    import json

    root = tmp_path / name
    write(root / ".claude" / "girok.json", json.dumps(config if config else {
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "adrStyle": "adr-prefixed",
    }))
    write(root / "STATE.md", "# 현황\n")
    write(root / "decisions" / "001-first.md", "# 001\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    notes_adopt.write_mapping(root, notes_adopt.plan(root), None)
    return root


def test_apply_makes_the_config_describe_where_the_files_went(tmp_path):
    # Files at `PROGRESS.md` and `docs/decisions/` with a config still
    # naming `STATE.md` and `decisions/` means girok breaks in this
    # repository the moment adoption reports success.
    import json

    root = _adoptable(tmp_path)

    notes_adopt.apply(root, today="20260901")

    config = json.loads((root / ".claude" / "girok.json").read_text(encoding="utf-8"))
    assert config["board"] == "PROGRESS.md"
    assert config["decisionsDir"] == "docs/decisions"


def test_the_updated_config_is_committed_with_the_adoption(tmp_path):
    root = _adoptable(tmp_path)

    notes_adopt.apply(root, today="20260901")

    status = notes_adopt.run_git(root, "status", "--porcelain").stdout
    assert "girok.json" not in status, "설정 갱신이 커밋에 들어가야 한다"


def test_the_config_update_is_recorded_in_the_mapping(tmp_path):
    root = _adoptable(tmp_path)

    notes_adopt.apply(root, today="20260901")

    updated = notes_adopt.read_mapping(root)["configUpdated"]
    assert updated["board"] == "PROGRESS.md"


def test_a_custom_doc_root_keeps_being_linted(tmp_path):
    # Documents land in `docs/`, so `docs` has to be a doc root — but the
    # roots the repository already declared are not ours to drop.
    import json

    root = _adoptable(tmp_path, config={
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "docRoots": ["documents"], "adrStyle": "adr-prefixed",
    })
    write(root / "documents" / "설계.md", "# 설계\n")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "doc")
    notes_adopt.write_mapping(root, notes_adopt.plan(root), None)

    notes_adopt.apply(root, today="20260901")

    config = json.loads((root / ".claude" / "girok.json").read_text(encoding="utf-8"))
    assert config["docRoots"] == ["docs", "documents"]


def test_the_console_reports_files_left_out_of_git(tmp_path, capsys):
    # A secret or a huge file is `.gitignore`d, which in a freshly
    # `git init`ed repository means it exists in the backup folder and
    # nowhere else. Nobody reads the mapping JSON to find that out.
    root = tmp_path / "proj"
    write(root / "STATE.md", "# 현황\n")
    write(root / ".env", "TOKEN=x\n")
    notes_adopt.write_mapping(root, notes_adopt.plan(root), None)

    code = notes_adopt.main(["apply", "--root", str(root), "--confirm", root.name])

    assert code == 0
    out = capsys.readouterr().out
    assert ".env" in out


def test_a_dry_run_plan_leaves_the_mapping_alone(tmp_path, capsys):
    # `/notes` runs `plan` as a routine check. Rewriting the mapping there
    # throws away the `?` resolutions a person filled in by hand.
    root = _adoptable(tmp_path)
    mapping = notes_adopt.read_mapping(root)
    mapping["files"][0]["why"] = "사람이 남긴 메모"
    notes_adopt._write_mapping_payload(root, mapping)
    before = (root / ".claude" / "girok-adopt.json").read_text(encoding="utf-8")

    code = notes_adopt.main(["plan", "--root", str(root), "--dry-run"])

    assert code == 0
    assert (root / ".claude" / "girok-adopt.json").read_text(encoding="utf-8") == before
    assert "STATE.md" in capsys.readouterr().out


def test_plan_refuses_to_throw_away_hand_filled_answers(tmp_path, capsys):
    # `plan` builds every entry from the repository, so rewriting the mapping
    # discards the `role` a person resolved, every `merge` they wrote by
    # hand, and every `keep`. The routine check used to do exactly that.
    root = _adoptable(tmp_path)
    write(root / "THESIS.md", "# 논지\n")
    notes_adopt.write_mapping(root, notes_adopt.plan(root), None)
    mapping = notes_adopt.read_mapping(root)
    for item in mapping["files"]:
        if item["from"] == "THESIS.md":
            item["role"] = "doc"
            item["to"] = "docs/thesis.md"
    notes_adopt._write_mapping_payload(root, mapping)
    before = (root / ".claude" / "girok-adopt.json").read_text(encoding="utf-8")

    code = notes_adopt.main(["plan", "--root", str(root)])

    assert code == 1
    assert (root / ".claude" / "girok-adopt.json").read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "THESIS.md" in out
    assert "--dry-run" in out
    assert "--reset-mapping" in out


def test_a_hand_written_merge_is_not_quietly_replanned(tmp_path):
    root = _adoptable(tmp_path)
    mapping = notes_adopt.read_mapping(root)
    for item in mapping["files"]:
        if item["from"] == "decisions/001-first.md":
            item["to"] = None
            item["merge"] = "PROGRESS.md"
    notes_adopt._write_mapping_payload(root, mapping)

    lost = notes_adopt.hand_filled(notes_adopt.read_mapping(root), notes_adopt.plan(root))

    assert lost == ["decisions/001-first.md"]


def test_a_document_confirmed_in_place_survives_a_replan(tmp_path):
    root = _adoptable(tmp_path)
    mapping = notes_adopt.read_mapping(root)
    mapping["files"].append({
        "from": "README.md", "to": None, "role": "keep", "merge": None,
        "sha1": "x", "sha1After": None, "bytes": 1, "why": "사람이 제자리로 확정",
    })
    notes_adopt._write_mapping_payload(root, mapping)

    lost = notes_adopt.hand_filled(notes_adopt.read_mapping(root), notes_adopt.plan(root))

    assert "README.md" in lost


def test_replanning_is_allowed_when_nothing_was_filled_in_by_hand(tmp_path, capsys):
    root = _adoptable(tmp_path)

    code = notes_adopt.main(["plan", "--root", str(root)])

    assert code == 0
    assert "STATE.md" in capsys.readouterr().out


def test_an_explicit_reset_may_replan_from_scratch(tmp_path):
    root = _adoptable(tmp_path)
    mapping = notes_adopt.read_mapping(root)
    for item in mapping["files"]:
        if item["from"] == "decisions/001-first.md":
            item["merge"] = "PROGRESS.md"
    notes_adopt._write_mapping_payload(root, mapping)

    code = notes_adopt.main(["plan", "--root", str(root), "--reset-mapping"])

    assert code == 0
    assert all(
        not item.get("merge") for item in notes_adopt.read_mapping(root)["files"]
    )


def test_the_safety_gate_lands_where_the_hook_looks_for_it(tmp_path):
    # Keeping the name is half the fix. The gate is opened at
    # `cfg.docs_dir / "SAFETY_GATE.md"`, and `docs_dir` is the *first*
    # doc root — so a config listing `docs` second leaves the hook reading
    # a path the file no longer occupies: no gate, nothing OPEN, real
    # motion commands allowed through. And `verify` passes.
    import notes_config

    root = _adoptable(tmp_path, config={
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "docRoots": ["documents", "docs"], "adrStyle": "adr-prefixed",
    })
    write(root / "documents" / "SAFETY_GATE.md", "# 안전 게이트\n")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "gate")
    entries = notes_adopt.plan(root)
    notes_adopt.write_mapping(root, entries, None)

    notes_adopt.apply(root, today="20260901")

    cfg = notes_config.load(root)
    gate = cfg.docs_dir / notes_adopt.GATE_NAME
    assert gate.is_file(), f"훅이 보는 자리는 {cfg.docs_dir} 다"
    assert notes_adopt.verify(root).ok


def test_a_merge_target_that_is_not_moving_still_has_to_be_committed(repo):
    # The restore tag has to hold the target's pre-merge content: the merge
    # appends to it and deletes the source. `CLAUDE.md` never moves, so the
    # narrowed gate stopped looking at it.
    write(repo / "CLAUDE.md", "# 규칙\n")
    mapping = _mapping([
        {"from": "CLAUDE.md", "to": None, "role": "rules", "merge": None,
         "sha1": "x", "bytes": 1, "why": ""},
        {"from": "STATE.md", "to": None, "role": "board", "merge": "CLAUDE.md",
         "sha1": "x", "bytes": 1, "why": ""},
    ])

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.check_preconditions(repo, mapping)

    assert "CLAUDE.md" in str(excinfo.value)


def test_an_exception_that_refuses_attributes_still_reports_the_safety_net(
    tmp_path, monkeypatch, capsys,
):
    # Attaching the tag to the exception must not become the failure that
    # gets reported — the original error and the safety net are what the
    # person needs.
    class Immutable(Exception):
        def __setattr__(self, name, value):
            raise AttributeError(name)

    root = _adoptable(tmp_path)

    def boom(*args, **kwargs):
        raise Immutable("디스크가 꽉 찼다")

    monkeypatch.setattr(notes_adopt, "rewrite_links", boom)

    code = notes_adopt.main(["apply", "--root", str(root), "--confirm", root.name])

    assert code == 1
    out = capsys.readouterr().out
    assert "디스크가 꽉 찼다" in out
    assert "girok-adopt-before-20" in out
    assert f"{root.name}-girok-backup-20" in out
