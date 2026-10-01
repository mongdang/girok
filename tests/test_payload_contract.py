"""The payload field names, and a guard against inventing them again.

Three field names were wrong at once, and every test agreed with the code
because the tests fed the same invented names. Green meant nothing:

- `user_input` instead of `prompt` - the safety-gate injection never fired
- `tool_result` instead of `tool_response` - a failed push read as done
- `notes_dir.relative_to(root)` on an unresolved root - crashed on `--root .`

The fix is structural rather than three edits: field access lives in
`hook_io`, with the real name recorded next to the evidence for it, and the
last test here fails if a hook reaches into the payload directly again.

Evidence for the names, from other plugins that read the same events:
- `claude-plugins-official/security-guidance` reads `tool_response` and takes
  `stdout`, `stderr`, `interrupted` out of it (Bash has no `exit_code`).
- `caveman` reads `event.prompt ?? event.user_prompt ?? event.userMessage`
  and `event.tool_output ?? event.tool_response ?? ...`.
"""
import re
from pathlib import Path

import hook_io
import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
ENTRY_SCRIPTS = sorted(HOOKS.glob("*-*.py")) + [HOOKS / "stop.py"]


# --- the prompt -------------------------------------------------------------

def test_the_prompt_field_is_prompt():
    assert hook_io.prompt_of({"prompt": "원점복귀 해줘"}) == "원점복귀 해줘"


def test_the_old_name_still_works_as_a_fallback():
    """Kept so a harness that sends the other name is not silently ignored -
    being wrong once about this cost the safety injection entirely."""
    assert hook_io.prompt_of({"user_input": "원점복귀 해줘"}) == "원점복귀 해줘"


def test_an_absent_prompt_is_an_empty_string():
    assert hook_io.prompt_of({}) == ""


# --- the tool's output ------------------------------------------------------

def test_the_output_field_is_tool_response():
    payload = {"tool_response": {"stdout": "Everything up-to-date", "stderr": ""}}

    assert "up-to-date" in hook_io.output_text_of(payload)


def test_stdout_and_stderr_are_both_read():
    payload = {"tool_response": {"stdout": "a", "stderr": "fatal: nope"}}

    text = hook_io.output_text_of(payload)

    assert "a" in text and "fatal: nope" in text


def test_a_plain_string_response_is_read(monkeypatch):
    assert "boom" in hook_io.output_text_of({"tool_response": "boom"})


def test_the_old_names_are_fallbacks():
    assert "x" in hook_io.output_text_of({"tool_result": "x"})
    assert "y" in hook_io.output_text_of({"tool_output": "y"})


def test_an_interrupted_call_counts_as_failed():
    """Bash `tool_response` carries no exit code, so an interruption is the
    only unambiguous failure signal available."""
    assert hook_io.failed({"tool_response": {"stdout": "", "interrupted": True}})


def test_an_error_flag_counts_as_failed():
    assert hook_io.failed({"tool_response": {"is_error": True}})


def test_an_error_in_the_text_counts_as_failed():
    assert hook_io.failed({"tool_response": {"stderr": "fatal: Authentication failed"}})


def test_ordinary_output_does_not_count_as_failed():
    assert not hook_io.failed({"tool_response": {"stdout": "Everything up-to-date"}})


def test_an_absent_response_is_not_treated_as_failure():
    """Saying a push failed when nothing said so would send people chasing a
    problem that is not there."""
    assert not hook_io.failed({})


# --- the guard --------------------------------------------------------------

RAW_ACCESS = re.compile(
    r"""\.get\(\s*["'](?:prompt|user_input|tool_response|tool_result|tool_output)["']"""
)


@pytest.mark.parametrize("script", ENTRY_SCRIPTS, ids=lambda p: p.name)
def test_no_hook_reads_a_payload_field_directly(script):
    """Field names belong in one place.

    Three of them were wrong at the same time because each hook spelled its
    own, and each test agreed with its hook. One accessor means one place to
    be wrong, and one place to fix.
    """
    text = script.read_text(encoding="utf-8")

    assert not RAW_ACCESS.search(text), (
        f"{script.name} 이 payload 필드를 직접 읽는다 - hook_io 의 접근자를 쓸 것"
    )
