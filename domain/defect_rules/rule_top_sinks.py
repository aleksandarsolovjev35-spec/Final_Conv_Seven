from __future__ import annotations

import math
from itertools import combinations

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


def infer_shape(*detection_lists):
    max_x = 1
    max_y = 1
    for detections in detection_lists:
        for detection in detections:
            points = mask_points(detection)
            if points is not None:
                max_x = max(max_x, int(np.ceil(points[:, 0].max())) + 2)
                max_y = max(max_y, int(np.ceil(points[:, 1].max())) + 2)
            bbox = detection.get("bbox")
            if bbox and len(bbox) == 4:
                max_x = max(max_x, int(np.ceil(float(bbox[2]))) + 2)
                max_y = max(max_y, int(np.ceil(float(bbox[3]))) + 2)
    return max_y, max_x


def rasterize_mask(detection, shape):
    points = mask_points(detection)
    if points is None:
        return None
    canvas = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(canvas, [points.astype(np.int32)], 255)
    return canvas


class _ContactsLayout:
    """Локальная копия разметки контактов TOP для этого правила."""

    EXPECTED_GROUPS = {"L": 5, "R": 5, "T": 2, "B": 2}

    @classmethod
    def _group_candidates(cls, detections, platform_bbox):
        groups = {group: [] for group in cls.EXPECTED_GROUPS}
        unassigned = []
        for detection in detections:
            parameters = cls._contact_parameters(detection)
            candidates = cls._side_candidates(parameters, platform_bbox)
            if not candidates:
                unassigned.append(detection)
                continue
            _distance, group = min(candidates, key=lambda item: item[0])
            groups[group].append(detection)
        return groups, unassigned

    @classmethod
    def _select_consistent_group(
        cls,
        detections,
        expected,
        group,
        platform_bbox,
    ):
        if len(detections) == expected:
            return list(detections), []
        scored = []
        for subset in combinations(detections, expected):
            parameters = [cls._contact_parameters(item) for item in subset]
            distances = [
                cls._distance_to_side(item, group, platform_bbox)
                for item in parameters
            ]
            scale_values = [
                item["width" if group in ("L", "R") else "height"]
                for item in parameters
            ]
            median_distance = float(np.median(distances))
            scale = max(1.0, float(np.median(scale_values)))
            deviation_ratio = max(
                abs(float(distance) - median_distance)
                for distance in distances
            ) / scale
            mean_confidence = float(np.mean([
                float(item.get("confidence", 0.0)) for item in subset
            ]))
            scored.append((deviation_ratio, -mean_confidence, subset))
        _ratio, _negative_confidence, best = min(
            scored,
            key=lambda item: (item[0], item[1]),
        )
        selected_ids = {id(item) for item in best}
        extras = [item for item in detections if id(item) not in selected_ids]
        return list(best), extras

    @staticmethod
    def _sort_group(detections, group):
        axis = 1 if group in ("L", "R") else 0
        return sorted(
            detections,
            key=lambda detection: (
                float(detection["bbox"][axis])
                + float(detection["bbox"][axis + 2])
            ) / 2.0,
        )

    @staticmethod
    def _side_candidates(parameters, platform_bbox):
        x1, y1, x2, y2 = map(float, platform_bbox)
        cx = parameters["center_x"]
        cy = parameters["center_y"]
        candidates = []
        if cx < x1:
            candidates.append((x1 - cx, "L"))
        if cx > x2:
            candidates.append((cx - x2, "R"))
        if cy < y1:
            candidates.append((y1 - cy, "T"))
        if cy > y2:
            candidates.append((cy - y2, "B"))
        return candidates

    @classmethod
    def _distance_to_side(cls, parameters, group, platform_bbox):
        candidates = {
            side: distance
            for distance, side in cls._side_candidates(parameters, platform_bbox)
        }
        return float(candidates[group])

    @staticmethod
    def _contact_parameters(contact):
        bbox = contact["bbox"]
        x1, y1, x2, y2 = map(float, bbox)
        return {
            "center_x": (x1+x2)/2.0,
            "center_y": (y1+y2)/2.0,
            "width": abs(x2-x1),
            "height": abs(y2-y1),
        }


