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
- 버튼 기반 quick action
- 자유 Codex prompt 입력
- 자유 shell command 입력
- Codex 로그인 슬롯 저장/선택
- `codex exec` 결과와 원본 로그를 같은 화면에서 확인
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

## 설치 반영

저장소 소스를 `/opt/util/codex`로 복사하면 된다.
