"""Развёрнутые строки телеметрии правила ``contacts_long``."""
from core.rule_report.details.common import _reference_missing_lines



def _detail_contacts_long(per_role: dict) -> list:
    detail_lines = []
    for role, role_details in per_role.items():
        if not isinstance(role_details, dict):
            continue
        reason = role_details.get("reason")
        if reason and str(reason).startswith("wrong_count"):
            detail_lines.append(
                f"{role}: найдено {int(role_details.get('found') or 0)}/5"
            )
            continue
        if reason == "invalid_contact_masks":
            indices = ", ".join(
                f"#{index}"
                for index in role_details.get("invalid_mask_indices", [])
            )
            detail_lines.append(
                f"{role}: нет segmentation mask контакта: {indices}"
            )
            continue
        detail_lines.append(
            f"{role}: rectangle {float(role_details.get('rect_width_px') or 0):g}x"
            f"{float(role_details.get('rect_height_px') or 0):g} px"
        )
        ignored = int(role_details.get("ignored") or 0)
        if ignored:
            detail_lines.append(
                f"{role}: лишних contacts показано серым: {ignored}"
            )
        if _reference_missing_lines(role, role_details, detail_lines):
            continue
        gap_max = float(role_details.get("gap_dev_max_px") or 0)
        detail_lines.append(
            f"{role}: заслонка перепад "
            f"{float(role_details.get('damper_open_px') or 0):.1f}/"
            f"{float(role_details.get('damper_open_max_px') or 0):.1f} px; "
            f"стены разброс "
            f"{float(role_details.get('gap_dev_px') or 0):.1f}/{gap_max:.1f} px"
        )
        straight = role_details.get("straight_dev_max_px")
        if straight is not None:
            detail_lines.append(
                f"{role}: прямолинейность (инфо) "
                f"{float(straight):.1f} px"
            )
        for item in role_details.get("items") or []:
            index = int(item.get("index") or 0)
            distance = item.get("omission_distance_px")
            distance_text = (
                f"{float(distance):.1f} px"
                if distance is not None else "—"
            )
            deviation = item.get("gap_deviation_px")
            deviation_text = (
                f"{float(deviation):+.1f}/{gap_max:.1f} px"
                if deviation is not None else "—"
            )
            text = (
                f"{role} #{index}: "
                f"rect {'OK' if item.get('rect_fits') else 'FAIL'}; "
                f"стена {distance_text}; "
                f"Δ стены {deviation_text}"
            )
            detail_lines.append(text)
    return detail_lines
