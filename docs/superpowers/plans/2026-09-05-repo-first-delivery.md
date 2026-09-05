# 저장소 우선 전달 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** girok 의 훅을 `.method/` 스냅샷에 동결하고 저장소 `.claude/settings.json` 에서 등록해, 플러그인이 깔리지 않은 PC 에서도 이미 도입된 저장소의 훅이 전부 돌게 한다.

**Architecture:** 훅 코드는 그대로 두고 **전달 경로만** 바꾼다. `method_sync.sync()` 가 `hooks/` 를 `.method/hooks/` 로 복사하고, `notes_init.sync_settings()` 가 `.claude/settings.json` 에 훅 다섯을 등록한다. 플러그인의 `hooks/hooks.json` 은 지워 중복 실행을 없앤다. 판본 조회가 플러그인 매니페스트를 읽던 한 곳만 고치면 `session-start` 가 살아난다.

**Tech Stack:** Python 3.10+, 표준 라이브러리만(`shutil`·`os`·`json`·`hashlib`·`pathlib`). pytest. 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-09-05-repo-first-delivery-design.md`

## Global Constraints

- Python `>=3.10` (`pyproject.toml`). `X | None` 표기 사용 가능.
- 새 서드파티 의존성 금지 — 표준 라이브러리만.
- 모든 파일 입출력은 `encoding="utf-8"`, 쓰기는 `newline="\n"`.
- 사용자에게 보이는 문자열은 **한국어**, 코드 주석과 docstring 은 **영어**.
- 테스트 이름은 함수가 아니라 **실패**로 짓는다 (`CONTRIBUTING.md`).
- 테스트를 먼저 쓴다. 실패를 확인한 뒤 구현한다.
- `.claude-plugin/plugin.json` 의 `version` 을 올리고 `CHANGELOG.md` 에 그 절을 쓴다 — 없으면 릴리스 CI 가 실패한다.
- 훅의 **동작 로직은 바꾸지 않는다.** 옮기고, 판본 조회 한 곳만 고친다.
- CI 는 Linux 와 Windows 양쪽에서 돈다. 줄바꿈·인코딩·권한을 양쪽에서 생각한다.

## 목차

- [Task 1: 판본 조회에서 플러그인을 뗀다](#task-1-판본-조회에서-플러그인을-뗀다)
- [Task 2: 스냅샷에 훅을 동결한다](#task-2-스냅샷에-훅을-동결한다)
- [Task 3: 스냅샷 훅이 플러그인 없이 돈다](#task-3-스냅샷-훅이-플러그인-없이-돈다)
- [Task 4: settings.json 훅 등록과 전환](#task-4-settingsjson-훅-등록과-전환)
- [Task 5: 등록 검증을 verify 에 넣는다](#task-5-등록-검증을-verify-에-넣는다)
- [Task 6: 중복 제거와 문언 개편](#task-6-중복-제거와-문언-개편)
- [Task 7: 판본과 문서](#task-7-판본과-문서)
- [실행 후 확인](#실행-후-확인)

---

### Task 1: 판본 조회에서 플러그인을 뗀다

`session-start` 가 플러그인 없이 죽는 유일한 원인이다. `plugin_version()` 이 매니페스트를 읽다 `FileNotFoundError` 를 내고, `session_report.build()` 가 그걸 잡지 않아 세션 시작 보고가 통째로 사라진다.

**Files:**
- Modify: `scripts/method_sync.py` (`Status`, `plugin_version`, `main`)
- Modify: `hooks/session_report.py` (`build` 의 ready 마커와 낡음 경고)
- Test: `tests/test_method_sync.py`, `tests/test_session_report.py`

**Interfaces:**
- Produces: `method_sync.plugin_version(plugin_root) -> str | None`
- Produces: `method_sync.Status(snapshot_version: str | None, plugin_version: str | None)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_method_sync.py`:

```python
def test_status_does_not_die_when_the_plugin_is_not_installed(notes_repo, tmp_path, monkeypatch):
    """플러그인 없는 PC 에서도 스냅샷 훅이 돈다. status 가 매니페스트를 찾다
    죽으면 세션 시작 보고가 통째로 사라진다."""
    method_sync.sync(notes_repo)
    monkeypatch.setattr(method_sync, "PLUGIN_ROOT", tmp_path / "no-plugin-here")

    state = method_sync.status(notes_repo, tmp_path / "no-plugin-here")

    assert state.plugin_version is None
    assert state.snapshot_version is not None
    assert not state.in_sync
