"""Локальная геометрия правил дефектов.

Чистая математика без внешних зависимостей: точки и маски детекций,
вписывание эталонного прямоугольника, ориентация масок. Каждое правило
держит собственную копию используемых функций, поэтому импорт идёт из
того правила, которое эту копию использует.
"""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from domain.defect_rules.rule_top_glass import (
    infer_shape,
    largest_valid_mask,
    mask_points,
    overlap_mask,
    rasterize_mask,
)
from domain.defect_rules.rule_top_platform import (
    try_inscribe_center_then_nearest,
)
from domain.defect_rules.rule_top_platform_overlap import (
    mask_orientation,
    oriented_rectangle_points,
)


def rect_mask(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class TopGeometryHelpersTest(unittest.TestCase):
    def test_mask_points_valid(self):
        points = mask_points({"mask": rect_mask(0, 0, 10, 10)})
        self.assertIsNotNone(points)
        self.assertEqual(points.shape, (4, 2))

    def test_mask_points_too_short(self):
        self.assertIsNone(mask_points({"mask": [[0, 0]]}))

    def test_mask_points_nan_rejected(self):
        self.assertIsNone(mask_points({"mask": [[0, 0], [float("nan"), 1], [2, 2]]}))

    def test_mask_points_zero_area_rejected(self):
        self.assertIsNone(mask_points({"mask": [[0, 0], [0, 5], [0, 9]]}))

    def test_largest_valid_mask(self):
        dets = [
            {"mask": rect_mask(0, 0, 5, 5)},
            {"mask": rect_mask(0, 0, 20, 20)},
            {"mask": [[0, 0]]},
        ]
        self.assertIs(largest_valid_mask(dets), dets[1])

    def test_largest_valid_mask_none(self):
        self.assertIsNone(largest_valid_mask([]))
        self.assertIsNone(largest_valid_mask([{"mask": [[0, 0]]}]))

    def test_infer_shape_from_masks_and_bboxes(self):
        dets = [{"mask": rect_mask(0, 0, 10, 10)}, {"bbox": [0, 0, 30, 40]}]
        rows, cols = infer_shape(dets)
        self.assertEqual((rows, cols), (42, 32))

    def test_infer_shape_minimum(self):
        self.assertEqual(infer_shape([]), (1, 1))

    def test_rasterize_mask(self):
        mask = rasterize_mask({"mask": rect_mask(0, 0, 10, 10)}, (20, 20))
        self.assertEqual(int(cv2.countNonZero(mask)), 121)

    def test_rasterize_mask_none(self):
        self.assertIsNone(rasterize_mask({"mask": None}, (20, 20)))

    def test_mask_orientation_horizontal_rect(self):
        angle = mask_orientation({"mask": rect_mask(0, 0, 50, 10)})
        self.assertIsNotNone(angle)

    def test_mask_orientation_none_for_degenerate(self):
        self.assertIsNone(mask_orientation({"mask": None}))
        self.assertIsNone(mask_orientation({"mask": [[0, 0], [1, 1], [2, 2]]}))

    def test_oriented_rectangle_points_size(self):
        points = oriented_rectangle_points(
            center=(10, 10), width_px=20, height_px=10, angle_deg=0.0,
        )
        self.assertEqual(points.shape, (4, 2))
        xs = points[:, 0]
        self.assertAlmostEqual(float(xs.max() - xs.min()), 20.0, places=3)

    def test_inscribe_center_fits_big_rect(self):
        result = try_inscribe_center_then_nearest(
            {"mask": rect_mask(0, 0, 100, 100)},
            width_px=40,
            height_px=40,
        )
        self.assertTrue(result["fits"])
        self.assertTrue(result["centered"])
        self.assertEqual(result["center"], [50.0, 50.0])

    def test_inscribe_fails_small_mask(self):
        result = try_inscribe_center_then_nearest(
            {"mask": rect_mask(0, 0, 30, 30)},
            width_px=100,
            height_px=100,
        )
        self.assertFalse(result["fits"])

    def test_inscribe_missing_mask(self):
        result = try_inscribe_center_then_nearest(
            {"mask": None}, width_px=10, height_px=10,
        )
        self.assertFalse(result["fits"])
        self.assertEqual(result["reason"], "missing_mask")

    def test_inscribe_shifted_placement(self):
        # Маска смещена от центра: прямоугольник впишется со сдвигом.
        mask = rect_mask(20, 20, 60, 60)
        result = try_inscribe_center_then_nearest(
            {"mask": mask}, width_px=20, height_px=20,
        )
        self.assertTrue(result["fits"])
        self.assertIn("placed_center", result)

    def test_overlap_mask(self):
        a = np.zeros((10, 10), dtype=np.uint8)
        b = np.zeros((10, 10), dtype=np.uint8)
        a[0:5, 0:5] = 255
        b[3:8, 3:8] = 255
        overlap = overlap_mask(a, b)
        self.assertEqual(int(cv2.countNonZero(overlap)), 4)

    def test_overlap_mask_none(self):
        self.assertIsNone(overlap_mask(None, None))


if __name__ == "__main__":
    unittest.main()
