"""Короткие человеческие причины дефектов для оператора."""

ROLE_REASON_TEXT = {
    "no_valid_platform": "не найдена платформа",
    "invalid_platform_bbox": "некорректная платформа",
    "invalid_platform_orientation": "не определена ориентация",
    "invalid_contact_masks": "нет масок контактов",
    "insufficient_valid_contact_masks": "мало валидных контактов",
    "insufficient_valid_contacts": "мало валидных контактов",
    "invalid_contact_layout": "нарушена раскладка контактов",
    "layout_groups_failed": "нарушена раскладка контактов",
    "missing_glass_mask": "нет маски стекла",
    "missing_pin_mask": "нет маски штифта",
    "empty_case_ring": "пустое кольцо корпуса",
    "case_central_not_inside_case": "смещён центр корпуса",
    "inner_platform_reference_not_fitted": "не построен эталон платформы",
    "contact_boundary_not_built": "область по контактам не построена",
}


def role_reason_text(reason) -> str:
    """Перевести машинный ``reason`` роли в короткую подпись вердикта."""
    if not reason:
        return ""
    text = str(reason)
    if text in ROLE_REASON_TEXT:
        return ROLE_REASON_TEXT[text]
    if text.startswith("wrong_count"):
        return "неверное количество объектов"
    if text.startswith("wrong_pin_count"):
        return "неверное количество пинов"
    if text.startswith("invalid_case"):
        return "некорректный корпус"
    return text.replace("_", " ")


# === Упрощённые человеческие причины дефектов (для быстрого понимания оператором) ===
HUMAN_CAUSE_MAP = {
    # INPUT
    ("window_geometry", True): "НЕПРАВИЛЬНАЯ ГЕОМЕТРИЯ ОКОН",
    ("window_sinks", True): "РАКОВИНА В ОКНЕ",
    # SPIDER
    ("contacts_long", True): "НАКЛОН / СМЕЩЕНИЕ ДЛИННЫХ КОНТАКТОВ",
    ("contacts_short", True): "НАКЛОН / СМЕЩЕНИЕ КОРОТКИХ КОНТАКТОВ",
    ("long_omission", True): "ИЗБЫТОЧНАЯ ТОЛЩИНА ДЛИННОЙ ПОЛОСЫ ПРОПУСКА",
    ("short_omission", True): "ИЗБЫТОЧНАЯ ТОЛЩИНА КОРОТКОЙ ПОЛОСЫ ПРОПУСКА",
    # TOP
    ("top_contacts", True): "СМЕЩЕНИЕ КОНТАКТОВ НА ПЛАТФОРМЕ",
    ("top_platform", True): "ПЛАТФОРМА НЕ ВПИСАЛАСЬ",
    ("platform_contacts_overlap", True): "ЗАПЛЫВ ПЛАТФОРМЫ",
    ("sinks", True): "РАКОВИНА ВНУТРИ КОРПУСА",
    ("glass", True): "СТЕКЛО НА ПЛАТФОРМЕ / ШТИФТАХ",

    ("glass_on_contacts", True): "СТЕКЛО НА КОНТАКТАХ",
}


def get_human_cause(rule_name: str, triggered: bool, details: dict) -> str | None:
    """Возвращает короткую читаемую причину дефекта."""
    if not triggered:
        return None

    key = (rule_name, True)
    if key in HUMAN_CAUSE_MAP:
        return HUMAN_CAUSE_MAP[key]

    # Fallback: пытаемся вытащить самую важную причину
    per_role = details.get("per_role") or {}
    reasons = []
    for role, rd in per_role.items():
        if isinstance(rd, dict) and rd.get("triggered"):
            r = rd.get("reason")
            if r:
                reasons.append(str(r))
            # для некоторых правил берём первую проблему
            if rule_name in ("window_sinks", "sinks", "glass_on_contacts"):
                # ``glass_on_contacts.hits`` is a count, while its overlap
                # rows live in ``pairs``.  Prefer the rows and only iterate
                # values that actually follow the collection contract.
                entries = rd.get("pairs") or rd.get("hits") or []
                if not isinstance(entries, (list, tuple)):
                    entries = []
                for hit in entries:
                    if hit:
                        reasons.append("пересечение")
                        break

    if reasons:
        return reasons[0].upper().replace("_", " ")[:60]
    return "ДЕФЕКТ"
