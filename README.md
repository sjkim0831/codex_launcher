# Carbonet Codex Launcher

`/opt/util/codex`에 설치해서 쓰는 프로젝트 공용 Codex 실행 콘솔 소스다.

구성:

- `bin/carbonet-codex`: 실행 진입점
- `app/server.py`: 표준 라이브러리 기반 로컬 HTTP 서버
- `config/workspaces.json`: 워크스페이스 선택 목록
- `config/actions.json`: 버튼 액션 정의
- `config/model-routing.json`: 난이도별 로컬 모델 / Codex 라우팅 정책
- `config/project-runtime.json`: 프로젝트별 start/stop/restart/verify 제어 정책
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
- 계정별 재사용 가능 시각/수동 상태 관리
- Quick Action별 계정 슬롯/토큰 프리셋 자동 연결
- 로컬 모델 자동 라우팅과 단일 로컬 모델 메모리 안전 모드
- 프로젝트별 runtime start/stop/restart/verify API
- 런처 밖 `codex` 실행 결과를 계정 메타데이터에 반영하는 래퍼 제공
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
- 계정별 상태/만료/메모 같은 운영 메타데이터는 각 `data/accounts/<slot>/metadata.json`에 저장된다.
- `.env.freeagent`: launcher 전용 FreeAgent runtime 설정 파일 (`.gitignore` 대상)

재시작 동작:

- 새 job은 `data/jobs/*.json`에서 복원된다.
- sidecar가 없는 예전 job은 `job-history.jsonl`에서 fallback 복원된다.
- 세션 정보가 없는 예전 job은 `Legacy History` 세션으로 묶인다.

## 확장 방식

1. 워크스페이스 추가: `config/workspaces.json`
2. 버튼 추가: `config/actions.json`
3. 모델 라우팅 기본값 변경: `config/model-routing.json`
4. 프로젝트 runtime 제어 등록: `config/project-runtime.json`
5. 복잡한 버튼 로직 추가: `scripts/*.sh`를 만들고 action에서 `script`로 연결
6. 로그인 슬롯 저장: UI 좌측 `Accounts`에서 현재 로그인 상태를 라벨과 함께 저장

## 모델 라우팅

- Composer에서 `자동 모델 라우팅`, `단일 로컬 모델 메모리 안전 모드`, `어려운 작업 Codex 승급`을 켜고 끌 수 있다.
- 기본 정책은 `config/model-routing.json`에서 관리한다.
- 현재 기본 매핑은 대략:
  - `question -> 1.5B`
  - `summary/lite -> 3B`
  - `migration/implementation/balanced -> 7B`
  - `review/debug/full -> Codex`
- 단일 로컬 모델 메모리 안전 모드는 새 로컬 모델 실행 전 `ollama stop <previous-model>`을 시도한다.
- `병렬 로컬 워커`는 기본 활성화되어 있고, `question/summary/lite` 같은 단순 preset은 Codex 선택 상태에서도 설치된 로컬 모델로 우선 분할 실행한다.
- 병렬 scout 대상 모델은 `config/model-routing.json`의 `scoutModels`에서 preset별로 관리한다.
- 실행 전 모델 준비 상태를 검사하고, 준비되지 않은 모델은 병렬 대상에서 제외한다.

## Codex 계정 Failover

- Codex 실행 중 `429`, `Quota exceeded`, `Rate limit reached`, 인증 만료가 감지되면 다른 reusable 계정으로 자동 전환을 시도한다.
- 전환 후보는 단순 슬롯 변경이 아니라 `activate -> loginReady 확인`까지 통과한 슬롯만 사용한다.
- 활성화는 됐지만 로그인 준비가 안 된 슬롯은 `unauthorized` 상태로 기록하고 다음 후보를 계속 찾는다.
- 계정 API/metadata에서 재사용 가능 시각을 못 가져온 `quota_wait` 슬롯은 영구 skip하지 않는다. 수동 차단이나 미래 `nextAvailableAt`이 있는 경우만 하드 skip하고, 그 외에는 `activate -> loginReady` probe 결과로 사용 가능 여부를 판단한다.
- 병렬 계정 실행은 `config/model-routing.json`의 `parallelAccountMax`와 `parallelAccountPresetLimits`에 따라 난이도별 계정 수를 자동 할당한다. 기본 최대치는 14개이고 `full=14`, `review/debug=10`, `implementation/balanced=6`, 단순 preset은 로컬 병렬 우선이다.
- 병렬 Codex 최종 실행에서 `quota/auth` 실패가 감지되면 같은 최종 요청을 preflight에서 확보한 다음 ready 계정으로 재시도한다.
- 실행 Output 패널에는 failover history, 후보 probe 결과, 로컬 모델 inspection 결과가 함께 표시된다.
- 병렬 로컬 모델 실행의 final synthesizer는 UI에서 선택한다. 선택지는 `off`, 준비된 첫 로컬 모델, `7B` 로컬 모델, `Codex`이며 `7B`가 없으면 작업 전체를 실패시키지 않고 합성 단계만 건너뛴다.

## 프로젝트 Runtime Control

