"""Короткие человеческие причины дефектов для оператора."""



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