class TopSinksRule:
    name = "sinks"
    ROLES = ("TOP",)
    SINK_CLASS = "shells"
    PLATFORM_CLASS = "platform"
    CONTACTS_CLASS = "contacts"
    CENTRAL_CLASS = "case_central"

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
            sink_conf = self._get("top_sinks_min_confidence", 0.4, role=role)
            platform_conf = self._get(
                "top_sinks_platform_min_confidence", 0.3, role=role,
            )
            # Тот же candidate contract, что и production top_contacts.
            contact_conf = self._get(
                "top_contacts_min_confidence", 0.3, role=role,
            )
            central_conf = self._get(
                "top_sinks_case_central_min_confidence", 0.3, role=role,
            )
            detections = vision_results[role]
            result = self._check_role(
                role=role,
                sinks=_filter(detections, self.SINK_CLASS, sink_conf),
                platforms=_filter(
                    detections, self.PLATFORM_CLASS, platform_conf,
                ),
                contacts=_filter(
                    detections, self.CONTACTS_CLASS, contact_conf,
                ),
                centrals=_filter(
                    detections, self.CENTRAL_CLASS, central_conf,
                ),
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

    @classmethod
    def _check_role(
        cls, *, role, sinks, platforms, contacts, centrals, drawings,
    ):
        if not sinks:
            return {
                "triggered": False,
                "reason": None,
                "sinks_total": 0,
                "defect_sinks": 0,
                "hits": [],
            }

        invalid_sink_indices = [
            index
            for index, sink in enumerate(sinks, start=1)
            if mask_points(sink) is None
        ]
        if invalid_sink_indices:
            for index in invalid_sink_indices:
                sink = sinks[index-1]
                drawings.append({
                    "type": "top_sink_invalid_reference",
                    "role": role,
                    "bbox": sink.get("bbox") or [0, 0, 0, 0],
                    "mask": sink.get("mask"),
                    "triggered": True,
                })
                drawings.append({
                    "type": "construction_error",
                    "role": role,
                    "bbox": sink.get("bbox") or [0, 0, 0, 0],
                    "message": f"NO SHELL MASK #{index}",
                    "triggered": True,
                })
            return {
                "triggered": True,
                "reason": "invalid_sink_masks",
                "invalid_sink_indices": invalid_sink_indices,
                "sinks_total": len(sinks),
                "defect_sinks": 0,
                "hits": [],
            }

        if len(centrals) != 1 or mask_points(centrals[0]) is None:
            if centrals:
                for central in centrals:
                    drawings.append({
                        "type": "top_sink_invalid_reference",
                        "role": role,
                        "bbox": central.get("bbox") or [0, 0, 0, 0],
                        "mask": central.get("mask"),
                        "triggered": True,
                    })
            drawings.append({
                "type": "construction_error",
                "role": role,
                "bbox": cls._combined_bbox(centrals),
                "message": f"CASE CENTRAL {len(centrals)}/1",
                "triggered": True,
            })
            return {
                "triggered": True,
                "reason": "invalid_case_central_reference",
                "case_central_found": len(centrals),
                "sinks_total": len(sinks),
                "defect_sinks": 0,
                "hits": [],
            }

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
                "sinks_total": len(sinks),
                "defect_sinks": 0,
                "hits": [],
            }
        platform_bbox = platform.get("bbox")
        if not _valid_bbox(platform_bbox):
            drawings.append({
                "type": "construction_error",
                "role": role,
                "bbox": platform.get("bbox") or [0, 0, 0, 0],
                "message": "NO PLATFORM BBOX",
                "triggered": True,
            })
            return {
                "triggered": True,
                "reason": "invalid_platform_bbox",
                "sinks_total": len(sinks),
                "defect_sinks": 0,
                "hits": [],
            }

        selected_contacts, contact_error = cls._select_contact_references(
            contacts,
            platform_bbox,
        )
        if contact_error is not None:
            available = [
                contact for contact in contacts
                if mask_points(contact) is not None
            ]
            for contact in available:
                drawings.append({
                    "type": "top_sink_reference_contact",
                    "role": role,
                    "bbox": contact.get("bbox") or [0, 0, 0, 0],
                    "mask": contact.get("mask"),
                    "invalid": True,
                    "triggered": True,
                })
            drawings.append({
                "type": "construction_error",
                "role": role,
                "bbox": cls._combined_bbox(available),
                "message": contact_error["message"],
                "triggered": True,
            })
            return {
                "triggered": True,
                "reason": contact_error["reason"],
                "contact_group_counts": contact_error.get("group_counts"),
                "valid_contacts": len(available),
                "sinks_total": len(sinks),
                "defect_sinks": 0,
                "hits": [],
            }

        central = centrals[0]
        shape = infer_shape(sinks, [platform], selected_contacts, [central])
        central_raster = rasterize_mask(central, shape)
        platform_raster = rasterize_mask(platform, shape)
        contact_rasters = [
            rasterize_mask(contact, shape) for contact in selected_contacts
        ]
        contacts_union = np.zeros(shape, dtype=np.uint8)
        for raster in contact_rasters:
            contacts_union = cv2.bitwise_or(contacts_union, raster)
        protected = cv2.bitwise_or(platform_raster, contacts_union)
        allowed_inside_central = cv2.bitwise_and(
            central_raster,
            cv2.bitwise_not(protected),
        )

        hits = []
        defect_rasters = []
        for index, sink in enumerate(sinks, start=1):
            sink_raster = rasterize_mask(sink, shape)
            central_px = _overlap_pixels(sink_raster, central_raster)
            platform_px = _overlap_pixels(sink_raster, platform_raster)
            contacts_px = _overlap_pixels(sink_raster, contacts_union)
            forbidden = cv2.bitwise_and(
                sink_raster,
                allowed_inside_central,
            )
            forbidden_px = int(np.count_nonzero(forbidden))
            if forbidden_px <= 0:
                continue
            hit = {
                "sink_index": index,
                "forbidden_pixels": forbidden_px,
                "central_overlap_px": central_px,
                "platform_overlap_px": platform_px,
                "contacts_overlap_px": contacts_px,
            }
            hits.append(hit)
            defect_rasters.append((index, sink, forbidden))

        if hits:
            drawings.append({
                "type": "top_sinks_references",
                "role": role,
                "case_central_mask": central.get("mask"),
                "case_central_bbox": central.get("bbox") or [0, 0, 0, 0],
                "platform_mask": platform.get("mask"),
                "platform_bbox": platform.get("bbox") or [0, 0, 0, 0],
                "contact_masks": [
                    contact.get("mask") for contact in selected_contacts
                ],
                "contact_bboxes": [
                    contact.get("bbox") or [0, 0, 0, 0]
                    for contact in selected_contacts
                ],
                "triggered": True,
            })
            for index, sink, forbidden in defect_rasters:
                contours, _hierarchy = cv2.findContours(
                    forbidden,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE,
                )
                drawings.append({
                    "type": "top_sink_forbidden_region",
                    "role": role,
                    "sink_index": index,
                    "sink_mask": sink.get("mask"),
                    "sink_bbox": sink.get("bbox") or [0, 0, 0, 0],
                    "forbidden_raster": forbidden,
                    "forbidden_contours": [
                        contour.reshape(-1, 2).astype(np.int32).tolist()
                        for contour in contours
                        if len(contour) >= 1
                    ],
                    "triggered": True,
                })

        return {
            "triggered": bool(hits),
            "reason": None,
            "sinks_total": len(sinks),
            "defect_sinks": len(hits),
            "hits": hits,
            "contacts_used": len(selected_contacts),
        }

    @classmethod
    def _select_contact_references(cls, contacts, platform_bbox):
        valid = [
            contact for contact in contacts
            if mask_points(contact) is not None
        ]
        if len(valid) < 14:
            return None, {
                "reason": "insufficient_valid_contacts",
                "message": f"CONTACTS REF {len(valid)}/14",
            }
        groups, _unassigned = _ContactsLayout._group_candidates(
            valid,
            platform_bbox,
        )
        counts = {
            group: len(groups[group])
            for group in _ContactsLayout.EXPECTED_GROUPS
        }
        insufficient = [
            group
            for group, expected in _ContactsLayout.EXPECTED_GROUPS.items()
            if len(groups[group]) < expected
        ]
        if insufficient:
            text = " ".join(
                f"{group}{counts[group]}/{expected}"
                for group, expected in _ContactsLayout.EXPECTED_GROUPS.items()
            )
            return None, {
                "reason": "invalid_contact_layout",
                "message": f"CONTACTS REF {text}",
                "group_counts": counts,
            }
        selected = []
        for group in ("L", "R", "T", "B"):
            group_selected, _extras = _ContactsLayout._select_consistent_group(
                groups[group],
                _ContactsLayout.EXPECTED_GROUPS[group],
                group,
                platform_bbox,
            )
            selected.extend(_ContactsLayout._sort_group(group_selected, group))
        return selected, None

    @staticmethod
    def _combined_bbox(detections):
        boxes = [detection.get("bbox") for detection in detections]
        boxes = [box for box in boxes if box and len(box) == 4]
        if not boxes:
            return [0, 0, 0, 0]
        return [
            min(float(box[0]) for box in boxes),
            min(float(box[1]) for box in boxes),
            max(float(box[2]) for box in boxes),
            max(float(box[3]) for box in boxes),
        ]


def _filter(detections, class_name, confidence):
    return [
        detection for detection in detections
        if detection.get("class") == class_name
        and float(detection.get("confidence", 0.0)) >= confidence
    ]


def _overlap_pixels(raster_a, raster_b):
    return int(np.count_nonzero(cv2.bitwise_and(raster_a, raster_b)))


def _valid_bbox(bbox):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    if any(
        type(value) not in (int, float) or not math.isfinite(float(value))
        for value in bbox
    ):
        return False
    return float(bbox[2]) > float(bbox[0]) and float(bbox[3]) > float(bbox[1])
