from __future__ import annotations

import numpy as np

from domain.defect_rules.result import RuleResult


# Локальная копия замера высоты ячейки окна по маске сегментации.
def _contour_points(mask) -> np.ndarray:
    """Привести маску детекции к массиву точек (N, 2) int."""
    pts = np.asarray(mask, dtype=float)
    if pts.ndim == 3:
        pts = pts[:, 0, :]
    return pts


def get_vertical_intersections(contour, x: float) -> list:
    """Все y-координаты пересечений вертикали x=x с контуром.

    Учитывает вертикальные рёбра (добавляет оба конца). Порт функции
    transporter/utils/intersections.py:get_vertical_intersections.
    """
    intersections = []
    n = len(contour)
    for i in range(n):
        pt1 = contour[i]
        pt2 = contour[(i + 1) % n]

        # Вертикальное ребро точно на x — добавляем оба конца.
        if abs(pt2[0] - pt1[0]) < 1e-5 and abs(pt1[0] - x) < 1e-5:
            intersections.append(pt1[1])
            intersections.append(pt2[1])
            continue

        # Обычное пересечение ребра.
        if (pt1[0] <= x <= pt2[0]) or (pt2[0] <= x <= pt1[0]):
            denom = pt2[0] - pt1[0]
            if abs(denom) < 1e-5:
                continue
            t = (x - pt1[0]) / denom
            y = pt1[1] + t * (pt2[1] - pt1[1])
            intersections.append(y)

    return sorted(set(intersections))


def measure_window_height(contour) -> tuple:
    """Резервный замер высоты ячейки: вершина -> точка под серединой по X.

    Порт transporter/processing/process_frame.py:measure_window_height.
    """
    seg = _contour_points(contour)
    if seg.size == 0:
        return None, None
    xs = seg[:, 0]
    ys = seg[:, 1]
    x_min, x_max = int(xs.min()), int(xs.max())
    y_min = int(ys.min())
    x_mid = int((x_min + x_max) / 2)

    nears = seg[
        (seg[:, 0] >= x_mid - 10)
        & (seg[:, 0] <= x_mid + 10)
        & (seg[:, 1] > y_min + 3)
    ]
    if nears.size == 0:
        y_mid = int(ys[seg[:, 0].argmin()]) if seg.shape[0] else y_min
        nears = np.array([[x_mid, y_mid]], dtype=int)
    y_mid = int(nears[:, 1].min())
    height = y_mid - y_min
    return height, (x_mid, y_min, y_mid)


def measure_window_by_intersections(mask, min_gap_px: float = 7.0) -> dict | None:
    """Основной замер: вертикальная секущая через середину bbox по X.

    Возвращает dict:
        height   — длина отрезка в px;
        x        — x секущей;
        y_top    — верхняя точка;
        y_bottom — нижняя точка;
        intersections — число пересечений (-1 = резервный замер).
    """
    seg = _contour_points(mask)
    if seg.size == 0 or len(seg) < 3:
        return None

    xs = seg[:, 0]
    x_min, x_max = int(np.min(xs)), int(np.max(xs))
    x_center = x_min + (x_max - x_min) // 2

    ys = get_vertical_intersections(seg, x_center)

    if len(ys) >= 2:
        ys_sorted = sorted(ys)
        y_top = int(ys_sorted[0])
        count = len(ys_sorted)
        y_bottom = None
        if len(ys_sorted) == 2:
            y_bottom = int(ys_sorted[1])
        else:
            for y in ys_sorted[1:]:
                if y - y_top > min_gap_px:
                    y_bottom = int(y)
                    break
            if y_bottom is None:
                y_bottom = int(ys_sorted[-1])
        return {
            "height": float(y_bottom - y_top),
            "x": int(x_center),
            "y_top": y_top,
            "y_bottom": y_bottom,
            "intersections": count,
        }

    # Резервный вариант (два пересечения не найдены).
    h_val, coord = measure_window_height(seg)
    if h_val is None or coord is None:
        return None
    x_mid, y_top, y_bottom = coord
    return {
        "height": float(h_val),
        "x": int(x_mid),
        "y_top": int(y_top),
        "y_bottom": int(y_bottom),
        "intersections": -1,
    }


def detections_of_kind(vision_results: dict, role: str, kind: str,
                       min_confidence: float = 0.0) -> list:
    """Детекции нужного типа модели на роли с фильтром по уверенности.

    ``kind`` проставляется VisionCluster'ом из model_config и повторяет
    семантику трёхкамерника: модель привязана к камере, а не к имени
    класса внутри весов.
    """
    out = []
    for det in vision_results.get(role, []) or []:
        if not isinstance(det, dict):
            continue
        if kind and det.get("kind") != kind:
            continue
        if float(det.get("confidence", 0.0)) < float(min_confidence):
            continue
        out.append(det)
    return out


