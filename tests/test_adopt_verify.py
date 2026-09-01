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
    # The board links the decision it records — the ordinary shape of a
    # repository worth adopting, and the one that makes `apply` rewrite a
    # link inside a document it also moves.
    write(
        root / "STATE.md",
        "# 현황\n\n돌아간다\n\n- [첫 결정](decisions/001-first.md)\n",
    )
    write(root / "decisions" / "001-first.md", "# 001\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    # `apply` refuses to run without a plan already on disk — the person
    # (or model) is meant to see the proposal and resolve any `?` before
    # anything moves. Every test here stands in for that step.
    notes_adopt.write_mapping(root, notes_adopt.plan(root), None)
    return root


def test_a_clean_adoption_verifies(adopted):
    notes_adopt.apply(adopted, today="20260901")

    result = notes_adopt.verify(adopted)

    assert result.ok, result.failures


def test_only_link_destinations_change_in_a_moved_document(adopted):
    # A moved document is not byte-identical to its original when `apply`
    # repointed a link inside it — that rewrite is the whole point. What is
    # guaranteed is narrower and still checkable: everything except the
    # link destinations is the same text.
    before = (adopted / "STATE.md").read_text(encoding="utf-8")

    notes_adopt.apply(adopted, today="20260901")

    after = (adopted / "PROGRESS.md").read_text(encoding="utf-8")
    assert after != before, "링크가 재작성됐어야 한다"
    assert notes_adopt.link_skeleton(after) == notes_adopt.link_skeleton(before)


def test_content_is_identical_when_no_link_was_rewritten(adopted):
    before = notes_adopt.sha1_of(adopted / "decisions" / "001-first.md")

    notes_adopt.apply(adopted, today="20260901")

    moved = adopted / "docs" / "decisions" / "ADR-001-first.md"
    assert notes_adopt.sha1_of(moved) == before


def test_verify_catches_a_change_that_hides_behind_the_recorded_hash(adopted):
    # The nightmare this check exists for: something mangles a moved
    # document and the mapping's post-move hash agrees with the mangled
    # bytes. Only the untouched backup can still tell the truth.
    notes_adopt.apply(adopted, today="20260901")
    board = adopted / "PROGRESS.md"
    board.write_text("# 현황\n\n딴 소리\n", encoding="utf-8")
    mapping = notes_adopt.read_mapping(adopted)
    for item in mapping["files"]:
        if item.get("to") == "PROGRESS.md":
            item["sha1After"] = notes_adopt.sha1_of(board)
    notes_adopt._write_mapping_payload(adopted, mapping)

    result = notes_adopt.verify(adopted)

    assert not result.ok
    assert any("PROGRESS.md" in f for f in result.failures)


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


def test_apply_does_not_sweep_unrelated_work_into_its_commit(adopted):
    # A pre-existing repository has other in-progress, uncommitted work
    # that has nothing to do with adoption. `apply` must never `git add -A`
    # in that case — only its own scoped changes (.gitignore, moved files).
    write(adopted / "unrelated.txt", "손대지 않은 작업\n")

    notes_adopt.apply(adopted, today="20260901")

    status = notes_adopt.run_git(adopted, "status", "--porcelain", "unrelated.txt").stdout
    assert "unrelated.txt" in status, "무관한 미완성 작업이 커밋에 쓸려 들어가면 안 된다"


def test_destination_collisions_are_blocked_not_auto_resolved(tmp_path):
    root = tmp_path / "proj"
    write(root / ".claude" / "girok.json", json.dumps({
        "notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",
        "adrStyle": "adr-prefixed",
    }))
    write(root / "docs" / "My Notes.md", "# a\n")
    write(root / "docs" / "my-notes.md", "# b\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")
    notes_adopt.write_mapping(root, notes_adopt.plan(root), None)

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.apply(root, today="20260901")

    message = str(excinfo.value)
    assert "my-notes.md" in message


def test_verify_ignores_links_broken_before_adoption(adopted):
    write(adopted / "docs" / "이미깨짐.md", "[없는 문서](없는파일.md)\n")
    notes_adopt.run_git(adopted, "add", "-A")
    notes_adopt.run_git(adopted, "commit", "-m", "pre-existing dead link")

    notes_adopt.apply(adopted, today="20260901")

    result = notes_adopt.verify(adopted)

    assert result.ok, result.failures


def test_verify_still_catches_newly_broken_links(adopted):
    notes_adopt.apply(adopted, today="20260901")
    (adopted / "PROGRESS.md").write_text("[깨짐](없는것.md)\n", encoding="utf-8")

    result = notes_adopt.verify(adopted)

    assert not result.ok
    assert any("없는것.md" in f for f in result.failures)


def test_merging_a_document_into_itself_is_blocked(adopted):
    mapping = notes_adopt.read_mapping(adopted)
    for item in mapping["files"]:
        if item["from"] == "decisions/001-first.md":
            item["merge"] = item["from"]
    notes_adopt._write_mapping_payload(adopted, mapping)

    with pytest.raises(notes_adopt.Blocked) as excinfo:
        notes_adopt.apply(adopted, today="20260901")

    assert "decisions/001-first.md" in str(excinfo.value)


def test_apply_without_a_plan_is_blocked_and_touches_nothing(tmp_path):
    # `plan` is the approval gate — a person (or model) sees the proposal
    # and resolves every `?` before anything is allowed to move. `apply`
    # must not silently generate one behind that gate.
    root = tmp_path / "proj"
    write(root / "STATE.md", "# 현황\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")

    with pytest.raises(notes_adopt.Blocked):
        notes_adopt.apply(root, today="20260901")

    assert not (root / ".claude" / "girok-adopt.json").exists()
    assert not (root.parent / f"{root.name}-girok-backup-20260901").exists()
    tags = notes_adopt.run_git(root, "tag").stdout
    assert "girok-adopt-before-20260901" not in tags


def test_a_mid_move_failure_names_the_real_tag_and_backup(adopted, monkeypatch, capsys):
    # A backup and restore tag already exist by the time `move_all` runs —
    # the person needs to be told exactly how to use them, not just that
    # something broke.
    import subprocess

    real_run_git = notes_adopt.run_git

    def failing_mv(root, *args):
        if args and args[0] == "mv":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="fatal: mv failed")
        return real_run_git(root, *args)

    monkeypatch.setattr(notes_adopt, "run_git", failing_mv)

    code = notes_adopt.main(["apply", "--root", str(adopted), "--confirm", adopted.name])

    assert code == 1
    out = capsys.readouterr().out
    assert "girok-adopt-before-20" in out  # real tag, not a placeholder
    assert f"{adopted.name}-girok-backup-20" in out  # real backup folder name
    assert "git reset --hard girok-adopt-before-20" in out


