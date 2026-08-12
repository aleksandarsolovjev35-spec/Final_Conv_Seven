import cv2
import numpy as np

from utils.contour_point import find_contour_point
from utils.intersections import find_vertical_intersection, get_vertical_intersections


def process_flatness_contour(frame, contour, manager, camera_index=None):
    """
    Обрабатывает контур плоскостности.
    Рисует контур, вертикаль через центр масс, выводит длину.
    При наличии camera_index выводит отладочную информацию о пересечениях.
    """
    import numpy as np
    from utils.intersections import get_vertical_intersections

    cv2.drawContours(frame, [contour], -1, (0, 255, 0), 1)

    # Вычисляем средний x
    if contour.ndim == 3:
        xs = contour[:, 0, 0]
    else:
        xs = contour[:, 0]
    x_min = int(np.min(xs))
    x_max = int(np.max(xs))
    x_center = x_min + (x_max - x_min) // 2

    # Получаем все пересечения
    ys = get_vertical_intersections(contour, x_center)

    # Отладка

    if len(ys) >= 2:
        ys_sorted = sorted(ys)
        y_top = int(min(ys_sorted))
        # Ищем подходящую нижнюю точку
        y_bottom = None
        if len(ys_sorted) == 2:
            y_bottom = int(max(ys_sorted))
        else:
            for y in ys_sorted[1:]:
                if y - y_top > 7:
                    y_bottom = int(y)
                    break
            if y_bottom is None:
                y_bottom = int(max(ys_sorted))
        line_length = y_bottom - y_top
        cv2.line(frame, (x_center, y_top), (x_center, y_bottom), (255, 0, 0), 2)
        cv2.putText(frame, f"{line_length}px", (x_center + 10, (y_top + y_bottom) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)
        # Бракуем по длине линии
        if line_length > manager.thresholds.get('flatness_length', 25):
            with manager.squares_lock:
                manager.squares_state[0] = 2


def is_contour_inside_or_intersecting(contour1, contour2):
    """
    Проверяет, находится ли contour1 внутри или пересекается с contour2.
    :param contour1: Первый контур.
    :param contour2: Второй контур.
    :return: Правда, если есть пересечение или вложенность, иначе ложь.
    """
    try:
        # Преобразование контуров в формат для OpenCV
        cnt1 = np.array(contour1, dtype=np.int32).reshape((-1, 1, 2))
        cnt2 = np.array(contour2, dtype=np.int32).reshape((-1, 1, 2))

        # Проверка на пересечение или вложенность
        # 1. Есть ли точки contour1 внутри contour2
        for point in cnt1:
            pt = (int(point[0][0]), int(point[0][1]))
            if cv2.pointPolygonTest(cnt2, pt, False) >= 0:
                return True

        # 2. Есть ли точки contour2 внутри contour1
        for point in cnt2:
            pt = (int(point[0][0]), int(point[0][1]))
            if cv2.pointPolygonTest(cnt1, pt, False) >= 0:
                return True

        # 3. Есть ли пересечение контуров
        # Поиск выпуклых оболочек для оптимизации
        hull1 = cv2.convexHull(cnt1)
        hull2 = cv2.convexHull(cnt2)
        ret, _ = cv2.intersectConvexConvex(hull1, hull2)
        return ret > 0

    except Exception as e:
        print(f"Error in is_contour_inside_or_intersecting: {e}")
        print(f"Contour1: {contour1}")
        print(f"Contour2: {contour2}")
        return False
