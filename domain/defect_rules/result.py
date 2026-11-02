"""Результат выполнения правила дефекта.

Единственный общий контракт между правилами и остальным приложением:
движок, инспекция, оверлеи и отчёты работают с этим типом.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuleResult:
    rule_name: str
    triggered: bool
    details: dict = field(default_factory=dict)
    drawings: list = field(default_factory=list)

    @property
    def defect(self) -> str | None:
        return self.rule_name if self.triggered else None

    def __repr__(self):
        status = "FAIL" if self.triggered else "OK"
        return f"<{self.rule_name}: {status} {self.details}>"
