"""README 이미지 생성기 — 실제 실행 출력을 터미널 카드 SVG 로 렌더한다.

    python ci/make_images.py

출력은 docs/images/*.svg. 캡처 원문은 이 파일의 CARDS 에 그대로 들어 있으므로,
동작이 바뀌면 명령을 다시 돌려 붙여 넣고 이 스크립트를 재실행한다.
"""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"

BG = "#0F1319"
PANEL = "#161B22"
BORDER = "#272E38"
FG = "#C9D1D9"
DIM = "#7D8590"
GREEN = "#4E9B6C"
AMBER = "#E0A458"
RED = "#D4644A"
BLUE = "#6E9FD4"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,DejaVu Sans Mono,monospace"
SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,Noto Sans KR,Helvetica,Arial,sans-serif"

FS = 13.5
LH = 21.0
PAD_X = 20.0
TITLEBAR = 34.0


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def width_of(s: str) -> float:
    """Monospace 폭 추정 — CJK 는 전각으로 센다."""
    w = 0.0
    for ch in s:
        w += FS if ord(ch) > 0x2000 else FS * 0.6
    return w


# 줄 앞머리 토큰 → 색
TOKENS = [
    (re.compile(r"^\[실패\]"), RED),
    (re.compile(r"^\[차단\]"), RED),
    (re.compile(r"^\[주의\]"), AMBER),
    (re.compile(r"^\[생성\]"), GREEN),
    (re.compile(r"^\[유지\]"), DIM),
    (re.compile(r"^\[girok\]"), GREEN),
]


def render_line(text: str, x: float, y: float) -> str:
    if text.startswith("$ "):
        return (
            f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{FS}" xml:space="preserve">'
            f'<tspan fill="{GREEN}">$</tspan>'
            f'<tspan fill="{FG}"> {esc(text[2:])}</tspan></text>'
        )
    for pat, color in TOKENS:
        m = pat.match(text)
        if m:
            head, tail = text[: m.end()], text[m.end():]
            return (
                f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{FS}" xml:space="preserve">'
                f'<tspan fill="{color}">{esc(head)}</tspan>'
                f'<tspan fill="{FG}">{esc(tail)}</tspan></text>'
            )
    fill = "#98A2AE" if text.startswith("  ") else FG
    return (
        f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="{FS}" '
        f'xml:space="preserve" fill="{fill}">{esc(text)}</text>'
    )


# 값을 나란히 세워야 하는 줄은 (라벨, 값) 으로 적는다 — 한글은 전각이라
# 공백으로 맞춘 열이 SVG 에서는 어긋난다


def column_of(body: list) -> float:
    labels = [width_of(r[0]) for r in body if isinstance(r, tuple)]
    return max(labels) + 26 if labels else 0.0


def row_width(row, col: float) -> float:
    if isinstance(row, tuple):
        return col + width_of(row[1])
    return width_of(row)


def render_row(row, x: float, y: float, col: float) -> str:
    if isinstance(row, tuple):
        return render_line(row[0], x, y) + render_line(row[1], x + col, y)
    return render_line(row, x, y)


def terminal(title: str, lines: list) -> str:
    body = list(lines)
    col = column_of(body)
    w = max([row_width(ln, col) for ln in body] + [width_of(title) + 120]) + PAD_X * 2
    w = max(660.0, min(w, 1180.0))
    h = TITLEBAR + PAD_X + LH * len(body) + 8

    dots = "".join(
        f'<circle cx="{20 + i * 16}" cy="{TITLEBAR / 2}" r="5" fill="{c}"/>'
        for i, c in enumerate(("#E06C5B", "#E0B45B", "#5BB07A"))
    )
    rows = "".join(
        render_row(ln, PAD_X, TITLEBAR + PAD_X + LH * i, col)
        for i, ln in enumerate(body)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
        f'viewBox="0 0 {w:.0f} {h:.0f}" role="img" aria-label="{esc(title)}">\n'
        f'  <rect width="{w:.0f}" height="{h:.0f}" rx="10" fill="{BG}"/>\n'
        f'  <rect x="0.5" y="0.5" width="{w - 1:.0f}" height="{h - 1:.0f}" rx="10" '
        f'fill="none" stroke="{BORDER}"/>\n'
        f'  <path d="M0 10 a10 10 0 0 1 10 -10 h{w - 20:.0f} a10 10 0 0 1 10 10 '
        f'v{TITLEBAR - 10:.0f} h-{w:.0f} z" fill="{PANEL}"/>\n'
        f'  <line x1="0" y1="{TITLEBAR:.0f}" x2="{w:.0f}" y2="{TITLEBAR:.0f}" stroke="{BORDER}"/>\n'
        f'  {dots}\n'
        f'  <text x="{w / 2:.0f}" y="{TITLEBAR / 2 + 4:.0f}" text-anchor="middle" '
        f'font-family="{SANS}" font-size="11.5" fill="{DIM}">{esc(title)}</text>\n'
        f'  {rows}\n'
        f'</svg>\n'
    )


