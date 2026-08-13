"""Развёрнутые строки телеметрии правила ``window_geometry``."""



def _detail_window_geometry(per_role: dict) -> list:
    detail_lines = []
    for role, role_details in per_role.items():
        if not isinstance(role_details, dict):
            continue
        reason = role_details.get("reason")
        if reason:
            detail_lines.append(
                f"{role}: найдено {int(role_details.get('found') or 0)}/"
                f"{int(role_details.get('expected_count') or 0)}"
            )
            continue
        top_limits = role_details.get("top_limits_px") or [0, 0]
        bottom_limits = role_details.get("bottom_limits_px") or [0, 0]
        detail_lines.append(
            f"{role}: T {float(top_limits[0]):g}-"
            f"{float(top_limits[1]):g} px; B "
            f"{float(bottom_limits[0]):g}-"
            f"{float(bottom_limits[1]):g} px"
        )
        ignored = int(role_details.get("ignored") or 0)
        if ignored:
            detail_lines.append(
                f"{role}: лишних detections показано серым: {ignored}"
            )
        for item in role_details.get("items") or []:
            index = int(item.get("index") or 0)
            if not item.get("valid"):
                detail_lines.append(
                    f"{role} #{index}: нет измерения T/B"
                )
                continue
            suffix = []
            if item.get("top_fail"):
                suffix.append("T вне допуска")
            if item.get("bottom_fail"):
                suffix.append("B вне допуска")
            text = (
                f"{role} #{index}: "
                f"T={float(item.get('top_px') or 0):.1f} px; "
                f"B={float(item.get('bottom_px') or 0):.1f} px"
            )
            if suffix:
                text += "; " + ", ".join(suffix)
            detail_lines.append(text)
    return detail_lines