```

`tests/test_session_report.py`:

```python
def test_the_ready_marker_survives_a_missing_plugin(notes_repo, tmp_path):
    """마커가 증명하는 것은 '이 저장소에 규칙이 있다' 이지 '이 머신에 플러그인이
    깔렸다' 가 아니다."""
    method_sync.sync(notes_repo)

    report = session_report.build(notes_repo, plugin_root=tmp_path / "no-plugin-here")

    assert report.ready
    assert "[girok] ready v" in report.text
    assert "낡았을 수 있다" not in report.text
```

- [ ] **Step 2: 실패를 확인한다**

`python -m pytest tests/test_method_sync.py::test_status_does_not_die_when_the_plugin_is_not_installed tests/test_session_report.py::test_the_ready_marker_survives_a_missing_plugin -v`
기대: `FileNotFoundError`

- [ ] **Step 3: 구현한다**

`scripts/method_sync.py`:

```python
@dataclass
class Status:
    snapshot_version: str | None
    plugin_version: str | None

    @property
    def in_sync(self) -> bool:
        return (
            self.snapshot_version is not None
            and self.plugin_version is not None
            and self.snapshot_version == self.plugin_version
        )


def plugin_version(plugin_root: Path = PLUGIN_ROOT) -> str | None:
    """The installed plugin's version, or None where it is not installed.

    The snapshot carries the hooks now, so a session runs on machines with
    no plugin at all. Raising here took the whole session-start report down
    with it -- a repository that was fully set up reported nothing.
    """
    manifest = plugin_root / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None
```

`main()` 의 status 분기에서 `state.plugin_version` 이 `None` 인 경우를 먼저 처리한다 — 플러그인이 없으면 낡음을 판정할 수 없으므로 스냅샷 판본만 보고하고 0 을 돌려준다.

`hooks/session_report.py` `build()`:

```python
    report.ready = True
    report.lines.append(f"[girok] ready v{state.snapshot_version}")
    if state.plugin_version is not None and not state.in_sync:
        report.lines.append(...)
```

- [ ] **Step 4: 통과를 확인한다**

`python -m pytest tests/test_method_sync.py tests/test_session_report.py -q`

- [ ] **Step 5: 커밋**

```bash
git add scripts/method_sync.py hooks/session_report.py tests/test_method_sync.py tests/test_session_report.py
git commit -m "fix: 플러그인이 없어도 세션 시작 보고가 선다"
```

---

### Task 2: 스냅샷에 훅을 동결한다

**Files:**
- Modify: `scripts/method_sync.py` (`SNAPSHOT_HOOKS`, `sync`, `_changed_files`)
- Test: `tests/test_method_sync.py`

**Interfaces:**
- Consumes: Task 1 의 `plugin_version() -> str | None`
- Produces: `method_sync.SNAPSHOT_HOOKS: tuple[str, ...]`, `.method/hooks/` 배치

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_sync_writes_the_hooks_too(notes_repo):
    """훅이 플러그인 안에만 있으면 플러그인 없는 PC 에서 규칙이 집행되지 않는다."""
    method_sync.sync(notes_repo)
    hooks = notes_repo / "notes" / ".method" / "hooks"

    for name in ("session-start.py", "pre-tool-use.py", "hook_io.py", "run-hook.cmd"):
        assert (hooks / name).is_file(), name


def test_editing_a_hook_changes_the_snapshot_hash(notes_repo):
    """훅 코드가 해시 밖에 있으면 사람이 고친 훅을 CI 가 못 잡는다."""
    method_sync.sync(notes_repo)
    hook = notes_repo / "notes" / ".method" / "hooks" / "hook_io.py"
    hook.write_text(hook.read_text(encoding="utf-8") + "\n# 한 줄\n", encoding="utf-8")

    result = method_sync.verify(notes_repo)

    assert not result.ok
    assert any("hook_io.py" in problem for problem in result.problems)


def test_verify_fails_when_a_hook_is_deleted(notes_repo):
    method_sync.sync(notes_repo)
    (notes_repo / "notes" / ".method" / "hooks" / "stop.py").unlink()

    assert not method_sync.verify(notes_repo).ok


def test_the_wrapper_is_executable_in_the_snapshot(notes_repo):
    """copyfile 은 권한 비트를 옮기지 않는다. Unix 에서 실행 비트가 없으면
    훅은 등록되어 있는데 조용히 돌지 않는다 — 감독받는 것처럼 보이는 세션."""
    method_sync.sync(notes_repo)
    wrapper = notes_repo / "notes" / ".method" / "hooks" / "run-hook.cmd"

    assert os.access(wrapper, os.X_OK)
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 구현한다**

`SNAPSHOT_HOOKS` 를 정의하고 `sync()` 에 복사 루프를 더한다. `expected` 집합에
`{f"hooks/{n}" for n in SNAPSHOT_HOOKS}` 를 합친다. `run-hook.cmd` 는 복사 후
`os.chmod(..., 0o755)`. `_changed_files()` 에 훅 비교 루프를 더해 어느 훅인지 이름이
나오게 한다.

- [ ] **Step 4: 통과를 확인한다**

`python -m pytest tests/test_method_sync.py -q`

- [ ] **Step 5: 커밋**

```bash
git commit -m "feat: 훅을 .method/ 스냅샷에 동결한다"
```

---

### Task 3: 스냅샷 훅이 플러그인 없이 돈다

Task 2 는 파일이 놓였는지만 본다. 이 태스크는 그 파일이 **실제로 도는지** 를 본다 — Claude Code 가 훅을 부르는 방식 그대로, subprocess 에 JSON payload 를 물린다.

**Files:**
- Modify: `tests/test_hook_entry.py` (`run_hook` 에 훅 디렉터리 인자)
- Test: `tests/test_hook_entry.py`

**Interfaces:**
- Produces: `run_hook(name, payload, hooks_dir=HOOKS, env=None)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
@pytest.mark.parametrize("name", ["session-start", "pre-tool-use", "user-prompt-submit", "post-tool-use", "stop"])
def test_the_snapshot_hooks_run_without_the_plugin(ready_repo, tmp_path, name):
    """플러그인 없는 PC 에서 저장소를 열었을 때 훅이 도는지. 스냅샷 사본을
    실행하고 CLAUDE_PLUGIN_ROOT 는 없는 경로로 둔다."""
    hooks = ready_repo / "notes" / ".method" / "hooks"
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(tmp_path / "no-plugin-here")}

    code, out, err = run_hook(name, PAYLOADS[name](ready_repo), hooks_dir=hooks, env=env)

    assert code == 0
    assert "Traceback" not in err
