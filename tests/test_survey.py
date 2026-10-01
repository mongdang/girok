"""Reading an existing repository before changing anything.

Initialization used to create the default skeleton and leave whatever was
already there sitting beside it. Choosing the right layout for the second
repository to adopt this was done by a person reading the repository – the
plugin could not do it, so `/notes` on a project with its own conventions
would have produced a second, empty set of documents.

The survey proposes; it never writes. Getting the mapping wrong is cheap when
it is a proposal and expensive when it is a file tree.
"""
import subprocess

import notes_survey
import pytest


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )


def make(repo, files: dict):
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return repo


LONG = "본문 문단입니다.\n" * 60


@pytest.fixture
def notes_in_subfolder(tmp_path):
    """The first layout: a notes folder beside the source."""
    return make(
        tmp_path / "Solution",
        {
            "Solution.sln": "sln\n",
            "src/Motion.cs": "public bool HomeCheck() => _sensor.Ok;\n",
            "Solution-notes/CLAUDE.md": f"# 지침\n\n{LONG}",
            "Solution-notes/docs/PROGRESS.md": f"# 현황판\n\n## 일자별 작업 로그\n\n{LONG}",
            "Solution-notes/docs/SAFETY_GATE.md": "# 안전 게이트\n\n| # | 상태 |\n|---|---|\n| 1 | OPEN |\n",
            "Solution-notes/docs/decisions/README.md": "# 결정 인덱스\n\n| ID |\n|---|\n",
            "Solution-notes/docs/decisions/ADR-001-first.md": "# ADR-001 – 첫\n",
            "Solution-notes/docs/archive/old.md": "# 옛 서사\n",
            "Solution-notes/docs_kdh/PROGRESS.md": "# 현황판 (kdh)\n",
        },
    )


@pytest.fixture
def notes_at_root(tmp_path):
    """The second layout: STATE.md and decisions/NNN-slug.md at the root."""
    return make(
        tmp_path / "research",
        {
            "STATE.md": f"# 지금 상태\n\n## 한 줄\n\n{LONG}",
            "METHOD.md": f"# 방법\n\n{LONG}",
            "agent/run.py": "print('x')\n",
            "docs/protocol.md": f"# 프로토콜\n\n{LONG}",
            "decisions/README.md": "# 결정 인덱스\n\n| ID |\n|---|\n",
            "decisions/001-first.md": "# 001 – 첫\n",
            "decisions/052-latest.md": "# 052 – 최신\n",
        },
    )


# --- layout inference --------------------------------------------------------

def test_it_finds_a_notes_folder_beside_the_source(notes_in_subfolder):
    survey = notes_survey.run(notes_in_subfolder)

    assert survey.proposal["notesDir"] == "Solution-notes"
    assert survey.proposal["board"] == "PROGRESS.md"
    assert survey.proposal["decisionsDir"] == "docs/decisions"
    assert survey.proposal["adrStyle"] == "adr-prefixed"


def test_it_recognizes_documents_at_the_repository_root(notes_at_root):
    survey = notes_survey.run(notes_at_root)

    assert survey.proposal["notesDir"] == "."
    assert survey.proposal["board"] == "STATE.md"
    assert survey.proposal["decisionsDir"] == "decisions"
    assert survey.proposal["adrStyle"] == "numbered"


def test_it_lists_the_root_documents_it_found(notes_at_root):
    survey = notes_survey.run(notes_at_root)

    assert "STATE.md" in survey.proposal["rootDocs"]
    assert "METHOD.md" in survey.proposal["rootDocs"]


def test_source_folders_are_not_mistaken_for_documentation(notes_at_root):
    survey = notes_survey.run(notes_at_root)

    assert "agent" not in survey.proposal["docRoots"]


# --- module inference --------------------------------------------------------

def test_a_gate_document_turns_the_safety_module_on(notes_in_subfolder):
    survey = notes_survey.run(notes_in_subfolder)

    assert survey.proposal["modules"]["safetyGate"] is True


def test_a_repository_with_no_hardware_signal_leaves_it_off(notes_at_root):
    survey = notes_survey.run(notes_at_root)

    assert survey.proposal["modules"]["safetyGate"] is False