- Project 탭에서 선택한 프로젝트에 대해 `Status`, `Runtime Start`, `Runtime Stop`, `Runtime Restart`, `Runtime Verify`를 실행할 수 있다.
- 각 프로젝트의 실제 스크립트와 health URL은 `config/project-runtime.json`에서 정의한다.
- 여러 프로젝트의 공통 jar, project adapter, app module, 백업, 트래픽 명령은 `config/project-assemblies.json`에서 관리한다.
- 프로젝트 코드는 공통 소스를 복사하지 않고 `commonAdapter`와 `adapterType`으로 연결되는 얇은 adapter 구조를 기본으로 한다.
- Project 탭의 `Build Common Jars`, `Install Common Jars`, `Build Project App`, `Build Common + Project`, `Traffic Status`, `Traffic Tail`은 assembly profile의 명령을 실행한다.
- 기본 Carbonet 로컬 프로필은 다음 스크립트를 사용한다:
  - `bash ops/scripts/start-18000.sh`
  - `bash ops/scripts/stop-18000.sh`
  - `bash ops/scripts/restart-18000.sh`
  - `bash ops/scripts/codex-verify-18000-freshness.sh`

## 계정 슬롯

- Codex CLI는 기본적으로 다중 로그인 프로필 전환 UI를 제공하지 않으므로 이 런처가 `~/.codex/auth.json` 스냅샷을 슬롯으로 관리한다.
- `Save Current`는 현재 로그인 상태를 `data/accounts/<slot>`에 저장한다.
- 저장된 슬롯을 클릭하면 해당 슬롯의 `auth.json`이 현재 Codex 홈에 활성화된다.
- `Accounts` 패널에서 `manualStatus`, `nextAvailableAt`, `paidPlanExpiresAt`, 메모를 직접 저장할 수 있다.
- 예전 `config/account-overrides.json`가 있으면 시작 시 해당 값들을 각 계정 `metadata.json`으로 한 번 흡수한다.
- 쿼터/만료 메시지에 재시도 가능 시각이 들어 있으면 launcher가 `suggestedNextAvailableAt`로 추정해서 편집기에 보여준다.
- 추정값이 없더라도 `auth token exp`를 참고값으로 재사용 가능 시각 입력칸에 복사할 수 있다.
- 주기 스캔은 기본적으로 로그인 가능/만료 여부만 갱신하며 `nextAvailableAt`을 임의로 계산해서 덮어쓰지 않는다.
- 필요하면 `CARBONET_CODEX_HOME`으로 별도 Codex 홈을 지정해 테스트할 수 있다.

## 액션별 라우팅

- 각 Quick Action은 `preferredAccountId`, `preferredAccountType`, `runtimePreset`을 가질 수 있다.
- 필요하면 `preferredAccountIds` 체인으로 `main -> sub1 -> sub2` 순서를 고정할 수 있다.
- 이 값은 UI의 `작업 자동 연결` 패널에서 저장되며 `config/actions.json`에도 반영된다.
- `runtimePreset`이 비어 있으면 서버가 최근 작업 패턴에 맞춰 자동 선택한다. 현재 기본 분류는 `question`, `summary`, `migration`, `implementation`, `review`, `debug`, `saver`, `lite`, `balanced`, `full`이다.
- `runtimePreset`이 지정되면 해당 액션은 `Preview`와 실제 실행 모두에서 같은 토큰 절약 프리셋을 사용한다.
- 계정 슬롯이 지정되면 재사용 가능한 경우 우선 사용하고, 사용할 수 없으면 타입 우선순위와 상태를 기준으로 자동 fallback 한다.

## 외부 Codex 감시

- WSL/터미널에서 `bin/carbonet-codex-watch`로 `codex`를 실행하면 `429`, `Quota exceeded`, `Rate limit reached`, `expired`, `unauthorized` 문구를 읽어 현재 활성 계정 슬롯 메타데이터를 갱신한다.
- Windows CMD에서는 `bin\carbonet-codex-watch.cmd`를 같은 용도로 사용할 수 있다.
- 단순 주기 점검은 WSL에서 `scripts/account-scan.sh`, Windows CMD에서 `scripts\account-scan.cmd`로 실행할 수 있고 이 스캔은 AI 토큰을 소비하지 않는다.
- 백그라운드 주기 스캔은 WSL에서 `scripts/account-scan-loop.sh`를 사용하면 된다.

예시:

```bash
/opt/util/codex/bin/carbonet-codex-watch exec "짧게 상태 점검해줘"
/opt/util/codex/scripts/account-scan.sh default
CARBONET_ACCOUNT_SCAN_INTERVAL_SEC=1800 /opt/util/codex/scripts/account-scan-loop.sh default
```

## 자동 등록

WSL systemd user timer:

```bash
/opt/util/codex/scripts/install-account-scan-timer.sh default
systemctl --user list-timers carbonet-account-scan.timer
```

제거:

```bash
/opt/util/codex/scripts/uninstall-account-scan-timer.sh
```

Windows 작업 스케줄러:

```cmd
\opt\util\codex\scripts\install-account-scan-task.cmd default
schtasks /Query /TN "CarbonetCodexAccountScan"
```

제거:

```cmd
\opt\util\codex\scripts\uninstall-account-scan-task.cmd
```

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
- `Composer`: `AI CLI = FreeAgent` 선택 시 `prompt / plan / explain / graph / apply` 모드와 `targets / test command` 입력 지원

세션 패널의 `Plan Status`, `Session Tree`, `Branch Navigation`, `Compare`는 각각 접고 펼칠 수 있다.

## 설치 반영

저장소 소스를 `/opt/util/codex`로 복사하면 된다.