```

`session-start` 는 여기에 더해 `[girok] ready` 가 나오는지 본다.

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 구현한다** — `run_hook()` 에 `hooks_dir`·`env` 인자를 더한다. 기존 호출부는 기본값으로 그대로 돈다.

- [ ] **Step 4: 통과를 확인한다**

`python -m pytest tests/test_hook_entry.py -q`

- [ ] **Step 5: 커밋**

---

### Task 4: settings.json 훅 등록과 전환

**Files:**
- Modify: `templates/settings.json`
- Modify: `scripts/notes_init.py` (`sync_settings` 신설, `init` 에서 호출)
- Test: `tests/test_notes_init.py`

**Interfaces:**
- Produces: `notes_init.sync_settings(root: Path, notes_prefix: str) -> bool`
- Produces: `notes_init.HOOK_EVENTS` — 이벤트별 (스크립트 이름, matcher, timeout)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_init_registers_the_hooks_in_the_repository(tmp_path):
    """플러그인이 아니라 저장소가 훅을 등록한다 — 그래야 플러그인 없는 PC 에서도
    같은 검사가 돈다."""
    notes_init.init(tmp_path / "repo", ...)
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))

    events = settings["hooks"]
    assert set(events) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
    command = events["SessionStart"][0]["hooks"][0]["command"]
    assert "$CLAUDE_PROJECT_DIR" in command
    assert "notes/.method/hooks/run-hook.cmd" in command


def test_settings_sync_keeps_what_was_already_there(tmp_path):
    """이미 도입한 저장소는 settings.json 이 이미 있다. _write 가 건너뛰던 자리라
    훅 등록을 영영 못 받았다 — 그렇다고 사람이 손으로 넣은 권한을 날리면 안 된다."""
    write(root / ".claude" / "settings.json", json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}))

    changed = notes_init.sync_settings(root, "notes/")

    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert changed
    assert settings["permissions"]["allow"] == ["Bash(ls:*)"]
    assert "SessionStart" in settings["hooks"]


def test_settings_sync_is_idempotent(tmp_path):
    notes_init.sync_settings(root, "notes/")
    assert not notes_init.sync_settings(root, "notes/")


def test_a_flat_repository_registers_hooks_at_its_root(tmp_path):
    """notesDir 이 "." 이면 .method/ 는 루트 바로 아래다. 경로를 notes/ 로 박으면
    평평한 저장소에서 훅이 없는 파일을 가리킨다."""
    notes_init.sync_settings(root, "")
    command = ...
    assert "$CLAUDE_PROJECT_DIR/.method/hooks/run-hook.cmd" in command
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 구현한다**

`templates/settings.json` 에 `hooks` 블록을 넣는다. `notesPrefix` 는 `str.format`
치환이므로 기존 `{{` 이스케이프 관례를 지킨다. `sync_settings()` 는 기존 JSON 을
읽어 `hooks` 키만 갈아끼우고, 나머지 키는 손대지 않는다. `init()` 은 `_write` 대신
이 함수를 부른다.

- [ ] **Step 4: 통과를 확인한다**

- [ ] **Step 5: 커밋**

---

### Task 5: 등록 검증을 verify 에 넣는다

`.claude/settings.json` 은 `.method/` 밖이라 해시가 지키지 못한다. 훅 블록이 지워지면 검사가 조용히 죽는다.

**Files:**
- Modify: `scripts/method_sync.py` (`verify`)
- Test: `tests/test_method_sync.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_verify_fails_when_the_hooks_are_not_registered(notes_repo):
    """훅이 스냅샷에 있어도 등록되지 않았으면 아무것도 돌지 않는다. 세션 안에서는
    ready 마커가 막지만, 그 마커 자체가 훅에서 나온다 — 밖에서 볼 수단이 필요하다."""
    method_sync.sync(notes_repo)
    notes_init.sync_settings(notes_repo, "notes/")
    settings = notes_repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    del data["hooks"]
    settings.write_text(json.dumps(data), encoding="utf-8")

    result = method_sync.verify(notes_repo)

    assert not result.ok
    assert any("settings.json" in problem for problem in result.problems)
```

`verify` 는 `notes_init` 을 import 하지 않는다 — 스냅샷에 `notes_init.py` 가 없어 CI 에서 깨진다. 기대 경로 문자열은 `method_sync` 안에서 만든다.

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 구현한다** — `verify()` 끝에 등록 확인을 더한다. `settings.json` 이 없거나, `hooks` 키가 없거나, 다섯 이벤트 중 빠진 것이 있거나, 명령이 이 저장소의 `.method/hooks/` 를 가리키지 않으면 문제로 보고한다.

- [ ] **Step 4: 통과를 확인한다**

- [ ] **Step 5: 커밋**

---

### Task 6: 중복 제거와 문언 개편

**Files:**
- Delete: `hooks/hooks.json`
- Modify: `templates/CLAUDE.md.pointer` (게이트 2번)
- Modify: `scripts/method_sync.py` (`GATE_BLOCK` 2번)
- Modify: `hooks/run-hook.cmd` 의 git 모드 (`--chmod=+x`)
- Test: `tests/test_method_sync.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_the_gate_does_not_ask_for_a_plugin(notes_repo):
    """훅이 저장소에서 도는 지금, 블록이 없다는 것은 플러그인이 없다는 뜻이 아니다.
    잘못된 진단은 멀쩡한 PC 에서 작업을 멈추게 한다."""
    method_sync.sync(notes_repo)
    head = (notes_repo / "notes" / ".method" / "RULES.md").read_text(encoding="utf-8")[:1500]

    assert "중단" in head
    assert "/notes" in head
    assert "플러그인 설치" not in head
```

- [ ] **Step 2: 실패를 확인한다**

- [ ] **Step 3: 구현한다** — `hooks/hooks.json` 을 지우고, 게이트 2번의 진단을 세 갈래(폴더 신뢰 · Python · 낡은 스냅샷 → `/notes`)로 고친다. `git update-index --chmod=+x hooks/run-hook.cmd`.

- [ ] **Step 4: 전체 테스트**

`python -m pytest -q`

- [ ] **Step 5: 커밋**

---

### Task 7: 판본과 문서

**Files:**
- Modify: `.claude-plugin/plugin.json` (`version` → `0.19.0`)
- Modify: `CHANGELOG.md` (`## 0.19.0` 절)
- Modify: `README.md`
- Modify: `commands/notes.md` (§3 sync 절에 훅 등록 언급)

- [ ] **Step 1: 판본을 올린다** — MINOR. 동작이 늘고 전환 절차가 한 번 필요하다.
- [ ] **Step 2: CHANGELOG 절을 쓴다** — 무엇이 깨져 있었는지까지 적는다: 플러그인 없는 PC 에서 girok 저장소가 작업을 거부했다는 것.
- [ ] **Step 3: README 의 설치 안내를 고친다** — "플러그인 필수" 에서 "도입·갱신에 필요" 로.
- [ ] **Step 4: `/notes` 문서에 전환 절차를 적는다** — 이 판본으로 올린 저장소는 `/notes` 를 한 번 돌려야 훅이 붙는다.
- [ ] **Step 5: 커밋**

---

## 실행 후 확인

문서가 아니라 실행으로 증명한다.

- [ ] `python -m pytest -q` 전부 통과
- [ ] 임시 저장소에 도입 → `CLAUDE_PLUGIN_ROOT` 를 없는 경로로 두고 훅 5 종 실행 → 전부 종료코드 0, `session-start` 가 `[girok] ready` 출력
- [ ] `python .method/scripts/method_sync.py verify` 통과
- [ ] `.claude/settings.json` 에 훅 다섯이 등록되어 있고 경로가 실제 파일을 가리킨다
- [ ] 훅이 **한 번만** 실행된다 — 플러그인에 `hooks.json` 이 없다
