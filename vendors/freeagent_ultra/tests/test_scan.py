from pathlib import Path
from freeagent.utils.project_scan import choose_files, detect_stack

def test_detect_stack_react_python(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text("import React from 'react'\nexport default function App(){return <div/>}\n", encoding="utf-8")
    (tmp_path / "api.py").write_text("from fastapi import FastAPI\napp=FastAPI()\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert "react" in detect_stack(".")
    assert "python" in detect_stack(".")

def test_choose_files_scores_targets(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Login.tsx").write_text("export default function Login(){return <button/>}\n", encoding="utf-8")
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "auth.py").write_text("def login_user():\n    raise Exception('bad')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cands = choose_files("login 401 instead of 500")
    assert cands
    assert cands[0].path.endswith(("auth.py", "Login.tsx"))
