def find_vertical_intersection(contour, start_x, start_y, direction='down'):
    """
    Находит пересечение контура с вертикальной линией x = start_x.
    :param contour: контур
    :param start_x: x-координата вертикали
    :param start_y: y-координата начальной точки (для фильтрации)
    :param direction: 'down' - искать точки ниже start_y, 'up' - выше
    :return: (x, y) или None
    """
    intersections = []
    for i in range(len(contour)):
        if contour.ndim == 3:
            pt1 = contour[i][0]
            pt2 = contour[(i + 1) % len(contour)][0]
        else:
            pt1 = contour[i]
            pt2 = contour[(i + 1) % len(contour)]

        if not (hasattr(pt1, "__len__") and hasattr(pt2, "__len__")):
            continue

        # Проверка, что вертикаль пересекает ребро
        if (pt1[0] <= start_x <= pt2[0]) or (pt2[0] <= start_x <= pt1[0]):
            denom = pt2[0] - pt1[0]
            if abs(denom) < 1e-5:
                continue  # вертикальное ребро – пропускаем (можно обработать отдельно)
            t = (start_x - pt1[0]) / denom
            y = pt1[1] + t * (pt2[1] - pt1[1])
            intersections.append((start_x, y))

    if not intersections:
        return None

    if direction == 'down':
        # Точки ниже start_y
        below = [p for p in intersections if p[1] > start_y]
        if not below:
            return None
        # Возвращаем самую верхнюю из нижних (ближайшую к start_y)
        return min(below, key=lambda p: p[1])
    else:  # up
        above = [p for p in intersections if p[1] < start_y]
        if not above:
            return None
        # Возвращаем самую нижнюю из верхних (ближайшую к start_y)
        return max(above, key=lambda p: p[1])


def get_vertical_intersections(contour, x):
    """
    Возвращает все y-координаты пересечений вертикальной линии x = x с контуром.
    Учитывает вертикальные рёбра (добавляет оба конца).
    """
    intersections = []
    for i in range(len(contour)):
        if contour.ndim == 3:
            pt1 = contour[i][0]
            pt2 = contour[(i + 1) % len(contour)][0]
        else:
            pt1 = contour[i]
            pt2 = contour[(i + 1) % len(contour)]

        # Проверка на вертикальное ребро
        if abs(pt2[0] - pt1[0]) < 1e-5 and abs(pt1[0] - x) < 1e-5:
            # Вертикальное ребро точно на x - добавляем оба конца
            intersections.append(pt1[1])
            intersections.append(pt2[1])
            continue

        # Обычное пересечение
        if (pt1[0] <= x <= pt2[0]) or (pt2[0] <= x <= pt1[0]):
            denom = pt2[0] - pt1[0]
            if abs(denom) < 1e-5:
                continue
            t = (x - pt1[0]) / denom
            y = pt1[1] + t * (pt2[1] - pt1[1])
            intersections.append(y)

    # Удаляем дубликаты и сортируем
    unique_y = sorted(set(intersections))
    return unique_y