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


# Замеры окна: T — расстояние до перекладины, B — после неё. Обе стороны
# считаются одинаково, поэтому параметры вынесены в таблицу, а не
# продублированы двумя ветками кода.
_SIDES = (
    ("top", "Окно #%d: верх, px", "window_%d_top_px"),
    ("bottom", "Окно #%d: низ, px", "window_%d_bottom_px"),
)

# Правило рассчитано на семь окон; ограничение защищает панель HMI от
# аномального результата детектора.
MAX_WINDOWS = 14


def _to_float(value):
    """Число или ``None``: телеметрия может прийти строкой или пустой."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ordered_values(items: list, key: str) -> list:
    """Значения по индексу окна, если правило не прислало готовый список."""
    return [
        item.get(key) for item in sorted(
            items, key=lambda row: int(row.get("index") or 0),
        )
        if item.get(key) is not None
    ]


def _range_check(value, limits):
    """``(в допуске, ближайшая граница)`` для значения внутри диапазона."""
    if len(limits) != 2:
        return None, None
    low, high = _to_float(limits[0]), _to_float(limits[1])
    if low is None or high is None:
        return None, None
    if value < low:
        return False, low
    if value > high:
        return False, high
    # Внутри допуска показываем ближнюю границу: видно, к чему идёт дрейф.
    nearest = low if abs(value - low) <= abs(high - value) else high
    return True, nearest


def _range_metrics(metrics, label: str, key: str, values: list, limits: list):
    """Минимум и максимум стороны против её допуска."""
    numbers = finite_numbers(values)
    if len(limits) != 2 or not numbers:
        return
    low, high = _to_float(limits[0]), _to_float(limits[1])
    if low is None or high is None:
        return
    smallest, largest = min(numbers), max(numbers)
    metrics.add(metric(
        f"{label}: мин., px", smallest, limits[0],
        ok=smallest >= low, unit=" px", key=f"{key}_min",
    ))
    metrics.add(metric(
        f"{label}: макс., px", largest, limits[1],
        ok=largest <= high, unit=" px", key=f"{key}_max",
    ))


def _window_metric(index: int, value, limits: list, label: str, key: str):
    """Замер одного окна с диапазоном допуска в поле ``limit``."""
    ok, nearest = _range_check(value, limits)
    item = metric(
        label % index, value, nearest, ok=ok, unit=" px",
        key=key % index, object=f"Окно #{index}",
    )
    if item is not None and len(limits) == 2:
        item["limit"] = f"{number(limits[0])}-{number(limits[1])} px"
    return item


def window_geometry_metrics(role_details: dict) -> list:
    """Метрики правила ``window_geometry`` (геометрия входного окна, 7 окон)."""
    metrics = Metrics()
    items = list(role_details.get("items") or [])

    limits = {
        "top": list(role_details.get("top_limits_px") or []),
        "bottom": list(role_details.get("bottom_limits_px") or []),
    }
    values = {
        side: list(role_details.get(f"{side}_values_px") or [])
        or (_ordered_values(items, f"{side}_px") if items else [])
        for side, _label, _key in _SIDES
    }

    found = role_details.get("found")
    expected = role_details.get("expected_count") or 7
    if found is not None:
        metrics.add(metric(
            "Найдено окон, шт", found, expected,
            ok=int(found) == int(expected), key="found",
        ))

    _range_metrics(
        metrics, "T до перекладины", "top_px",
        values["top"], limits["top"],
    )
    _range_metrics(
        metrics, "B после перекладины", "bottom_px",
        values["bottom"], limits["bottom"],
    )

    by_index = {
        int(item.get("index") or 0): item
        for item in items
        if int(item.get("index") or 0) > 0
    }
    window_count = min(
        max(len(values["top"]), len(values["bottom"]), len(by_index), 0),
        MAX_WINDOWS,
    )

    for index in range(1, window_count + 1):
        item = by_index.get(index)
        for side, label, key in _SIDES:
            side_values = values[side]
            value = (
                _to_float(side_values[index - 1])
                if index - 1 < len(side_values) else None
            )
            if value is None and item is not None:
                value = _to_float(item.get(f"{side}_px"))
            if value is None:
                continue
            metrics.add(
                _window_metric(index, value, limits[side], label, key)
            )

        if item is None:
            continue
        top_fail = item.get("top_fail")
        bottom_fail = item.get("bottom_fail")
        valid = item.get("valid")
        if top_fail is None and bottom_fail is None and valid is not False:
            continue
        ok = valid is not False and not (top_fail or bottom_fail)
        metrics.add(metric(
            f"Окно #{index}: в допуске", 1 if ok else 0, 1, ok=ok,
            key=f"window_{index}_ok", object=f"Окно #{index}",
        ))

    if items:
        bad = [
            item for item in items
            if not item.get("valid")
            or item.get("top_fail")
            or item.get("bottom_fail")
        ]
        metrics.add(metric(
            "Окон вне допуска, шт", len(bad), 0,
            ok=not bad, key="windows_out_of_tolerance",
        ))

    return metrics
