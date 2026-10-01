"""PreToolUse: block what must not happen, warn about the rest."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hook_io
import gate_rules
import marker_scan


def main() -> int:
    try:
        payload = hook_io.read_payload()
        if not payload:
            return 0
        root = hook_io.cwd_of(payload)
    except hook_io.PayloadError as exc:
        hook_io.fail_loud(f"{exc} – 이 도구 호출은 검사되지 않았다")
        return 0

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    try:
        decision = gate_rules.decide(root, tool, tool_input)
    except Exception as exc:  # noqa: BLE001
        hook_io.fail_loud(f"차단 규칙 검사 실패: {exc} – 이 도구 호출은 검사되지 않았다")
        return 0

    if decision.blocked:
        hook_io.emit_deny(decision.reason)
        return 0

    # The marker rule is checked when a commit is made, not when a file is
    # edited: writing the marker first and registering it second is the
    # normal order, and blocking the first half would teach people to work
    # around the hook.
    if tool == "Bash" and "git commit" in tool_input.get("command", ""):
        try:
            added, changed = marker_scan.staged_from_git(root)
            staged = marker_scan.check_staged(root, added, changed)
        except Exception as exc:  # noqa: BLE001
            hook_io.fail_loud(f"마커 검사 실패: {exc}")
            return 0
        if not staged.ok:
            hook_io.emit_deny(" / ".join(staged.problems))
            return 0

    if decision.warnings:
        hook_io.emit_context("PreToolUse", "[girok] " + " / ".join(decision.warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
