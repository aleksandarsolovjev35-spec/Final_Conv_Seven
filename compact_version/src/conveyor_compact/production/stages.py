"""Чистая проверка порядка фаз производственного шага."""

from __future__ import annotations

import threading
from enum import Enum


class StageSequenceError(RuntimeError):
    pass


class StepStage(str, Enum):
    IDLE = "IDLE"
    MOTION = "MOTION"
    SETTLE = "SETTLE"
    CAPTURE = "CAPTURE"
    ANALYSIS = "ANALYSIS"
    PUBLISH = "PUBLISH"


_ALLOWED = {
    StepStage.IDLE: (StepStage.MOTION,),
    StepStage.MOTION: (StepStage.SETTLE,),
    StepStage.SETTLE: (StepStage.CAPTURE,),
    StepStage.CAPTURE: (StepStage.ANALYSIS,),
    StepStage.ANALYSIS: (StepStage.PUBLISH,),
    StepStage.PUBLISH: (StepStage.MOTION,),
}


class StageSequence:
    """Хранит только порядок фаз; владение камерами реализует адаптер."""

    def __init__(self) -> None:
        self._stage = StepStage.IDLE
        self._lock = threading.Lock()

    @property
    def stage(self) -> StepStage:
        with self._lock:
            return self._stage

    def move_to(self, target: StepStage) -> None:
        with self._lock:
            current = self._stage
            if target not in _ALLOWED[current]:
                raise StageSequenceError(
                    f"Недопустимый переход шага: {current.value} -> {target.value}"
                )
            self._stage = target

    def reset(self) -> None:
        with self._lock:
            self._stage = StepStage.IDLE
