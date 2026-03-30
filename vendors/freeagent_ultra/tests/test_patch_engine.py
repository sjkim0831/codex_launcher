from freeagent.patch_engine import patch_file

def test_patch_python_auth_status():
    src = "from fastapi import APIRouter\n\ndef login_user():\n    raise Exception('bad')\n"
    out = patch_file("auth.py", src, "login failure should return 401 not 500")
    assert "HTTPException" in out or "401" in out

def test_patch_react_button():
    src = "import React from 'react'\nexport default function App(){\n  return (\n    <div>Hello</div>\n  )\n}\n"
    out = patch_file("src/App.tsx", src, "react button add fetch toast")
    assert "handleAgentClick" in out
    assert "Run Agent" in out
