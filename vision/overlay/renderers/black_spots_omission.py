import cv2
import numpy as np

COLOR_REGION = (0, 255, 200)

THICK = 1
MASK_ALPHA = 0.18


class BlackSpotsOmissionRenderer:
    """Отрисовка области short omission (опорная область для пятен black-spot).

    Сами подтверждённые пятна рисуются через общий примитив ``rule_bbox``
    (``DrawPrimitives.draw_rule_bbox``) уже в ``DebugOverlay``.
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
                img, [contour], True, COLOR_REGION, THICK,
                lineType=cv2.LINE_AA,
            )

        mask = filled > 0
        if not int(np.count_nonzero(mask)):
            return
        color = np.asarray(COLOR_REGION, dtype=np.float64)
        blended = (
            img.astype(np.float64) * (1.0 - MASK_ALPHA)
            + color.reshape(1, 1, 3) * MASK_ALPHA
        )
        img[mask] = blended[mask].round().astype(np.uint8)