CARDS: dict[str, tuple[str, list[str]]] = {}

CARDS["survey"] = (
    "/notes — 뼈대를 만들기 전에 저장소부터 읽는다",
    [
        "$ /notes",
        "",
        "저장소: trading-bot · 문서 43건",
        "",
        "제안하는 설정:",
        ("  진행기록 위치", "."),
        ("  현황판", "STATE.md"),
        ("  결정 기록", "decisions (numbered)"),
        ("  검사할 폴더", "decisions, docs, experiments"),
        ("  안전 게이트", "끔"),
        ("  아카이브", "끔"),
        ("  병행 작업", "끔"),
        "",
        "살펴볼 것 1건:",
        "  - `CLAUDE.md` 가 아카이브 폴더를 만들지 않는다고 못 박아 뒀다",
        "    — 그 관례를 따라 archive 모듈을 끈다",
        "",
        "이건 제안이다 — 아무것도 쓰지 않았다. 사람이 확인한 뒤 초기화할 것.",
    ],
)

CARDS["init"] = (
    "확인을 받은 뒤에야 만든다 — 이미 있는 파일은 건드리지 않는다",
    [
        "$ /notes  →  확인",
        "",
        "[생성] .claude/girok.json",
        "[생성] .claude/settings.json",
        "[생성] notes/CLAUDE.md",
        "[생성] notes/GEMINI.md",
        "[생성] notes/AGENTS.md",
        "[생성] notes/docs/PROGRESS.md",
        "[생성] notes/docs/decisions/README.md",
        "[생성] notes/docs/SAFETY_GATE.md",
        ("[유지] README.md", "← 이미 있다. 덮어쓰지 않는다"),
        ("[생성] notes/.method/", "← 규칙 원문의 동결 사본"),
        "",
        "만든 것 10건, 유지 1건",
    ],
)

CARDS["session"] = (
    "세션이 시작되는 시점에 이미 상황을 알고 있다",
    [
        "$ cd my-robot && claude",
        "",
        "[girok] ready v0.18.0",
        "작업자 abc (git user.email 로 확정)",
        "현황판 notes/docs_abc/PROGRESS.md — 활성 위험 0건, 열린 질문 0건",
        "안전 게이트 OPEN 1건",
        "",
        "안전: 게이트 OPEN 항목이 남아 있는 동안 실장비 모션 명령(원점복귀·이동·",
        "자동 테스트)을 실행하거나 안내하지 않는다. 항목의 확인자 칸은 사람만",
        "채운다 — 에이전트가 채우지 않는다.",
    ],
)

CARDS["lint"] = (
    "문서를 쓰는 순간 검사기가 돈다",
    [
        "$ python notes/.method/scripts/check_docs.py",
        "",
        "[실패] notes/docs/SETUP.md -> 표가 빈 줄로 끊김 — 14번째 줄부터의 행이",
        "       표 밖 텍스트로 렌더링됨",
        "[실패] notes/docs/SETUP.md -> 목차 앵커 `#보정-절차` 에 대응하는 헤더가 없음",
        "[실패] notes/docs/SETUP.md -> 존재하지 않는 ADR-042 인용",
        "[주의] notes/CLAUDE.md -> `## 목차` 가 없다 (2,479바이트)",
        "[주의] notes/docs/SETUP.md -> 로컬 절대경로가 있다 (C:\\Users\\abc\\build)",
        "       — 머신마다 달라진다. 저장소 이름과 상대경로로만 쓸 것",
        "",
        "7개 문서 검사, 3건 실패",
    ],
)

CARDS["block"] = (
    "스위치가 아니라 이유를 요구한다",
    [
        "$ git push origin +master",
        "",
        "[차단] force push 금지 — 변경 이력 자체가 결정 기록이라 되돌리기 어렵다.",
        "       이력 정리가 필요하면 트리 불변 커밋(`-s ours` 조상 연결 등)으로",
        "       할 것. 그래도 해야 한다면 GIROK_FORCE_PUSH_REASON 에 이유를 담아",
        "       실행할 것 — 스위치가 아니라 이유다(8자 이상). 그 이유는 세션에",
        "       그대로 남는다",
        "",
        '$ GIROK_FORCE_PUSH_REASON="이력 리셋 — 사용자 지시 2026-09-01" \\',
        "    git push origin +master",
        "",
        "[girok] 규칙을 어겼다: force push · 이유가 세션 기록에 남았다",
    ],
)


