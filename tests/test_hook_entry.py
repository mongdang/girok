"""The hook scripts as Claude Code actually runs them: a JSON payload on
stdin, a JSON response on stdout, an exit code.

The response shape is worth testing on its own, because a malformed block is
ignored rather than rejected — a check nobody can see failing is worse than
no check, since everyone believes it is running.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import method_sync
import pytest
from conftest import write

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def run_hook(
    name: str,
    payload: dict,
    hooks_dir: Path = HOOKS,
    env: dict | None = None,
) -> tuple[int, dict | None, str]:
    """Run a hook the way Claude Code does.

    `hooks_dir` exists so the same checks can be pointed at the committed
    copies in .method/hooks/ — the ones a machine without the plugin runs.
    """
    proc = subprocess.run(
        [sys.executable, str(hooks_dir / f"{name}.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    out = proc.stdout.strip()
    parsed = None
    if out:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = None
    return proc.returncode, parsed, proc.stderr


@pytest.fixture
def ready_repo(notes_repo):
    method_sync.sync(notes_repo)
    return notes_repo


def test_session_start_returns_additional_context(ready_repo):
    code, out, _ = run_hook(
        "session-start",
        {"hook_event_name": "SessionStart", "cwd": str(ready_repo), "startup_type": "startup"},
    )

    assert code == 0
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "[girok] ready" in out["hookSpecificOutput"]["additionalContext"]


def test_pre_tool_use_denies_with_a_reason(ready_repo):
    code, out, _ = run_hook(
        "pre-tool-use",
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(ready_repo),
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force azure main"},
        },
    )

    assert code == 0
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "force" in decision["permissionDecisionReason"].lower()


def test_pre_tool_use_stays_silent_on_an_ordinary_call(ready_repo):
    code, out, _ = run_hook(
        "pre-tool-use",
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(ready_repo),
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        },
    )

    assert code == 0
    assert out is None


def test_user_prompt_submit_injects_the_gate_only_for_motion(ready_repo):
    write(
        ready_repo / "notes" / "docs" / "SAFETY_GATE.md",
        "# 게이트\n\n| # | 항목 | 상태 |\n|---|---|---|\n| 1 | 정위치 | OPEN |\n",
    )

    _, quiet, _ = run_hook(
        "user-prompt-submit",
        {"hook_event_name": "UserPromptSubmit", "cwd": str(ready_repo), "prompt": "문서 정리해줘"},
    )
    _, loud, _ = run_hook(
        "user-prompt-submit",
        {"hook_event_name": "UserPromptSubmit", "cwd": str(ready_repo), "prompt": "원점복귀 돌려줘"},
    )

    assert quiet is None
    assert "OPEN 1건" in loud["hookSpecificOutput"]["additionalContext"]


def test_post_tool_use_feeds_back_a_broken_document(ready_repo):
    board = write(
        ready_repo / "notes" / "docs" / "PROGRESS.md",
        "# 현황판\n\n---\n\n## 목차\n\n- [없음](#없음)\n\n---\n\n## 있음\n\n내용\n",
    )

    code, out, _ = run_hook(
        "post-tool-use",
        {
            "hook_event_name": "PostToolUse",
            "cwd": str(ready_repo),
            "tool_name": "Edit",
            "tool_input": {"file_path": str(board)},
        },
    )

    assert code == 0
    assert "없음" in out["hookSpecificOutput"]["additionalContext"]


def test_stop_reports_to_stderr_and_does_not_block(ready_repo):
    write(
        ready_repo / "notes" / "docs" / "PROGRESS.md",
        "# 현황판\n\n---\n\n## 목차\n\n- [없음](#없음)\n\n---\n\n## 있음\n\n내용\n",
    )

    code, out, err = run_hook("stop", {"hook_event_name": "Stop", "cwd": str(ready_repo)})

    assert code == 0
    assert out is None
    assert "girok" in err


def test_every_hook_survives_an_empty_payload():
    """Hooks run in contexts that do not always fill every field. Dying here
    would take the rest of the session's checks with it."""
    for name in ("session-start", "user-prompt-submit", "pre-tool-use", "post-tool-use", "stop"):
        code, _, _ = run_hook(name, {})
        assert code == 0, name


