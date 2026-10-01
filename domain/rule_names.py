"""Имена defect rules для списка ``disabled_rules`` в ``thresholds.json``.

У каждого правила есть внутреннее имя (``BaseRule.name``) и имя группы
порогов, под которым его параметры лежат в ``thresholds.json`` и редакторе
порогов HMI (например, ``window_geometry`` и ``input_window_geometry``).
Раньше ``disabled_rules`` понимал только внутреннее имя, а имя группы
порогов молча игнорировалось — правило продолжало работать. Теперь
принимаются оба варианта, а неизвестное имя даёт явную ошибку загрузки.

Модуль без тяжёлых зависимостей: его импортирует и загрузчик порогов,
и базовый класс правил.
"""

PART_PRESENCE_RULE = "part_presence"

# Внутренние имена правил, которые можно отключить (порядок как в HMI).
DISABLEABLE_RULES = (
    "window_geometry",
    "window_sinks",
    "contacts_long",
    "long_omission",
    "contacts_short",
    "short_omission",
    "black_spots_omission",
    "top_contacts",
    "platform_contacts_overlap",
    "top_platform",
    "sinks",
    "glass",
    "glass_on_contacts",
)

# Имя группы порогов (thresholds.json / HMI) -> внутреннее имя правила.
RULE_ALIASES = {
    "input_part_presence": PART_PRESENCE_RULE,
    "input_window_geometry": "window_geometry",
    "input_window_sinks": "window_sinks",
    "spider_contacts_long": "contacts_long",
    "spider_long_omission": "long_omission",
    "spider_contacts_short": "contacts_short",
    "spider_short_omission": "short_omission",
    "top_platform_overlap": "platform_contacts_overlap",
    "top_sinks": "sinks",
    "top_glass": "glass",
}


def canonical_rule_name(name) -> str:
    """Привести имя из ``disabled_rules`` к внутреннему имени правила."""
    text = str(name).strip()
    return RULE_ALIASES.get(text, text)


def normalize_disabled_rules(names) -> set:
    """Множество внутренних имён отключённых правил."""
    return {canonical_rule_name(name) for name in (names or ())}


def describe_allowed_names() -> str:
    """Подсказка для сообщения об ошибке: какие имена допустимы."""
    aliases = {}
    for alias, rule in RULE_ALIASES.items():
        aliases.setdefault(rule, []).append(alias)
    parts = []
    for rule in DISABLEABLE_RULES:
        extra = aliases.get(rule)
        parts.append(f"{rule} ({', '.join(extra)})" if extra else rule)
    return ", ".join(parts)
