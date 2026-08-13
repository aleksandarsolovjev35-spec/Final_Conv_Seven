"""Общие хелперы для тестов правил инспекции.

Синтетические детекции повторяют формат vision-результата YOLO:
``{role: [{"class": ..., "confidence": ..., "bbox": [...], "mask": [...]}]}``.
"""

from __future__ import annotations

import os

import numpy as np

from domain.threshold_loader import ThresholdLoader

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESHOLDS_PATH = os.path.join(REPO_ROOT, "thresholds.json")


def rect_mask(x1, y1, x2, y2):
    """Контур прямоугольника как список точек маски."""
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def det(class_name, bbox, confidence=0.9, mask=None):
    """Одна детекция в формате vision-результата."""
    detection = {
        "class": class_name,
        "confidence": confidence,
        "bbox": list(bbox),
    }
    if mask is not None:
        detection["mask"] = mask
    return detection


def load_thresholds():
    return ThresholdLoader(THRESHOLDS_PATH).get_all()


def contacts_layout(platform_bbox):
    """14 контактов вокруг платформы: 5L + 5R + 2T + 2B.

    Возвращает список детекций, укладывающихся в раскладку
    ``EXPECTED_GROUPS`` правила top_contacts: расстояния до сторон
    платформы внутри каждой группы одинаковы, боковые контакты лежат
    в вертикальном диапазоне платформы.
    """
    x1, y1, x2, y2 = platform_bbox
    contacts = []
    side_ys = [
        y1 + 15 + i * (y2 - y1 - 30) / 4.0
        for i in range(5)
    ]
    top_xs = [x1 + 60, x2 - 60]
    bottom_xs = list(top_xs)

    for cy in side_ys:
        mask = rect_mask(x1 - 60, cy - 17, x1 - 20, cy + 18)
        contacts.append(det(
            "contacts", [x1 - 60, cy - 17, x1 - 20, cy + 18], 0.9, mask,
        ))
    for cy in side_ys:
        mask = rect_mask(x2 + 20, cy - 17, x2 + 60, cy + 18)
        contacts.append(det(
            "contacts", [x2 + 20, cy - 17, x2 + 60, cy + 18], 0.9, mask,
        ))
    for x_center in top_xs:
        mask = rect_mask(x_center - 20, y1 - 45, x_center + 20, y1 - 15)
        contacts.append(det(
            "contacts", [x_center - 20, y1 - 45, x_center + 20, y1 - 15],
            0.9, mask,
        ))
    for x_center in bottom_xs:
        mask = rect_mask(x_center - 20, y2 + 15, x_center + 20, y2 + 45)
        contacts.append(det(
            "contacts", [x_center - 20, y2 + 15, x_center + 20, y2 + 45],
            0.9, mask,
        ))
    return contacts


def pins_layout(case_bbox, central_bbox):
    """14 штифтов в кольце между case и central."""
    cx1, cy1, cx2, cy2 = case_bbox
    pins = []
    positions = []
    ring_x = [cx1 + 20, cx1 + 80, cx2 - 80, cx2 - 20]
    ring_y = [cy1 + 20, cy1 + 80, cy2 - 80, cy2 - 20]
    for x in ring_x:
        for y in (cy1 + 40, cy2 - 40):
            positions.append((x, y))
    for y in ring_y:
        for x in (cx1 + 40, cx2 - 40):
            positions.append((x, y))
    for (px, py) in positions[:14]:
        pins.append(det(
            "pin", [px - 8, py - 8, px + 8, py + 8], 0.9,
            rect_mask(px - 8, py - 8, px + 8, py + 8),
        ))
    return pins


def glass_context_detections(
    *,
    glasses=(),
    platform_bbox=(120, 120, 280, 200),
    with_contacts=True,
    with_pins=True,
):
    """Полный набор детекций для top_glass / top_glass_on_contacts."""
    px1, py1, px2, py2 = platform_bbox
    case_bbox = (60, 60, 340, 260)
    central_bbox = (100, 100, 300, 220)

    detections = [
        det("platform", list(platform_bbox), 0.9,
            rect_mask(px1, py1, px2, py2)),
        det("case", list(case_bbox), 0.9, rect_mask(*case_bbox)),
        det("case_central", list(central_bbox), 0.9,
            rect_mask(*central_bbox)),
    ]
    if with_contacts:
        detections.extend(contacts_layout(platform_bbox))
    if with_pins:
        detections.extend(pins_layout(case_bbox, central_bbox))
    for glass_bbox in glasses:
        detections.append(det(
            "glass", list(glass_bbox), 0.9, rect_mask(*glass_bbox),
        ))
    return detections


def window_mask(x, top_from, top_to, bottom_from, bottom_to):
    """Маска окна с перекладиной: два прямоугольника с зазором.

    ``top_from..top_to`` — верхняя часть (нижняя кромка = граница
    перекладины), ``bottom_from..bottom_to`` — нижняя часть.
    """
    return rect_mask(
        x, top_from, x + 40, top_to,
    ) + rect_mask(
        x, bottom_from, x + 40, bottom_to,
    )


def asarray(mask):
    return np.asarray(mask, dtype=np.float32)
