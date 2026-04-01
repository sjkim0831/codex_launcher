from __future__ import annotations


class PolicyGuard:
    BLOCKED_PREFIXES = (
        "rm -rf",
        "git push",
        "docker compose down",
    )

    def assert_command_allowed(self, command: str) -> None:
        normalized = command.strip().lower()
        for prefix in self.BLOCKED_PREFIXES:
            if normalized.startswith(prefix):
                raise PermissionError(f"blocked by policy guard: {command}")

    def requires_write_approval(self, path: str) -> bool:
        normalized = path.strip().lower()
        return normalized.endswith((".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".md"))

    def requires_command_approval(self, command: str) -> bool:
        normalized = command.strip().lower()
        return normalized.startswith(("pytest", "python3 -m pytest", "npm test", "npm run", "make "))
