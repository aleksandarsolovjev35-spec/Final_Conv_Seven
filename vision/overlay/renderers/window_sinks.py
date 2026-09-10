import cv2
import numpy as np

from vision.overlay.palette import COLOR_OBJECTS
from vision.overlay.renderers.primitives import (
    COLOR_FAIL,
    LINE_THIN,
    MASK_ALPHA,
)


class WindowSinksRenderer:
    @staticmethod
    def draw_overlap(img, drawing):
        # Конвенция «красная зона»: окно, где найдена раковина, загорается
        # красным (заливка α=MASK_ALPHA всегда, контур — когда окно не
        # рисуется правилом window_geometry). Раковина — объектный
        # каталожный цвет, как в режиме «МОДЕЛИ».
        window_points = WindowSinksRenderer._points(
            drawing.get("window_mask"),
            drawing.get("window_bbox"),
        )
        sink_points = WindowSinksRenderer._points(
            drawing.get("sink_mask"),
            drawing.get("sink_bbox"),
        )
        WindowSinksRenderer._fill(img, window_points, COLOR_FAIL)
        if drawing.get("draw_window_reference", True):
            cv2.polylines(
                img, [window_points], True, COLOR_FAIL, LINE_THIN,
                lineType=cv2.LINE_AA,
            )
        WindowSinksRenderer._fill(img, sink_points, COLOR_OBJECTS)
        cv2.polylines(img, [sink_points], True, COLOR_OBJECTS, LINE_THIN, lineType=cv2.LINE_AA)

    @staticmethod
    def draw_invalid_reference(img, drawing):
        points = WindowSinksRenderer._points(
            drawing.get("mask"),
            drawing.get("bbox"),
        )
        cv2.polylines(img, [points], True, COLOR_FAIL, LINE_THIN, lineType=cv2.LINE_AA)

    @staticmethod
    def draw_reference_count_item(img, drawing):
        points = WindowSinksRenderer._points(
            drawing.get("mask"),
            drawing.get("bbox"),
        )
        cv2.polylines(img, [points], True, COLOR_FAIL, LINE_THIN, lineType=cv2.LINE_AA)

    @staticmethod
    def _fill(img, points, color):
        overlay = img.copy()
        cv2.fillPoly(overlay, [points], color)
        cv2.addWeighted(overlay, MASK_ALPHA, img, 1 - MASK_ALPHA, 0, img)

    @staticmethod
    def _points(mask, bbox):
        mask = mask or []
        if len(mask) >= 3:
            points = np.asarray(mask, dtype=np.int32)
            if points.ndim == 2 and points.shape[1] == 2:
                return points.reshape(-1, 1, 2)
        x1, y1, x2, y2 = map(int, bbox or [0, 0, 0, 0])
        return np.asarray(
            [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            dtype=np.int32,
        ).reshape(-1, 1, 2)