def test_an_existing_safety_marker_turns_it_on_even_without_a_gate(tmp_path):
    """A marker with no gate document is the worst of the two states, so the
    survey has to notice rather than propose the module off."""
    repo = make(tmp_path / "hw", {"src/a.cs": "// SAFETY-STUB\n", "docs/NOTE.md": "# 메모\n"})

    survey = notes_survey.run(repo)

    assert survey.proposal["modules"]["safetyGate"] is True
    assert any("SAFETY-STUB" in f.message for f in survey.findings)


def test_worker_folders_turn_parallel_mode_on(notes_in_subfolder):
    survey = notes_survey.run(notes_in_subfolder)

    assert survey.proposal["parallelMode"] is True
    assert "kdh" in survey.proposal["workers"]


def test_a_single_author_repository_proposes_parallel_mode_off(notes_at_root):
    git(notes_at_root, "init", "-q")
    git(notes_at_root, "config", "user.email", "solo@example.invalid")
    git(notes_at_root, "config", "user.name", "solo")
    git(notes_at_root, "add", "-A")
    git(notes_at_root, "commit", "-q", "-m", "init")

    survey = notes_survey.run(notes_at_root)

    assert survey.proposal["parallelMode"] is False


def test_an_existing_archive_folder_keeps_the_module_on(notes_in_subfolder):
    survey = notes_survey.run(notes_in_subfolder)

    assert survey.proposal["modules"]["archive"] is True


def test_a_repository_that_forbids_an_archive_is_respected(notes_at_root):
    """One repository's rules say in as many words: no archive folder, what
    was deleted is in git history. Proposing one would have this plugin
    breaking the convention of the repository it was invited into."""
    (notes_at_root / "CLAUDE.md").write_text(
        "# 지침\n\n- **아카이브 폴더를 만들지 않는다** – 지운 건 git 히스토리에 있다\n",
        encoding="utf-8",
    )

    survey = notes_survey.run(notes_at_root)

    assert survey.proposal["modules"]["archive"] is False
    assert any("아카이브" in f.message for f in survey.findings)


# --- findings ---------------------------------------------------------------

def test_it_reports_a_decisions_folder_with_no_index(tmp_path):
    repo = make(
        tmp_path / "x",
        {"docs/NOTE.md": "# 메모\n", "docs/decisions/ADR-001-a.md": "# ADR-001 – a\n"},
    )

    survey = notes_survey.run(repo)

    assert any("인덱스" in f.message for f in survey.findings)


def test_it_reports_a_document_over_its_budget(notes_in_subfolder):
    board = notes_in_subfolder / "Solution-notes" / "docs" / "PROGRESS.md"
    board.write_text("# 현황판\n" + "가" * 40_000, encoding="utf-8")

    survey = notes_survey.run(notes_in_subfolder)

    assert any("크기" in f.message and "PROGRESS.md" in f.message for f in survey.findings)


def test_it_reports_decision_files_outside_the_decisions_folder(tmp_path):
    repo = make(
        tmp_path / "x",
        {
            "docs/NOTE.md": "# 메모\n",
            "docs/decisions/README.md": "# 인덱스\n",
            "docs/ADR-007-stray.md": "# ADR-007 – 떠돌이\n",
        },
    )

    survey = notes_survey.run(repo)

    assert any("ADR-007" in f.message for f in survey.findings)


def test_it_says_when_it_could_not_find_a_board(tmp_path):
    repo = make(tmp_path / "x", {"docs/protocol.md": "# 프로토콜\n"})

    survey = notes_survey.run(repo)

    assert survey.proposal["board"] is None
    assert any("현황판" in f.message for f in survey.findings)


def test_two_board_candidates_are_reported_rather_than_guessed(tmp_path):
    repo = make(
        tmp_path / "x",
        {"docs/PROGRESS.md": f"# 현황판\n{LONG}", "docs/STATUS.md": f"# 상태\n{LONG}"},
    )

    survey = notes_survey.run(repo)

    assert any("후보" in f.message for f in survey.findings)


# --- it never writes --------------------------------------------------------

def test_the_survey_writes_nothing(notes_in_subfolder):
    before = sorted(p.relative_to(notes_in_subfolder).as_posix() for p in notes_in_subfolder.rglob("*"))

    notes_survey.run(notes_in_subfolder)

    after = sorted(p.relative_to(notes_in_subfolder).as_posix() for p in notes_in_subfolder.rglob("*"))
    assert before == after


