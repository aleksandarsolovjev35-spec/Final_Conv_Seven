"""Развёрнутые строки телеметрии правила ``top_contacts``."""
from core.rule_report.metrics import Metrics, metric, within



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


def top_contacts_metrics(role_details: dict) -> list:
    """Метрики правила ``top_contacts`` (контакты сверху, 14 шт)."""
    metrics = Metrics()

    found = role_details.get("found")
    found_raw = role_details.get("found_raw")
    if found is not None:
        metrics.add(metric(
            "Валидных контактов, шт", found, 14,
            ok=int(found) == 14, key="found",
        ))
    elif found_raw is not None:
        metrics.add(metric(
            "Найдено контактов, шт", found_raw, 14,
            ok=int(found_raw) == 14, key="found_raw",
        ))
    for group in ("L", "R", "T", "B"):
        check = (role_details.get("group_checks") or {}).get(group) or {}
        deviation = check.get("max_deviation_px")
        allowed = check.get("allowed_deviation_px")
        median = check.get("median_distance_px")
        if median is not None:
            metrics.add(metric(
                f"Группа {group}: медиана дист., px", median,
                unit=" px", key=f"group_{group}_median_px",
            ))
        if deviation is None:
            continue
        metrics.add(metric(
            f"Группа {group}: откл., px", deviation, allowed,
            ok=within(deviation, allowed), unit=" px",
            key=f"group_{group}_deviation_px",
        ))
    items = role_details.get("items") or []
    for it in items:
        idx = int(it.get("index") or 0)
        group = it.get("group") or ""
        distance = it.get("distance_px")
        deviation = it.get("deviation_px")
        allowed = it.get("allowed_deviation_px")
        rect_fits = it.get("rect_fits")
        if idx:
            lab = f"Контакт #{idx} {group}".strip() + ":"
            obj = f"Контакт #{idx} ({group})" if group else f"Контакт #{idx}"
        else:
            lab = f"Контакт {group}:"
            obj = f"Контакт ({group})" if group else None
        if distance is not None:
            metrics.add(metric(
                f"{lab} дист. до края, px", distance,
                unit=" px", key=f"contact_{idx}_distance_px", object=obj,
            ))
        if deviation is not None:
            metrics.add(metric(
                f"{lab} откл., px", deviation, allowed,
                ok=within(deviation, allowed), unit=" px",
                key=f"contact_{idx}_deviation_px", object=obj,
            ))
        if rect_fits is not None:
            metrics.add(metric(
                f"{lab} прямоугольник",
                1 if rect_fits else 0, 1, ok=bool(rect_fits),
                key=f"contact_{idx}_rect_fits", object=obj,
            ))

    return metrics
