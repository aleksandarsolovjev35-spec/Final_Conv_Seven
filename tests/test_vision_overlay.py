"""Оверлеи: RawOverlay, DebugOverlay и все рендереры разметки.

Каждый тип drawing из dispatch-таблицы DebugOverlay прогоняется на
синтетическом кадре: рендер не должен падать и обязан возвращать кадр
той же формы.
"""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from vision.overlay.debug_overlay import DebugOverlay
from vision.overlay.raw_overlay import RawOverlay
from vision.overlay.renderers.primitives import (
    COLOR_FAIL,
    COLOR_PASS,
    DrawPrimitives,
)
from domain.defect_rules import RuleResult

MASK = [[10, 10], [60, 10], [60, 60], [10, 60]]
RASTER = np.zeros((24, 32), dtype=np.uint8)
RASTER[8:16, 8:20] = 255
CONTOURS = [[[10, 10], [20, 10], [20, 20], [10, 20]]]


def drawing(draw_type, **overrides):
    """Универсальный drawing с полным набором полей рендереров."""
    base = {
        "type": draw_type,
        "role": "TOP",
        "bbox": [10, 10, 60, 60],
        "mask": MASK,
        "points": [[10, 10], [60, 10], [60, 60], [10, 60]],
        "message": "TEST",
        "index": 1,
        "triggered": True,
        "valid": True,
        "invalid": False,
        "slot": 0,
        "fits": True,
        "centered": True,
        "shifted": False,
        "label": "label",
        "tolerance": 5,
        "center": [35, 35],
        "target_center": [35, 35],
        "placed_center": [35, 35],
        "top_x": 20,
        "bottom_x": 40,
        "x_line_start": 10,
        "x_line_end": 60,
        "mask_top": 10.0,
        "mask_bottom": 60.0,
        "boundary_y": 30.0,
        "top_px": 20.0,
        "bottom_px": 30.0,
        "full_height": 50.0,
        "top_fail": False,
        "bottom_fail": False,
        "x_start": 0,
        "y_start": 0,
        "x_end": 100,
        "y_end": 20,
        "x": 20,
        "y_top": 5,
        "y_bottom": 45,
        "x_a": 15,
        "y_a": 20,
        "x_b": 45,
        "y_b": 20,
        "start": [10, 20],
        "end": [50, 20],
        "contact_point": [30, 40],
        "projection_point": [30, 20],
        "distance_px": 20.0,
        "deviation_px": 1.0,
        "raster": RASTER,
        "overlap_raster": RASTER,
        "forbidden_raster": RASTER,
        "cleanup_raster": RASTER,
        "excess_mask": RASTER,
        "confirmed_raster": RASTER,
        "contours": CONTOURS,
        "excess_contours": CONTOURS,
        "forbidden_contours": CONTOURS,
        "overlap_contours": CONTOURS,
        "cleanup_contours": CONTOURS,
        "excess_origin": [0, 0],
        "top_line": {"x_start": 0, "y_start": 0, "x_end": 100, "y_end": 10,
                     "sample_points": [[0, 0]]},
        "limit_line": {"x_start": 0, "y_start": 20, "x_end": 100, "y_end": 30,
                       "sample_points": []},
        "window_mask": MASK,
        "window_bbox": [10, 10, 60, 60],
        "sink_mask": MASK,
        "sink_bbox": [10, 10, 60, 60],
        "glass_mask": MASK,
        "glass_bbox": [10, 10, 60, 60],
        "contact_mask": MASK,
        "contact_bbox": [10, 10, 60, 60],
        "platform_mask": MASK,
        "platform_bbox": [10, 10, 60, 60],
        "case_mask": MASK,
        "case_bbox": [10, 10, 60, 60],
        "central_mask": MASK,
        "central_bbox": [10, 10, 60, 60],
        "pin_masks": [MASK],
        "pin_bboxes": [[10, 10, 60, 60]],
        "contact_masks": [MASK],
        "contact_bboxes": [[10, 10, 60, 60]],
        "case_central_mask": MASK,
        "case_central_bbox": [10, 10, 60, 60],
        "draw_window_reference": True,
        "draw_platform_reference": True,
        "draw_contact_references": True,
        "draw_central_reference": True,
        "failures": [],
        "group": "L",
        "sink_index": 1,
        "glass_index": 1,
        "contact_index": 1,
        "color_hint": None,
    }
    base.update(overrides)
    return base


