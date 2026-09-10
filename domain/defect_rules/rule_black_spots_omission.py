"""Чёрные пятна на короткой полосе пропуска (SPIDER_IN / SPIDER_OUT).

Логика повторяет принцип правила ``glass`` (объект становится дефектом только
когда его область пересекается с опорной областью), но применительно к камерам
короткой omission: ``black-spot`` модель даёт кандидатов пятен на внутренней и
внешней камерах, а подтверждающей областью выступает «область short omission»,
построенная по детекциям ``omission-short`` той же камеры.

Решение по одной камере:
  * сначала проверяется наличие области short omission (детекции
    ``omission-short`` после порога уверенности);
  * если области нет — пятна нечем подтвердить, брак не фиксируется
    (части соответствуют «годное»);
  * если область есть — каждое пятно ``black-spot`` считается браком только
    когда его маска пересекается с областью short omission (пересечение > 0 px);
  * пятно, не пересекающее область short omission — ложное срабатывание модели,
    брак по нему не ставится.

Правило находится на SPIDER-стадии: сработавший дефект добавляется в
``spider_defects`` и ведёт в маршрут ``BAD`` (не входит в ``CLEANUP_DEFECTS``).
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from domain.defect_rules.base import BaseRule, RuleResult


class SpiderBlackSpotsOmissionRule(BaseRule):
    """Чёрные пятна, подтверждённые пересечением с областью short omission."""

    name = "black_spots_omission"
    ROLES = ("SPIDER_IN", "SPIDER_OUT")
    TARGET_CLASS = "black-spot"
    OMISSION_CLASS = "omission-short"

    def check(self, vision_results: dict, **kwargs) -> RuleResult:
        if not self.enabled:
            return self._make_skip(self.name)

        drawings = []
        triggered = False
        per_role = {}
        for role in self.ROLES:
            if role not in vision_results:
                continue
            role_result, role_drawings = self._check_role(
                role, vision_results[role],
            )
            triggered = triggered or role_result["triggered"]
            drawings.extend(role_drawings)
            per_role[role] = role_result

        return RuleResult(
            self.name,
            triggered,
            details={"per_role": per_role},
            drawings=drawings,
        )

    def _check_role(self, role: str, detections) -> tuple:
        min_spot_conf = float(self._get(
            "black_spots_omission_min_confidence", 0.1, role=role,
        ))
        min_omission_conf = float(self._get(
            "spider_short_omission_min_confidence", 0.1, role=role,
        ))

        spots = [
            detection for detection in detections
            if detection.get("class") == self.TARGET_CLASS
            and _conf(detection) >= min_spot_conf
        ]
        omissions = [
            detection for detection in detections
            if detection.get("class") == self.OMISSION_CLASS
            and _conf(detection) >= min_omission_conf
        ]

        # 1) Сначала проверяем наличие области short omission.
        region_rasters, region_bbox = _rasterize_union(omissions)
        if region_rasters is None:
            return (
                {
                    "triggered": False,
                    "class": self.TARGET_CLASS,
                    "reason": "no_omission_region",
                    "omission_detections": len(omissions),
                    "found": len(spots),
                    "confirmed_hits": 0,
                    "false_positives": len(spots),
                    "hits": [],
                },
                [],
            )

        offset_x, offset_y, width, height = region_bbox
        region = region_rasters

        confirmed = []
        false_positives = 0
        unverifiable = 0
        hit_drawings = []
        for index, spot in enumerate(spots, start=1):
            points = _mask_points(spot)
            if points is None:
                unverifiable += 1
                continue
            local = points - np.array(
                [[offset_x, offset_y]], dtype=np.float64,
            )
            spot_canvas = np.zeros((height, width), dtype=np.uint8)
            cv2.fillPoly(
                spot_canvas,
                [local.astype(np.int32)],
                255,
            )
            overlap = cv2.bitwise_and(spot_canvas, region)
            overlap_px = int(np.count_nonzero(overlap))
            if overlap_px <= 0:
                false_positives += 1
                continue
            confirmed.append({
                "spot_index": index,
                "overlap_px": overlap_px,
            })
            # Показываем только пересечение пятна с областью: часть пятна
            # за пределами области пропуска в режиме «ПРАВИЛА» не рисуем.
            contours, _hierarchy = cv2.findContours(
                overlap,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            overlap_contours = [
                (
                    contour.reshape(-1, 2).astype(np.int32)
                    + np.array([offset_x, offset_y], dtype=np.int32)
                ).tolist()
                for contour in contours
                if len(contour) >= 1
            ]
            bbox = spot.get("bbox") or [0, 0, 0, 0]
            hit_drawings.append({
                "type": "black_spots_omission_hit",
                "role": role,
                "triggered": True,
                "bbox": [float(v) for v in bbox],
                "mask": points.tolist(),
                "overlap_contours": overlap_contours,
                "overlap_px": overlap_px,
            })

        region_drawing = {
            "type": "black_spots_omission_region",
            "role": role,
            # Зона загорается красным, только если пятно подтверждено.
            "triggered": bool(confirmed),
            "bbox": [
                float(offset_x), float(offset_y),
                float(offset_x + width - 1), float(offset_y + height - 1),
            ],
            "region_mask": region,
            "region_origin": [offset_x, offset_y],
        }

        result = {
            "triggered": bool(confirmed),
            "class": self.TARGET_CLASS,
            "reason": "black_spot_in_omission_region" if confirmed else None,
            "omission_detections": len(omissions),
            "found": len(spots),
            "confirmed_hits": len(confirmed),
            "false_positives": false_positives,
            "unverifiable": unverifiable,
            "hits": confirmed,
            "min_confidence": min_spot_conf,
        }
        return result, [region_drawing] + hit_drawings


def _conf(detection) -> float:
    return float(detection.get("confidence", 0.0))


def _mask_points(detection):
    mask = detection.get("mask")
    if mask is None or len(mask) < 3:
        return None
    points = np.asarray(mask, dtype=np.float64)
    if (
        points.ndim != 2
        or points.shape[1] != 2
        or len(points) < 3
        or not np.isfinite(points).all()
    ):
        return None
    return points


def _rasterize_union(detections):
    """Залить объединение масок ``omission-short`` в одну бинарную область.

    Возвращает ``(region, (offset_x, offset_y, width, height))`` либо
    ``(None, None)``, если валидных масок нет.
    """
    valid = []
    for detection in detections:
        points = _mask_points(detection)
        if points is None:
            continue
        area = float(abs(cv2.contourArea(points.astype(np.float32))))
        if area <= 0.0:
            continue
        valid.append(points)
    if not valid:
        return None, None

    all_points = np.vstack(valid)
    x_min = int(math.floor(float(all_points[:, 0].min())))
    y_min = int(math.floor(float(all_points[:, 1].min())))
    x_max = int(math.ceil(float(all_points[:, 0].max())))
    y_max = int(math.ceil(float(all_points[:, 1].max())))
    width = x_max - x_min + 1
    height = y_max - y_min + 1
    if width < 1 or height < 1:
        return None, None

    canvas = np.zeros((height, width), dtype=np.uint8)
    for points in valid:
        local = points - np.array(
            [[x_min, y_min]], dtype=np.float64,
        )
        cv2.fillPoly(canvas, [local.astype(np.int32)], 255)
    if not int(np.count_nonzero(canvas)):
        return None, None
    return canvas, (x_min, y_min, width, height)
