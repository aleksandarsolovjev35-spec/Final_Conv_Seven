"""Развёрнутые строки телеметрии правила ``platform_contacts_overlap``."""
from core.rule_report.metrics import Metrics, metric



def _detail_platform_overlap(per_role: dict) -> list:
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
        if reason == "contact_boundary_not_built":
            groups = role_details.get("contact_groups") or {}
            group_text = "/".join(
                f"{side}{int(groups.get(side) or 0)}"
                for side in ("L", "R", "T", "B")
            )
            detail_lines.append(
                f"{role}: область по контактам не построена "
                f"({group_text})"
            )
            continue
        detail_lines.append(
            f"{role}: boundary "
            f"{float(role_details.get('boundary_width_px') or 0):g}x"
            f"{float(role_details.get('boundary_height_px') or 0):g} px; "
            f"component min "
            f"{int(role_details.get('excess_component_min_px') or 0)} px; "
            f"contacts {int(role_details.get('used_contacts') or 0)}"
        )
        detail_lines.append(
            f"{role}: largest component "
            f"{int(role_details.get('largest_component_pixels') or 0)} px; "
            f"confirmed "
            f"{int(role_details.get('excess_pixels') or 0)} px"
        )
    return detail_lines


def platform_contacts_overlap_metrics(role_details: dict) -> list:
    """Метрики правила ``platform_contacts_overlap`` (заплыв платформы)."""
    metrics = Metrics()

    metrics.add(metric(
        "Заплыв, px", role_details.get("excess_pixels"),
        role_details.get("excess_component_min_px"),
        ok=not role_details.get("triggered"), unit=" px",
        key="excess_component_min_px",
    ))
    metrics.add(metric(
        "Макс. компонент, px",
        role_details.get("largest_component_pixels"),
        unit=" px", key="largest_component_px",
    ))
    metrics.add(metric(
        "Контакты области, шт", role_details.get("used_contacts"),
        unit="", key="used_contacts",
    ))
    metrics.add(metric(
        "Ширина области, px", role_details.get("boundary_width_px"),
        unit=" px", key="boundary_width_px",
    ))
    metrics.add(metric(
        "Высота области, px", role_details.get("boundary_height_px"),
        unit=" px", key="boundary_height_px",
    ))

    return metrics
