"""Сборка одной строки отчёта по правилу (3 камеры)."""

from __future__ import annotations

import copy

from core.rule_report.cards import build_presence_summary, build_rule_summary
from core.rule_report.constants import (
    DETAILED_RULES,
    METRIC_PARAM_LABELS,
    PART_PRESENCE_RULE,
    RULE_LABELS,
)
from core.rule_report.human_cause import get_human_cause
from core.rule_report.scope import (
    filter_rule_report_rows,
    scope_rule_result_to_role,
)


def _status_label(
    rule_name: str, triggered: bool, details: dict, consensus: dict,
):
    """Итог правила для правой панели: текст и признак нейтрального статуса."""
    if rule_name == PART_PRESENCE_RULE and details.get("empty_tray"):
        label = "ДЕТАЛЬ НЕ ОБНАРУЖЕНА"
        if consensus:
            label += (
                f" · {int(consensus.get('empty_votes') or 0)}/"
                f"{int(consensus.get('runs') or 0)}"
            )
        return label, True
    if rule_name == PART_PRESENCE_RULE:
        if not consensus:
            return None, False
        return (
            "ДЕТАЛЬ ОБНАРУЖЕНА · "
            f"{int(consensus.get('present_votes') or 0)}/"
            f"{int(consensus.get('runs') or 0)}"
        ), False
    if not consensus:
        return None, False
    votes_key = "triggered_votes" if triggered else "normal_votes"
    return (
        ("СРАБОТАЛО" if triggered else "НОРМА")
        + f" · {int(consensus.get(votes_key) or 0)}/"
        f"{int(consensus.get('runs') or 0)}"
    ), False


def _detail_lines(rule_name: str, per_role: dict) -> list:
    """Строки мини-отчёта по ролям для панели диагностики."""
    lines = []
    for role, rd in per_role.items():
        if not isinstance(rd, dict):
            continue
        if rd.get("triggered"):
            found = rd.get("found")
            reason = rd.get("reason")
            text = f"{role}: отклонение"
            if reason:
                text += f" ({str(reason).replace('_', ' ')})"
            if found is not None:
                text += f", объектов: {found}"
            lines.append(text)
    return lines


def _summary_lines(
    rule_name, triggered, skipped, details, per_role,
    detail_lines, detail,
):
    """Краткие строки под правилом в карточке анализа."""
    lines = []
    if skipped:
        lines.append("Пропущено: правило отключено")
    for line in detail_lines or []:
        lines.append(str(line))
    if not lines and detail:
        lines.append(str(detail))
    return lines[:6]


def _threshold_breaches(summary_cards) -> list:
    """Метрики, не прошедшие проверку порога."""
    breaches = []
    for card in summary_cards or []:
        if not isinstance(card, dict):
            continue
        role = card.get("role")
        for metric in card.get("metrics") or []:
            if not isinstance(metric, dict):
                continue
            if metric.get("ok") is False:
                breaches.append({
                    "role": role,
                    "label": metric.get("label"),
                    "value": metric.get("value"),
                    "limit": metric.get("limit"),
                    "object": metric.get("object"),
                })
    return breaches


def _threshold_conclusion(triggered: bool, human_cause, breaches) -> str | None:
    if not triggered:
        return None
    if human_cause:
        return str(human_cause)
    if breaches:
        return "Порог превышен"
    return "Сработало"


def _extract_vote_details(consensus: dict, rule_name: str) -> dict:
    if not isinstance(consensus, dict) or not consensus:
        return {}
    return {
        "runs": consensus.get("runs"),
        "triggered_votes": consensus.get("triggered_votes"),
        "normal_votes": consensus.get("normal_votes"),
        "decision": consensus.get("decision"),
    }


def _fallback_run_status(run_cards) -> list:
    if not run_cards:
        return []
    status_rows = []
    for cards in run_cards:
        rows = []
        for card in cards or []:
            if not isinstance(card, dict):
                continue
            ok = card.get("ok")
            if ok is True:
                status = "В НОРМЕ"
            elif ok is False:
                status = "ОТКЛОНЕНИЕ"
            else:
                status = "НЕТ ИЗМЕРЕНИЯ"
            rows.append(
                {"role": card.get("role"), "status": status, "reason": None}
            )
        status_rows.append(rows)
    return status_rows


