"""Консольное логирование результатов правил дефектов.

Заменяет прежний отчёт по правилам: вместо строк и карточек для HMI
каждый результат печатается одной строкой в консоль.
"""

from __future__ import annotations


def _role_parts(details: dict) -> list[str]:
    parts = []
    per_role = details.get("per_role")
    if isinstance(per_role, dict):
        for role, role_details in per_role.items():
            if not isinstance(role_details, dict):
                continue
            if role_details.get("skipped"):
                parts.append(f"{role}=skip")
                continue
            status = "fail" if role_details.get("triggered") else "ok"
            reason = role_details.get("reason")
            if reason:
                parts.append(f"{role}={status}({reason})")
            else:
                parts.append(f"{role}={status}")
    return parts


def format_rule_result(stage: str, result) -> str:
    """Строка лога для одного результата правила."""
    name = str(getattr(result, "rule_name", "") or "?")
    triggered = bool(getattr(result, "triggered", False))
    details = getattr(result, "details", None)
    if not isinstance(details, dict):
        details = {}

    prefix = f"[RULES] {stage} {name}:"
    if details.get("skipped"):
        return f"{prefix} SKIP"

    status = "FAIL" if triggered else "OK"
    if name == "part_presence":
        empty_tray = bool(details.get("empty_tray"))
        return f"{prefix} {status} empty_tray={empty_tray}"

    parts = _role_parts(details)
    if parts:
        return f"{prefix} {status} " + " ".join(parts)
    return f"{prefix} {status}"


def log_rule_result(stage: str, result) -> None:
    print(format_rule_result(stage, result))


def log_rule_results(stage: str, results) -> None:
    for result in results or ():
        log_rule_result(stage, result)