def hero() -> str:
    w, h = 1000, 340
    label = "girok — 문서 규칙은 한 곳에만 두고, 모든 저장소가 같은 규칙을 따르게 한다"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{label}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0F1319"/>
      <stop offset="1" stop-color="#141B19"/>
    </linearGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
      <path d="M28 0 H0 V28" fill="none" stroke="#1C232B" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="{w}" height="{h}" rx="12" fill="url(#bg)"/>
  <rect width="{w}" height="{h}" rx="12" fill="url(#grid)" opacity="0.55"/>
  <rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="12" fill="none" stroke="{BORDER}"/>

  <text x="70" y="120" font-family="{MONO}" font-size="66" font-weight="700" fill="#EAF0F6" letter-spacing="-1">girok</text>
  <text x="268" y="120" font-family="{MONO}" font-size="15" fill="{GREEN}">기록</text>
  <rect x="70" y="142" width="86" height="3" rx="1.5" fill="{GREEN}"/>

  <text x="70" y="186" font-family="{SANS}" font-size="19" fill="#D6DEE8">문서 규칙은 한 곳에만 두고,</text>
  <text x="70" y="214" font-family="{SANS}" font-size="19" fill="#D6DEE8">모든 저장소가 <tspan font-weight="700" fill="#FFFFFF">같은</tspan> 규칙을 따르게 한다</text>
  <text x="70" y="246" font-family="{SANS}" font-size="12.5" fill="{DIM}">A documentation methodology as a Claude Code plugin — the rules ship frozen into every repo that adopts them.</text>

  <g font-family="{SANS}" font-size="12">
    <rect x="70" y="270" width="132" height="28" rx="6" fill="#182119" stroke="{GREEN}"/>
    <text x="136" y="289" text-anchor="middle" fill="{GREEN}">현황판 · ADR</text>
    <rect x="214" y="270" width="112" height="28" rx="6" fill="#211D16" stroke="{AMBER}"/>
    <text x="270" y="289" text-anchor="middle" fill="{AMBER}">문서 검사기</text>
    <rect x="338" y="270" width="112" height="28" rx="6" fill="#211714" stroke="{RED}"/>
    <text x="394" y="289" text-anchor="middle" fill="{RED}">안전 게이트</text>
    <rect x="462" y="270" width="164" height="28" rx="6" fill="#161C22" stroke="{BLUE}"/>
    <text x="544" y="289" text-anchor="middle" fill="{BLUE}">.method/ 동결 사본</text>
  </g>

  <g opacity="0.9">
    <rect x="736" y="56" width="196" height="58" rx="8" fill="#182119" stroke="{GREEN}"/>
    <text x="834" y="80" text-anchor="middle" font-family="{SANS}" font-size="12.5" fill="{GREEN}">플러그인</text>
    <text x="834" y="99" text-anchor="middle" font-family="{SANS}" font-size="11" fill="{DIM}">규칙 원본 하나</text>

    <path d="M834 114 V146" stroke="{DIM}" stroke-width="1.5"/>
    <path d="M829 140 l5 8 l5 -8" fill="none" stroke="{DIM}" stroke-width="1.5"/>
    <text x="846" y="136" font-family="{MONO}" font-size="10.5" fill="{DIM}">sync</text>

    <rect x="736" y="148" width="196" height="58" rx="8" fill="#211D16" stroke="{AMBER}"/>
    <text x="834" y="172" text-anchor="middle" font-family="{SANS}" font-size="12.5" fill="{AMBER}">.method/</text>
    <text x="834" y="191" text-anchor="middle" font-family="{SANS}" font-size="11" fill="{DIM}">저장소에 커밋된다</text>

    <path d="M834 206 V238" stroke="{DIM}" stroke-width="1.5"/>
    <path d="M829 232 l5 8 l5 -8" fill="none" stroke="{DIM}" stroke-width="1.5"/>
    <text x="846" y="228" font-family="{MONO}" font-size="10.5" fill="{DIM}">CI 검증</text>

    <rect x="736" y="240" width="196" height="58" rx="8" fill="#171B20" stroke="#4B5563"/>
    <text x="834" y="264" text-anchor="middle" font-family="{SANS}" font-size="12.5" fill="#9AA4B2">저장소</text>
    <text x="834" y="283" text-anchor="middle" font-family="{SANS}" font-size="11" fill="{DIM}">clone 만 해도 읽힌다</text>
  </g>
</svg>
'''


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = [("hero.svg", hero())]
    for name, (title, lines) in CARDS.items():
        written.append((f"{name}.svg", terminal(title, lines)))
    for name, svg in written:
        (OUT / name).write_text(svg, encoding="utf-8", newline="\n")
        print(f"[생성] docs/images/{name}")


if __name__ == "__main__":
    main()