def test_a_repository_without_the_snapshot_gets_told_not_the_ready_marker(notes_repo):
    code, out, _ = run_hook(
        "session-start",
        {"hook_event_name": "SessionStart", "cwd": str(notes_repo), "startup_type": "startup"},
    )

    context = out["hookSpecificOutput"]["additionalContext"]
    assert code == 0
    assert "[girok] ready" not in context
    assert "초기화" in context


def test_a_payload_with_a_bom_still_reaches_the_right_repository(ready_repo):
    """Found by accident: a BOM in front of the payload made the reader
    return an empty dict, cwd resolved to the process directory, and the
    hook reported 'the snapshot is missing' for a repository whose snapshot
    was right there."""
    payload = json.dumps(
        {"hook_event_name": "SessionStart", "cwd": str(ready_repo), "startup_type": "startup"}
    )
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "session-start.py")],
        input="﻿" + payload,
        capture_output=True, text=True, encoding="utf-8",
    )

    assert proc.returncode == 0
    assert "[girok] ready" in proc.stdout
    assert "스냅샷이 없다" not in proc.stdout


def test_an_unreadable_payload_is_said_out_loud(ready_repo):
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "session-start.py")],
        input="{not json at all",
        capture_output=True, text=True, encoding="utf-8",
    )

    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
    assert "girok" in proc.stderr


def test_a_payload_without_cwd_does_not_report_on_some_other_directory(ready_repo):
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "session-start.py")],
        input=json.dumps({"hook_event_name": "SessionStart"}),
        capture_output=True, text=True, encoding="utf-8",
    )

    assert proc.returncode == 0
    assert "ready" not in proc.stdout
    assert "cwd" in proc.stderr


