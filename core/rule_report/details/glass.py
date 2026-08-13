"""Карточки замера правил ``glass`` и ``glass_on_contacts``."""
from core.rule_report.metrics import Metrics, metric


def glass_metrics(role_details: dict) -> list:
    """Метрики правила ``glass`` (стекло)."""
    metrics = Metrics()

    hits = role_details.get("hits") or []
    metrics.add(metric(
        "Совпадений стекла, шт", len(hits), 0,
        ok=not hits, key="glass_hits",
    ))
    for hit in hits:
        idx = hit.get("glass_index")
        obj = f"Стекло #{idx}"
        plat = hit.get("platform_overlap_px")
        pin = hit.get("pin_overlap_px")
        ring = hit.get("ring_overlap_px")
        union = hit.get("cleanup_overlap_px")
        if plat is not None:
            metrics.add(metric(
                f"Стекло #{idx}: платформа, px", plat,
                unit=" px", key=f"glass_{idx}_platform_px", object=obj,
            ))
        if pin is not None:
            metrics.add(metric(
                f"Стекло #{idx}: пины, px", pin,
                unit=" px", key=f"glass_{idx}_pin_px", object=obj,
            ))
        if ring is not None:
            metrics.add(metric(
                f"Стекло #{idx}: кольцо, px", ring,
                unit=" px", key=f"glass_{idx}_ring_px", object=obj,
            ))
        if union is not None:
            metrics.add(metric(
                f"Стекло #{idx}: union, px", union,
                unit=" px", key=f"glass_{idx}_union_px", object=obj,
            ))

    return metrics


def glass_on_contacts_metrics(role_details: dict) -> list:
    """Метрики правила ``glass_on_contacts`` (стекло на контактах)."""
    metrics = Metrics()

    pairs = role_details.get("pairs") or []
    hits = role_details.get("hits")
    if isinstance(hits, int):
        metrics.add(metric("Стекла, шт", hits, unit="", key="glass_count"))
    pins = role_details.get("pins_found")
    if pins is not None:
        metrics.add(metric(
            "Пинов, шт", pins, 14,
            ok=int(pins) == 14, key="pins_found",
        ))
    metrics.add(metric(
        "Пар стекло/контакт, шт", len(pairs), 0,
        ok=not pairs, key="glass_contact_pairs",
    ))
    for pair in pairs:
        g_idx = pair.get("glass_index")
        c_idx = pair.get("contact_index")
        overlap = pair.get("overlap_pixels")
        if overlap is not None:
            metrics.add(metric(
                f"Стекло #{g_idx} → контакт #{c_idx}: перехл., px",
                overlap, unit=" px",
                key=f"glass_{g_idx}_contact_{c_idx}_overlap_px",
                object=f"Стекло #{g_idx} → контакт #{c_idx}",
            ))

    return metrics
