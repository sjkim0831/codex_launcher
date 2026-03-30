from __future__ import annotations
import os, platform, shutil, subprocess, time
from pathlib import Path
import requests

ENV_FILE = Path(".env.freeagent")

def ensure_env_file(model: str = "qwen2.5-coder:7b") -> None:
    if ENV_FILE.exists():
        return
    ENV_FILE.write_text(
        f"FREEAGENT_PROVIDER=ollama\nFREEAGENT_MODEL={model}\nOLLAMA_HOST=http://127.0.0.1:11434\nOLLAMA_TIMEOUT_SEC=90\nOPENAI_BASE_URL=\nOPENAI_API_KEY=\n",
        encoding="utf-8",
    )

def load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

def ollama_running(host: str = "http://127.0.0.1:11434") -> bool:
    try:
        return requests.get(f"{host}/api/version", timeout=2).ok
    except Exception:
        return False

def start_ollama() -> bool:
    if shutil.which("ollama") is None:
        return False
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        return True
    except Exception:
        return False

def install_ollama_attempt() -> bool:
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.call(["powershell", "-ExecutionPolicy", "Bypass", "-Command", "irm https://ollama.com/install.ps1 | iex"])
            return True
        if system in ("Linux", "Darwin"):
            subprocess.call(["bash", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"])
            return True
    except Exception:
        return False
    return False

def ensure_model(model: str, host: str = "http://127.0.0.1:11434") -> bool:
    try:
        tags = requests.get(f"{host}/api/tags", timeout=5)
        if tags.ok and any(m.get("name") == model for m in tags.json().get("models", [])):
            return True
        pull = requests.post(f"{host}/api/pull", json={"name": model}, timeout=180)
        return pull.ok
    except Exception:
        return False

def bootstrap_all(model: str = "qwen2.5-coder:7b", yes: bool = False) -> dict:
    ensure_env_file(model)
    load_env_file()
    status = {"env": True, "ollama_installed": shutil.which("ollama") is not None}
    if not status["ollama_installed"] and yes:
        status["install_attempted"] = install_ollama_attempt()
        status["ollama_installed"] = shutil.which("ollama") is not None
    status["ollama_running"] = ollama_running()
    if not status["ollama_running"] and status["ollama_installed"]:
        start_ollama()
        status["ollama_running"] = ollama_running()
    status["model_ready"] = ensure_model(model) if status["ollama_running"] else False
    return status
