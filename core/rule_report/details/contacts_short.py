"""Развёрнутые строки телеметрии правила ``contacts_short``."""
from core.rule_report.details.common import _reference_missing_lines



def _detail_contacts_short(per_role: dict) -> list:
    detail_lines = []
    for role, role_details in per_role.items():
        if not isinstance(role_details, dict):
            continue
        reason = role_details.get("reason")
        if reason and str(reason).startswith("wrong_count"):
            detail_lines.append(
                f"{role}: найдено {int(role_details.get('found') or 0)}/2; "
                f"area min "
                f"{float(role_details.get('area_absolute_min_px2') or 0):g} px²"
            )
            invalid_indices = role_details.get(
                "invalid_mask_indices", []
            )
            if invalid_indices:
                detail_lines.append(
                    f"{role}: нет segmentation mask контакта: "
                    + ", ".join(
                        f"#{index}" for index in invalid_indices
                    )
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
            f"{role}: area min "
            f"{float(role_details.get('area_absolute_min_px2') or 0):g} px²; "
            f"rectangle "
            f"{float(role_details.get('rect_width_px') or 0):g}x"
            f"{float(role_details.get('rect_height_px') or 0):g} px"
        )
        ignored = int(role_details.get("ignored") or 0)
        if ignored:
            detail_lines.append(
                f"{role}: лишних contacts показано серым: {ignored}"
            )
        if _reference_missing_lines(role, role_details, detail_lines):
            continue
        detail_lines.append(
            f"{role}: заслонка открытие "
            f"{float(role_details.get('damper_open_px') or 0):.1f}/"
            f"{float(role_details.get('damper_open_max_px') or 0):.1f} px"
        )
        straight = role_details.get("straight_delta_y_px")
        if straight is not None:
            detail_lines.append(
                f"{role}: Δцентров по Y (инфо) {float(straight):.1f} px"
            )
        for item in role_details.get("items") or []:
            distance = item.get("omission_distance_px")
            distance_text = (
                f"{float(distance):.1f} px"
                if distance is not None else "—"
            )
            detail_lines.append(
                f"{role} #{int(item.get('index') or 0)}: "
                f"top={float(item.get('top_y') or 0):.1f}; "
                f"bottom={float(item.get('bottom_y') or 0):.1f}; "
                f"height={float(item.get('height_px') or 0):.1f} px; "
                f"rect {'OK' if item.get('rect_fits') else 'FAIL'}; "
                f"стена {distance_text}"
            )
    return detail_lines