class UnevenHeightsRule:
    """Разновысотность окон по камерам LEFT и RIGHT.

    Перенос логики трёхкамерника: для каждой найденной ячейки окна
    вертикальная секущая через середину по X даёт высоту в пикселях.
    Брак (по каждой стороне), если:

      * ``h_max >= height_max_px`` — ячейка слишком высокая;
      * ``h_min <= height_min_px`` — ячейка слишком низкая;
      * ``h_max - h_min >= height_difference_px`` — перепад высот.

    Триггеры оригинала: ``left_cam_*`` / ``right_cam_*`` из transporter.
    """

    name = "uneven_heights"
    ROLES = ("LEFT", "RIGHT")
    TARGET_KIND = "uneven_heights"

    def __init__(self, thresholds: dict):
        self.thresholds = thresholds
        self._enabled = self.name not in thresholds.get(
            "disabled_rules", []
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _get(self, key, default=None, role=None):
        """Порог этого правила: сначала ROLE.key, затем key, затем default."""
        if role:
            role_key = f"{role}.{key}"
            if role_key in self.thresholds:
                return self.thresholds[role_key]
        return self.thresholds.get(key, default)

    def _make_skip(self, rule_name):
        """Результат для отключённого правила."""
        return RuleResult(
            rule_name, False,
            details={"skipped": "rule disabled"},
        )

    def check(self, vision_results: dict, **kwargs) -> RuleResult:
        if not self.enabled:
            return self._make_skip(self.name)

        roles_to_check = [r for r in self.ROLES if r in vision_results]
        if not roles_to_check:
            roles_to_check = list(self.ROLES)

        per_role = {}
        drawings = []
        any_triggered = False

        for role in roles_to_check:
            min_confidence = float(self._get(
                "uneven_heights_min_confidence", 0.7, role=role,
            ))
            height_min = float(self._get(
                "uneven_heights_height_min_px", 20.0, role=role,
            ))
            height_max = float(self._get(
                "uneven_heights_height_max_px", 42.0, role=role,
            ))
            difference = float(self._get(
                "uneven_heights_height_difference_px", 11.0, role=role,
            ))
            min_gap = float(self._get(
                "uneven_heights_min_intersection_gap_px", 7.0, role=role,
            ))

            detections = detections_of_kind(
                vision_results, role, self.TARGET_KIND, min_confidence,
            )

            measures = []
            for det in detections:
                mask = det.get("mask")
                measure = None
                if mask and len(mask) >= 3:
                    measure = measure_window_by_intersections(
                        mask, min_gap_px=min_gap,
                    )
                measures.append({
                    "detection": det,
                    "measure": measure,
                })

            heights = [
                m["measure"]["height"]
                for m in measures
                if m["measure"] is not None
            ]

            h_max = max(heights) if heights else None
            h_min = min(heights) if heights else None
            spread = (h_max - h_min) if heights else None

            triggered = False
            reason = None
            if heights:
                if h_max >= height_max:
                    triggered, reason = True, "height_above_max"
                elif h_min <= height_min:
                    triggered, reason = True, "height_below_min"
                elif spread >= difference:
                    triggered, reason = True, "spread_exceeded"

            per_role[role] = {
                "valid": True,
                "skipped": False,
                "triggered": triggered,
                "reason": reason,
                "found": len(detections),
                "measured": len(heights),
                "heights": [round(h, 1) for h in heights],
                "h_max": round(h_max, 1) if h_max is not None else None,
                "h_min": round(h_min, 1) if h_min is not None else None,
                "spread": round(spread, 1) if spread is not None else None,
                "height_min_px": height_min,
                "height_max_px": height_max,
                "height_difference_px": difference,
                "min_confidence": min_confidence,
            }

            for item in measures:
                det = item["detection"]
                measure = item["measure"]
                drawings.append({
                    "type": "rule_bbox",
                    "role": role,
                    "rule": self.name,
                    "bbox": det.get("bbox"),
                    "mask": det.get("mask"),
                    "triggered": triggered,
                    "confidence": det.get("confidence"),
                })
                if measure is not None:
                    drawings.append({
                        "type": "uneven_height_measure",
                        "role": role,
                        "rule": self.name,
                        "x": measure["x"],
                        "y_top": measure["y_top"],
                        "y_bottom": measure["y_bottom"],
                        "height": round(measure["height"], 1),
                        "triggered": triggered,
                    })

            any_triggered = any_triggered or triggered

        return RuleResult(
            self.name,
            triggered=any_triggered,
            details={"per_role": per_role},
            drawings=drawings,
        )
