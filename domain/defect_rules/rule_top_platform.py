from __future__ import annotations

import cv2
import numpy as np

from domain.defect_rules.result import RuleResult


def mask_points(detection):
    mask = detection.get("mask")
    if mask is None or len(mask) < 3:
        return None
    points = np.asarray(mask, dtype=np.float32)
    if (
        points.ndim != 2
        or points.shape[1] != 2
        or len(points) < 3
        or not np.isfinite(points).all()
    ):
        return None
    if abs(float(cv2.contourArea(points))) <= 0.0:
        return None
    return points


def mask_area(detection):
    points = mask_points(detection)
    return 0.0 if points is None else abs(float(cv2.contourArea(points)))


def largest_valid_mask(detections):
    valid = [detection for detection in detections if mask_points(detection) is not None]
    if not valid:
        return None
    return max(valid, key=mask_area)


def mask_orientation(detection):
    points = mask_points(detection)
    if points is None:
        return None
    _center, (width, height), angle = cv2.minAreaRect(points)
    if width < 1.0 or height < 1.0:
        return None
    return float(angle + 90.0 if width < height else angle)


def try_inscribe_center_then_nearest(
    detection,
    *,
    width_px,
    height_px,
    angle_deg=0.0,
):
    """Сохранённый алгоритм: центр, затем ближайшее допустимое положение."""
    points = mask_points(detection)
    if points is None:
        return {"fits": False, "points": None, "reason": "missing_mask"}
    x_min = float(points[:, 0].min())
    x_max = float(points[:, 0].max())
    y_min = float(points[:, 1].min())
    y_max = float(points[:, 1].max())
    center_x = (x_min + x_max) / 2.0
    center_y = (y_min + y_max) / 2.0
    max_dimension = max(x_max - x_min, y_max - y_min, width_px, height_px)
    padding = int(max_dimension * 0.8) + 20
    canvas_size = int(max_dimension) + 2 * padding

    local = points - np.asarray([center_x, center_y], dtype=np.float32)
    local[:, 0] += canvas_size / 2.0
    local[:, 1] += canvas_size / 2.0
    canvas = np.zeros((canvas_size, canvas_size), dtype=np.uint8)
    cv2.fillPoly(canvas, [local.astype(np.int32)], 255)

    matrix = cv2.getRotationMatrix2D(
        (canvas_size / 2.0, canvas_size / 2.0),
        angle_deg,
        1.0,
    )
    rotated = cv2.warpAffine(
        canvas,
        matrix,
        (canvas_size, canvas_size),
        flags=cv2.INTER_NEAREST,
        borderValue=0,
    )

    kernel_width = max(1, int(round(width_px)))
    kernel_height = max(1, int(round(height_px)))
    target_x = canvas_size / 2.0
    target_y = canvas_size / 2.0

    def centered_bounds(cx, cy):
        left = kernel_width // 2
        top = kernel_height // 2
        x0 = int(round(cx - left))
        y0 = int(round(cy - top))
        return x0, y0, x0 + kernel_width, y0 + kernel_height

    x0, y0, x1, y1 = centered_bounds(target_x, target_y)
    fits_center = (
        x0 >= 0
        and y0 >= 0
        and x1 <= rotated.shape[1]
        and y1 <= rotated.shape[0]
        and bool(np.all(rotated[y0:y1, x0:x1] == 255))
    )

    if fits_center:
        fits = True
        fit_x = target_x
        fit_y = target_y
    elif (
        kernel_width > rotated.shape[1]
        or kernel_height > rotated.shape[0]
    ):
        fits = False
        fit_x = target_x
        fit_y = target_y
    else:
        kernel = np.ones((kernel_height, kernel_width), dtype=np.uint8)
        eroded = cv2.erode(rotated, kernel, iterations=1)
        valid_y, valid_x = np.where(eroded > 0)
        if len(valid_x):
            distances = (
                (valid_x.astype(np.float32) - target_x) ** 2
                + (valid_y.astype(np.float32) - target_y) ** 2
            )
            best = int(np.argmin(distances))
            fits = True
            fit_x = float(valid_x[best])
            fit_y = float(valid_y[best])
        else:
            fits = False
            fit_x = target_x
            fit_y = target_y

    half_width = width_px / 2.0
    half_height = height_px / 2.0
    rectangle = np.asarray([
        [fit_x - half_width, fit_y - half_height],
        [fit_x + half_width, fit_y - half_height],
        [fit_x + half_width, fit_y + half_height],
        [fit_x - half_width, fit_y + half_height],
    ], dtype=np.float32)
    inverse = cv2.getRotationMatrix2D(
        (canvas_size / 2.0, canvas_size / 2.0),
        -angle_deg,
        1.0,
    )
    restored = (
        inverse
        @ np.hstack([
            rectangle,
            np.ones((4, 1), dtype=np.float32),
        ]).T
    ).T
    restored[:, 0] -= canvas_size / 2.0
    restored[:, 1] -= canvas_size / 2.0
    restored[:, 0] += center_x
    restored[:, 1] += center_y
    placed_center = restored.mean(axis=0)
    return {
        "fits": bool(fits),
        "points": np.rint(restored).astype(np.int32).tolist(),
        "centered": bool(fits_center),
        "center": [round(center_x, 3), round(center_y, 3)],
        "placed_center": [
            round(float(placed_center[0]), 3),
            round(float(placed_center[1]), 3),
        ],
        "angle_deg": round(float(angle_deg), 6),
    }


