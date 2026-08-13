"""Карточки замера правила ``window_sinks``."""
from core.rule_report.metrics import Metrics, metric


def window_sinks_metrics(role_details: dict) -> list:
    """Метрики правила ``window_sinks`` (раковины в окнах)."""
    metrics = Metrics()

    hits = role_details.get("hits") or []
    limit = role_details.get("overlap_min_px")
    metrics.add(metric(
        "Пересечений, шт", len(hits), 0,
        ok=not hits, key="overlap_count",
    ))
    for hit in hits:
        sink_idx = hit.get("sink_index")
        win_idx = hit.get("window_index")
        overlap = hit.get("overlap_px")
        if overlap is not None:
            ok = None
            if limit is not None:
                try:
                    ok = float(overlap) < float(limit)
                except (TypeError, ValueError):
                    ok = None
            metrics.add(metric(
                f"Раковина #{sink_idx} → окно #{win_idx}: перехл., px",
                overlap, limit, ok=ok, unit=" px",
                key=f"sink_{sink_idx}_win_{win_idx}_overlap_px",
                object=f"Раковина #{sink_idx} → окно #{win_idx}",
            ))
    if hits:
        worst = max((hit.get("overlap_px") or 0) for hit in hits)
        ok = None
        if limit is not None:
            try:
                ok = float(worst) < float(limit)
            except (TypeError, ValueError):
                ok = False
        metrics.add(metric(
            "Макс. перекрытие, px", worst, limit,
            ok=ok if ok is not None else False, unit=" px",
            key="max_overlap_px",
        ))

    return metrics