def test_a_pre_backup_failure_gives_no_restore_guidance(tmp_path, capsys):
    # Nothing was written yet (no mapping, so `apply` refuses immediately)
    # — telling the person to restore something that was never touched
    # invents a problem that does not exist.
    root = tmp_path / "proj"
    write(root / "STATE.md", "# 현황\n")
    notes_adopt.run_git(root, "init")
    notes_adopt.run_git(root, "config", "user.email", "t@example.invalid")
    notes_adopt.run_git(root, "config", "user.name", "t")
    notes_adopt.run_git(root, "add", "-A")
    notes_adopt.run_git(root, "commit", "-m", "init")

    code = notes_adopt.main(["apply", "--root", str(root), "--confirm", root.name])

    assert code == 1
    out = capsys.readouterr().out
    assert "복원" not in out
    assert "checkout" not in out


def test_a_merge_target_is_what_verify_checks(adopted):
    # A mapping may carry both fields — a person resolving `?` fills in
    # `to` and then decides the document should be merged instead. The
    # merge is what actually happened, so it is what must be checked; the
    # stale `to` names a path that was never created.
    mapping = notes_adopt.read_mapping(adopted)
    for item in mapping["files"]:
        if item["from"] == "decisions/001-first.md":
            item["to"] = "docs/decisions/ADR-001-first.md"
            item["merge"] = "PROGRESS.md"
    notes_adopt._write_mapping_payload(adopted, mapping)

    notes_adopt.apply(adopted, today="20260901")
    result = notes_adopt.verify(adopted)

    assert result.ok, result.failures


def test_the_mapping_records_the_restore_tag(adopted):
    notes_adopt.apply(adopted, today="20260101")

    assert notes_adopt.read_mapping(adopted)["tag"] == "girok-adopt-before-20260101"


def test_verify_names_the_tag_that_exists_not_todays(adopted, capsys):
    # Adopting yesterday and verifying today used to print a tag nobody
    # ever created — precisely when a person needs the command to work.
    notes_adopt.apply(adopted, today="20260101")
    (adopted / "PROGRESS.md").unlink()

    code = notes_adopt.main(["verify", "--root", str(adopted)])

    assert code == 1
    out = capsys.readouterr().out
    assert "girok-adopt-before-20260101" in out
    assert f"{adopted.name}-girok-backup-20260101" in out


def test_verify_leads_with_the_backup_not_a_partial_checkout(adopted, capsys):
    # `git checkout <tag> -- .` restores the old paths and leaves the new
    # ones in place, so the repository ends up holding both copies.
    notes_adopt.apply(adopted, today="20260101")
    (adopted / "PROGRESS.md").unlink()

    notes_adopt.main(["verify", "--root", str(adopted)])

    out = capsys.readouterr().out
    assert out.index("-girok-backup-") < out.index("girok-adopt-before-")
    assert "git checkout girok-adopt-before" not in out


def test_an_undecodable_document_is_named_not_a_traceback(adopted, capsys):
    # One .md saved in cp949 used to end the run in a UnicodeDecodeError
    # that did not even say which file — with a backup and a tag already
    # made and no word about either.
    (adopted / "docs").mkdir(exist_ok=True)
    (adopted / "docs" / "옛문서.md").write_bytes("# 옛 문서\n".encode("cp949"))
    notes_adopt.run_git(adopted, "add", "-A")
    notes_adopt.run_git(adopted, "commit", "-m", "cp949")
    notes_adopt.write_mapping(adopted, notes_adopt.plan(adopted), None)

    code = notes_adopt.main(["apply", "--root", str(adopted), "--confirm", adopted.name])

    assert code == 1
    out = capsys.readouterr().out
    assert "옛문서.md" in out
    assert "-girok-backup-20" in out, "이미 만들어진 백업을 알려야 한다"


def test_an_unreadable_backup_copy_fails_verification_without_a_traceback(adopted):
    # The skeleton comparison reads the backup's original. If that copy
    # cannot be decoded, the verification did not finish — which is a
    # failure, never a traceback out of `verify()`.
    notes_adopt.apply(adopted, today="20260901")
    backup = adopted.parent / f"{adopted.name}-girok-backup-20260901"
    (backup / "STATE.md").write_bytes("# 현황\n돌아간다\n".encode("cp949"))

    result = notes_adopt.verify(adopted)

    assert not result.ok
    assert any("STATE.md" in f for f in result.failures)