def test_a_korean_payload_sent_as_real_utf8_is_read_correctly(ready_repo):
    """Claude Code does not ASCII-escape its JSON. Reading stdin through the
    locale encoding — cp949 on a Korean Windows install — mangles a prompt
    or a path written in Korean. Every earlier test passed only because
    json.dumps escapes by default."""
    write(
        ready_repo / "notes" / "docs" / "SAFETY_GATE.md",
        "# 게이트\n\n| # | 항목 | 상태 |\n|---|---|---|\n| 1 | 정위치 | OPEN |\n",
    )
    payload = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(ready_repo),
            "prompt": "원점복귀 절차 알려줘",
        },
        ensure_ascii=False,
    )

    proc = subprocess.run(
        [sys.executable, str(HOOKS / "user-prompt-submit.py")],
        input=payload.encode("utf-8"),
        capture_output=True,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "OPEN 1건" in proc.stdout.decode("utf-8")


def test_post_tool_use_confirms_a_push(ready_repo):
    code, out, _ = run_hook(
        "post-tool-use",
        {
            "hook_event_name": "PostToolUse",
            "cwd": str(ready_repo),
            "tool_name": "Bash",
            "tool_input": {"command": "git push azure abc"},
            "tool_response": "Everything up-to-date",
        },
    )

    assert code == 0
    assert "push 완료" in out["hookSpecificOutput"]["additionalContext"]


def test_post_tool_use_does_not_claim_a_failed_push_succeeded(ready_repo):
    code, out, _ = run_hook(
        "post-tool-use",
        {
            "hook_event_name": "PostToolUse",
            "cwd": str(ready_repo),
            "tool_name": "Bash",
            "tool_input": {"command": "git push azure abc"},
            "tool_response": "fatal: Authentication failed",
        },
    )

    assert "실패" in out["hookSpecificOutput"]["additionalContext"]


# The payload each hook needs to do something observable, so that "it ran"
# means the check ran and not merely that the process started.
SNAPSHOT_PAYLOADS = {
    "session-start": lambda root: {
        "hook_event_name": "SessionStart", "cwd": str(root), "startup_type": "startup",
    },
    "user-prompt-submit": lambda root: {
        "hook_event_name": "UserPromptSubmit", "cwd": str(root), "prompt": "원점복귀 돌려줘",
    },
    "pre-tool-use": lambda root: {
        "hook_event_name": "PreToolUse", "cwd": str(root),
        "tool_name": "Bash", "tool_input": {"command": "git push --force origin main"},
    },
    "post-tool-use": lambda root: {
        "hook_event_name": "PostToolUse", "cwd": str(root),
        "tool_name": "Bash", "tool_input": {"command": "git push origin abc"},
        "tool_response": "Everything up-to-date",
    },
    "stop": lambda root: {"hook_event_name": "Stop", "cwd": str(root)},
}


def without_the_plugin(tmp_path):
    """The environment of a machine that never installed girok.

    PYTHONPATH goes too: pytest puts the plugin's own hooks/ and scripts/ on
    the path, and inheriting that would let the snapshot copy import the
    plugin's modules — the test would pass for the wrong reason.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["CLAUDE_PLUGIN_ROOT"] = str(tmp_path / "no-plugin-here")
    return env


@pytest.mark.parametrize("name", sorted(SNAPSHOT_PAYLOADS))
def test_the_snapshot_hooks_run_without_the_plugin(ready_repo, tmp_path, name):
    """A machine with no plugin runs the copies in .method/hooks/. If those
    cannot import what they need, the repository is unsupervised and nothing
    says so."""
    hooks = ready_repo / "notes" / ".method" / "hooks"

    code, _, err = run_hook(
        name, SNAPSHOT_PAYLOADS[name](ready_repo),
        hooks_dir=hooks, env=without_the_plugin(tmp_path),
    )

    assert code == 0, err
    assert "Traceback" not in err, err


def test_the_snapshot_session_start_still_emits_the_ready_marker(ready_repo, tmp_path):
    """The CLAUDE.md gate keys off this marker. Losing it on a machine that
    has the rules and runs every check would stop work for no reason."""
    hooks = ready_repo / "notes" / ".method" / "hooks"

    _, out, err = run_hook(
        "session-start", SNAPSHOT_PAYLOADS["session-start"](ready_repo),
        hooks_dir=hooks, env=without_the_plugin(tmp_path),
    )

    assert out is not None, err
    assert "[girok] ready" in out["hookSpecificOutput"]["additionalContext"]


def test_the_snapshot_pre_tool_use_still_blocks(ready_repo, tmp_path):
    """Blocking is the one thing a rule document cannot do. If it does not
    survive the move into the snapshot, the whole plugin-free story is advice
    rather than enforcement."""
    hooks = ready_repo / "notes" / ".method" / "hooks"

    _, out, err = run_hook(
        "pre-tool-use", SNAPSHOT_PAYLOADS["pre-tool-use"](ready_repo),
        hooks_dir=hooks, env=without_the_plugin(tmp_path),
    )

    assert out is not None, err
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_snapshot_user_prompt_submit_still_raises_the_gate(ready_repo, tmp_path):
    """Exit code 0 only says the process lived. What matters is that the open
    gate item reached the session."""
    write(
        ready_repo / "notes" / "docs" / "SAFETY_GATE.md",
        "# 게이트\n\n| # | 항목 | 상태 |\n|---|---|---|\n| 1 | 정위치 | OPEN |\n",
    )
    hooks = ready_repo / "notes" / ".method" / "hooks"

    _, out, err = run_hook(
        "user-prompt-submit", SNAPSHOT_PAYLOADS["user-prompt-submit"](ready_repo),
        hooks_dir=hooks, env=without_the_plugin(tmp_path),
    )

    assert out is not None, err
    assert "OPEN 1건" in out["hookSpecificOutput"]["additionalContext"]


def test_the_snapshot_post_tool_use_still_checks_the_document(ready_repo, tmp_path):
    board = write(
        ready_repo / "notes" / "docs" / "PROGRESS.md",
        "# 현황판\n\n---\n\n## 목차\n\n- [없음](#없음)\n\n---\n\n## 있음\n\n내용\n",
    )
    hooks = ready_repo / "notes" / ".method" / "hooks"

    _, out, err = run_hook(
        "post-tool-use",
        {
            "hook_event_name": "PostToolUse", "cwd": str(ready_repo),
            "tool_name": "Edit", "tool_input": {"file_path": str(board)},
        },
        hooks_dir=hooks, env=without_the_plugin(tmp_path),
    )

    assert out is not None, err
    assert "없음" in out["hookSpecificOutput"]["additionalContext"]


def test_the_snapshot_stop_still_reports_to_stderr(ready_repo, tmp_path):
    write(
        ready_repo / "notes" / "docs" / "PROGRESS.md",
        "# 현황판\n\n---\n\n## 목차\n\n- [없음](#없음)\n\n---\n\n## 있음\n\n내용\n",
    )
    hooks = ready_repo / "notes" / ".method" / "hooks"

    _, _, err = run_hook(
        "stop", SNAPSHOT_PAYLOADS["stop"](ready_repo),
        hooks_dir=hooks, env=without_the_plugin(tmp_path),
    )

    assert "girok" in err
