"""Two people, one repository, from adoption to noticing each other.

This is the scenario the parallel-work rules exist for, so it is tested as a
scenario rather than as separate units: kdh adopts, pjm joins, both work, and
each session tells its owner what the other one pushed.
"""
import json
import subprocess

import method_sync
import notes_init
import pytest
import session_report


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )


def commit(repo, path, text, message):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


@pytest.fixture
def team(tmp_path):
    """A bare remote plus a checkout for each of two workers."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-q", str(bare))

    kdh = tmp_path / "kdh"
    kdh.mkdir()
    git(kdh, "init", "-q")
    git(kdh, "config", "user.email", "kdh@example.invalid")
    git(kdh, "config", "user.name", "kdh")
    git(kdh, "remote", "add", "origin", str(bare))

    # kdh adopts the methodology and records both workers.
    notes_init.init(kdh, notes_dir="notes", repo_name="LifeTimeSolution", worker="kdh")
    config = kdh / ".claude" / "girok.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    data["workers"] = {"kdh": "kdh@example.invalid", "pjm": "pjm@example.invalid"}
    data["mergeOwner"] = "kdh"
    config.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    commit(kdh, "src/a.cs", "code\n", "chore: adopt girok")
    git(kdh, "branch", "-M", "master")
    git(kdh, "push", "-q", "-u", "origin", "master")
    git(kdh, "checkout", "-q", "-b", "kdh")

    pjm = tmp_path / "pjm"
    git(tmp_path, "clone", "-q", str(bare), str(pjm))
    git(pjm, "config", "user.email", "pjm@example.invalid")
    git(pjm, "config", "user.name", "pjm")
    git(pjm, "checkout", "-q", "-b", "pjm")

    return {"kdh": kdh, "pjm": pjm}


def test_adoption_records_both_workers_so_neither_is_asked(team):
    for who, repo in team.items():
        report = session_report.build(repo, scan_remote=False)
        assert not report.needs_worker_answer, who
        assert report.worker == who


def test_the_joining_worker_gets_the_rules_from_the_clone(team):
    """No sync, no install step for the rules themselves - the snapshot came
    with the repository."""
    pjm = team["pjm"]

    assert (pjm / "notes" / ".method" / "RULES.md").is_file()
    assert method_sync.verify(pjm).ok


def test_joining_adds_only_the_new_worker_folder(team):
    pjm = team["pjm"]
    board_before = (pjm / "notes" / "docs_kdh" / "PROGRESS.md").read_text(encoding="utf-8")

    notes_init.init(pjm, worker="pjm")

    assert (pjm / "notes" / "docs_pjm" / "PROGRESS.md").is_file()
    assert (pjm / "notes" / "docs_kdh" / "PROGRESS.md").read_text(encoding="utf-8") == board_before


def test_each_session_reports_what_the_other_pushed(team):
    kdh, pjm = team["kdh"], team["pjm"]

    notes_init.init(pjm, worker="pjm")
    commit(pjm, "notes/docs_pjm/PROGRESS.md", "# 현황판 (pjm)\n\n측정 완료\n", "docs: pjm 진행")
    git(pjm, "push", "-q", "-u", "origin", "pjm")

    report = session_report.build(kdh)

    assert "[반입]" in report.text
    assert "origin/pjm" in report.text
    assert "승인 없이" in report.text


def test_an_incoming_safety_change_is_flagged_first(team):
    kdh, pjm = team["kdh"], team["pjm"]

    commit(
        pjm,
        "notes/docs/SAFETY_GATE.md",
        "# 게이트\n\n| # | 항목 | 상태 |\n|---|---|---|\n| 1 | 정위치 | OPEN |\n",
        "docs: 게이트 항목 추가",
    )
    git(pjm, "push", "-q", "-u", "origin", "pjm")

    report = session_report.build(kdh)

    assert "안전 게이트 변경 포함" in report.text


def test_a_quiet_remote_adds_no_noise(team):
    report = session_report.build(team["kdh"])

    assert "[반입]" not in report.text


def test_the_scan_leaves_the_working_tree_alone(team):
    kdh, pjm = team["kdh"], team["pjm"]
    commit(pjm, "notes/docs_pjm/PROGRESS.md", "# pjm\n", "docs: pjm")
    git(pjm, "push", "-q", "-u", "origin", "pjm")

    head = git(kdh, "rev-parse", "HEAD").stdout
    status = git(kdh, "status", "--porcelain").stdout

    session_report.build(kdh)

    assert git(kdh, "rev-parse", "HEAD").stdout == head
    assert git(kdh, "status", "--porcelain").stdout == status
