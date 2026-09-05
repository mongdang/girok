"""The summary injected at the start of a session.

Aim: by the first response the session already knows the state of the
repository, so the only thing left for a person is judgement. That means
this runs the checks rather than telling the agent to run them.

Two things are always present when the module applies:

- `[girok] ready vX.Y.Z` — the marker the CLAUDE.md gate keys off.
  Emitting it while the snapshot is missing would defeat the gate, so it is
  written only when the snapshot is actually there.
- the safety summary — a lazily loaded skill can fail to load without
  anyone noticing, so these rules are injected instead of skilled.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import notes_config
import method_sync
import gate_rules
import incoming

WRONG_PLACE = (
    "여기는 저장소가 아니다 — `.git` 도 `.claude/girok.json` 도 없다. 둘 중 하나다: ① Claude Code 는 켠 폴더를 대상으로 삼으므로 한 단계 위에서 켰다 → 작업할 저장소 폴더로 이동해 다시 켤 것. ② 이 프로젝트가 아직 git 을 쓰지 않는다 → `git init` 을 먼저 할 것. 이 방법론은 판본 추적·병합·커밋 즉시 push 를 git 에 의존하므로 git 없이는 절반이 동작하지 않는다"
)

SAFETY_REMINDER = (
    "안전: 게이트 OPEN 항목이 남아 있는 동안 실장비 모션 명령(원점복귀·이동·자동 테스트)을 "
    "실행하거나 안내하지 않는다. 항목의 확인자 칸은 사람만 채운다 — 에이전트가 채우지 않는다. "
    "훅은 에이전트 경로만 막는다(사람이 장비 콘솔에서 하는 동작은 막지 못한다)."
)


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    ready: bool = False
    needs_worker_answer: bool = False
    worker: str | None = None
    incoming: object | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _count_rows(section: str) -> int:
    rows = [l for l in section.splitlines() if re.match(r"^\s*\|", l)]
    body = [l for l in rows if not re.match(r"^\s*\|[\s:|-]+\|\s*$", l)]
    return max(0, len(body) - 1)


def _section(text: str, heading: str) -> str | None:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)", text, re.S | re.M)
    return m.group(1) if m else None


def _board_summary(cfg: notes_config.NotesConfig, worker: str | None) -> list[str]:
    candidates = []
    if worker:
        candidates.append(cfg.notes_dir / f"docs_{worker}" / cfg.board)
    candidates.extend(cfg.board_paths())

    for board in candidates:
        if not board.is_file():
            continue
        text = board.read_text(encoding="utf-8")
        bits = []
        for heading, label in (("활성 위험", "활성 위험"), ("열린 질문", "열린 질문")):
            section = _section(text, heading)
            if section is not None:
                bits.append(f"{label} {_count_rows(section)}건")
        rel = board.relative_to(cfg.repo_root).as_posix()
        return [f"현황판 {rel}" + (f" — {', '.join(bits)}" if bits else "")]

    return [f"[경고] 현황판 {cfg.board} 을 찾지 못했다 — `/notes` 로 초기화할 것"]


def _resolve_worker(cfg: notes_config.NotesConfig, email: str | None) -> tuple[str | None, list[str]]:
    """Resolve the worker without asking, and ask only when that fails.

    Asking every session costs a turn for an answer that git already knows.
    Asking when the mapping is missing or ambiguous is the case where a
    wrong guess would file this session's work under someone else's name.
    """
    if not cfg.parallel_mode:
        return None, []

    matches = [wid for wid, mail in cfg.workers.items() if mail and mail == email]
    if len(matches) == 1:
        return matches[0], [f"작업자 {matches[0]} (git user.email 로 확정)"]

    folders = sorted(p.name[len("docs_"):] for p in cfg.worker_dirs())
    listed = ", ".join(folders) if folders else "(없음)"
    reason = "매핑에 없음" if not matches else "후보가 둘 이상"
    return None, [
        f"[확인 필요] git user.email `{email or '미설정'}` 이 {reason}. "
        f"등록된 작업자: {listed} — 누구십니까? (목록에 없으면 신규 작업자 id 를 알려주세요) "
        f"확정 전에는 어떤 쓰기도 하지 않는다."
    ]


def build(
    start: Path | str = ".",
    git_email: str | None = None,
    plugin_root: Path = method_sync.PLUGIN_ROOT,
    scan_remote: bool = True,
) -> Report:
    cfg = notes_config.load(start)
    report = Report()

    if not cfg.is_repository:
        report.lines.append(f"[girok] {WRONG_PLACE}")
        return report

    state = method_sync.status(cfg.repo_root, plugin_root)
    if state.snapshot_version is None:
        report.lines.append(
            f"[girok] `.method/` 스냅샷이 없다 — 규칙 전문이 저장소에 없는 상태다. "
            f"`/notes` 로 초기화할 것. 초기화 전에는 이 방법론의 규칙이 적용되지 않는다."
        )
        return report

    report.ready = True
    # The marker says the rules are in this repository, not that a plugin is
    # installed on this machine -- the snapshot is what carries them, and it
    # is what a machine without the plugin still has.
    report.lines.append(f"[girok] ready v{state.snapshot_version}")
    if state.plugin_version is not None and not state.in_sync:
        report.lines.append(
            f"[주의] 스냅샷 v{state.snapshot_version} ≠ 플러그인 v{state.plugin_version} — "
            f"규칙이 낡았을 수 있다. `/notes` 로 sync 할 것"
        )

    email = git_email if git_email is not None else gate_rules.read_git_email(cfg.repo_root)
    worker, worker_lines = _resolve_worker(cfg, email)
    report.worker = worker
    report.needs_worker_answer = worker is None and bool(worker_lines)
    report.lines.extend(worker_lines)

    report.lines.extend(_board_summary(cfg, worker))

    # The parallel-work rules all begin with noticing there is something to
    # merge. Noticing it by remembering to look is exactly what does not
    # happen, so the scan runs here.
    if cfg.parallel_mode and scan_remote:
        try:
            report.incoming = incoming.scan(cfg.repo_root, worker=worker)
            report.lines.extend(incoming.summary(report.incoming))
        except Exception as exc:  # noqa: BLE001 - a slow remote must not take the rest down
            report.lines.append(f"[주의] 반입 스캔 실패: {exc}")

    if cfg.modules.get("safetyGate", True):
        open_items = gate_rules.open_gate_items(cfg)
        report.lines.append(f"안전 게이트 OPEN {open_items}건")
        report.lines.append(SAFETY_REMINDER)

    return report
