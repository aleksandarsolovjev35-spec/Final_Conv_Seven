"""Потокобезопасное состояние линии."""

from __future__ import annotations

import threading
from collections.abc import Callable
from enum import Enum


class LineState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAULT = "FAULT"


TransitionCallback = Callable[[LineState, LineState, str], None]

_TRANSITIONS = {
    (LineState.IDLE, "START"): LineState.RUNNING,
    (LineState.STOPPED, "START"): LineState.RUNNING,
    (LineState.RUNNING, "STOP"): LineState.STOPPING,
    (LineState.STOPPING, "EMPTY"): LineState.STOPPED,
    (LineState.RUNNING, "PAUSE"): LineState.PAUSED,
    (LineState.PAUSED, "RESUME"): LineState.RUNNING,
    (LineState.PAUSED, "STOP"): LineState.STOPPING,
    **{(state, "FAULT"): LineState.FAULT for state in LineState if state is not LineState.FAULT},
}


class StateMachine:
    def __init__(self, on_transition: TransitionCallback | None = None):
        self._state = LineState.IDLE
        self._exit_requested = False
        self._force_exit = False
        self._on_transition = on_transition
        self._lock = threading.Lock()

    @property
    def state(self) -> LineState:
        with self._lock:
            return self._state

    @property
    def exit_requested(self) -> bool:
        with self._lock:
            return self._exit_requested

    @property
    def force_exit(self) -> bool:
        with self._lock:
            return self._force_exit

    @property
    def is_active(self) -> bool:
        return self.state in (LineState.RUNNING, LineState.STOPPING)

    @property
    def accepts_new_parts(self) -> bool:
        return self.state is LineState.RUNNING

    def request_start(self) -> bool:
        return self._apply("START")

    def request_stop(self) -> bool:
        return self._apply("STOP")

    def request_pause(self) -> bool:
        return self._apply("PAUSE")

    def request_resume(self) -> bool:
        return self._apply("RESUME")

    def notify_line_empty(self) -> bool:
        return self._apply("EMPTY")

    def notify_fault(self) -> bool:
        return self._apply("FAULT")

    def request_exit(self) -> bool:
        callback_args = None
        with self._lock:
            self._exit_requested = True
            if self._state is LineState.RUNNING:
                old = self._state
                self._state = LineState.STOPPING
                callback_args = (old, self._state, "STOP")
        if callback_args is not None and self._on_transition is not None:
            self._on_transition(*callback_args)
        return True

    def request_force_exit(self) -> bool:
        with self._lock:
            self._exit_requested = True
            self._force_exit = True
        return True

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "exit_requested": self._exit_requested,
                "force_exit": self._force_exit,
            }

    def _apply(self, action: str) -> bool:
        callback_args = None
        with self._lock:
            old = self._state
            new = _TRANSITIONS.get((old, action))
            if new is None:
                return False
            self._state = new
            callback_args = (old, new, action)

        if self._on_transition is not None:
            self._on_transition(*callback_args)
        return True
