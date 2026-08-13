"""Развёрнутые строки телеметрии правила ``top_contacts``."""



def _detail_top_contacts(per_role: dict) -> list:
    detail_lines = []
    for role, role_details in per_role.items():
        if not isinstance(role_details, dict):
            continue
        reason = role_details.get("reason")
        if reason and str(reason).startswith("wrong_count"):
            detail_lines.append(
                f"{role}: найдено {int(role_details.get('found_raw') or 0)}/14"
            )
            continue
        if reason == "insufficient_valid_contact_masks":
            detail_lines.append(
                f"{role}: valid contact masks "
                f"{int(role_details.get('found') or 0)}/14"
            )
            indices = role_details.get("invalid_mask_indices", [])
            if indices:
                detail_lines.append(
                    f"{role}: нет segmentation mask: "
                    + ", ".join(f"#{index}" for index in indices)
                )
            continue
        if reason == "no_valid_platform":
            detail_lines.append(f"{role}: нет valid platform mask")
            continue
        if reason == "invalid_platform_bbox":
            detail_lines.append(f"{role}: нет valid platform bbox")
            continue
        if reason == "layout_groups_failed":
            counts = role_details.get("group_counts") or {}
            detail_lines.append(
                f"{role}: layout "
                + ", ".join(
                    f"{group}={int(counts.get(group) or 0)}/"
                    f"{TopContactsRuleCount}"
                    for group, TopContactsRuleCount in (
                        ("L", 5), ("R", 5), ("T", 2), ("B", 2)
                    )
                )
            )
            continue
        ignored = int(role_details.get("ignored") or 0)
        if ignored:
            detail_lines.append(
                f"{role}: лишних contacts показано серым: {ignored}"
            )
        for group in ("L", "R", "T", "B"):
            check = (role_details.get("group_checks") or {}).get(group) or {}
            detail_lines.append(
                f"{role} {group}: distance median "
                f"{float(check.get('median_distance_px') or 0):.1f} px; "
                f"max deviation "
                f"{float(check.get('max_deviation_px') or 0):.1f}/"
                f"{float(check.get('allowed_deviation_px') or 0):.1f} px"
            )
        for item in role_details.get("items") or []:
            detail_lines.append(
                f"{role} #{int(item.get('index') or 0)} {item.get('group')}: "
                f"distance {float(item.get('distance_px') or 0):.1f} px; "
                f"deviation {float(item.get('deviation_px') or 0):.1f}/"
                f"{float(item.get('allowed_deviation_px') or 0):.1f} px; "
                f"rect {float(item.get('rect_width_px') or 0):g}x"
                f"{float(item.get('rect_height_px') or 0):g} px "
                f"{'OK' if item.get('rect_fits') else 'FAIL'}"
            )
    return detail_lines
