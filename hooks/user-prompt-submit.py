"""UserPromptSubmit: what a session has to hear when a prompt arrives.

Two things. Open gate items the moment motion is mentioned - the gate
summary is already in the session start block, but a long session pushes it
out of view exactly when it matters. And, once, that this session never went
through its start check at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hook_io
import notes_config
import gate_rules

STARTED_BEFORE_THE_HOOKS = (
    "[girok] 이 세션에서는 세션 시작 검사가 돌지 않았다 - 훅이 걸리기 전에 시작된 세션이다"
    "(pull 이나 `/notes` 로 훅 등록이 방금 들어온 경우가 그렇다). ready 블록·작업자 확인·"
    "반입 스캔·브랜치 확인이 모두 빠져 있다. 사용자에게 **Claude Code 세션을 새로 시작**"
    "하라고 알릴 것. 새 세션에서 검사가 돈 뒤에 편집·커밋을 한다."
)


def _late_session(payload: dict, cfg: notes_config.NotesConfig) -> bool:
    """Whether to say, this once, that the session predates its hooks.

    Claude Code picks up a settings file that appears mid-session and runs
    its hooks from then on, but SessionStart has already passed. The session
    then has hooks and no start check, and looks exactly like one that had
    both.
    """
    if cfg.source is None or not (cfg.notes_dir / ".method" / "VERSION").is_file():
        return False
    if hook_io.session_marked(payload) is not False:
        return False
    # Marked first: if that cannot be written, saying it would repeat on
    # every prompt for the rest of the session.
    return hook_io.mark_session(payload)


def _open_gate(prompt: str, cfg: notes_config.NotesConfig) -> str | None:
    if not gate_rules.MOTION_RE.search(prompt):
        return None
    if not cfg.modules.get("safetyGate", True):
        return None
    open_items = gate_rules.open_gate_items(cfg)
    if not open_items:
        return None
    return (
        f"[girok] 실장비 모션이 언급됐다. SAFETY_GATE.md OPEN {open_items}건 - "
        f"OPEN 이 남아 있는 동안 모션 명령을 실행하거나 실행을 안내하지 않는다. "
        f"항목은 사람 확인자만 닫는다."
    )


def main() -> int:
    try:
        payload = hook_io.read_payload()
    except hook_io.PayloadError as exc:
        hook_io.fail_loud(str(exc))
        return 0
    if not payload:
        return 0

    prompt = hook_io.prompt_of(payload)
    # Most prompts need nothing. The config is read only when the payload
    # names a session to check or the prompt mentions motion.
    if payload.get("session_id") is None and not gate_rules.MOTION_RE.search(prompt):
        return 0

    try:
        cfg = notes_config.load(hook_io.cwd_of(payload))
        texts = []
        if _late_session(payload, cfg):
            texts.append(STARTED_BEFORE_THE_HOOKS)
        gate = _open_gate(prompt, cfg)
        if gate:
            texts.append(gate)
    except Exception as exc:  # noqa: BLE001
        hook_io.fail_loud(f"게이트 확인 실패: {exc}")
        return 0

    hook_io.emit_context("UserPromptSubmit", "\n".join(texts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
