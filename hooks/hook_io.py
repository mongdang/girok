"""Reading a hook's stdin payload and writing its response.

Kept in one place because getting the response shape wrong fails silently:
a malformed block is ignored, and a check that is ignored is worse than no
check, since everyone believes it is running.
"""
import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent))


class PayloadError(Exception):
    """The payload could not be read.

    Raised rather than swallowed. The old behaviour returned an empty dict,
    the caller resolved cwd to ".", and the hook then reported confidently
    on a different repository – "the snapshot is missing" for a repository
    whose snapshot was right there. Nothing in that output said it was wrong.
    """


def _prepare_streams() -> None:
    """Korean Windows consoles default to cp949, which cannot encode the
    text these hooks emit. Without this a hook dies on its own output."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _read_raw() -> str:
    """The payload, decoded as UTF-8 regardless of the machine's locale.

    Reading through `sys.stdin` would decode with the locale encoding –
    cp949 on a Korean Windows install – so a payload carrying Korean (a
    prompt, a path) would arrive mangled or raise. Claude Code sends UTF-8,
    so the bytes are decoded here rather than left to the locale.

    `utf-8-sig` also drops a leading byte order mark, which Windows tooling
    puts there often enough to matter.
    """
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:  # a test injected a text stream
        return sys.stdin.read().lstrip("﻿")
    try:
        return buffer.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PayloadError(f"hook payload 가 UTF-8 이 아니다: {exc}") from exc


def read_payload() -> dict:
    _prepare_streams()
    stripped = _read_raw().strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise PayloadError(f"hook payload 를 JSON 으로 읽지 못했다: {exc}") from exc


# Payload field names live here and nowhere else.
#
# Three of them were wrong at the same time – `user_input` for the prompt,
# `tool_result` for the output – and every test agreed with the code because
# the tests fed the same invented names. The safety-gate injection never
# fired and a failed push read as done, both with a green suite.
#
# Evidence for the real names, from plugins that read the same events:
#   - claude-plugins-official/security-guidance reads `tool_response` and
#     takes `stdout`, `stderr`, `interrupted` out of it. Bash carries no
#     exit code, so failure is inferred from the text.
#   - caveman reads `event.prompt ?? event.user_prompt ?? event.userMessage`.
#
# The older names stay as fallbacks: being wrong here is silent, and a
# fallback costs nothing.
PROMPT_FIELDS = ("prompt", "user_prompt", "user_input")
RESPONSE_FIELDS = ("tool_response", "tool_output", "tool_result")

# Failure signals in Bash output. Conservative on purpose: claiming a push
# failed when nothing says so sends people chasing a problem that is not
# there, and claiming it succeeded leaves a commit on one machine while
# everyone believes it is shared.
FAILURE_SIGNS = ("error:", "fatal:", "rejected", "denied", "permission denied")


def prompt_of(payload: dict) -> str:
    for field in PROMPT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    return ""


def _response(payload: dict):
    for field in RESPONSE_FIELDS:
        if field in payload and payload[field] is not None:
            return payload[field]
    return None


def output_text_of(payload: dict) -> str:
    """Everything the tool printed, stdout and stderr together."""
    response = _response(payload)
    if response is None:
        return ""
    if isinstance(response, dict):
        parts = [response.get(key) for key in ("stdout", "stderr", "output", "content")]
        return "\n".join(str(p) for p in parts if p)
    return str(response)


def failed(payload: dict) -> bool:
    """Whether the tool call reported a failure.

    An absent response is not a failure – silence is not evidence.
    """
    response = _response(payload)
    if response is None:
        return False
    if isinstance(response, dict):
        if response.get("interrupted") or response.get("is_error") or response.get("isError"):
            return True
    text = output_text_of(payload).lower()
    return any(sign in text for sign in FAILURE_SIGNS)


def cwd_of(payload: dict) -> Path:
    """The directory the session is running in.

    No fallback to the process directory: that fallback is how a hook came
    to report on a repository nobody had asked about.
    """
    cwd = payload.get("cwd")
    if not cwd:
        raise PayloadError("hook payload 에 cwd 가 없다 – 어느 저장소인지 알 수 없다")
    return Path(cwd)


def emit_context(event: str, text: str) -> None:
    if not text.strip():
        return
    json.dump(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
        sys.stdout,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


def emit_deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


def fail_loud(message: str) -> None:
    """Safety-related checks never fail quietly.

    A hook that dies silently leaves a session that looks supervised and is
    not. If this text has nowhere to go, the CLAUDE.md gate is the backstop:
    without the readiness marker, work stops.
    """
    print(f"[girok] 훅 실패: {message}", file=sys.stderr)
