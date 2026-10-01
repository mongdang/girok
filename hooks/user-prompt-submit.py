"""UserPromptSubmit: surface open gate items the moment motion is mentioned.

The gate summary is already in the session start block, but a long session
pushes it out of view exactly when it matters.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hook_io
import notes_config
import gate_rules


def main() -> int:
    try:
        payload = hook_io.read_payload()
    except hook_io.PayloadError as exc:
        hook_io.fail_loud(str(exc))
        return 0

    prompt = hook_io.prompt_of(payload)
    if not gate_rules.MOTION_RE.search(prompt):
        return 0

    try:
        cfg = notes_config.load(hook_io.cwd_of(payload))
        if not cfg.modules.get("safetyGate", True):
            return 0
        open_items = gate_rules.open_gate_items(cfg)
    except Exception as exc:  # noqa: BLE001
        hook_io.fail_loud(f"게이트 확인 실패: {exc}")
        return 0

    if not open_items:
        return 0

    hook_io.emit_context(
        "UserPromptSubmit",
        f"[girok] 실장비 모션이 언급됐다. SAFETY_GATE.md OPEN {open_items}건 - "
        f"OPEN 이 남아 있는 동안 모션 명령을 실행하거나 실행을 안내하지 않는다. "
        f"항목은 사람 확인자만 닫는다.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
