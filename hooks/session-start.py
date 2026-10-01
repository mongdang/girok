"""SessionStart: put the state of the repository into the first turn."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hook_io
import session_report


def main() -> int:
    try:
        payload = hook_io.read_payload()
        root = hook_io.cwd_of(payload)
    except hook_io.PayloadError as exc:
        hook_io.fail_loud(f"{exc} – 이 세션에는 규칙 검사가 적용되지 않았다")
        return 0

    try:
        report = session_report.build(root)
    except Exception as exc:  # noqa: BLE001 - never fail quietly
        hook_io.fail_loud(f"세션 시작 검사 실패: {exc}")
        return 0

    hook_io.emit_context("SessionStart", report.text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
