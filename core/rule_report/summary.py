"""Сводка правила для правой панели: skip-итоги, статус, строки summary."""
from core.rule_report.constants import (
    NO_MEASUREMENT,
    PART_PRESENCE_RULE,
    SUMMARY_LINES_LIMIT,
)
from core.rule_report.details.generic import _generic_failure_rows


def _skip_summary(per_role: dict) -> tuple:
    """Вернуть ``(текст, все_ли_роли_пропущены)`` для правила без измерений."""
    skipped_rows = [
        (role, role_details)
        for role, role_details in per_role.items()
        if isinstance(role_details, dict) and role_details.get("skipped")
    ]
    if not skipped_rows:
        return None, False
    reasons = "; ".join(
        f"{role}: {row.get('reason', NO_MEASUREMENT)}"
        for role, row in skipped_rows
    )
    if len(skipped_rows) == len(per_role):

        return f"Не выполнено: {reasons}", True
    return f"Частично выполнено: {reasons}", False


def _status_label(rule_name: str, triggered: bool, details: dict):
    """Итог правила для правой панели: текст и признак нейтрального статуса."""
    if rule_name == "part_presence" and details.get("empty_tray"):

        return "КОРПУС НЕ ОБНАРУЖЕН", True
    if rule_name == "part_presence":
        return "КОРПУС ОБНАРУЖЕН", False
    return ("СРАБОТАЛО" if triggered else "НОРМА"), False


def _presence_summary(details: dict) -> list:
    """Короткая сводка по правилу присутствия детали."""
    limits = details.get("false_positive_max_count_by_role") or {}
    lines = []
    for role, key in (
        ("INPUT_LEFT", "flatness_left"),
        ("INPUT_RIGHT", "flatness_right"),
    ):
        raw = details.get(key)
        if raw is None and key not in details:
            # Поле отсутствует (срез до одной камеры) — не показываем.
            continue
        if raw is None:
            continue
        found = int(raw or 0)

        limit = limits.get(role)
        limit_text = (
            f" (порог ложных {int(limit)})" if isinstance(limit, int) else ""
        )
        lines.append(f"{role}: flatness {found}{limit_text}")

    return lines


def _failing_roles(per_role: dict) -> set:
    return {
        role
        for role, role_details in per_role.items()
        if isinstance(role_details, dict) and role_details.get("triggered")
    }


def _summary_lines(
    rule_name: str,
    triggered: bool,
    skipped: bool,
    details: dict,
    per_role: dict,
    detail_lines: list,
    detail: str,
) -> list:
    """Компактная, но информативная сводка по правилу для правой панели.

    Показываются только те строки, которые реально влияли на решение по детали:
    для сработавшего правила — роли камер с отклонением, для пропущенного —
    причина отсутствия измерения. Список ограничен ``SUMMARY_LINES_LIMIT``.
    """
    if rule_name == PART_PRESENCE_RULE:
        return _presence_summary(details)

    if skipped:
        return [str(detail)] if detail else []

    if not triggered:
        return []

    lines = []
    if isinstance(per_role, dict) and per_role:
        roles = _failing_roles(per_role) or set(per_role)
        if detail_lines:
            lines = [
                line
                for line in detail_lines
                if str(line).split(":", 1)[0].split(" ", 1)[0] in roles
            ] or list(detail_lines)
        else:
            lines = _generic_failure_rows(rule_name, per_role)
    if not lines and detail:
        lines = [str(detail)]

    if len(lines) > SUMMARY_LINES_LIMIT:
        hidden = len(lines) - SUMMARY_LINES_LIMIT
        lines = lines[:SUMMARY_LINES_LIMIT] + [f"…ещё {hidden} строк(и)"]
    return [str(line) for line in lines]
