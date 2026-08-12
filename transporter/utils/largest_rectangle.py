import cv2
import numpy


def largest_rectangle(contour):
    """
    Строит для заданного контура окаймляющий прямоугольник наибольшей площади.
    :param contour: Контур объекта, который нужно обвести
    :return: Кортеж вида (прямоугольник, площадь)
    """
    x, y, w, h = cv2.boundingRect(contour)
    mask = numpy.zeros((h, w), dtype=numpy.uint8)
    cv2.drawContours(mask,
                     [contour - (x, y)],
                     0,
                     (255.0, 0.0, 0.0),
                     -1)

    height = numpy.zeros((h, w), dtype=int)

    for j in range(w):
        for i in range(h):
            if mask[i, j] == 255:
                height[i, j] = 1 + height[i - 1, j] if i > 0 else 1
            else:
                height[i, j] = 0

    max_area = 0
    best_rect = None

    for i in range(h):
        stack = []
        for j in range(w + 1):
            if j < w:
                h = height[i, j]
            else:
                h = 0

            start = j

            while stack and stack[-1][1] > h:
                j_prev, h_prev = stack.pop()
                area = (j - j_prev) * h_prev
                if area > max_area:
                    max_area = area
                    best_rect = (j_prev, i - h_prev + 1, j - j_prev - 3, h_prev - 3)
                start = j_prev
            stack.append((start, h))

    if best_rect is not None:
        i, j, w, h = best_rect
        box = numpy.array([
            [i, j],
            [i + w, j],
            [i + w, j + h],
            [i, j + h]
        ],
            dtype=numpy.int32)

        box += (x, y)

        return box, max_area

    else:
        return None, 0
