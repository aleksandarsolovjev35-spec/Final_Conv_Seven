"""Движение ленты на шаг для мастера сбора датасета.

Мастер обучения намеренно отделён от производственного цикла, но оператору
нужен тот же шаг ленты: разметил все камеры детали → нажал «ДАЛЕЕ» → лента
сдвинулась на одну позицию → новая деталь и новые изображения. Здесь живут
тонкие адаптеры над ``hardware.Conveyor``: доменный коллектор видит только
протокол ``BeltStepSource`` с одним методом ``advance()``.
"""

from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BeltStepSource(Protocol):
    """Минимальный интерфейс шага ленты для мастера обучения."""

    def advance(self) -> dict[str, Any]:
        """Выполнить один шаг ленты и вернуть описание результата."""


class ConveyorBeltStep:
    """Адаптер настоящего ``hardware.Conveyor``: шаг, останов, затухание.

    ``move_step`` + ``wait_stop`` повторяют последовательность
    ``core/cycle/step.py``: логическая позиция фиксируется только после
    подтверждённой остановки. После остановки выдерживается ``settle_seconds``
    (как стадия SETTLE в производственном цикле), чтобы вибрация не попала
    в первый кадр новой детали.
    """

    def __init__(
        self,
        conveyor: Any,
        *,
        settle_seconds: float = 0.2,
        wait_timeout: float = 15.0,
    ):
        if not hasattr(conveyor, "move_step") or not hasattr(conveyor, "wait_stop"):
            raise TypeError("Источник шага должен иметь move_step() и wait_stop()")
        if settle_seconds < 0:
            raise ValueError("settle_seconds не может быть отрицательным")
        self.conveyor = conveyor
        self.settle_seconds = float(settle_seconds)
        self.wait_timeout = float(wait_timeout)
        self.step_count = 0

    def advance(self) -> dict[str, Any]:
        started = time.monotonic()
        self.conveyor.move_step()
        self.conveyor.wait_stop(timeout=self.wait_timeout)
        if self.settle_seconds:
            time.sleep(self.settle_seconds)
        self.step_count += 1
        return {
            "available": True,
            "moved": True,
            "steps": self.step_count,
            "settle_seconds": self.settle_seconds,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }


class VirtualBeltStep:
    """Эмулятор ленты для стендов без контроллера и автоматических тестов.

    Считает шаги и выдерживает ``settle_seconds`` без реального движения.
    """

    def __init__(self, *, settle_seconds: float = 0.0):
        self.settle_seconds = float(settle_seconds)
        self.step_count = 0

    def advance(self) -> dict[str, Any]:
        if self.settle_seconds:
            time.sleep(self.settle_seconds)
        self.step_count += 1
        return {
            "available": True,
            "moved": True,
            "steps": self.step_count,
            "settle_seconds": self.settle_seconds,
            "virtual": True,
        }
