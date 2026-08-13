"""Формирование строк отчёта по правилам дефектов для HMI и диагностики.

Каждое правило со своей развёрнутой телеметрией имеет отдельный форматтер
в :mod:`core.rule_report.details`: он возвращает список строк, которые UI
показывает под правилом. Правила без собственного форматтера получают общее
описание сработавших ролей через
:func:`core.rule_report.details.generic._generic_failure_rows`.

Публичный API пакета — сборка строк:
:func:`build_rule_report_row` и :func:`build_rule_report_rows`.
"""
from core.rule_report.constants import (
    DETAILED_RULES,
    METRIC_PARAM_LABELS,
    NO_MEASUREMENT,
    PART_PRESENCE_RULE,
    RULE_CAMERA_ROLES,
    SUMMARY_LINES_LIMIT,
)
from core.rule_report.human_cause import get_human_cause
from core.rule_report.row import build_rule_report_row, build_rule_report_rows
from core.rule_report.scope import (
    filter_rule_report_rows,
    rule_applies_to_role,
    scope_rule_result_to_role,
)



__all__ = [
    "build_rule_report_row",
    "build_rule_report_rows",
    "filter_rule_report_rows",
    "get_human_cause",
    "rule_applies_to_role",
    "scope_rule_result_to_role",
]
