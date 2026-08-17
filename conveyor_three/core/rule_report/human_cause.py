"""Человекочитаемые причины дефектов (3 камеры)."""

from core.rule_report.constants import HUMAN_CAUSE_MAP


def get_human_cause(rule_name: str, triggered: bool, details: dict) -> str | None:
    """Короткая читаемая причина дефекта."""
    if not triggered:
        return None
    key = (rule_name, True)
    if key in HUMAN_CAUSE_MAP:
        return HUMAN_CAUSE_MAP[key]
    return "ДЕФЕКТ"
