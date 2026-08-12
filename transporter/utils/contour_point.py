import numpy as np


def find_contour_point(contour, target_x, target_y):
    """
    Определяет массив точек на одинаковом расстоянии от контура до заданной точки.
    :param contour: Заданный контур.
    :param target_x: X-координата искомой точки.
    :param target_y: Y-координата искомой точки.
    :return: Массив точек.
    """
    if contour.ndim == 3:
        contour_points = contour[:, 0, :]
    else:
        contour_points = contour
    distances = np.sqrt((contour_points[:, 0] - target_x) ** 2 + (contour_points[:, 1] - target_y) ** 2)
    return contour_points[np.argmin(distances)]
