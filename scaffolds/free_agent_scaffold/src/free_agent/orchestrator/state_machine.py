from __future__ import annotations

from free_agent.models import TaskState


class StateMachine:
    def __init__(self) -> None:
        self._history: list[TaskState] = [TaskState.IDLE]

    @property
    def current(self) -> TaskState:
        return self._history[-1]

    @property
    def history(self) -> list[TaskState]:
        return list(self._history)

    def transition(self, next_state: TaskState) -> TaskState:
        allowed = {
            TaskState.IDLE: {TaskState.ANALYZE},
            TaskState.ANALYZE: {TaskState.PLAN, TaskState.REPORT},
            TaskState.PLAN: {TaskState.GATHER_CONTEXT, TaskState.REPORT},
            TaskState.GATHER_CONTEXT: {TaskState.EXECUTE, TaskState.REPORT},
            TaskState.EXECUTE: {TaskState.VERIFY, TaskState.RECOVER, TaskState.REPORT},
            TaskState.VERIFY: {TaskState.REVIEW, TaskState.RECOVER, TaskState.REPORT},
            TaskState.REVIEW: {TaskState.REPORT},
            TaskState.RECOVER: {TaskState.EXECUTE, TaskState.REPORT},
            TaskState.REPORT: {TaskState.DONE},
            TaskState.DONE: set(),
        }
        if next_state not in allowed[self.current]:
            raise ValueError(f"invalid transition: {self.current.value} -> {next_state.value}")
        self._history.append(next_state)
        return next_state