ALL_DRAWING_TYPES = [
    "construction_error", "rule_bbox",
    "window_geometry_item", "window_geometry_count_item",
    "window_geometry_ignored",
    "window_sink_overlap", "window_sink_invalid_reference",
    "window_sink_reference_count_item",
    "contacts_long_item", "contacts_long_count_item",
    "contacts_long_invalid_mask", "contacts_long_ignored",
    "contacts_long_fit_line", "contacts_long_level_center",
    "contacts_long_omission_line", "contacts_long_omission_distance",
    "contacts_long_omission_missing", "contacts_long_inscribed_rect",
    "contacts_short_item", "contacts_short_count_item",
    "contacts_short_invalid_mask", "contacts_short_ignored",
    "contacts_short_level_line", "contacts_short_level_center",
    "contacts_short_height_segment", "contacts_short_omission_line",
    "contacts_short_omission_distance", "contacts_short_omission_missing",
    "contacts_short_inscribed_rect",
    "long_omission_item", "short_omission_item",
    "top_contacts_platform_bbox", "top_contacts_group_reference",
    "top_contacts_distance", "top_contacts_item",
    "top_contacts_count_item", "top_contacts_invalid_mask",
    "top_contacts_ignored", "top_contact_inscribed_rect",
    "top_platform_actual", "top_platform_inscribed_rect",
    "top_platform_centers",
    "top_sinks_references", "top_sink_forbidden_region",
    "top_sink_invalid_reference", "top_sink_reference_contact",
    "top_glass_cleanup_references", "top_glass_cleanup_region",
    "top_glass_bad_references", "top_glass_contact_overlap",
    "top_glass_bad_glass",
    "black_spots_omission_region", "black_spots_omission_hit",
    "platform_overlap_platform", "platform_overlap_boundary",
    "platform_overlap_region",
]


class RawOverlayTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((120, 160, 3), dtype=np.uint8)

    def test_empty_detections_returns_copy(self):
        result = RawOverlay.render(self.frame, [])
        self.assertEqual(result.shape, self.frame.shape)

    def test_render_mask_and_bbox(self):
        detections = [
            {"class": "flatness", "mask": MASK},
            {"class": "platform", "bbox": [10, 10, 60, 60]},
            {"class": "unknown_class", "bbox": [70, 70, 90, 90]},
        ]
        result = RawOverlay.render(self.frame, detections)
        self.assertEqual(result.shape, self.frame.shape)
        self.assertFalse(np.array_equal(result, self.frame))

    def test_unknown_class_uses_default_color(self):
        overlay = RawOverlay._draw_bbox
        img = self.frame.copy()
        overlay(img, [0, 0, 10, 10], (180, 180, 180))
        self.assertTrue(img[1:9, 1:9].any())


class DebugOverlayTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((120, 160, 3), dtype=np.uint8)

    def test_render_frame_no_drawings(self):
        result = DebugOverlay.render_frame(
            self.frame, "TOP", [RuleResult("x", False)],
        )
        self.assertEqual(result.shape, self.frame.shape)

    def test_render_frame_filters_by_role(self):
        result = RuleResult("x", True, drawings=[
            drawing("rule_bbox", role="OTHER"),
            drawing("rule_bbox", role="TOP"),
        ])
        DebugOverlay.render_frame(self.frame, "TOP", [result])

    def test_construction_error_dedup_by_message(self):
        result = RuleResult("x", True, drawings=[
            drawing("construction_error", message="SAME"),
            drawing("construction_error", message="SAME"),
            drawing("construction_error", message="OTHER"),
        ])
        DebugOverlay.render_frame(self.frame, "TOP", [result])

    def test_stats_panel_entry_skipped(self):
        result = RuleResult("x", True, drawings=[
            drawing("stats_panel_entry"),
        ])
        DebugOverlay.render_frame(self.frame, "TOP", [result])

    def test_platform_overlap_duplicate_skipped(self):
        result = RuleResult("x", True, drawings=[
            drawing("platform_overlap_platform"),
            drawing("top_platform_actual"),
        ])
        DebugOverlay.render_frame(self.frame, "TOP", [result])

    def test_all_drawing_types_render(self):
        for draw_type in ALL_DRAWING_TYPES:
            with self.subTest(draw_type=draw_type):
                result = RuleResult("x", True, drawings=[drawing(draw_type)])
                img = DebugOverlay.render_frame(self.frame, "TOP", [result])
                self.assertEqual(img.shape, self.frame.shape)

    def test_black_spots_region_offset_fill(self):
        # Область со смещённым origin: рендер не падает и заливает маску.
        raster = np.zeros((24, 32), dtype=np.uint8)
        raster[8:16, 8:20] = 255
        result = RuleResult("x", True, drawings=[drawing(
            "black_spots_omission_region",
            region_mask=raster,
            region_origin=[30, 20],
        )])
        img = DebugOverlay.render_frame(self.frame, "TOP", [result])
        self.assertEqual(img.shape, self.frame.shape)
        # Центр области (origin 30,20 + raster (12,14)) попадает в кадр и
        # заливается отличным от фона цветом.
        self.assertTrue(img[20 + 12, 30 + 14].any())

    def test_black_spots_region_missing_raster_noop(self):
        result = RuleResult("x", True, drawings=[drawing(
            "black_spots_omission_region",
            region_mask=None,
            region_origin=[0, 0],
        )])
        img = DebugOverlay.render_frame(self.frame, "TOP", [result])
        self.assertTrue(np.array_equal(img, self.frame))

    def test_black_spots_hit_drawn(self):
        result = RuleResult("x", True, drawings=[drawing(
            "black_spots_omission_hit", mask=MASK,
        )])
        img = DebugOverlay.render_frame(self.frame, "TOP", [result])
        self.assertTrue(img.any())


class DrawPrimitivesTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((120, 160, 3), dtype=np.uint8)

    def test_pick_color(self):
        self.assertEqual(DrawPrimitives.pick_color({"triggered": True}),
                         COLOR_FAIL)
        self.assertEqual(DrawPrimitives.pick_color({"triggered": False}),
                         COLOR_PASS)
        self.assertEqual(
            DrawPrimitives.pick_color(
                {"triggered": False, "color_hint": "glass"}),
            (200, 100, 0),
        )

    def test_draw_rule_bbox_with_mask(self):
        DrawPrimitives.draw_rule_bbox(self.frame, drawing("rule_bbox"))
        self.assertTrue(self.frame.any())

    def test_draw_rule_bbox_without_mask(self):
        DrawPrimitives.draw_rule_bbox(
            self.frame, drawing("rule_bbox", mask=None),
        )

    def test_draw_text_with_bg(self):
        DrawPrimitives.draw_text_with_bg(
            self.frame, "HELLO", (10, 10), COLOR_FAIL, center_x=True,
        )

    def test_draw_dashed_line(self):
        DrawPrimitives.draw_dashed_line(
            self.frame, (0, 0), (100, 0), COLOR_PASS, 1,
        )
        DrawPrimitives.draw_dashed_line(
            self.frame, (0, 0), (0, 0), COLOR_PASS, 1,
        )


