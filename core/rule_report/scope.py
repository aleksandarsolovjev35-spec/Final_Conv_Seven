"""Срез результата правила до одной камеры и фильтрация строк отчёта."""
import copy
from types import SimpleNamespace

from core.rule_report.constants import PART_PRESENCE_RULE, RULE_CAMERA_ROLES



# Поля part_presence, привязанные к конкретной INPUT-камере.
_PRESENCE_ROLE_FIELDS = {
    "INPUT_LEFT": {
        "flatness": "flatness_left",
        "effective": "effective_flatness_left",
        "ignored": "false_positive_ignored_left",
    },
    "INPUT_RIGHT": {
        "flatness": "flatness_right",
        "effective": "effective_flatness_right",
        "ignored": "false_positive_ignored_right",


    },
}

def filter_rule_report_rows(rows) -> list:
    """Оставить только решающие правила.

    Если деталь не обнаружена, все прочие правила не влияли на решение —
    показывается единственная строка «ДЕТАЛЬ НЕ ОБНАРУЖЕНА».
    """
    rows = list(rows or [])


    for row in rows:
        if row.get("name") == PART_PRESENCE_RULE and row.get("part_absent"):
            return [row]
    return rows

def rule_applies_to_role(rule_name: str, role: str | None) -> bool:
    """Правило относится к выбранной камере (или роль не задана)."""
    if not role:


        return True
    roles = RULE_CAMERA_ROLES.get(rule_name)
    if roles is None:
        # Неизвестное правило: оставляем, если role явно есть в данных.
        return True
    return role in roles


def _filter_role_cards(cards, role: str) -> list:
    if not isinstance(cards, list):
        return []
    return [
        card for card in cards
        if isinstance(card, dict) and card.get("role") == role
    ]

def _filter_measurement_cards(cards, role: str) -> list:
    return _filter_role_cards(cards, role)

def _filter_role_status(rows, role: str) -> list:
    if not isinstance(rows, list):


        return []
    return [
        row for row in rows
        if isinstance(row, dict) and (
            row.get("role") == role
            # part_presence пишет общий статус role=INPUT — оставляем.
            or row.get("role") in (None, "", "INPUT")
        )
    ]

def _scope_presence_details(details: dict, role: str) -> dict:
    """Оставить в part_presence только поля выбранной INPUT-камеры."""
    scoped = dict(details)
    if role not in _PRESENCE_ROLE_FIELDS:
        return scoped

    for details_key in (
        "min_confidence_by_role",
        "false_positive_max_count_by_role",
        "presence_by_role",
    ):


        raw = details.get(details_key)
        if isinstance(raw, dict):
            scoped[details_key] = {
                key: value for key, value in raw.items() if key == role
            }

    # Убираем поля чужой камеры (None → summary её пропустит).
    other = "INPUT_RIGHT" if role == "INPUT_LEFT" else "INPUT_LEFT"
    for key in _PRESENCE_ROLE_FIELDS[other].values():
        scoped[key] = None
    return scoped



def _scope_measurement_to_role(details: dict, role: str) -> dict:
    """Оставить в details только карточки/статусы выбранной камеры."""
    scoped = dict(details)
    if "measurement_cards" in scoped:
        scoped["measurement_cards"] = _filter_measurement_cards(
            scoped.get("measurement_cards"), role,
        )
    if "role_status" in scoped:
        scoped["role_status"] = _filter_role_status(
            scoped.get("role_status"), role,
        )
    return scoped

def scope_rule_result_to_role(result, role: str | None):
    """Срез RuleResult до данных одной камеры.

    В UI анализа кадра остаются только измерения выбранной роли.
    ``triggered`` берётся из per_role выбранной камеры (если есть),
    чтобы статус «СРАБОТАЛО/НОРМА» соответствовал тому, что видно на кадре.
    """
    if not role or result is None:
        return result

    rule_name = getattr(result, "rule_name", "") or ""
    if not rule_applies_to_role(rule_name, role):
        return None


    details = copy.deepcopy(getattr(result, "details", {}) or {})
    triggered = bool(getattr(result, "triggered", False))

    if rule_name == PART_PRESENCE_RULE:
        details = _scope_presence_details(details, role)
    else:
        per_role = details.get("per_role")
        if isinstance(per_role, dict) and per_role:
            if role not in per_role:
                return None
            role_details = per_role[role]
            details["per_role"] = {role: role_details}
            if isinstance(role_details, dict) and "triggered" in role_details:
                triggered = bool(role_details.get("triggered"))

    details = _scope_measurement_to_role(details, role)

    return SimpleNamespace(
        rule_name=rule_name,
        triggered=triggered,
        details=details,
        drawings=getattr(result, "drawings", []) or [],
    )
