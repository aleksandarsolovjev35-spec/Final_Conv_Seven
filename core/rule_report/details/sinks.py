"""Карточки замера правила ``sinks``."""
from core.rule_report.metrics import Metrics, metric


def sinks_metrics(role_details: dict) -> list:
    """Метрики правила ``sinks`` (раковины корпуса)."""
    metrics = Metrics()

    hits = role_details.get("hits") or []
    metrics.add(metric(
        "Пересечений, шт", len(hits), 0,
        ok=not hits, key="sinks_hits",
    ))
    for hit in hits:
        idx = hit.get("sink_index")
        obj = f"Раковина #{idx}"
        forbidden = hit.get("forbidden_pixels")
        central = hit.get("central_overlap_px")
        platform = hit.get("platform_overlap_px")
        contacts = hit.get("contacts_overlap_px")
        if forbidden is not None:
            metrics.add(metric(
                f"Shell #{idx}: запрещ., px", forbidden,
                unit=" px", key=f"shell_{idx}_forbidden_px", object=obj,
            ))
        if central is not None:
            metrics.add(metric(
                f"Shell #{idx}: центр. перехл., px", central,
                unit=" px", key=f"shell_{idx}_central_px", object=obj,
            ))
        if platform is not None:
            metrics.add(metric(
                f"Shell #{idx}: платформа, px", platform,
                unit=" px", key=f"shell_{idx}_platform_px", object=obj,
            ))
        if contacts is not None:
            metrics.add(metric(
                f"Shell #{idx}: контакты, px", contacts,
                unit=" px", key=f"shell_{idx}_contacts_px", object=obj,
            ))

    return metrics
