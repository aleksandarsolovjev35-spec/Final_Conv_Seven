"""Развёрнутые строки телеметрии правила ``window_geometry``."""
from core.rule_report.metrics import Metrics, finite_numbers, metric, number



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


def window_geometry_metrics(role_details: dict) -> list:
    """Метрики правила ``window_geometry`` (геометрия входного окна, 7 окон)."""
    metrics = Metrics()

    top_limits = role_details.get("top_limits_px") or []
    bottom_limits = role_details.get("bottom_limits_px") or []
    top_values = list(role_details.get("top_values_px") or [])
    bottom_values = list(role_details.get("bottom_values_px") or [])
    items = list(role_details.get("items") or [])

    if not top_values and items:
        top_values = [
            it.get("top_px") for it in sorted(
                items, key=lambda row: int(row.get("index") or 0),
            )
            if it.get("top_px") is not None
        ]
    if not bottom_values and items:
        bottom_values = [
            it.get("bottom_px") for it in sorted(
                items, key=lambda row: int(row.get("index") or 0),
            )
            if it.get("bottom_px") is not None
        ]

    found = role_details.get("found")
    expected = role_details.get("expected_count") or 7
    if found is not None:
        metrics.add(metric(
            "Найдено окон, шт", found, expected,
            ok=int(found) == int(expected), key="found",
        ))

    top_nums = finite_numbers(top_values)
    bottom_nums = finite_numbers(bottom_values)
    if len(top_limits) == 2 and top_nums:
        min_top = min(top_nums)
        max_top = max(top_nums)
        metrics.add(metric(
            "T до перекладины: мин., px", min_top, top_limits[0],
            ok=min_top >= float(top_limits[0]), unit=" px",
            key="top_px_min",
        ))
        metrics.add(metric(
            "T до перекладины: макс., px", max_top, top_limits[1],
            ok=max_top <= float(top_limits[1]), unit=" px",
            key="top_px_max",
        ))
    if len(bottom_limits) == 2 and bottom_nums:
        min_bottom = min(bottom_nums)
        max_bottom = max(bottom_nums)
        metrics.add(metric(
            "B после перекладины: мин., px", min_bottom, bottom_limits[0],
            ok=min_bottom >= float(bottom_limits[0]), unit=" px",
            key="bottom_px_min",
        ))
        metrics.add(metric(
            "B после перекладины: макс., px", max_bottom, bottom_limits[1],
            ok=max_bottom <= float(bottom_limits[1]), unit=" px",
            key="bottom_px_max",
        ))

    by_index = {
        int(it.get("index") or 0): it
        for it in items
        if int(it.get("index") or 0) > 0
    }
    max_windows = max(len(top_values), len(bottom_values), len(by_index), 0)
    for idx in range(1, max_windows + 1):
        if idx > 14:
            break
        it = by_index.get(idx)
        t = None
        b = None
        if idx - 1 < len(top_values):
            try:
                t = float(top_values[idx - 1])
            except (TypeError, ValueError):
                t = None
        if idx - 1 < len(bottom_values):
            try:
                b = float(bottom_values[idx - 1])
            except (TypeError, ValueError):
                b = None
        if t is None and it is not None and it.get("top_px") is not None:
            try:
                t = float(it.get("top_px"))
            except (TypeError, ValueError):
                t = None
        if b is None and it is not None and it.get("bottom_px") is not None:
            try:
                b = float(it.get("bottom_px"))
            except (TypeError, ValueError):
                b = None

        obj = f"Окно #{idx}"
        if t is not None:
            nearest_top = None
            top_ok = None
            if len(top_limits) == 2:
                try:
                    low, high = float(top_limits[0]), float(top_limits[1])
                    top_ok = low <= float(t) <= high
                    if float(t) < low:
                        nearest_top = low
                    elif float(t) > high:
                        nearest_top = high
                    else:
                        nearest_top = (
                            low if abs(float(t) - low) <= abs(high - float(t))
                            else high
                        )
                except (TypeError, ValueError):
                    nearest_top = None
            item = metric(
                f"Окно #{idx}: верх, px", t, nearest_top,
                ok=top_ok, unit=" px",
                key=f"window_{idx}_top_px", object=obj,
            )
            if item is not None and len(top_limits) == 2:
                item["limit"] = (
                    f"{number(top_limits[0])}-{number(top_limits[1])} px"
                )
            metrics.add(item)

        if b is not None:
            nearest_bot = None
            bottom_ok = None
            if len(bottom_limits) == 2:
                try:
                    low, high = float(bottom_limits[0]), float(bottom_limits[1])
                    bottom_ok = low <= float(b) <= high
                    if float(b) < low:
                        nearest_bot = low
                    elif float(b) > high:
                        nearest_bot = high
                    else:
                        nearest_bot = (
                            low if abs(float(b) - low) <= abs(high - float(b))
                            else high
                        )
                except (TypeError, ValueError):
                    nearest_bot = None
            item = metric(
                f"Окно #{idx}: низ, px", b, nearest_bot,
                ok=bottom_ok, unit=" px",
                key=f"window_{idx}_bottom_px", object=obj,
            )
            if item is not None and len(bottom_limits) == 2:
                item["limit"] = (
                    f"{number(bottom_limits[0])}-"
                    f"{number(bottom_limits[1])} px"
                )
            metrics.add(item)

        if it is not None:
            top_fail = it.get("top_fail")
            bottom_fail = it.get("bottom_fail")
            valid = it.get("valid")
            if top_fail is not None or bottom_fail is not None or valid is False:
                ok = bool(valid is not False) and not (
                    top_fail or bottom_fail
                )
                metrics.add(metric(
                    f"Окно #{idx}: в допуске",
                    1 if ok else 0, 1, ok=ok,
                    key=f"window_{idx}_ok", object=obj,
                ))

    if items:
        bad = [
            it for it in items
            if not it.get("valid")
            or it.get("top_fail")
            or it.get("bottom_fail")
        ]
        metrics.add(metric(
            "Окон вне допуска, шт", len(bad), 0,
            ok=not bad, key="windows_out_of_tolerance",
        ))

    return metrics
