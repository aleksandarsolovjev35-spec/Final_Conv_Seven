import cv2
import numpy as np

def bounding_rectangular(y_max_global, y_min_global, segment, frame):
    """
    Строит окаймляющий прямоугольник вокруг участка изображения.
    :param y_max_global: Верхняя граница кадра по y
    :param y_min_global: Нижняя граница кадра по y
    :param segment: Участок изображения
    :param frame: Кадр, содержащий изображение
    :return:
    """
    x_min, y_min, width, height = cv2.boundingRect(np.array(segment))

    y_min_global = min(y_min_global, y_min)
    y_max_global = max(y_max_global, y_min + height)

    distance_y = (y_max_global - y_min_global - 1)

    box = np.array([[x_min, y_min],
                    [x_min + width - 1, y_min],
                    [x_min + width - 1, y_min + height - 1],
                    [x_min, y_min + height - 1]])

    if distance_y > 0:
        segment = segment.astype(int)

        cv2.polylines(frame,
                      [box],
                      isClosed=True,
                      color=(255, 0, 0),
                      thickness=2
                      )
        cv2.polylines(frame,
                      [segment],
                      isClosed=True,
                      color=(0, 0, 255),
                      thickness=2
                      )

    return distance_y
