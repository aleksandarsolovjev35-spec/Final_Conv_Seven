import cv2
import numpy as np

from vision.overlay.palette import (
    COLOR_BLACK_SPOT,
    COLOR_FAIL,
    COLOR_OMISSION_SHORT,
    MASK_ALPHA,
)

# Область — объект omission-short: тот же цвет, что и детекция
# в режиме «МОДЕЛИ»; когда правило сработало, область загорается
# красным как зона нарушения.
COLOR_REGION = COLOR_OMISSION_SHORT

THICK = 1


class BlackSpotsOmissionRenderer:
    """Отрисовка области short omission и подтверждённых пятен.

    Конвенция «красная зона»: область, в которой найдено пятно,
    загорается красным (контур + заливка α=MASK_ALPHA); само пятно —
    в объектном каталожном цвете, как в режиме «МОДЕЛИ».
    """

    @staticmethod
    def draw_region(img, drawing):
        """Контур и полупрозрачная заливка области short omission."""
        region = drawing.get("region_mask")
        origin = drawing.get("region_origin") or [0, 0]
        if region is None or not isinstance(region, np.ndarray):
            return
        if region.ndim != 2 or region.shape[0] < 1 or region.shape[1] < 1:
            return
        ox, oy = int(origin[0]), int(origin[1])
        height, width = img.shape[:2]
        color = COLOR_FAIL if drawing.get("triggered") else COLOR_REGION

        contours, _ = cv2.findContours(
            (region > 0).astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        filled = np.zeros((height, width), dtype=np.uint8)
        for contour in contours:
            contour = contour.reshape(-1, 1, 2).astype(np.int32)
            contour[:, 0, 0] += ox
            contour[:, 0, 1] += oy
            cv2.drawContours(filled, [contour], -1, 255, -1)
            cv2.polylines(
                img, [contour], True, color, THICK,
                lineType=cv2.LINE_AA,
            )

        mask = filled > 0
        if not int(np.count_nonzero(mask)):
            return
        region_color = np.asarray(color, dtype=np.float64)
        blended = (
            img.astype(np.float64) * (1.0 - MASK_ALPHA)
            + region_color.reshape(1, 1, 3) * MASK_ALPHA
        )
        img[mask] = blended[mask].round().astype(np.uint8)

    @staticmethod
    def draw_hit(img, drawing):
        """Подтверждённое пятно: только пересечение с областью,
        каталожный цвет класса + заливка α=MASK_ALPHA. Часть пятна
        вне области не рисуется.
        """
        contours = []
        for raw in drawing.get("overlap_contours") or []:
            if not raw:
                continue
            contours.append(np.asarray(raw, dtype=np.int32).reshape(-1, 1, 2))
        if not contours:
            # Фолбэк (контуров быть не должно): маска целиком.
            mask = drawing.get("mask")
            if mask and len(mask) >= 3:
                contours = [np.asarray(mask, dtype=np.int32).reshape(-1, 1, 2)]
            else:
                x1, y1, x2, y2 = map(int, drawing.get("bbox") or [0, 0, 0, 0])
                contours = [np.asarray(
                    [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                    dtype=np.int32,
                ).reshape(-1, 1, 2)]
        overlay = img.copy()
        cv2.fillPoly(overlay, contours, COLOR_BLACK_SPOT)
        cv2.addWeighted(overlay, MASK_ALPHA, img, 1 - MASK_ALPHA, 0, img)
        for contour in contours:
            cv2.polylines(img, [contour], True, COLOR_BLACK_SPOT, THICK, lineType=cv2.LINE_AA)
