# FreeAgent Ultra

로컬/무료 친화적인 AI 코딩 에이전트 CLI입니다.

## 핵심 기능
- 원클릭 실행기 `START_FREEAGENT.py`
- `inspect`, `scan`, `prompt`, `plan`, `ask`, `apply`, `explain`, `diff`, `rollback`, `sessions`, `doctor`, `bootstrap`
- 멀티파일 자동 탐색
- React/TSX, Python, Node 프로젝트 휴리스틱 분석
- unified diff 생성
- 승인 기반 적용
- 테스트 실패 시 자동 롤백 옵션
- mock / Ollama / MiniMax / OpenAI-compatible provider fallback

## 빠른 시작
```bash
python START_FREEAGENT.py
python START_FREEAGENT.py inspect
python START_FREEAGENT.py prompt "로그인 실패 시 500 대신 401 반환"
python START_FREEAGENT.py ask "관리자 센서 목록 화면을 어떻게 설계할까?"
python START_FREEAGENT.py plan "로그인 실패 시 500 대신 401 반환"
python START_FREEAGENT.py apply "로그인 실패 시 500 대신 401 반환" --yes
```

## 설치형 사용
```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .[dev]
freeagent doctor
freeagent inspect
```

## 자주 쓰는 명령
```bash
freeagent inspect
freeagent scan --goal "버튼 클릭 시 API 호출 추가"
freeagent prompt "버튼 클릭 시 API 호출 추가"
freeagent ask "관리자 센서 목록 화면을 어떻게 설계할까?"
freeagent explain --targets src/App.tsx
freeagent explain --symbol login_user
freeagent plan "React 버튼 추가 후 fetch 호출"
freeagent apply "React 버튼 추가 후 fetch 호출" --yes
freeagent diff
freeagent sessions
freeagent rollback <session_id>
```

## bootstrap
```bash
freeagent bootstrap --yes --model qwen2.5-coder:7b
```

## 환경 변수
`.env.freeagent` 또는 `FREEAGENT_ENV_FILE`로 지정한 파일
```bash
FREEAGENT_PROVIDER=mock
FREEAGENT_MODEL=qwen2.5-coder:7b
OLLAMA_HOST=http://127.0.0.1:11434
OPENAI_BASE_URL=
OPENAI_API_KEY=
FREEAGENT_MINIMAX_MODEL=minimax2.7
MINIMAX_BASE_URL=https://api.minimaxi.chat/v1
MINIMAX_API_KEY=
```

## 현재 범위
- 의미 기반 수정은 휴리스틱 + provider 응답 기반
- 정밀 patch 엔진은 심볼/구간/패턴 기반 최소 수정 우선
- 기본적으로 외부 업로드 금지, 민감 파일 보호

## 테스트
```bash
pytest -q
```
// agent note: updated by FreeAgent Ultra
