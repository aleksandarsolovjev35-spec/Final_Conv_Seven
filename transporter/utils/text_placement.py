import cv2
import numpy


def text_placement(moment, draw_area, area, frame):
    """
    Рассчитывает позицию текста для заданной зоны и рисует его.
    :param moment: Моменты обнаруженного контура.
    :param draw_area: Область, допустимая для рисования.
    :param area: Вся обнаруженная область.
    :param frame: Изображение с камеры целиком.
    :return: None
    """
    if moment["m00"] != 0:
        c_x = int(moment["m10"] / moment["m00"])
        c_y = int(moment["m01"] / moment["m00"])

        if draw_area:
            text_size = 0.3
            text_color = (0, 0, 255)
            text = f"{int(area)}"
            text_size_tuple = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX, text_size, 1)[0]
            text_x = c_x - text_size_tuple[0] // 2
            text_y = c_y + text_size_tuple[1] // 2
            cv2.putText(
                frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX,
                text_size, text_color, 1
            )
