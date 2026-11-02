from __future__ import annotations

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


def overlap_mask(raster_a, raster_b):
    if raster_a is None or raster_b is None:
        return None
    return cv2.bitwise_and(raster_a, raster_b)


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


EXPECTED_PINS = 14
EXPECTED_CONTACTS = 14


def build_top_glass_context(detections, confidence):
    glasses = _filter(detections, "glass", confidence["glass"])
    if not glasses:
        return {
            "valid": True,
            "has_glass": False,
            "glasses": [],
            "reason": None,
        }
    invalid_glasses = [
        index
        for index, glass in enumerate(glasses, start=1)
        if mask_points(glass) is None
    ]
    if invalid_glasses:
        return _invalid(
            "missing_glass_mask",
            glasses,
            invalid_glass_indices=invalid_glasses,
        )

    platforms = _filter(detections, "platform", confidence["platform"])
    contacts = _filter(detections, "contacts", confidence["contacts"])
    cases = _filter(detections, "case", confidence["case"])
    centrals = _filter(detections, "case_central", confidence["central"])
    pins = _filter(detections, "pin", confidence["pin"])

    platform = largest_valid_mask(platforms)
    if platform is None:
        return _invalid("no_valid_platform", glasses)
    platform_bbox = platform.get("bbox")
    if not _valid_bbox(platform_bbox):
        return _invalid("invalid_platform_bbox", glasses)

    selected_contacts, contact_error = _select_contact_references(
        contacts,
        platform_bbox,
    )
    if contact_error is not None:
        return _invalid(
            contact_error["reason"],
            glasses,
            **{
                key: value
                for key, value in contact_error.items()
                if key != "reason"
            },
        )

    if len(pins) != EXPECTED_PINS:
        return _invalid(
            f"wrong_pin_count: {len(pins)}/14",
            glasses,
            pins_found=len(pins),
        )
    invalid_pins = [
        index
        for index, pin in enumerate(pins, start=1)
        if mask_points(pin) is None
    ]
    if invalid_pins:
        return _invalid(
            "missing_pin_mask",
            glasses,
            invalid_pin_indices=invalid_pins,
        )
    if len(cases) != 1 or mask_points(cases[0]) is None:
        return _invalid(
            f"invalid_case_count: {len(cases)}/1",
            glasses,
            case_found=len(cases),
        )
    if len(centrals) != 1 or mask_points(centrals[0]) is None:
        return _invalid(
            f"invalid_case_central_count: {len(centrals)}/1",
            glasses,
            case_central_found=len(centrals),
        )

    case = cases[0]
    central = centrals[0]
    shape = infer_shape(
        glasses,
        [platform],
        selected_contacts,
        [case],
        [central],
        pins,
    )
    platform_raster = rasterize_mask(platform, shape)
    contact_rasters = [
        rasterize_mask(contact, shape) for contact in selected_contacts
    ]
    pin_rasters = [rasterize_mask(pin, shape) for pin in pins]
    case_raster = rasterize_mask(case, shape)
    central_raster = rasterize_mask(central, shape)
    case_central_overlap = overlap_mask(case_raster, central_raster)
    if (
        case_central_overlap is None
        or int(np.count_nonzero(case_central_overlap)) <= 0
    ):
        return _invalid("case_central_not_inside_case", glasses)
    ring_raster = case_raster.copy()
    ring_raster[central_raster > 0] = 0
    if int(np.count_nonzero(ring_raster)) <= 0:
        return _invalid("empty_case_ring", glasses)

    contact_union = np.zeros(shape, dtype=np.uint8)
    for raster in contact_rasters:
        contact_union = cv2.bitwise_or(contact_union, raster)
    pin_union = np.zeros(shape, dtype=np.uint8)
    for raster in pin_rasters:
        pin_union = cv2.bitwise_or(pin_union, raster)

    return {
        "valid": True,
        "has_glass": True,
        "reason": None,
        "shape": shape,
        "glasses": glasses,
        "glass_rasters": [rasterize_mask(glass, shape) for glass in glasses],
        "platform": platform,
        "platform_raster": platform_raster,
        "contacts": selected_contacts,
        "contact_rasters": contact_rasters,
        "contact_union": contact_union,
        "pins": pins,
        "pin_rasters": pin_rasters,
        "pin_union": pin_union,
        "case": case,
        "central": central,
        "ring_raster": ring_raster,
        "ignored_platforms": max(0, len(platforms)-1),
        "ignored_contacts": max(0, len(contacts)-len(selected_contacts)),
    }


