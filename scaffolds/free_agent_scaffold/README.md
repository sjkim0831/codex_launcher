# Free Agent Scaffold

`free agent`의 차세대 구조를 별도 디렉터리에서 실험하기 위한 최소 스캐폴드입니다.

현재 범위:
- CLI 엔트리포인트
- 상태 머신 기반 오케스트레이터
- 기본 planner/context/repo/tool/verify/policy/report 모듈
- 추후 LLM, 승인 플로우, 심볼 인덱싱을 붙이기 쉬운 인터페이스
- UI preset 카탈로그: `configs/ui_presets.json`

실행:

```bash
cd scaffolds/free_agent_scaffold
PYTHONPATH=src python -m free_agent "로그인 실패 시 401 반환"
```

또는:

```bash
cd scaffolds/free_agent_scaffold
PYTHONPATH=src python -m free_agent plan "React 버튼 클릭 시 fetch 호출"
```

UI preset:

```bash
cd scaffolds/free_agent_scaffold
PYTHONPATH=src python -m free_agent "\"Button\"에 secondary 버튼 스타일 preset 적용"
```

필요하면 `FREE_AGENT_UI_PRESETS_PATH=/path/to/ui_presets.json` 으로 preset 카탈로그 경로를 바꿀 수 있습니다.
