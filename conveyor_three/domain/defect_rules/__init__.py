"""Правила дефектов трёхкамерной линии.

Каждое правило — автономный модуль: своя геометрия, свои пороги и своя
проверка включённости. Общим остаётся только тип результата ``RuleResult``.
"""

from domain.defect_rules.result import RuleResult

from domain.defect_rules.rule_part_presence  import PartPresenceRule
from domain.defect_rules.rule_uneven_heights import UnevenHeightsRule
from domain.defect_rules.rule_window_sinks   import WindowSinksRule
from domain.defect_rules.rule_bottom_glass   import BottomGlassRule
from domain.defect_rules.rule_welding        import WeldingRule

__all__ = [
    "RuleResult",
    "PartPresenceRule",
    "UnevenHeightsRule",
    "WindowSinksRule",
    "BottomGlassRule",
    "WeldingRule",
]
