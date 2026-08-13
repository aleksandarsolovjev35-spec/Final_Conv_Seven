"""Развёрнутые строки телеметрии правила ``contacts_long``."""
from core.rule_report.details.common import _reference_missing_lines
from core.rule_report.metrics import Metrics, metric, within



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


def contacts_long_metrics(role_details: dict) -> list:
    """Метрики правила ``contacts_long`` (длинные контакты, 5 шт)."""
    metrics = Metrics()

    expected = role_details.get("expected_count") or 5
    found = role_details.get("found")
    if found is not None:
        metrics.add(metric(
            "Найдено контактов, шт", found, expected,
            ok=int(found) == int(expected),
            key="found",
        ))
    damper_open = role_details.get("damper_open_px")
    damper_open_max = role_details.get("damper_open_max_px")
    gap_dev = role_details.get("gap_dev_px")
    gap_dev_max = role_details.get("gap_dev_max_px")
    if damper_open is None and damper_open_max is not None:
        metrics.add(metric(
            "Порог заслонки, px", damper_open_max, unit=" px",
            key="damper_open_max_px",
        ))
    else:
        metrics.add(metric(
            "Заслонка: перепад, px", damper_open, damper_open_max,
            ok=within(damper_open, damper_open_max),
            unit=" px", key="damper_open_max_px",
        ))
    if gap_dev is None and gap_dev_max is not None:
        metrics.add(metric(
            "Порог разброса стен, px", gap_dev_max, unit=" px",
            key="gap_dev_max_px",
        ))
    else:
        metrics.add(metric(
            "Стены: разброс, px", gap_dev, gap_dev_max,
            ok=within(gap_dev, gap_dev_max),
            unit=" px", key="gap_dev_max_px",
        ))
    straight = role_details.get("straight_dev_max_px")
    if straight is not None:
        metrics.add(metric(
            "Прямолинейность (инфо), px", straight,
            unit=" px", key="straight_dev_max_px",
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
        gap_distance = it.get("omission_distance_px")
        gap_deviation = it.get("gap_deviation_px")
        straight_dev = it.get("straight_dev_px")
        rect_fits = it.get("rect_fits")
        if gap_distance is not None:
            metrics.add(metric(
                f"Контакт #{idx}: расстояние до линии пропуска, px",
                gap_distance, unit=" px",
                key=f"contact_{idx}_omission_dist_px", object=obj,
            ))
        if gap_deviation is not None:
            metrics.add(metric(
                f"Контакт #{idx}: Δ стены, px", gap_deviation,
                gap_dev_max,
                ok=within(abs(float(gap_deviation)), gap_dev_max),
                unit=" px",
                key=f"contact_{idx}_gap_dev_px", object=obj,
            ))
        if straight_dev is not None:
            metrics.add(metric(
                f"Контакт #{idx}: прямолинейность (инфо), px",
                straight_dev, unit=" px",
                key=f"contact_{idx}_straight_dev_px", object=obj,
            ))
        if rect_fits is not None:
            metrics.add(metric(
                f"Контакт #{idx}: прямоугольник",
                1 if rect_fits else 0, 1, ok=bool(rect_fits),
                key=f"contact_{idx}_rect_fits", object=obj,
            ))

    return metrics
