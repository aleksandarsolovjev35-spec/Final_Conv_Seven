"""Развёрнутые строки телеметрии правила ``top_platform``."""



def _detail_top_platform(per_role: dict) -> list:
    detail_lines = []
    for role, role_details in per_role.items():
        if not isinstance(role_details, dict):
            continue
        reason = role_details.get("reason")
        if reason == "no_valid_platform":
            detail_lines.append(f"{role}: нет valid platform mask")
            continue
        if reason == "invalid_platform_orientation":
            detail_lines.append(f"{role}: не построена orientation platform")
            continue
        placement = role_details.get("placement") or "not_fitted"
        placement_text = {
            "centered": "по центру",
            "shifted": "сдвинут",
            "not_fitted": "не вписался",
        }.get(placement, str(placement))
        detail_lines.append(
            f"{role}: rectangle "
            f"{float(role_details.get('rect_width_px') or 0):g}x"
            f"{float(role_details.get('rect_height_px') or 0):g} px; "
            f"angle {float(role_details.get('angle_deg') or 0):.1f}°"
        )
        detail_lines.append(
            f"{role}: {placement_text}; shift "
            f"{float(role_details.get('shift_distance_px') or 0):.1f} px"
        )
    return detail_lines