def test_an_already_configured_repository_is_compared_not_reproposed(notes_in_subfolder):
    """Once a repository has decided, the survey's job is to say whether the
    decision still matches what is on disk."""
    config = notes_in_subfolder / ".claude" / "girok.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('{"notesDir": "Solution-notes", "board": "STATE.md"}', encoding="utf-8")

    survey = notes_survey.run(notes_in_subfolder)

    assert survey.configured
    assert any("STATE.md" in f.message for f in survey.findings)


# --- three false positives found by running it on real repositories ---------

def test_a_parallel_worker_decision_is_not_a_stray(notes_in_subfolder):
    """During parallel work a decision belongs in `docs_<id>/decisions/` –
    the rules say so. Reporting those as strays flagged eight correctly
    placed files in the first repository it was pointed at."""
    folder = notes_in_subfolder / "Solution-notes" / "docs_kdh" / "decisions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "README.md").write_text("# 인덱스\n", encoding="utf-8")
    (folder / "ADR-260821-kdh-parallel.md").write_text("# ADR – 병행\n", encoding="utf-8")

    survey = notes_survey.run(notes_in_subfolder)

    assert not any("ADR-260821-kdh-parallel" in f.message for f in survey.findings)


def test_a_decision_file_is_not_a_board_candidate(tmp_path):
    """`041-screen-shows-state-we-were-not-reading.md` was proposed as the
    board because its name contains "state"."""
    repo = make(
        tmp_path / "x",
        {
            "STATE.md": f"# 지금 상태\n\n## 한 줄\n\n{LONG}",
            "decisions/README.md": "# 인덱스\n",
            "decisions/041-screen-shows-state.md": f"# 041 – 화면\n\n{LONG}",
        },
    )

    survey = notes_survey.run(repo)

    assert survey.proposal["board"] == "STATE.md"
    assert not any("041" in f.message for f in survey.findings)


def test_several_git_emails_are_a_question_not_a_decision(notes_at_root):
    """One person on four machines produces four author emails. Turning
    parallel mode on for that would block every write until a `workers`
    mapping existed for identities that are all the same person."""
    git(notes_at_root, "init", "-q")
    for email in ("a@x.invalid", "a@laptop.invalid", "colab@runtime"):
        git(notes_at_root, "config", "user.email", email)
        git(notes_at_root, "config", "user.name", "a")
        (notes_at_root / f"{email[0]}{len(email)}.md").write_text("# x\n", encoding="utf-8")
        git(notes_at_root, "add", "-A")
        git(notes_at_root, "commit", "-q", "-m", f"as {email}")

    survey = notes_survey.run(notes_at_root)

    assert survey.proposal["parallelMode"] is False
    assert any("이메일" in f.message for f in survey.findings)


# --- a configured repository whose signals have changed ---------------------

def test_a_module_that_no_longer_matches_the_repository_is_reported(notes_at_root):
    """eq-agent was adopted with the safety module off, correctly at the time.
    The code has since grown interlock and motion handling. A survey that only
    compared paths would never say so."""
    config = notes_at_root / ".claude"
    config.mkdir(parents=True, exist_ok=True)
    (config / "girok.json").write_text(
        '{"notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",'
        ' "adrStyle": "numbered", "modules": {"safetyGate": false}}',
        encoding="utf-8",
    )
    (notes_at_root / "agent" / "motion.py").write_text(
        "def check_interlock():\n    return True\n", encoding="utf-8"
    )

    survey = notes_survey.run(notes_at_root)

    assert survey.configured
    assert any("safetyGate" in f.message for f in survey.findings)


def test_a_module_that_still_matches_is_not_reported(notes_at_root):
    config = notes_at_root / ".claude"
    config.mkdir(parents=True, exist_ok=True)
    (config / "girok.json").write_text(
        '{"notesDir": ".", "board": "STATE.md", "decisionsDir": "decisions",'
        ' "adrStyle": "numbered", "modules": {"safetyGate": false, "archive": true}}',
        encoding="utf-8",
    )

    survey = notes_survey.run(notes_at_root)

    assert not any("safetyGate" in f.message for f in survey.findings)


def test_the_survey_travels_with_the_snapshot(tmp_path):
    """An adopted repository should be able to ask "has my structure drifted?"
    without the plugin installed – same reason the linters ship in there."""
    import method_sync

    assert "notes_survey.py" in method_sync.SNAPSHOT_SCRIPTS
