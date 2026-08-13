"""Общие помощники форматтеров детальной телеметрии."""


def _reference_missing_lines(role, role_details, detail_lines):
    reason = role_details.get("reason")
    if reason in ("no_valid_omission_top_line", "omission_reference_too_short"):
        detail_lines.append(
            f"{role}: нет опорной линии пропуска ({reason})"
        )
        return True
    return False