class PaletteConsistencyTest(unittest.TestCase):
    """Один и тот же объект — один цвет в режимах «МОДЕЛИ» и «ПРАВИЛА».

    Общий каталог ``vision/overlay/palette.py`` — единственный источник
    объектных цветов; статус правила (OK/FAIL) при этом сохраняется.

    Проверка цвета устойчива к сглаживанию ``LINE_AA``: на чёрном фоне
    альфа просто масштабирует все каналы пикселя, поэтому сравнивается
    нормированное соотношение каналов, а не абсолютные значения.
    """

    def setUp(self):
        self.frame = np.zeros((120, 160, 3), dtype=np.uint8)

    @staticmethod
    def _has_color_tint(img, color, min_intensity=60, atol=0.05):
        target = np.asarray(color, dtype=np.float64)
        target_max = target.max()
        if target_max <= 0:
            return False
        target_norm = target / target_max
        px = img.reshape(-1, 3).astype(np.float64)
        px_max = px.max(axis=1)
        mask = px_max >= min_intensity
        if not mask.any():
            return False
        px_norm = px[mask] / px_max[mask, None]
        close = (np.abs(px_norm - target_norm[None, :]) <= atol).all(axis=1)
        return bool(close.any())

    @staticmethod
    def _offscreen_line():
        # Ссылочные линии за пределами кадра: не мешают проверке цвета маски.
        return {"x_start": 500, "y_start": 500, "x_end": 501, "y_start": 500}

    def test_raw_overlay_uses_shared_catalog(self):
        import vision.overlay.raw_overlay as raw_overlay_mod
        from vision.overlay import palette
        self.assertIs(raw_overlay_mod.CLASS_COLORS, palette.CLASS_COLORS)
        self.assertIs(raw_overlay_mod.DEFAULT_COLOR, palette.DEFAULT_COLOR)

    def test_platform_color_same_in_both_modes(self):
        from vision.overlay import palette
        from vision.overlay.raw_overlay import RawOverlay
        # Режим «МОДЕЛИ»: детекция класса platform.
        img = RawOverlay.render(self.frame, [
            {"class": "platform", "bbox": [10, 10, 60, 60]},
        ])
        self.assertTrue(self._has_color_tint(img, palette.COLOR_PLATFORM))
        # Режим «ПРАВИЛА»: целая платформа (top_platform_actual) — тот же цвет.
        result = RuleResult("x", True, drawings=[
            drawing("top_platform_actual", triggered=False, valid=True),
        ])
        img = DebugOverlay.render_frame(self.frame, "TOP", [result])
        self.assertTrue(self._has_color_tint(img, palette.COLOR_PLATFORM))
        # Статус сохраняется: повреждённая платформа — красная, не объектная.
        result = RuleResult("x", True, drawings=[
            drawing("top_platform_actual", triggered=False, valid=False),
        ])
        img = DebugOverlay.render_frame(self.frame, "TOP", [result])
        self.assertTrue(self._has_color_tint(img, COLOR_FAIL))
        self.assertFalse(self._has_color_tint(img, palette.COLOR_PLATFORM))

    def test_omission_colors_match_model_classes(self):
        from vision.overlay import palette
        long_img = DebugOverlay.render_frame(self.frame, "SPIDER_LEFT", [
            RuleResult("x", True, drawings=[
                drawing("long_omission_item", role="SPIDER_LEFT",
                        top_line=self._offscreen_line(),
                        limit_line=self._offscreen_line(),
                        excess_mask=None, excess_contours=[]),
            ]),
        ])
        self.assertTrue(self._has_color_tint(long_img, palette.COLOR_OMISSION_LONG))
        short_img = DebugOverlay.render_frame(self.frame, "SPIDER_IN", [
            RuleResult("x", True, drawings=[
                drawing("short_omission_item", role="SPIDER_IN",
                        top_line=self._offscreen_line(),
                        limit_line=self._offscreen_line(),
                        excess_mask=None, excess_contours=[]),
            ]),
        ])
        self.assertTrue(self._has_color_tint(short_img, palette.COLOR_OMISSION_SHORT))

    def test_references_take_model_class_colors(self):
        from vision.overlay import palette
        # Окно — зона нарушения: красная заливка/контур (не цвет класса);
        # раковина — каталожный цвет objects из режима «МОДЕЛИ».
        img = DebugOverlay.render_frame(self.frame, "INPUT_LEFT", [
            RuleResult("x", True, drawings=[
                drawing("window_sink_overlap", role="INPUT_LEFT",
                        window_mask=None, window_bbox=[10, 10, 60, 40],
                        sink_mask=[[20, 15], [50, 15], [50, 35], [20, 35]],
                        sink_bbox=[20, 15, 50, 35]),
            ]),
        ])
        self.assertTrue(self._has_color_tint(img, palette.COLOR_FAIL))
        self.assertTrue(self._has_color_tint(img, palette.COLOR_OBJECTS))
        self.assertFalse(self._has_color_tint(img, palette.COLOR_FLATNESS))
        # Ссылки на платформу/корпус/централь/пины в стекле — цвета классов;
        # контуры не перекрывают друг друга, чтобы цвета не смешивались.
        refs = drawing("top_glass_cleanup_references",
                       platform_mask=None, platform_bbox=[10, 10, 40, 25],
                       case_mask=None, case_bbox=[50, 10, 80, 25],
                       central_mask=None, central_bbox=[10, 40, 40, 55],
                       pin_masks=[None], pin_bboxes=[[50, 40, 70, 55]])
        img = DebugOverlay.render_frame(self.frame, "TOP", [
            RuleResult("x", True, drawings=[refs]),
        ])
        for color in (
            palette.COLOR_PLATFORM,
            palette.COLOR_CASE,
            palette.COLOR_CASE_CENTRAL,
            palette.COLOR_PIN,
        ):
            self.assertTrue(self._has_color_tint(img, color))

    def test_window_sinks_zone_red_sink_catalog(self):
        # Конвенция «красная зона»: окно загорается красным, раковина —
        # в каталожном цвете objects (как в «МОДЕЛИ»).
        from vision.overlay import palette
        img = DebugOverlay.render_frame(self.frame, "INPUT_LEFT", [
            RuleResult("x", True, drawings=[
                drawing("window_sink_overlap", role="INPUT_LEFT",
                        window_mask=[[10, 10], [60, 10], [60, 40], [10, 40]],
                        window_bbox=[10, 10, 60, 40],
                        sink_mask=[[20, 15], [50, 15], [50, 35], [20, 35]],
                        sink_bbox=[20, 15, 50, 35]),
            ]),
        ])
        self.assertTrue(self._has_color_tint(img, palette.COLOR_FAIL))
        self.assertTrue(self._has_color_tint(img, palette.COLOR_OBJECTS))
        self.assertFalse(self._has_color_tint(img, palette.COLOR_FLATNESS))

    def test_black_spots_region_red_when_triggered(self):
        # Область с подтверждённым пятном — красная зона; пятно —
        # каталожный цвет black-spot (как в «МОДЕЛИ»).
        from vision.overlay import palette
        raster = np.zeros((20, 20), dtype=np.uint8)
        raster[5:15, 5:15] = 255
        spot_local = np.asarray(
            [[17, 17], [23, 17], [23, 23], [17, 23]], dtype=np.int32,
        ) - np.array([10, 10])
        spot_canvas = np.zeros((20, 20), dtype=np.uint8)
        cv2.fillPoly(spot_canvas, [spot_local], 255)
        overlap = cv2.bitwise_and(spot_canvas, raster)
        contours, _ = cv2.findContours(
            overlap, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        frame_contours = [
            (c.reshape(-1, 2) + np.array([10, 10])).tolist() for c in contours
        ]
        img = DebugOverlay.render_frame(self.frame, "SPIDER_IN", [
            RuleResult("x", True, drawings=[
                drawing("black_spots_omission_region", role="SPIDER_IN",
                        triggered=True,
                        region_mask=raster, region_origin=[10, 10]),
                drawing("black_spots_omission_hit", role="SPIDER_IN",
                        triggered=True,
                        mask=[[17, 17], [23, 17], [23, 23], [17, 23]],
                        bbox=[17, 17, 23, 23],
                        overlap_contours=frame_contours),
            ]),
        ])
        self.assertTrue(self._has_color_tint(img, palette.COLOR_FAIL))
        self.assertTrue(
            self._has_color_tint(img, palette.COLOR_BLACK_SPOT, atol=0.1),
        )
        self.assertFalse(self._has_color_tint(img, palette.COLOR_OMISSION_SHORT))

    def test_black_spots_hit_only_intersection(self):
        # Рисуется только пересечение пятна с областью: часть пятна
        # за пределами области пропуска не рисуется.
        from vision.overlay import palette
        raster = np.zeros((20, 20), dtype=np.uint8)
        raster[5:15, 5:15] = 255
        # Пятно в кадре x 10..30, y 10..25; область x 15..24, y 15..24.
        # Пересечение считаем как в правиле: в локальных координатах
        # области (origin [10, 10]), затем сдвиг в кадр.
        spot_mask = [[10, 10], [30, 10], [30, 25], [10, 25]]
        spot_local = (
            np.asarray(spot_mask, dtype=np.int32) - np.array([10, 10])
        )
        spot_canvas = np.zeros((20, 20), dtype=np.uint8)
        cv2.fillPoly(spot_canvas, [spot_local], 255)
        overlap = cv2.bitwise_and(spot_canvas, raster)
        contours, _ = cv2.findContours(
            overlap, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        frame_contours = [
            (c.reshape(-1, 2) + np.array([10, 10])).tolist() for c in contours
        ]
        img = DebugOverlay.render_frame(self.frame, "SPIDER_IN", [
            RuleResult("x", True, drawings=[
                drawing("black_spots_omission_region", role="SPIDER_IN",
                        triggered=True,
                        region_mask=raster, region_origin=[10, 10]),
                drawing("black_spots_omission_hit", role="SPIDER_IN",
                        triggered=True,
                        mask=spot_mask, bbox=[10, 10, 30, 25],
                        overlap_contours=frame_contours),
            ]),
        ])
        # Пересечение залито цветом пятна (atol шире: фиолетовая
        # линия ложится на красную заливку зоны, AA смешивает каналы).
        self.assertTrue(
            self._has_color_tint(img, palette.COLOR_BLACK_SPOT, atol=0.1),
        )
        # Угол пятна вне области не залит (чёрный кадр).
        self.assertEqual(int(img[11:14, 11:14].max()), 0)

    def test_black_spots_region_catalog_color_when_ok(self):
        # Без подтверждённого пятна область — просто объект omission-short
        # в каталожном цвете (как в «МОДЕЛИ»), красного нет.
        from vision.overlay import palette
        raster = np.zeros((20, 20), dtype=np.uint8)
        raster[5:15, 5:15] = 255
        img = DebugOverlay.render_frame(self.frame, "SPIDER_IN", [
            RuleResult("x", False, drawings=[
                drawing("black_spots_omission_region", role="SPIDER_IN",
                        triggered=False,
                        region_mask=raster, region_origin=[10, 10]),
            ]),
        ])
        self.assertTrue(self._has_color_tint(img, palette.COLOR_OMISSION_SHORT))
        self.assertFalse(self._has_color_tint(img, palette.COLOR_FAIL))


if __name__ == "__main__":
    unittest.main()
