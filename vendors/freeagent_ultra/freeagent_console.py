from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_WORKSPACE = Path("/opt/projects/carbonet")
DEFAULT_APP_PORT = os.getenv("FREEAGENT_APP_PORT", "18080")
APP_HOST_TOKEN = f"localhost:{DEFAULT_APP_PORT}"

PASS_THROUGH_COMMANDS = {
    "bootstrap",
    "inspect",
    "scan",
    "plan",
    "apply",
    "explain",
    "diff",
    "status",
    "rollback",
    "sessions",
    "doctor",
    "run",
}


def is_restart_request(text: str) -> bool:
    low = text.lower()
    restart_words = (
        "restart",
        "reboot",
        "redeploy",
        "reload",
        "project restart",
        "\uc7ac\uc2dc\uc791",  # 재시작
        "\ub2e4\uc2dc \uc2dc\uc791",  # 다시 시작
        "\ud504\ub85c\uc81d\ud2b8 \uc7ac\uc2dc\uc791",  # 프로젝트 재시작
    )
    return any(word in low for word in restart_words)


def is_build_request(text: str) -> bool:
    low = text.lower()
    words = ("build", "compile", "컴파일", "빌드")
    return any(word in low for word in words)


def is_model_question(text: str) -> bool:
    low = text.lower()
    return "모델" in text or ("model" in low and "?" in text)


def is_capability_question(text: str) -> bool:
    return "가능" in text and any(k in text for k in ("수정", "실행", "적용", "빌드", "재시작"))


def has_localhost_port(text: str) -> bool:
    return re.search(r"localhost:\d+", text.lower()) is not None


def _wsl_unc_candidates(unix_like: str) -> list[Path]:
    # Map /opt/projects/carbonet -> \\wsl$\Ubuntu\opt\projects\carbonet
    suffix = unix_like.lstrip("/").replace("/", "\\")
    distros = ["Ubuntu", "Ubuntu-22.04", "Ubuntu-24.04"]
    return [Path(f"\\\\wsl$\\{d}\\{suffix}") for d in distros]


def resolve_workspace_path(raw_path: str) -> Path:
    p = Path(raw_path).expanduser()
    if p.exists():
        return p
    if sys.platform.startswith("win") and raw_path.startswith("/"):
        for cand in _wsl_unc_candidates(raw_path):
            if cand.exists():
                return cand
    return p


def switch_to_default_workspace_if_possible(current_ws: Path) -> Path:
    target = resolve_workspace_path(str(DEFAULT_WORKSPACE))
    if target.exists():
        print(f"[OK] workspace changed to: {target}")
        return target
    print(f"[WARN] default workspace not found, keep current: {current_ws}")
    return current_ws


def resolve_workspace(workspace_arg: str | None) -> Path:
    if workspace_arg:
        return resolve_workspace_path(workspace_arg)
    default_ws = resolve_workspace_path(str(DEFAULT_WORKSPACE))
    if default_ws.exists():
        return default_ws
    return Path.cwd()


def run_cli(py_exe: str, workspace: Path, args: list[str]) -> int:
    cmd = [py_exe, "-m", "freeagent.cli", *args]
    proc = subprocess.run(cmd, cwd=str(workspace))
    return proc.returncode


def run_shell(command: list[str], workspace: Path) -> int:
    print(f"[RUN] {' '.join(command)}")
    proc = subprocess.run(command, cwd=str(workspace))
    return proc.returncode