def _select_contact_references(contacts, platform_bbox):
    valid = [contact for contact in contacts if mask_points(contact) is not None]
    if len(valid) < EXPECTED_CONTACTS:
        return None, {
            "reason": "insufficient_valid_contacts",
            "valid_contacts": len(valid),
        }
    groups, _unassigned = _ContactsLayout._group_candidates(valid, platform_bbox)
    counts = {
        group: len(groups[group]) for group in _ContactsLayout.EXPECTED_GROUPS
    }
    insufficient = [
        group
        for group, expected in _ContactsLayout.EXPECTED_GROUPS.items()
        if len(groups[group]) < expected
    ]
    if insufficient:
        return None, {
            "reason": "invalid_contact_layout",
            "contact_group_counts": counts,
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


def _filter(detections, class_name, confidence):
    return [
        detection for detection in detections
        if detection.get("class") == class_name
        and float(detection.get("confidence", 0.0)) >= confidence
    ]


def _invalid(reason, glasses, **details):
    return {
        "valid": False,
        "has_glass": True,
        "reason": reason,
        "glasses": glasses,
        **details,
    }


def _valid_bbox(bbox):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    values = np.asarray(bbox, dtype=np.float64)
    return bool(
        np.isfinite(values).all()
        and values[2] > values[0]
        and values[3] > values[1]
    )


class TopGlassRule:
    """Glass на platform/pin/case ring -> CLEANUP; contacts -> BAD rule."""

    name = "glass"
    ROLES = ("TOP",)

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
            context = build_top_glass_context(
                vision_results[role],
                _confidence(self, role),
            )
            result = self._check_role(role, context, drawings)
            per_role[role] = result
            triggered = triggered or result["triggered"]
        return RuleResult(
            self.name,
            triggered,
            details={"per_role": per_role},
            drawings=drawings,
        )

    @staticmethod
    def _check_role(role, context, drawings):
        if not context["has_glass"]:
            return {
                "triggered": False,
                "reason": None,
                "glasses_total": 0,
                "cleanup_hits": 0,
                "hits": [],
            }
        if not context["valid"]:
            # Общий fail closed публикует BAD rule glass_on_contacts.
            return {
                "triggered": False,
                "skipped": True,
                "reason": f"reference_invalid: {context['reason']}",
                "glasses_total": len(context["glasses"]),
                "cleanup_hits": 0,
                "hits": [],
            }

        hits = []
        on_contacts = []
        for index, (glass, glass_raster) in enumerate(
            zip(context["glasses"], context["glass_rasters"], strict=True),
            start=1,
        ):
            contact_overlap = cv2.bitwise_and(
                glass_raster,
                context["contact_union"],
            )
            contact_overlap_px = int(np.count_nonzero(contact_overlap))
            if contact_overlap_px > 0:
                on_contacts.append(index)
                continue

            platform_overlap = cv2.bitwise_and(
                glass_raster,
                context["platform_raster"],
            )
            pin_overlap = cv2.bitwise_and(
                glass_raster,
                context["pin_union"],
            )
            ring_overlap = cv2.bitwise_and(
                glass_raster,
                context["ring_raster"],
            )
            platform_px = int(np.count_nonzero(platform_overlap))
            pin_px = int(np.count_nonzero(pin_overlap))
            ring_px = int(np.count_nonzero(ring_overlap))
            cleanup_union = cv2.bitwise_or(platform_overlap, pin_overlap)
            cleanup_union = cv2.bitwise_or(cleanup_union, ring_overlap)
            cleanup_px = int(np.count_nonzero(cleanup_union))
            if cleanup_px <= 0:
                continue
            hits.append({
                "glass_index": index,
                "platform_overlap_px": platform_px,
                "pin_overlap_px": pin_px,
                "ring_overlap_px": ring_px,
                "cleanup_overlap_px": cleanup_px,
                "route": "CLEANUP",
            })
            contours, _hierarchy = cv2.findContours(
                cleanup_union,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            drawings.append({
                "type": "top_glass_cleanup_region",
                "role": role,
                "glass_index": index,
                "glass_mask": glass.get("mask"),
                "glass_bbox": glass.get("bbox") or [0, 0, 0, 0],
                "cleanup_raster": cleanup_union,
                "cleanup_contours": [
                    contour.reshape(-1, 2).astype(np.int32).tolist()
                    for contour in contours
                    if len(contour) >= 1
                ],
                "triggered": True,
            })

        if hits:
            drawings.insert(0, {
                "type": "top_glass_cleanup_references",
                "role": role,
                "platform_mask": context["platform"].get("mask"),
                "platform_bbox": context["platform"].get("bbox") or [0, 0, 0, 0],
                "pin_masks": [pin.get("mask") for pin in context["pins"]],
                "pin_bboxes": [
                    pin.get("bbox") or [0, 0, 0, 0]
                    for pin in context["pins"]
                ],
                "case_mask": context["case"].get("mask"),
                "case_bbox": context["case"].get("bbox") or [0, 0, 0, 0],
                "central_mask": context["central"].get("mask"),
                "central_bbox": context["central"].get("bbox") or [0, 0, 0, 0],
                "triggered": True,
            })

        return {
            "triggered": bool(hits),
            "reason": None,
            "glasses_total": len(context["glasses"]),
            "cleanup_hits": len(hits),
            "hits": hits,
            "on_contacts_indices": on_contacts,
        }


def _confidence(rule, role):
    return {
        "glass": rule._get("top_glass_min_confidence", 0.1, role=role),
        "platform": rule._get(
            "top_glass_platform_min_confidence", 0.3, role=role,
        ),
        "contacts": rule._get(
            "top_contacts_min_confidence", 0.3, role=role,
        ),
        "case": rule._get("top_glass_case_min_confidence", 0.3, role=role),
        "central": rule._get(
            "top_glass_case_central_min_confidence", 0.3, role=role,
        ),
        "pin": rule._get("top_glass_pin_min_confidence", 0.3, role=role),
    }
