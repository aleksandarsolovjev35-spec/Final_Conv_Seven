"""Единый порядок запуска и безопасного обратного выключения компонентов."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ManagedComponent:
    name: str
    start: Callable[[], None]
    stop: Callable[[], None]


class LifecycleError(RuntimeError):
    pass


class Lifecycle:
    """Заменяет вложенную инициализацию из большого main.py.

    Компоненты запускаются по порядку, останавливаются в обратном порядке.
    При ошибке запуска уже поднятые компоненты автоматически откатываются.
    """

    def __init__(self, components: Iterable[ManagedComponent] = ()) -> None:
        self._components = tuple(components)
        self._started: list[ManagedComponent] = []

    @property
    def started_names(self) -> tuple[str, ...]:
        return tuple(component.name for component in self._started)

    def start(self) -> None:
        if self._started:
            raise LifecycleError("Lifecycle уже запущен")
        try:
            for component in self._components:
                component.start()
                self._started.append(component)
        except Exception as exc:
            rollback_errors = self._stop_started()
            details = self._format_errors(rollback_errors)
            suffix = f"; ошибки отката: {details}" if details else ""
            raise LifecycleError(
                f"Не удалось запустить {component.name}: {exc}{suffix}"
            ) from exc

    def stop(self) -> None:
        errors = self._stop_started()
        if errors:
            raise LifecycleError(
                f"Ошибки выключения: {self._format_errors(errors)}"
            )

    def _stop_started(self) -> list[tuple[str, Exception]]:
        errors = []
        while self._started:
            component = self._started.pop()
            try:
                component.stop()
            except Exception as exc:
                errors.append((component.name, exc))
        return errors

    @staticmethod
    def _format_errors(errors: list[tuple[str, Exception]]) -> str:
        return "; ".join(f"{name}: {error}" for name, error in errors)
