"""Развёрнутые строки телеметрии правила ``contacts_short``."""
from core.rule_report.details.common import _reference_missing_lines
from core.rule_report.metrics import Metrics, metric, within


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


def contacts_short_metrics(role_details: dict) -> list:
    """Метрики правила ``contacts_short`` (короткие контакты, 2 шт)."""
    metrics = Metrics()

    expected = role_details.get("expected_count") or 2
    found = role_details.get("found")
    if found is not None:
        metrics.add(metric(
            "Найдено контактов, шт", found, expected,
            ok=int(found) == int(expected),
            key="found",
        ))
    area_min = role_details.get("area_absolute_min_px2")
    if area_min is not None:
        metrics.add(metric(
            "Мин. площадь, px²", area_min, unit=" px²",
            key="area_absolute_min_px2",
        ))
    damper_open = role_details.get("damper_open_px")
    damper_open_max = role_details.get("damper_open_max_px")
    if damper_open is None and damper_open_max is not None:
        metrics.add(metric(
            "Порог заслонки, px", damper_open_max, unit=" px",
            key="damper_open_max_px",
        ))
    else:
        metrics.add(metric(
            "Заслонка: открытие, px", damper_open, damper_open_max,
            ok=within(damper_open, damper_open_max),
            unit=" px", key="damper_open_max_px",
        ))
    straight = role_details.get("straight_delta_y_px")
    if straight is not None:
        metrics.add(metric(
            "Δцентров по Y (инфо), px", straight,
            unit=" px", key="straight_delta_y_px",
        ))
    if role_details.get("rect_width_px") is not None:
        metrics.add(metric(
            "Ширина эталона, px", role_details.get("rect_width_px"),
            unit=" px", key="rect_width_px",
        ))
    if role_details.get("rect_height_px") is not None:
        metrics.add(metric(
            "Высота эталона, px", role_details.get("rect_height_px"),
            unit=" px", key="rect_height_px",
        ))
    items = role_details.get("items") or []
    for it in items:
        idx = int(it.get("index") or 0)
        if not idx:
            continue
        obj = f"Контакт #{idx}"
        top_y = it.get("top_y")
        bottom_y = it.get("bottom_y")
        height = it.get("height_px")
        rect_fits = it.get("rect_fits")
        omission = it.get("omission_distance_px")
        if top_y is not None:
            metrics.add(metric(
                f"Контакт #{idx}: верх, px", top_y,
                unit=" px", key=f"contact_{idx}_top_y", object=obj,
            ))
        if bottom_y is not None:
            metrics.add(metric(
                f"Контакт #{idx}: низ, px", bottom_y,
                unit=" px", key=f"contact_{idx}_bottom_y", object=obj,
            ))
        if height is not None:
            metrics.add(metric(
                f"Контакт #{idx}: высота, px", height,
                unit=" px", key=f"contact_{idx}_height_px", object=obj,
            ))
        if rect_fits is not None:
            metrics.add(metric(
                f"Контакт #{idx}: прямоугольник",
                1 if rect_fits else 0, 1, ok=bool(rect_fits),
                key=f"contact_{idx}_rect_fits", object=obj,
            ))
        if omission is not None:
            metrics.add(metric(
                f"Контакт #{idx}: расстояние до линии пропуска, px",
                omission, unit=" px",
                key=f"contact_{idx}_omission_dist_px", object=obj,
            ))

    return metrics
