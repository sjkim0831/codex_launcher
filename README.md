# Carbonet Codex Launcher

`/opt/util/codex`에 설치해서 쓰는 프로젝트 공용 Codex 실행 콘솔 소스다.

구성:

- `bin/carbonet-codex`: 실행 진입점
- `app/server.py`: 표준 라이브러리 기반 로컬 HTTP 서버
- `config/workspaces.json`: 워크스페이스 선택 목록
- `config/actions.json`: 버튼 액션 정의
- `static/`: 브라우저 UI
- `data/`: 런타임 job/history 저장소

핵심 기능:

- Carbonet 기준 자주 쓰는 workspace 선택
- 세션 기반 작업 연속성 유지
- 세션 브랜치 생성 및 부모/형제 브랜치 탐색
- 세션 notes / plan / active step 관리
- 세션 compare, tree, family 뷰
- 버튼 기반 quick action
- 자유 Codex prompt 입력
- 자유 shell command 입력
- Codex 로그인 슬롯 저장/선택
- `codex exec` 결과와 원본 로그를 같은 화면에서 확인
- job 결과를 세션 요약과 plan 상태에 자동 반영
- 재시작 후 job/session 복원
- `job-history.jsonl` 기반 Legacy History fallback 복원
- JSON/스크립트 기반 확장

## 실행

```bash
/opt/util/codex/bin/carbonet-codex
```

기본 주소:

```text
http://localhost:43110
```

환경 변수:

- `CARBONET_CODEX_HOST`
- `CARBONET_CODEX_PORT`
- `CARBONET_CODEX_BIN`

## 세션 모델

- 모든 AI/shell 실행은 현재 선택된 session에 귀속된다.
- session은 `data/sessions/<sessionId>/session.json`에 저장된다.
- session에는 `notes`, `plan`, `recentJobs`, `summary`, `parentSessionId`가 포함된다.
- `Branch Current`를 누르면 현재 session의 notes/plan/recentJobs를 복사한 브랜치 session이 생성된다.
- session compare는 부모 session 대비 notes diff, changed steps, new jobs를 보여준다.
- session family는 부모/형제 브랜치를 빠르게 전환하는 용도다.

## 작업 연속성

- Codex / FreeAgent 실행 시 launcher가 현재 session context를 프롬프트 앞에 자동 주입한다.
- session plan은 `status | step` 형식으로 저장한다.
- `Active Step`을 지정하면 실행 job이 특정 plan step과 연결된다.
- 성공한 job은 기본적으로 plan을 자동 진행시키고, 실패한 job은 notes에 실패 흔적을 남긴다.
- compare에서 changed step을 클릭하면 해당 step이 `Active Step`으로 맞춰지고 관련 job 상세를 바로 열 수 있다.

## 런타임 저장소

- `data/jobs/<jobId>.json`: 최신 job 스냅샷
- `data/jobs/<jobId>-final.txt`: 최종 응답/출력 텍스트
- `data/job-history.jsonl`: 레거시 포함 전체 실행 이력
- `data/current-session.txt`: 현재 활성 session id
- `data/accounts/<slot>`: Codex 로그인 슬롯
- `.env.freeagent`: launcher 전용 FreeAgent runtime 설정 파일 (`.gitignore` 대상)

재시작 동작:

- 새 job은 `data/jobs/*.json`에서 복원된다.
- sidecar가 없는 예전 job은 `job-history.jsonl`에서 fallback 복원된다.
- 세션 정보가 없는 예전 job은 `Legacy History` 세션으로 묶인다.

## 확장 방식

1. 워크스페이스 추가: `config/workspaces.json`
2. 버튼 추가: `config/actions.json`
3. 복잡한 버튼 로직 추가: `scripts/*.sh`를 만들고 action에서 `script`로 연결
4. 로그인 슬롯 저장: UI 좌측 `Accounts`에서 현재 로그인 상태를 라벨과 함께 저장

## 계정 슬롯

- Codex CLI는 기본적으로 다중 로그인 프로필 전환 UI를 제공하지 않으므로 이 런처가 `~/.codex/auth.json` 스냅샷을 슬롯으로 관리한다.
- `Save Current`는 현재 로그인 상태를 `data/accounts/<slot>`에 저장한다.
- 저장된 슬롯을 클릭하면 해당 슬롯의 `auth.json`이 현재 Codex 홈에 활성화된다.
- 필요하면 `CARBONET_CODEX_HOME`으로 별도 Codex 홈을 지정해 테스트할 수 있다.

## 액션 종류

- `shell`: 일반 명령 실행
- `codex`: `codex exec`로 프롬프트 실행

## UI 요약

- `Sessions`: 생성, 브랜치, notes/plan 저장, active step 선택
- `Plan Status`: 현재 session plan 상태
- `Session Tree`: 부모-브랜치 구조와 진행도 요약
- `Branch Navigation`: 부모/형제 브랜치 빠른 이동
- `Compare`: 부모 session 대비 notes diff / changed steps / new jobs
- `Jobs`: 현재 session 기준 실행 이력
- `FreeAgent`: `Setup FreeAgent`, `Start Agent`, `Pull Model` 버튼으로 런타임 준비와 모델 다운로드 수행
- `Composer`: `AI CLI = FreeAgent` 선택 시 `prompt / plan / explain / apply` 모드와 `targets / test command` 입력 지원

세션 패널의 `Plan Status`, `Session Tree`, `Branch Navigation`, `Compare`는 각각 접고 펼칠 수 있다.

## 설치 반영

저장소 소스를 `/opt/util/codex`로 복사하면 된다.
