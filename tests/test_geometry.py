"""Геометрические хелперы ``domain.geometry`` и ``domain.defect_rules.top_geometry``.

Чистая математика без внешних зависимостей: пересечения bbox, центроиды
по маскам, подбор ряда контактов и вписывание эталонного прямоугольника.
"""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from domain.geometry.fitting import split_top_row
from domain.geometry.primitives import (
    bbox_intersect,
    bbox_intersection_rect,
    centroid_from_det,
    mask_area,
)
from domain.defect_rules.top_geometry import (
    infer_shape,
    largest_valid_mask,
    mask_orientation,
    mask_points,
    oriented_rectangle_points,
    overlap_mask,
    rasterize_mask,
    try_inscribe_center_then_nearest,
)


def rect_mask(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class BboxPrimitivesTest(unittest.TestCase):
    def test_intersect_overlapping(self):
        self.assertTrue(bbox_intersect([0, 0, 10, 10], [5, 5, 20, 20]))

    def test_intersect_disjoint(self):
        self.assertFalse(bbox_intersect([0, 0, 10, 10], [20, 20, 30, 30]))

    def test_intersect_touching_edges_is_not_overlap(self):
        self.assertFalse(bbox_intersect([0, 0, 10, 10], [10, 0, 20, 10]))

    def test_intersection_rect(self):
        self.assertEqual(
            bbox_intersection_rect([0, 0, 10, 10], [5, 5, 20, 20]),
            [5, 5, 10, 10],
        )

    def test_intersection_rect_none_when_disjoint(self):
        self.assertIsNone(
            bbox_intersection_rect([0, 0, 10, 10], [20, 20, 30, 30])
        )

    def test_intersection_rect_none_when_line(self):
        self.assertIsNone(
            bbox_intersection_rect([0, 0, 10, 10], [10, 0, 20, 10])
        )

    def test_centroid_from_mask(self):
        det = {"mask": rect_mask(0, 0, 10, 10)}
        self.assertEqual(centroid_from_det(det), (5, 5))

    def test_centroid_bbox_fallback(self):
        det = {"bbox": [0, 0, 10, 20]}
        self.assertEqual(centroid_from_det(det), (5, 10))

    def test_centroid_short_mask_falls_to_bbox(self):
        det = {"mask": [[0, 0]], "bbox": [0, 0, 4, 4]}
        self.assertEqual(centroid_from_det(det), (2, 2))

    def test_centroid_none_when_no_geometry(self):
        self.assertIsNone(centroid_from_det({"confidence": 0.9}))

    def test_mask_area_from_mask(self):
        det = {"mask": rect_mask(0, 0, 10, 10)}
        self.assertEqual(mask_area(det), 100)

    def test_mask_area_from_bbox(self):
        det = {"bbox": [0, 0, 10, 20]}
        self.assertEqual(mask_area(det), 200)

    def test_mask_area_zero_without_geometry(self):
        self.assertEqual(mask_area({}), 0)


class SplitTopRowTest(unittest.TestCase):
    def test_fewer_or_equal_points_returned_as_is(self):
        points = [(i * 10, 5) for i in range(5)]
        kept, rejected = split_top_row(points, expected_count=5)
        self.assertEqual(kept, points)
        self.assertEqual(rejected, [])

    def test_extra_points_rejected(self):
        points = [(0, 5), (10, 6), (20, 5), (30, 7), (40, 5), (50, 5)]
        kept, rejected = split_top_row(points, expected_count=5)
        self.assertEqual(len(kept), 5)
        self.assertEqual(len(rejected), 1)
        self.assertIn(rejected[0], points)

    def test_outlier_far_by_y_is_rejected(self):
        points = [(0, 5), (10, 6), (20, 5), (30, 7), (40, 5), (500, 300)]
        kept, rejected = split_top_row(points, expected_count=5)
        self.assertEqual(len(kept), 5)
        self.assertEqual(rejected, [(500, 300)])

    def test_more_than_max_points_pre_rejected(self):
        points = [(i * 10, i % 3) for i in range(20)]
        kept, rejected = split_top_row(points, expected_count=5)
        self.assertEqual(len(kept), 5)
        self.assertGreater(len(rejected), 0)

    def test_single_point_row(self):
        kept, rejected = split_top_row([(5, 5)], expected_count=5)
        self.assertEqual(kept, [(5, 5)])


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
