from typer.testing import CliRunner

from freeagent.cli import app


runner = CliRunner()


def test_prompt_command_exists_and_renders_answer(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login_user():\n    raise Exception('bad')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["prompt", "login should return 401 instead of 500"])
    assert result.exit_code == 0
    assert "PROMPT" in result.stdout
    assert '"answer":' in result.stdout
    assert '"provider":' in result.stdout


def test_prompt_low_signal_request_still_returns_answer_shape(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["prompt", "됨?"])
    assert result.exit_code == 0
    assert '"answer":' in result.stdout
    assert '"provider":' in result.stdout


def test_ask_command_exists_and_renders_answer(tmp_path, monkeypatch):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "SensorListPage.tsx").write_text(
        "export default function SensorListPage(){return <div>sensor</div>}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["ask", "센서 목록 화면을 설계해줘"])
    assert result.exit_code == 0
    assert "ASK" in result.stdout
    assert '"answer":' in result.stdout
# agent note: updated by FreeAgent Ultra
