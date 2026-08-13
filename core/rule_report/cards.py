"""Карточки замера правила для правой панели HMI («Анализ кадра»)."""
from core.rule_report.details import ROLE_METRIC_BUILDERS
from core.rule_report.human_cause import role_reason_text
from core.rule_report.metrics import (
    METRICS_PER_ROLE_LIMIT,
    _UNKNOWN,
    count_found,
    metric,
    number,
)


def _role_metrics(rule_name: str, role_details: dict) -> list:
    builder = ROLE_METRIC_BUILDERS.get(rule_name)
    metrics = list(builder(role_details)) if builder is not None else []

    if not metrics:
        for label, key, unit in (
            ("Найдено, шт", "found", ""),
            ("Найдено (сырые), шт", "found_raw", ""),
            ("Пересечение, px", "overlap_px", " px"),
            ("Площадь, px²", "mask_area_px2", " px²"),
        ):
            if key in role_details and role_details.get(key) is not None:
                metrics.append(metric(
                    label, role_details.get(key), unit=unit, key=key,
                ))

    if len(metrics) > METRICS_PER_ROLE_LIMIT:
        metrics = metrics[:METRICS_PER_ROLE_LIMIT]
    return metrics


def _role_verdict(role_details: dict) -> tuple:
    if role_details.get("skipped"):
        return None, "нет измерения" + (
            f" · {role_reason_text(role_details.get('reason'))}"
            if role_details.get("reason") else ""
        )
    if role_details.get("triggered"):
        reason = role_reason_text(role_details.get("reason"))
        return False, f"отклонение{f' · {reason}' if reason else ''}"
    reason = role_reason_text(role_details.get("reason"))
    if reason:
        return None, f"без измерения · {reason}"
    return True, "в допуске"


def build_rule_summary(rule_name: str, details: dict) -> list:
    per_role = details.get("per_role")
    if not isinstance(per_role, dict) or not per_role:
        return []

    cards = []
    for role, role_details in per_role.items():
        if not isinstance(role_details, dict):
            continue
        ok, verdict = _role_verdict(role_details)
        cards.append({
            "role": role,
            "ok": ok,
            "verdict": verdict,
            "found": count_found(role_details),
            "metrics": _role_metrics(rule_name, role_details),
        })
    cards.sort(key=lambda card: (card["ok"] is not False, card["role"]))
    return cards


def build_presence_summary(details: dict) -> list:
    limits = details.get("false_positive_max_count_by_role") or {}
    cards = []
    for role, raw_key, effective_key in (
        ("INPUT_LEFT", "flatness_left", "effective_flatness_left"),
        ("INPUT_RIGHT", "flatness_right", "effective_flatness_right"),
    ):
        found = details.get(raw_key)
        if found is None:
            continue
        limit = limits.get(role)
        present = None
        if isinstance(limit, int):
            present = int(found) > limit
        metrics = [
            item for item in (
                metric(
                    "flatness", found, limit,
                    ok=present if present is not None else None,
                    key="false_positive_max_count",
                ),
                metric(
                    "Зачтено, шт", details.get(effective_key),
                    key="effective_flatness",
                ),
            ) if item is not None
        ]
        cards.append({
            "role": role,
            "ok": present,
            "verdict": (
                "корпус виден" if present else (
                    "корпус не виден" if present is False else _UNKNOWN
                )
            ),
            "found": [f"flatness: {number(found)}"],
            "metrics": metrics,
        })
    return cards
