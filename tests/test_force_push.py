"""The force-push guard, and the one way past it.

The guard was written to catch `--force`, `--force-with-lease` and `-f`. It
missed the refspec form – `git push origin +master` is the same operation
with no flag – and that is how it was bypassed on the day it mattered. A
guard with a hole that only its author knows about is worse than no guard,
because everyone else trusts it.

The way past is deliberately not a switch. `GIROK_FORCE_PUSH_REASON` must
carry a reason, and the reason is echoed into the session so the fact that a
rule was broken, and why, ends up in the transcript rather than in nobody's
memory.
"""
import json

import gate_rules
import pytest
from conftest import write


@pytest.fixture
def repo(notes_repo):
    (notes_repo / ".claude" / "girok.json").write_text(
        json.dumps(
            {
                "notesDir": "notes",
                "parallelMode": True,
                "workers": {"abc": "abc@example.invalid"},
            }
        ),
        encoding="utf-8",
    )
    legacy = notes_repo / ".claude" / "notes-method.json"
    if legacy.exists():
        legacy.unlink()
    return notes_repo


def decide(repo, command, **kw):
    return gate_rules.decide(
        repo, "Bash", {"command": command}, git_email="abc@example.invalid", **kw
    )


# --- every form of force ----------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin master",
        "git push --force-with-lease",
        "git push -f origin master",
        "git push origin +master",
        "git push origin +refs/heads/master:refs/heads/master",
        "git push origin +HEAD:main",
        "git push origin +master --quiet",
        "git push  origin   +refs/tags/v1",
    ],
)
def test_force_is_blocked_in_every_form(repo, command):
    assert decide(repo, command).blocked, command


@pytest.mark.parametrize(
    "command",
    [
        "git push origin master",
        "git push azure abc",
        "git push --set-upstream origin master",
        "git push origin refs/tags/v1",
        "git push origin HEAD:main",
        # A branch whose name contains a plus is not a force refspec.
        "git push origin feature+extra",
    ],
)
def test_an_ordinary_push_is_not_mistaken_for_force(repo, command):
    assert not decide(repo, command).blocked, command


def test_the_refspec_form_was_the_hole(repo):
    """Named on its own because this is the one that got through."""
    assert decide(repo, "git push origin +refs/heads/master:refs/heads/master").blocked


# --- the way past -----------------------------------------------------------

def test_a_reason_lets_it_through(repo, monkeypatch):
    monkeypatch.setenv("GIROK_FORCE_PUSH_REASON", "이력 리셋 – 새 이름으로 새 출발, 사용자 지시")

    decision = decide(repo, "git push --force origin master")

    assert not decision.blocked


def test_the_reason_is_echoed_so_it_lands_in_the_transcript(repo, monkeypatch):
    monkeypatch.setenv("GIROK_FORCE_PUSH_REASON", "이력 리셋 – 사용자 지시")

    decision = decide(repo, "git push --force origin master")

    assert any("이력 리셋" in w for w in decision.warnings)
    assert any("force push" in w for w in decision.warnings)


def test_an_empty_reason_is_not_a_reason(repo, monkeypatch):
    """A bare `=1` would make this a switch. The record is the point."""
    monkeypatch.setenv("GIROK_FORCE_PUSH_REASON", "   ")

    assert decide(repo, "git push --force origin master").blocked


def test_a_one_word_reason_is_not_enough(repo, monkeypatch):
    monkeypatch.setenv("GIROK_FORCE_PUSH_REASON", "ok")

    assert decide(repo, "git push --force origin master").blocked


def test_the_override_does_not_unlock_anything_else(repo, monkeypatch):
    """It is about history, not about the safety rules."""
    monkeypatch.setenv("GIROK_FORCE_PUSH_REASON", "이력 리셋 – 사용자 지시")
    write(
        repo / "notes" / "docs" / "SAFETY_GATE.md",
        "# 게이트\n\n| # | 항목 | 상태 |\n|---|---|---|\n| 1 | 정위치 | OPEN |\n",
    )

    assert decide(repo, "dotnet run -- --home-all").blocked


def test_the_block_message_names_both_ways_out(repo):
    reason = decide(repo, "git push --force origin master").reason

    assert "-s ours" in reason
    assert "GIROK_FORCE_PUSH_REASON" in reason


# --- the guard must not swallow the rest of the line ------------------------
#
# The scan ran from `git push` to the end of the line, so a flag belonging to
# a *later* command read as a flag on the push. A guard that stops ordinary
# work gets switched off, and then it guards nothing.

@pytest.mark.parametrize(
    "command",
    [
        "git push origin master && rm -f /tmp/x",
        "git push origin master; grep -f patterns file",
        "git push origin master | tee -f log",
        "git push origin master && echo +done",
    ],
)
def test_a_later_command_on_the_same_line_is_not_the_push(repo, command):
    assert not decide(repo, command).blocked, command


@pytest.mark.parametrize(
    "command",
    [
        "git status && git push --force origin master",
        "git add -A; git push origin +master",
    ],
)
def test_a_force_push_later_on_the_line_is_still_caught(repo, command):
    assert decide(repo, command).blocked, command
