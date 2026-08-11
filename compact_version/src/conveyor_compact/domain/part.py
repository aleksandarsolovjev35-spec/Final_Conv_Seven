"""Состояние детали без зависимостей от камер, UI и оборудования."""

from __future__ import annotations

from dataclasses import dataclass, field


CATEGORY_GOOD = "GOOD"
CATEGORY_BAD = "BAD"
CATEGORY_CLEANUP = "CLEANUP"
CATEGORY_UNKNOWN = "UNKNOWN"

CLEANUP_DEFECTS = frozenset({"glass", "glass_glare"})


@dataclass(slots=True, eq=False)
class Part:
    """Совместимая доменная модель детали.

    Категория GOOD появляется только после обеих стадий. Любой обычный
    дефект направляет деталь в BAD; только glass/glass_glare — в CLEANUP.
    """

    part_id: int
    step_created: int
    input_defects: list[str] = field(default_factory=list)
    spider_defects: list[str] = field(default_factory=list)
    input_inspected: bool = False
    spider_inspected: bool = False
    final_decision: str = "none"
    route_category: str = CATEGORY_UNKNOWN
    inspection_consensus: dict = field(default_factory=dict)

    @property
    def id(self) -> int:
        return self.part_id

    @id.setter
    def id(self, value: int) -> None:
        self.part_id = value

    def add_input_defect(self, defect: str) -> None:
        if defect:
            self.input_defects.append(defect)

    def add_spider_defect(self, defect: str) -> None:
        if defect:
            self.spider_defects.append(defect)

    def mark_input_done(self) -> None:
        self.input_inspected = True
        self._recompute()

    def mark_spider_done(self) -> None:
        self.spider_inspected = True
        self._recompute()

    def get_all_defects(self) -> list[str]:
        return self.input_defects + self.spider_defects

    @property
    def fully_inspected(self) -> bool:
        return self.input_inspected and self.spider_inspected

    def _recompute(self) -> None:
        defects = self.get_all_defects()
        if not defects:
            self.final_decision = "none"
            self.route_category = (
                CATEGORY_GOOD if self.fully_inspected else CATEGORY_UNKNOWN
            )
            return

        if all(defect in CLEANUP_DEFECTS for defect in defects):
            self.final_decision = defects[-1]
            self.route_category = CATEGORY_CLEANUP
            return

        self.final_decision = next(
            defect for defect in defects if defect not in CLEANUP_DEFECTS
        )
        self.route_category = CATEGORY_BAD

    def __repr__(self) -> str:
        inspected = "full" if self.fully_inspected else "partial"
        return (
            f"<Part #{self.id} step={self.step_created} "
            f"category={self.route_category} inspected={inspected} "
            f"defects={self.get_all_defects()}>"
        )