def build_rule_report_rows(results, role: str | None = None) -> list:
    """Собрать строки отчёта; при ``role`` — только выбранная камера."""
    rows = []
    for result in results or []:
        if role:
            scoped = scope_rule_result_to_role(result, role)
            if scoped is None:
                continue
            rows.append(build_rule_report_row(scoped))
        else:
            rows.append(build_rule_report_row(result))
    return filter_rule_report_rows(rows)


def build_rule_report_row(result) -> dict:
    """Собрать одну строку отчёта по правилу для HMI и диагностики."""
    details = getattr(result, "details", {}) or {}
    rule_name = getattr(result, "rule_name", "")
    triggered = bool(result.triggered)
    per_role = details.get("per_role")
    has_per_role = isinstance(per_role, dict) and bool(per_role)

    detail = details.get("reason") or details.get("status")
    skipped = False
    if has_per_role:
        if any(
            isinstance(rd, dict) and rd.get("skipped")
            for rd in per_role.values()
        ):
            skipped = True
            detail = "Правило отключено"

    detail_lines = []
    if has_per_role and triggered:
        detail_lines = _detail_lines(rule_name, per_role)
        if detail_lines:
            detail = "; ".join(detail_lines)

    consensus = details.get("consensus")
    if not isinstance(consensus, dict):
        consensus = {}

    if rule_name == PART_PRESENCE_RULE:
        detail = (
            "ДЕТАЛЬ НЕ ОБНАРУЖЕНА"
            if details.get("empty_tray")
            else "Деталь обнаружена"
        )

    human_cause = None
    if triggered:
        human_cause = get_human_cause(rule_name, triggered, details)

    if not detail:
        detail = human_cause or ("Сработало" if triggered else "Норма")

    status_label, neutral = _status_label(
        rule_name, triggered, details, consensus,
    )

    part_absent = bool(
        rule_name == PART_PRESENCE_RULE and details.get("empty_tray")
    )

    if rule_name == PART_PRESENCE_RULE:
        summary_cards = build_presence_summary(details)
    else:
        summary_cards = build_rule_summary(
            rule_name, details if has_per_role else {},
        )

    summary_lines = _summary_lines(
        rule_name,
        triggered,
        skipped,
        details,
        per_role if has_per_role else {},
        detail_lines,
        str(detail),
    )
    threshold_breaches = _threshold_breaches(summary_cards)
    threshold_conclusion = _threshold_conclusion(
        triggered, human_cause, threshold_breaches,
    )

    # Замеры анализа кадра: подписи порогов согласованы с панелью порогов.
    run_cards = copy.deepcopy(consensus.get("run_cards") or [])
    for cards in run_cards:
        for card in cards:
            for metric in card.get("metrics") or []:
                key = metric.get("key")
                if not key:
                    continue
                label = METRIC_PARAM_LABELS.get((rule_name, key))
                if label:
                    metric["label"] = label

    run_status = consensus.get("run_status") or _fallback_run_status(run_cards)

    return {
        "name": result.rule_name,
        "label": RULE_LABELS.get(rule_name, rule_name),
        "triggered": triggered,
        "skipped": skipped,
        "status_label": status_label,
        "neutral": neutral,
        "show_detail": rule_name in DETAILED_RULES,
        "detail": str(detail),
        "human_cause": human_cause,
        "detail_lines": detail_lines,
        "summary_lines": summary_lines,
        "summary_cards": summary_cards,
        "run_cards": run_cards,
        "run_status": copy.deepcopy(run_status),
        "threshold_breaches": threshold_breaches,
        "threshold_conclusion": threshold_conclusion,
        "vote_details": _extract_vote_details(consensus, rule_name),
        "part_absent": part_absent,
        "decisive": bool(part_absent or triggered or skipped),
        "consensus": dict(consensus),
    }