def detect_package_manager(workspace: Path) -> str:
    if (workspace / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (workspace / "yarn.lock").exists():
        return "yarn"
    return "npm"


def load_package_scripts(workspace: Path) -> dict[str, str]:
    package_json = workspace / "package.json"
    if not package_json.exists():
        return {}
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return {}
    scripts = data.get("scripts", {})
    return scripts if isinstance(scripts, dict) else {}


def compile_and_restart(workspace: Path) -> int:
    scripts = load_package_scripts(workspace)
    pm = detect_package_manager(workspace)
    ok = True

    if (workspace / "package.json").exists():
        ok = run_shell([pm, "install"], workspace) == 0 and ok
        if "build" in scripts:
            ok = run_shell([pm, "run", "build"], workspace) == 0 and ok
    else:
        print("[INFO] package.json not found, skipping install/build.")

    docker_file = (workspace / "docker-compose.yml").exists() or (workspace / "docker-compose.yaml").exists()
    if docker_file and shutil.which("docker"):
        ok = run_shell(["docker", "compose", "up", "-d", "--build"], workspace) == 0 and ok
        return 0 if ok else 1

    if "restart" in scripts:
        ok = run_shell([pm, "run", "restart"], workspace) == 0 and ok
        return 0 if ok else 1

    if "stop" in scripts and "start" in scripts:
        ok = run_shell([pm, "run", "stop"], workspace) == 0 and ok
        ok = run_shell([pm, "run", "start"], workspace) == 0 and ok
        return 0 if ok else 1

    if "start" in scripts:
        print("[INFO] start script found. Launching in background.")
        if sys.platform.startswith("win"):
            subprocess.Popen(
                ["cmd.exe", "/c", f"cd /d {workspace} && {pm} run start"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            subprocess.Popen([pm, "run", "start"], cwd=str(workspace))
        return 0 if ok else 1

    print("[WARN] no restart/start path found. install/build only applied.")
    return 0 if ok else 1


def install_and_build_only(workspace: Path) -> int:
    scripts = load_package_scripts(workspace)
    pm = detect_package_manager(workspace)
    ok = True
    if (workspace / "package.json").exists():
        ok = run_shell([pm, "install"], workspace) == 0 and ok
        if "build" in scripts:
            ok = run_shell([pm, "run", "build"], workspace) == 0 and ok
            return 0 if ok else 1
        print("[WARN] build script not found. install only applied.")
        return 0 if ok else 1
    print("[INFO] package.json not found, skipping install/build.")
    return 1


def print_model_info(workspace: Path) -> None:
    env_file = workspace / ".env.freeagent"
    provider = "mock"
    model = "qwen2.5-coder:7b"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("FREEAGENT_PROVIDER="):
                provider = line.split("=", 1)[1].strip() or provider
            if line.startswith("FREEAGENT_MODEL="):
                model = line.split("=", 1)[1].strip() or model
    print(f"[INFO] provider={provider}, model={model}")
    print("[INFO] plan/scan은 휴리스틱 기반, apply/explain 단계에서 모델 응답을 사용합니다.")


def handle_natural_ops(raw: str, current_ws: Path) -> tuple[bool, Path]:
    if is_model_question(raw):
        print_model_info(current_ws)
        return True, current_ws
    if is_restart_request(raw):
        current_ws = switch_to_default_workspace_if_possible(current_ws)
        code = compile_and_restart(current_ws)
        if code == 0:
            print("[OK] restart workflow completed.")
        else:
            print("[ERROR] restart workflow failed.")
        return True, current_ws
    if is_build_request(raw):
        code = install_and_build_only(current_ws)
        if code == 0:
            print("[OK] build workflow completed.")
        else:
            print("[ERROR] build workflow failed.")
        return True, current_ws
    if is_capability_question(raw):
        print("[INFO] 가능합니다. '수정해줘 ...'는 apply로, '재시작해줘'는 wsapp+opsapp으로 처리됩니다.")
        return True, current_ws
    return False, current_ws


def maybe_apply_ui_goal(raw: str) -> list[str] | None:
    low = raw.lower()
    if (APP_HOST_TOKEN in low or has_localhost_port(low)) and any(k in low for k in ("개선", "편의", "ui", "ux", "화면")):
        return ["apply", raw, "--yes"]
    return None


def maybe_apply_general_goal(raw: str) -> list[str] | None:
    low = raw.lower()
    # Plain questions should not auto-apply unless they explicitly ask to do it.
    explicit_do_it = any(k in raw for k in ("해줘", "해주세요", "해 주", "바꿔줘", "고쳐줘", "수정해", "적용해", "만들어줘"))
    if "?" in raw and not explicit_do_it:
        return None
    apply_words = (
        "fix",
        "update",
        "change",
        "implement",
        "add",
        "remove",
        "refactor",
        "improve",
        "수정",
        "수정해",
        "고쳐",
        "고쳐줘",
        "변경",
        "바꿔",
        "바꿔줘",
        "추가",
        "추가해",
        "추가해줘",
        "삭제",
        "제거",
        "제거해",
        "제거해줘",
        "개선",
        "리팩토링",
        "만들어",
        "만들어줘",
        "적용",
        "적용해",
        "패치",
    )
    command_tone = any(raw.strip().endswith(s) for s in ("해", "해줘", "해주세요", "바꿔", "고쳐", "추가해", "삭제해", "제거해"))
    if (any(word in low for word in apply_words) or command_tone) and len(raw.strip()) >= 4:
        return ["apply", raw, "--yes"]
    return None


def is_probable_web_workspace(workspace: Path) -> bool:
    if (workspace / "package.json").exists():
        return True
    if (workspace / "src").exists() or (workspace / "app").exists():
        return True
    return False


def normalize_to_cli_args(raw: str, workspace: Path) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    parts = shlex.split(text, posix=False)
    if not parts:
        return []
    if parts[0].lower() == "help":
        return ["_help"]

    auto_apply = maybe_apply_ui_goal(text)
    if auto_apply:
        if is_probable_web_workspace(workspace):
            return auto_apply
        return ["plan", text]

    general_apply = maybe_apply_general_goal(text)
    if general_apply:
        return general_apply

    if parts[0] in PASS_THROUGH_COMMANDS:
        return parts

    # Free text defaults to planning.
    return ["plan", text]


def print_help() -> None:
    print("Commands:")
    print("  help                            show this help")
    print("  exit | quit                     exit console")
    print("  ws <path>                       change workspace")
    print("  workspace <path>                change workspace")
    print("  wsapp                           set workspace to /opt/projects/carbonet")
    print("  opsapp                          auto install/build/restart in workspace")
    print("  ws18000 / ops18000              legacy aliases")
    print("  inspect | doctor | sessions     pass-through")
    print('  plan "goal"                     free-text planning')
    print('  apply "goal" --yes              apply changes')
    print(f"  {APP_HOST_TOKEN} ... 개선        auto apply mode (web workspace)")
    print("  localhost:<port> ... 개선       auto apply mode (any port)")
    print('  "수정/변경/추가 ..."             auto apply mode')
    print('  "재시작해줘"                    auto wsapp + opsapp')


def interactive(py_exe: str, workspace: Path) -> int:
    current_ws = workspace
    print("[FreeAgent Console]")
    print(f"workspace: {current_ws}")
    print('Type "help" for commands, "exit" to quit.')

    while True:
        try:
            raw = input("freeagent> ").strip()
        except EOFError:
            return 0
        except KeyboardInterrupt:
            print()
            return 0

        if not raw:
            continue
        lowered = raw.lower()

        if lowered in {"exit", "quit"}:
            return 0
        if lowered == "help":
            print_help()
            continue
        handled, current_ws = handle_natural_ops(raw, current_ws)
        if handled:
            continue
        if lowered in {"wsapp", "ws18000"}:
            target = resolve_workspace_path(str(DEFAULT_WORKSPACE))
            if not target.exists():
                print(f"[ERROR] workspace not found: {target}")
                continue
            current_ws = target
            print(f"[OK] workspace changed to: {current_ws}")
            continue
        if lowered in {"opsapp", "ops18000"}:
            code = compile_and_restart(current_ws)
            if code == 0:
                print("[OK] install/build/restart completed.")
            else:
                print("[ERROR] install/build/restart failed.")
            continue
        if lowered.startswith("ws ") or lowered.startswith("workspace "):
            _, _, path_part = raw.partition(" ")
            target = resolve_workspace_path(path_part.strip())
            if not path_part.strip():
                print("[ERROR] workspace path is required.")
                continue
            if not target.exists():
                print(f"[ERROR] workspace not found: {target}")
                continue
            current_ws = target
            print(f"[OK] workspace changed to: {current_ws}")
            continue

        # Auto-switch to carbonet workspace for localhost:<port> web-improvement goals.
        if maybe_apply_ui_goal(raw) and not is_probable_web_workspace(current_ws):
            switched = switch_to_default_workspace_if_possible(current_ws)
            if switched != current_ws:
                current_ws = switched

        cli_args = normalize_to_cli_args(raw, current_ws)
        if not cli_args:
            continue
        if cli_args == ["_help"]:
            print_help()
            continue
        run_cli(py_exe, current_ws, cli_args)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--workspace", dest="workspace", default=None)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    py_exe = sys.executable
    workspace = resolve_workspace(args.workspace)

    if args.interactive or not args.command:
        return interactive(py_exe, workspace)

    raw = " ".join(args.command).strip()
    handled, workspace = handle_natural_ops(raw, workspace)
    if handled:
        return 0
    if maybe_apply_ui_goal(raw) and not is_probable_web_workspace(workspace):
        workspace = switch_to_default_workspace_if_possible(workspace)
    if is_restart_request(raw):
        workspace = switch_to_default_workspace_if_possible(workspace)
        return compile_and_restart(workspace)

    cli_args = normalize_to_cli_args(raw, workspace)
    if not cli_args:
        return 0
    if cli_args == ["_help"]:
        print_help()
        return 0
    return run_cli(py_exe, workspace, cli_args)


if __name__ == "__main__":
    raise SystemExit(main())
