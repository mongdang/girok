# 저장소 우선 전달 — 플러그인 없이도 도는 훅 설계

> 상태: 구현 완료 · v0.19.0
> 날짜: 2026-09-05

## 목차

- [배경](#배경)
- [무엇이 이미 되고 무엇이 안 되는가](#무엇이-이미-되고-무엇이-안-되는가)
- [목표와 비목표](#목표와-비목표)
- [전달 계층 재배치](#전달-계층-재배치)
- [1 스냅샷에 훅을 동결한다](#1-스냅샷에-훅을-동결한다)
- [2 판본 조회에서 플러그인을 뗀다](#2-판본-조회에서-플러그인을-뗀다)
- [3 저장소 settings.json 에 등록한다](#3-저장소-settingsjson-에-등록한다)
- [4 이미 도입한 저장소의 전환](#4-이미-도입한-저장소의-전환)
- [5 게이트 문언](#5-게이트-문언)
- [6 등록이 지워지는 경우](#6-등록이-지워지는-경우)
- [남는 한계](#남는-한계)
- [테스트](#테스트)
- [별도 안건](#별도-안건)

## 배경

girok 은 규칙을 두 갈래로 전달한다. 규칙 **전문**은 `.method/RULES.md` 로 저장소에
커밋되고, 규칙의 **집행**은 플러그인의 훅이 한다. 앞쪽은 플러그인 없이도 읽히지만
뒤쪽은 그렇지 않다.

그 결과가 `templates/CLAUDE.md.pointer` 의 게이트 2번이다.

> 이 세션에 `[girok] ready vX.Y.Z` 주입 블록이 있는가? 없으면 플러그인이 로드되지
> 않은 것이다 — **작업을 중단**하고 사용자에게 알린다.

플러그인이 깔리지 않은 PC 에서 girok 저장소를 열면 에이전트가 작업을 거부한다. 이건
실수가 아니라 의도였다 — 감독받는 것처럼 보이는데 실은 아닌 세션이 가장 나쁜 상태라서
그렇다. 하지만 그 대가로 girok 은 "플러그인이 깔린 PC 에서만 쓰는 것" 이 되었다.

이 설계는 집행을 저장소로 내린다. **훅을 스냅샷에 함께 동결하고, 저장소의
`.claude/settings.json` 에서 등록한다.** 플러그인은 훅을 실행하는 주체에서 훅의
원본을 공급하는 주체로 내려간다.

## 무엇이 이미 되고 무엇이 안 되는가

설계 전에 실측했다. 임시 저장소를 만들어 `.method/hooks/` 에 훅을 복사하고
`CLAUDE_PLUGIN_ROOT` 없이 실행한 결과다.

| 훅 | 플러그인 없이 | 확인된 동작 |
|---|---|---|
| `pre-tool-use` | 동작 | 미확정 작업자의 `git push` 를 `deny` |
| `user-prompt-submit` | 동작 | "원점복귀" 감지 → 게이트 OPEN 1건 경고 |
| `post-tool-use` | 동작 | 문서 스탬프 갱신 |
| `stop` | 동작 | 검사기 실행, `## 목차` 누락 지적 |
| `session-start` | **실패** | `.method/.claude-plugin/plugin.json` 없음 |

5 종 중 4 종은 손댈 것이 없다. 훅 진입 스크립트가 `sys.path` 를 `__file__` 기준으로
잡기 때문이다(`hooks/session-start.py:5-6`) — `.method/hooks/` 와 `.method/scripts/`
가 형제로 놓이면 그대로 성립한다.

`session-start` 만 실패한다. 원인은 판본 조회 한 곳이다. `session_report.build()` 가
`method_sync.status()` 를 부르고, 그 안의 `plugin_version()` 이 플러그인 매니페스트를
읽는다(`scripts/method_sync.py:126-128`). 매니페스트 사본을 저장소에 심는 것이 아니라
조회 경로를 고치는 것이 답이다 — `.method/VERSION` 에 이미 판본이 들어 있다.

부수 확인 하나. 손으로 복사한 훅을 두고 `verify` 를 돌리자 해시 불일치를 정확히
잡아냈다. 훅을 정식으로 스냅샷에 넣으면 CI 가 훅 변조까지 지킨다.

## 목표와 비목표

목표는 셋이다.

1. **이미 도입된 저장소를 플러그인 없는 PC 에서 열어도 훅이 전부 돈다.** 차단까지
   포함한다.
2. 플러그인이 있든 없든 **동작이 같다.** 훅이 두 번 돌지 않는다.
3. 훅 코드가 `.method/` 무결성 검사 아래로 들어간다 — 사람이 고치면 CI 가 잡는다.

비목표는 셋이다.

- **도입과 갱신은 플러그인이 한다.** 새 저장소를 girok 화하는 `notes_init` 은
  `templates/` 를, `build_rules()` 는 `skills/` 를 읽는다. 둘 다 스냅샷에 없고, 넣지
  않는다 — 넣으면 규칙 원본이 저장소마다 갈라진다.
- **Python 이 없는 PC 는 범위 밖이다.** 훅은 Python 으로만 돈다. 그 환경에서 남는
  것은 규칙 전문과 CI 뿐이고, 그건 설계가 아니라 사실이다.
- 훅의 **동작 자체는 바꾸지 않는다.** 옮기는 것뿐이다.

## 전달 계층 재배치

| | 지금 | 이후 |
|---|---|---|
| 플러그인 | skills · commands · **hooks + hooks.json** · scripts · templates | skills · commands · hooks(원본) · scripts · templates |
| `.method/` | RULES.md · VERSION · .gitignore · scripts×5 | 〃 + **hooks×12** |
| `.claude/settings.json` | 마켓플레이스 · 플러그인 활성화 · 권한 | 〃 + **hooks 5 종** |

플러그인의 `hooks/hooks.json` 은 지운다. 남겨 두면 저장소 훅과 함께 두 번 돈다 —
Claude Code 는 플러그인 훅과 프로젝트 훅을 별개로 유지하고, 명령 문자열이 다르면
중복 제거가 걸리지 않는다.

## 1 스냅샷에 훅을 동결한다

`method_sync.SNAPSHOT_HOOKS` 에 `hooks/` 의 파일 전부를 올린다 — 진입 스크립트 5 개,
공용 모듈 6 개, 실행 wrapper 1 개.

```
session-start.py  user-prompt-submit.py  pre-tool-use.py  post-tool-use.py  stop.py
hook_io.py  gate_rules.py  session_report.py  session_close.py  doc_followup.py  incoming.py
run-hook.cmd
```

`hooks.json` 은 넣지 않는다. 등록은 `.claude/settings.json` 이 하고, 스냅샷 안의
`hooks.json` 은 아무도 읽지 않는 사본이 된다.

`sync()` 는 `.method/hooks/` 를 만들고 위 파일을 복사한다. `expected` 집합과
`_content_hash()` 대상에 자동으로 들어가므로 `verify` 가 함께 지킨다.
`_changed_files()` 에도 훅 비교를 넣어, 해시가 어긋났을 때 어느 훅인지 이름이 나오게
한다.

> [!IMPORTANT]
> `shutil.copyfile` 은 권한 비트를 옮기지 않는다. `run-hook.cmd` 는 복사 후
> `os.chmod(0o755)` 를 건다. Windows 에서는 무해한 no-op 이고, Linux·macOS 에서는
> 이게 없으면 훅이 실행 권한 없이 놓여 조용히 죽는다.

## 2 판본 조회에서 플러그인을 뗀다

세 곳을 고친다.

| 위치 | 지금 | 이후 |
|---|---|---|
| `method_sync.plugin_version()` | `str` — 매니페스트 없으면 `FileNotFoundError` | `str \| None` — 없으면 `None` |
| `method_sync.Status.in_sync` | 두 값이 같으면 참 | 두 값이 **모두 있고** 같으면 참 |
| `session_report.build()` | `ready v{state.plugin_version}` | `ready v{state.snapshot_version}` |

ready 마커가 스냅샷 판본을 말하게 되는 것은 부수 효과가 아니라 교정이다. 그 마커가
증명하는 것은 "이 저장소에 규칙이 있다" 이지 "이 머신에 플러그인이 깔렸다" 가 아니다.

플러그인이 있을 때의 동작은 그대로다. `in_sync` 가 거짓이면 지금처럼 "스냅샷이
낡았다" 를 알린다. 플러그인이 없으면 `plugin_version` 이 `None` 이라 `in_sync` 도
거짓이 되는데, 그 경우 낡음 경고는 띄우지 않는다 — 비교할 대상이 없는 것과 비교해서
어긋난 것은 다르다.

## 3 저장소 settings.json 에 등록한다

훅 다섯의 등록 블록은 `method_sync` 가 만든다. 명령 문자열은 플러그인 루트 대신
프로젝트 루트를 가리킨다.

```
"${CLAUDE_PROJECT_DIR}/<notesPrefix>.method/hooks/run-hook.cmd" session-start
```

템플릿이 아니라 코드인 이유는 하나다. `templates/settings.json` 은 `str.format` 을
거치므로 JSON 의 중괄호를 전부 이중으로 써야 하고, 훅 블록을 그렇게 쓰면 아무도 읽거나
고칠 수 없는 파일이 된다. `notesPrefix` 는 `notesDir` 에서 계산한다(`"."` 이면 빈
문자열, `"notes"` 면 `"notes/"`). matcher 와 timeout 은 현행 `hooks/hooks.json` 을
그대로 옮긴다.

`.claude/settings.json` 은 커밋되는 파일이다. `.gitignore` 에 없고, `/notes` 안내가
이미 "커밋되어야 팀원이 명령 없이 플러그인을 받는다" 고 말한다. 이제 그 문장에 훅도
함께 걸린다.

## 4 이미 도입한 저장소의 전환

`notes_init._write()` 는 파일이 있으면 건드리지 않는다(`scripts/notes_init.py:58-60`).
이미 girok 을 도입한 저장소는 `.claude/settings.json` 이 이미 있으므로 훅 등록을
영영 받지 못한다. 초기화 경로만으로는 전환이 일어나지 않는다.

그래서 병합 함수를 하나 만든다.

```python
method_sync.sync_settings(root: Path, prefix: str, plugin_root: Path) -> bool
```

기존 JSON 을 읽어 `hooks` 키만 갈아끼우고 나머지 키는 그대로 둔다. 파일이 없으면
템플릿 전체를 쓴다. 바뀐 것이 있으면 참을 돌려준다.

호출 시점은 `sync()` **안**이다. 스냅샷을 쓰는 일과 그 훅을 등록하는 일을 둘로 나누면
훅은 커밋되어 있는데 아무도 등록하지 않은 저장소가 생길 수 있고, 그 상태는 정상과
겉모습이 같다. 한 함수 안에 두면 그 중간 상태 자체가 없다. `/notes` 의 초기화 절과
sync 절이 모두 `sync()` 를 거치므로 양쪽에서 등록이 함께 따라온다.

전환 절차는 이 저장소의 기존 규칙 배포 경로와 같다 — `CONTRIBUTING.md` 가 이미
"판본을 올린다 → push → 각 저장소에서 `/notes`" 로 정해 두었다. 이 판본으로 올린
사용자는 저장소마다 `/notes` 를 한 번 돌려야 훅이 다시 붙는다. 그 전까지는 세션
시작 블록이 뜨지 않고, CLAUDE.md 게이트가 작업을 멈춘다 — 검사가 실제로 돌지 않는
상태이므로 그게 옳은 동작이다.

## 5 게이트 문언

`templates/CLAUDE.md.pointer` 와 `method_sync.GATE_BLOCK` 의 2 번 항목을 고친다.
중단 규칙 자체는 유지한다. 바뀌는 것은 원인 진단이다.

| | 지금 | 이후 |
|---|---|---|
| 블록이 없다 | 플러그인이 로드되지 않았다 → 설치를 요청 | 폴더 신뢰가 승인되지 않았거나 · Python 이 없거나 · 스냅샷이 낡아 훅이 등록되지 않았다 → `/notes` |

플러그인 유무는 더 이상 진단 대상이 아니다. 게이트는 오히려 정확해진다 — 지금은
플러그인 없는 PC 에서 무조건 걸리지만, 이후에는 검사가 실제로 돌지 않을 때만 걸린다.

`templates/AGENTS.md` 와 `templates/GEMINI.md` 는 손대지 않는다. 두 파일은 플러그인을
언급하지 않고 `.method/RULES.md` 만 가리킨다.

## 6 등록이 지워지는 경우

`.claude/settings.json` 은 `.method/` 밖이라 콘텐츠 해시가 지키지 못한다. 누가 훅
블록을 지우면 검사가 조용히 죽는다. 세션 안에서는 ready 마커 게이트가 그대로
최후 방어선이다 — 훅이 죽으면 마커가 없고, 마커가 없으면 작업이 멈춘다.

사후 탐지는 `verify` 가 맡는다. `.claude/settings.json` 에 훅 다섯이 스냅샷 경로를
가리키며 등록되어 있는지 확인하고, 아니면 문제로 보고한다. 대상 저장소의 CI 가 이미
`verify` 를 돌리므로(`ci/github-actions.yml`) 추가 배선은 없다.

## 남는 한계

문서에 적는다. 감추지 않는다.

- **Python 이 없으면 훅은 돌지 않는다.** `run-hook.cmd` 가 그 사실을 stderr 로
  말하고 종료한다. 그 환경에서 남는 것은 규칙 전문(사람이 따르는 것)과 CI(사후
  거부)뿐이다. 강제 차단은 없다.
- **도입과 갱신에는 플러그인이 필요하다.** 저장소를 새로 girok 화하거나 규칙 개정을
  내려받는 일은 `templates/`·`skills/` 를 읽어야 한다.
- **폴더 신뢰 승인이 한 번 필요하다.** 커밋된 프로젝트 훅은 workspace trust 이후에
  실행된다. 폴더 신뢰는 어차피 거치는 절차라 실질 마찰은 없다.
- **`verify` 는 저장소 안의 일관성만 증명한다.** 훅과 `VERSION` 해시를 함께 고치면
  통과한다 — CI 에는 플러그인이 없어 원본과 대조할 수단이 없다. 원본과 같음은 플러그인이
  있는 머신의 `sync` 가 보증하고, 저장소의 코드를 실행할지는 폴더 신뢰 승인이 정한다.
  훅이 스냅샷으로 내려오면서 이 경계가 전보다 중요해졌으므로 README 에도 적었다.
- **`${CLAUDE_PROJECT_DIR}` 치환은 공식 문서 근거로만 확인했다.** 실제 세션에서 등록이
  붙는 것은 이 판본을 올린 뒤 저장소에서 `/notes` 를 돌려 확인해야 한다.

## 테스트

`tests/test_hook_entry.py` 가 이미 훅 5 종을 실제 subprocess 로 돌린다. `run_hook()`
에 훅 디렉터리 인자를 더해 스냅샷 경로에서도 같은 검사를 돌린다.

| 무엇이 깨지면 | 어느 테스트 |
|---|---|
| 훅이 스냅샷에 안 들어간다 | `test_sync_writes_the_hooks_too` |
| 훅을 고쳤는데 해시가 그대로다 | `test_editing_a_hook_changes_the_snapshot_hash` |
| 훅이 지워졌는데 verify 가 통과한다 | `test_verify_fails_when_a_hook_is_deleted` |
| 플러그인 없이 세션 시작이 죽는다 | `test_the_ready_marker_survives_a_missing_plugin` |
| 스냅샷 훅이 플러그인 없이 안 돈다 | `test_the_snapshot_hooks_run_without_the_plugin` |
| 훅 등록이 기존 설정을 날린다 | `test_settings_sync_keeps_what_was_already_there` |
| 등록이 지워졌는데 verify 가 통과한다 | `test_verify_fails_when_the_hooks_are_not_registered` |
| 등록이 엉뚱한 경로를 가리킨다 | `test_verify_fails_when_a_registration_points_somewhere_else` |
| 저장소가 자기 훅을 더 넣었다고 실패한다 | `test_a_repository_may_register_hooks_of_its_own` |
| wrapper 가 실행 권한 없이 커밋된다 | `test_the_wrapper_is_committed_executable` |

## 별도 안건

`hooks/run-hook.cmd` 의 git 모드가 `100644` 다 — 실행 비트가 없다. Linux·macOS 에서
플러그인을 설치하면 훅이 실행되지 않을 수 있다. `.gitattributes` 의 `*.cmd text eol=lf`
로 줄바꿈은 이미 잡혀 있으나 권한은 별개다.

스냅샷 사본은 위 `chmod` 로 해결되지만 플러그인 원본은 그렇지 않다. 같은 판본에서
`git update-index --chmod=+x` 로 함께 고친다.
