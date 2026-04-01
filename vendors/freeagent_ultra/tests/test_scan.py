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


def test_choose_files_ignores_generated_outputs(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login_user():\n    raise Exception('bad')\n", encoding="utf-8")
    (tmp_path / "target" / "classes").mkdir(parents=True)
    (tmp_path / "target" / "classes" / "auth.py").write_text("generated copy\n", encoding="utf-8")
    (tmp_path / "BOOT-INF" / "classes" / "static").mkdir(parents=True)
    (tmp_path / "BOOT-INF" / "classes" / "static" / "bundle.js").write_text("generated bundle\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cands = choose_files("login 401 instead of 500")
    assert cands
    paths = {Path(c.path).as_posix() for c in cands}
    assert "src/auth.py" in paths
    assert "target/classes/auth.py" not in paths
    assert "BOOT-INF/classes/static/bundle.js" not in paths


def test_choose_files_ignores_hashed_frontend_assets(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login_user():\n    raise Exception('bad')\n", encoding="utf-8")
    hashed = tmp_path / "src" / "main" / "resources" / "static" / "react-app" / "assets"
    hashed.mkdir(parents=True)
    (hashed / "HelpManagementMigrationPage-Dl_S2KJi.js").write_text("children:[e.jsxs('article')]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cands = choose_files("로그인 실패 시 500 대신 401 반환")
    paths = {Path(c.path).as_posix() for c in cands}
    assert "src/auth.py" in paths
    assert "src/main/resources/static/react-app/assets/HelpManagementMigrationPage-Dl_S2KJi.js" not in paths


def test_choose_files_ignores_generic_question_requests(tmp_path, monkeypatch):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "AdminPermissionMigrationPage.tsx").write_text("사용 가능 여부\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cands = choose_files("이거 지금 사용 가능해?")
    assert cands == []
