"""Развёрнутые строки телеметрии правила ``top_platform``."""
from core.rule_report.metrics import Metrics, metric


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


def top_platform_metrics(role_details: dict) -> list:
    """Метрики правила ``top_platform`` (платформа)."""
    metrics = Metrics()

    placement = {
        "centered": "по центру",
        "shifted": "сдвинут",
        "not_fitted": "не вписался",
    }.get(role_details.get("placement"), role_details.get("placement"))
    if placement:
        metrics.append({
            "label": "положение",
            "value": str(placement),
            "limit": None,
            "ok": role_details.get("placement") == "centered",
            "value_raw": None,
            "limit_raw": None,
            "key": "placement",
        })
    metrics.add(metric(
        "Смещение, px", role_details.get("shift_distance_px"),
        unit=" px", key="shift_distance_px",
    ))
    metrics.add(metric(
        "Угол, °", role_details.get("angle_deg"),
        unit="°", key="angle_deg",
    ))
    metrics.add(metric(
        "Ширина эталона, px", role_details.get("rect_width_px"),
        unit=" px", key="rect_width_px",
    ))
    metrics.add(metric(
        "Высота эталона, px", role_details.get("rect_height_px"),
        unit=" px", key="rect_height_px",
    ))

    return metrics
