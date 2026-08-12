"""Формирование строк отчёта по правилам дефектов для HMI (3 камеры).

Компактная версия семикамерного модуля: тот же публичный интерфейс
(``build_rule_report_row``, ``build_rule_report_rows``,
``scope_rule_result_to_role``, ``filter_rule_report_rows``), но без
форматтеров отдельных правил — сводка строится универсально по
``per_role`` деталям правил.
"""

import copy
from types import SimpleNamespace

from core.rule_summary import build_presence_summary, build_rule_summary

PART_PRESENCE_RULE = "part_presence"

# Названия правил -> человекочитаемые заголовки.
RULE_LABELS = {
    "part_presence":  "НАЛИЧИЕ ДЕТАЛИ",
    "uneven_heights": "РАЗНОВЫСОТНОСТЬ ОКОН",
    "window_sinks":   "РАКОВИНЫ ОКОН",
    "bottom_glass":   "СТЕКЛО НА ДНЕ",
    "welding":        "БРАК СВАРКИ",
}

# Камеры, для которых правило имеет смысл в анализе кадра.
RULE_CAMERA_ROLES = {
    "part_presence":  ("NEAR", "FAR"),
    "uneven_heights": ("NEAR", "FAR"),
    "window_sinks":   ("NEAR", "FAR"),
    "bottom_glass":   ("MIDDLE",),
    "welding":        ("MIDDLE",),
}

# Правила с развёрнутым detail в панели.
DETAILED_RULES = ("uneven_heights",)

# Подписи метрик замеров (как в панели «Пороги правил»).
METRIC_PARAM_LABELS = {
    ("uneven_heights", "height_px"): "Высота ячейки, px",
    ("uneven_heights", "height_max_px"): "Высота ячейки: макс., px",
    ("uneven_heights", "height_min_px"): "Высота ячейки: мин., px",
    ("uneven_heights", "height_difference_px"): "Макс. разброс высот ячеек, px",
    ("window_sinks", "found"): "Число раковин, шт",
    ("bottom_glass", "found"): "Число стёкол, шт",
    ("welding", "found"): "Число дефектов сварки, шт",
}

# Короткие человеческие причины дефектов.
HUMAN_CAUSE_MAP = {
    ("uneven_heights", True): "РАЗНОВЫСОТНОСТЬ ОКОН",
    ("window_sinks", True):   "РАКОВИНА В ОКНЕ",
    ("bottom_glass", True):   "СТЕКЛО НА ДНЕ ИЗДЕЛИЯ",
    ("welding", True):        "БРАК СВАРКИ",
}

# Поля part_presence, привязанные к конкретной камере.
_PRESENCE_ROLE_FIELDS = {
    "NEAR": {"windows": "windows_near"},
    "FAR":  {"windows": "windows_far"},
}


def get_human_cause(rule_name: str, triggered: bool, details: dict) -> str | None:
    """Короткая читаемая причина дефекта."""
    if not triggered:
        return None
    key = (rule_name, True)
    if key in HUMAN_CAUSE_MAP:
        return HUMAN_CAUSE_MAP[key]
    return "ДЕФЕКТ"


def rule_applies_to_role(rule_name: str, role: str | None) -> bool:
    """Правило относится к выбранной камере (или роль не задана)."""
    if not role:
        return True
    roles = RULE_CAMERA_ROLES.get(rule_name)
    if roles is None:
        return True
    return role in roles


def _status_label(rule_name: str, triggered: bool, details: dict):
    """Итог правила для правой панели: текст и признак нейтрального статуса."""
    if rule_name == PART_PRESENCE_RULE and details.get("empty_tray"):
        return "ДЕТАЛЬ НЕ ОБНАРУЖЕНА", True
    if rule_name == PART_PRESENCE_RULE:
        return "ДЕТАЛЬ ОБНАРУЖЕНА", False
    return ("СРАБОТАЛО" if triggered else "НОРМА"), False


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


def _summary_lines(rule_name, triggered, skipped, details, per_role, detail_lines, detail):
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
            rows.append({"role": card.get("role"), "status": status, "reason": None})
        status_rows.append(rows)
    return status_rows


def _scope_presence_details(details: dict, role: str) -> dict:
    """Оставить в part_presence только поля выбранной камеры."""
    scoped = dict(details)
    if role not in _PRESENCE_ROLE_FIELDS:
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
    for key in _PRESENCE_ROLE_FIELDS[other].values():
        scoped[key] = None
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
        if any(isinstance(rd, dict) and rd.get("skipped") for rd in per_role.values()):
            skipped = True
            detail = "Правило отключено"

    detail_lines = []
    if has_per_role and triggered:
        detail_lines = _detail_lines(rule_name, per_role)
        if detail_lines:
            detail = "; ".join(detail_lines)

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

    status_label, neutral = _status_label(rule_name, triggered, details)

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

    run_cards = [copy.deepcopy(summary_cards)]
    for cards in run_cards:
        for card in cards:
            for metric in card.get("metrics") or []:
                key = metric.get("key")
                if not key:
                    continue
                label = METRIC_PARAM_LABELS.get((rule_name, key))
                if label:
                    metric["label"] = label

    run_status = _fallback_run_status(run_cards)

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
        "part_absent": part_absent,
        "decisive": bool(part_absent or triggered or skipped),
    }
