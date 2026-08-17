"""Срез результата правила до одной камеры (3 камеры)."""

from __future__ import annotations

import copy
from types import SimpleNamespace

from core.rule_report.constants import (
    PART_PRESENCE_RULE,
    PRESENCE_ROLE_FIELDS,
    RULE_CAMERA_ROLES,
)


def rule_applies_to_role(rule_name: str, role: str | None) -> bool:
    """Правило относится к выбранной камере (или роль не задана)."""
    if not role:
        return True
    roles = RULE_CAMERA_ROLES.get(rule_name)
    if roles is None:
        return True
    return role in roles


def _filter_role_cards(cards, role: str) -> list:
    if not isinstance(cards, list):
        return []
    return [
        card for card in cards
        if isinstance(card, dict) and card.get("role") == role
    ]


def _filter_run_cards(run_cards, role: str) -> list:
    if not isinstance(run_cards, list):
        return []
    return [_filter_role_cards(cards, role) for cards in run_cards]


def _filter_run_status(run_status, role: str) -> list:
    if not isinstance(run_status, list):
        return []
    filtered = []
    for rows in run_status:
        if not isinstance(rows, list):
            filtered.append([])
            continue
        filtered.append([
            row for row in rows
            if isinstance(row, dict) and (
                row.get("role") == role
                or row.get("role") in (None, "", "INPUT")
            )
        ])
    return filtered


def _scope_presence_details(details: dict, role: str) -> dict:
    """Оставить в part_presence только поля выбранной камеры."""
    scoped = dict(details)
    if role not in PRESENCE_ROLE_FIELDS:
        return scoped

    for details_key in (
        "min_confidence_by_role",
        "min_windows_by_role",
        "presence_by_role",
        "windows_by_role",
    ):
        raw = details.get(details_key)
        if isinstance(raw, dict):
            scoped[details_key] = {
                key: value for key, value in raw.items() if key == role
            }

    other = "FAR" if role == "NEAR" else "NEAR"
    for key in PRESENCE_ROLE_FIELDS[other].values():
        scoped[key] = None
    return scoped


def _scope_consensus_to_role(consensus: dict, role: str) -> dict:
    """Оставить в consensus только карточки/статусы выбранной камеры."""
    scoped = dict(consensus)
    if "run_cards" in scoped:
        scoped["run_cards"] = _filter_run_cards(scoped.get("run_cards"), role)
    if "run_status" in scoped:
        scoped["run_status"] = _filter_run_status(
            scoped.get("run_status"), role
        )
    return scoped


def scope_rule_result_to_role(result, role: str | None):
    """Срез RuleResult до данных одной камеры."""
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

    consensus = details.get("consensus")
    if isinstance(consensus, dict):
        details["consensus"] = _scope_consensus_to_role(consensus, role)

    return SimpleNamespace(
        rule_name=rule_name,
        triggered=triggered,
        details=details,
        drawings=getattr(result, "drawings", []) or [],
    )


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