class TopPlatformRule:
    name = "top_platform"
    ROLES = ("TOP",)
    PLATFORM_CLASS = "platform"

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
        drawings = []
        per_role = {}
        triggered = False
        for role in self.ROLES:
            if role not in vision_results:
                continue
            min_confidence = self._get(
                "top_platform_min_confidence", 0.3, role=role,
            )
            rect_width = self._get(
                "top_platform_inscribed_rect_width_px", 260, role=role,
            )
            rect_height = self._get(
                "top_platform_inscribed_rect_height_px", 120, role=role,
            )
            platforms = [
                detection for detection in vision_results[role]
                if detection.get("class") == self.PLATFORM_CLASS
                and float(detection.get("confidence", 0.0))
                >= min_confidence
            ]
            result = self._check_role(
                role=role,
                platforms=platforms,
                rect_width=float(rect_width),
                rect_height=float(rect_height),
                drawings=drawings,
            )
            per_role[role] = result
            triggered = triggered or result["triggered"]
        return RuleResult(
            self.name,
            triggered,
            details={"per_role": per_role},
            drawings=drawings,
        )

    @staticmethod
    def _check_role(*, role, platforms, rect_width, rect_height, drawings):
        platform = largest_valid_mask(platforms)
        if platform is None:
            drawings.append({
                "type": "construction_error",
                "role": role,
                "message": "NO PLATFORM",
                "triggered": True,
            })
            return {
                "triggered": True,
                "reason": "no_valid_platform",
                "found": len(platforms),
                "ignored": 0,
            }
        angle = mask_orientation(platform)
        if angle is None:
            drawings.append({
                "type": "top_platform_actual",
                "role": role,
                "bbox": platform.get("bbox") or [0, 0, 0, 0],
                "mask": platform.get("mask"),
                "valid": False,
                "triggered": True,
            })
            drawings.append({
                "type": "construction_error",
                "role": role,
                "bbox": platform.get("bbox") or [0, 0, 0, 0],
                "message": "NO ORIENTATION",
                "triggered": True,
            })
            return {
                "triggered": True,
                "reason": "invalid_platform_orientation",
                "found": len(platforms),
                "ignored": max(0, len(platforms) - 1),
            }
        fit = try_inscribe_center_then_nearest(
            platform,
            width_px=rect_width,
            height_px=rect_height,
            angle_deg=angle,
        )
        triggered = not fit["fits"]
        target_center = fit.get("center") or [0.0, 0.0]
        placed_center = fit.get("placed_center") or target_center
        shift_distance = (
            (float(placed_center[0]) - float(target_center[0])) ** 2
            + (float(placed_center[1]) - float(target_center[1])) ** 2
        ) ** 0.5
        placement = (
            "not_fitted"
            if triggered
            else ("centered" if fit.get("centered") else "shifted")
        )
        drawings.append({
            "type": "top_platform_actual",
            "role": role,
            "bbox": platform.get("bbox") or [0, 0, 0, 0],
            "mask": platform.get("mask"),
            "valid": True,
            "triggered": triggered,
        })
        if fit.get("points") is not None:
            drawings.append({
                "type": "top_platform_inscribed_rect",
                "role": role,
                "points": fit["points"],
                "fits": fit["fits"],
                "triggered": triggered,
            })
        drawings.append({
            "type": "top_platform_centers",
            "role": role,
            "target_center": target_center,
            "placed_center": placed_center,
            "shifted": placement == "shifted",
            "triggered": triggered,
        })
        return {
            "triggered": triggered,
            "reason": None,
            "found": len(platforms),
            "ignored": max(0, len(platforms) - 1),
            "rect_width_px": rect_width,
            "rect_height_px": rect_height,
            "angle_deg": round(angle, 3),
            "fits": fit["fits"],
            "centered": fit.get("centered", False),
            "placement": placement,
            "target_center": [round(float(value), 3) for value in target_center],
            "placed_center": [round(float(value), 3) for value in placed_center],
            "shift_distance_px": round(float(shift_distance), 3),
            "inscribe_fail": triggered,
            "inscribe_check": {
                "status": "fail" if triggered else "ok",
                "rect_width_px": rect_width,
                "rect_height_px": rect_height,
                "expected_width_px": rect_width,
                "expected_height_px": rect_height,
                "fits": fit["fits"],
            },
        }
