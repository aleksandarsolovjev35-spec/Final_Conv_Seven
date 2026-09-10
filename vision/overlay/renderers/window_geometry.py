import cv2
import numpy as np

from vision.overlay.renderers.primitives import (
    COLOR_FAIL,
    COLOR_PASS,
    COLOR_SKIP,
    DrawPrimitives,
    LINE_THIN,
)

# Разные цвета идентифицируют физические размеры, красный всегда имеет
# приоритет и означает выход конкретного размера за допуск.
COLOR_TOP_MEASURE = (255, 210, 80)
COLOR_BOTTOM_MEASURE = (0, 190, 255)
COLOR_CROSSBAR_EDGE = (210, 210, 210)


class WindowGeometryRenderer:
    @staticmethod
    def draw_item(img, drawing):
        valid = bool(drawing.get("valid"))
        triggered = bool(drawing.get("triggered"))
        points = WindowGeometryRenderer._points(drawing)
        mask_top = int(round(drawing.get("mask_top", 0)))
        mask_bottom = int(round(drawing.get("mask_bottom", 0)))
        boundary = int(round(drawing.get("boundary_y", 0)))
        degenerate = (
            mask_bottom <= mask_top or boundary < mask_top or boundary > mask_bottom
        )
        contour_color = (
            COLOR_FAIL if triggered or not valid or degenerate else COLOR_PASS
        )
        cv2.polylines(img, [points], True, contour_color, LINE_THIN, lineType=cv2.LINE_AA)

        if not valid or degenerate:
            return

        x_start = int(drawing.get("x_line_start", 0))
        x_end = int(drawing.get("x_line_end", 0))

        if x_end > x_start:
            cv2.line(
                img,
                (x_start, boundary),
                (x_end, boundary),
                COLOR_CROSSBAR_EDGE,
                LINE_THIN,
            )

        WindowGeometryRenderer._draw_measure_segment(
            img,
            x=int(drawing.get("top_x", x_start)),
            y_start=mask_top,
            y_end=boundary,
            color=(
                COLOR_FAIL
                if drawing.get("top_fail")
                else COLOR_TOP_MEASURE
            ),
            failed=bool(drawing.get("top_fail")),
        )
        WindowGeometryRenderer._draw_measure_segment(
            img,
            x=int(drawing.get("bottom_x", x_end)),
            y_start=boundary,
            y_end=mask_bottom,
            color=(
                COLOR_FAIL
                if drawing.get("bottom_fail")
                else COLOR_BOTTOM_MEASURE
            ),
            failed=bool(drawing.get("bottom_fail")),
        )

    @staticmethod
    def draw_count_item(img, drawing):
        points = WindowGeometryRenderer._points(drawing)
        cv2.polylines(img, [points], True, COLOR_FAIL, LINE_THIN, lineType=cv2.LINE_AA)

    @staticmethod
    def draw_ignored(img, drawing):
        points = WindowGeometryRenderer._points(drawing)
        raw_points = [tuple(map(int, point)) for point in points.reshape(-1, 2)]
        for index, start in enumerate(raw_points):
            end = raw_points[(index + 1) % len(raw_points)]
            DrawPrimitives.draw_dashed_line(
                img,
                start,
                end,
                COLOR_SKIP,
                LINE_THIN,
                dash_len=6,
            )

    @staticmethod
    def _draw_measure_segment(img, *, x, y_start, y_end, color, failed):
        y_start = int(y_start)
        y_end = int(y_end)
        width = LINE_THIN
        cv2.line(img, (x, y_start), (x, y_end), color, width)
        tick = 4
        cv2.line(img, (x - tick, y_start), (x + tick, y_start), color, width)
        cv2.line(img, (x - tick, y_end), (x + tick, y_end), color, width)

    @staticmethod
    def _points(drawing):
        mask = drawing.get("mask") or []
        if len(mask) >= 3:
            points = np.asarray(mask, dtype=np.int32)
            if points.ndim == 2 and points.shape[1] == 2:
                return points.reshape(-1, 1, 2)
        x1, y1, x2, y2 = map(
            int,
            drawing.get("bbox") or [0, 0, 0, 0],
        )
        return np.asarray(
            [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            dtype=np.int32,
        ).reshape(-1, 1, 2)
