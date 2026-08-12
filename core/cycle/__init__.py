"""Производственный цикл линии.

Публичная точка входа — ``ProductionCycle``. Реализация разложена по частям:

* ``orchestrator`` — пуск/стоп, главный цикл, авария, архив;
* ``step``         — один шаг ленты и инспекции;
* ``diagnostics``  — предстартовые проверки;
* ``jog``          — ручной ход;
* ``status``       — снимок для HMI.

Совместимый импорт: ``from core.production_cycle import ProductionCycle``.
"""

from core.cycle.orchestrator import ProductionCycle

__all__ = ["ProductionCycle"]
