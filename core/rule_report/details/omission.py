"""Развёрнутые строки телеметрии правил omission (``long_omission`` / ``short_omission``)."""



def _detail_omission(per_role: dict) -> list:
    detail_lines = []
    for role, role_details in per_role.items():
        if not isinstance(role_details, dict):
            continue
        reason = role_details.get("reason")
        if reason:
            detail_lines.append(
                f"{role}: нет valid omission reference ({reason})"
            )
            continue
        line = (
            f"{role}: толщина "
            f"{float(role_details.get('allowed_thickness_px') or 0):.1f} px; "
            f"component min "
            f"{int(role_details.get('excess_component_min_px') or 0)} px; "
            f"residual "
            f"{float(role_details.get('top_line_actual_max_residual_px') or 0):.1f}/"
            f"{float(role_details.get('top_line_max_residual_px') or 0):.1f} px"
        )
        ratio_actual = role_details.get("top_line_actual_inlier_ratio")
        ratio_limit = role_details.get("top_line_min_inlier_ratio")
        if ratio_actual is not None and ratio_limit is not None:
            line += (
                f"; доля у линии "
                f"{float(ratio_actual):.2f}/{float(ratio_limit):.2f}"
            )
        detail_lines.append(line)

        detail_lines.append(
            f"{role}: largest component "
            f"{int(role_details.get('largest_component_pixels') or 0)} px; "
            f"confirmed "
            f"{int(role_details.get('excess_pixels') or 0)} px; "
            f"max depth "
            f"{float(role_details.get('max_excess_depth_px') or 0):.1f} px"
        )
    return detail_lines
