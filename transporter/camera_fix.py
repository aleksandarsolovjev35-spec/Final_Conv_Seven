"""
Определяет дополнительную программу для отладки камер.
"""
import cv2
import numpy as np

# Настройки
NUM_CAMERAS = 3
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
BUTTON_HEIGHT = 50
CAMERA_RESOLUTION = (1280, 720)

# Инициализация камер
cameras = []
for i in range(NUM_CAMERAS):
    cap = cv2.VideoCapture(i)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
    cameras.append(cap)

current_cam = 0
cv2.namedWindow('Пульт управления конвейером', cv2.WINDOW_NORMAL)
cv2.resizeWindow('Пульт управления конвейером', WINDOW_WIDTH, WINDOW_HEIGHT + BUTTON_HEIGHT)


def draw_buttons(my_frame, current):
    """
    Создаёт кнопки в программном окне.
    :param my_frame: Кадр, содержащий изображение
    :param current: Индекс активной на данный момент камеры
    :return: Преобразованный кадр
    """
    button_width = WINDOW_WIDTH // NUM_CAMERAS
    for i in range(NUM_CAMERAS):
        # Определяем цвет кнопки (зеленая для активной, серая для остальных)
        color = (0, 200, 0) if i == current else (100, 100, 100)

        # Рисуем прямоугольник кнопки
        cv2.rectangle(frame,
                      (i * button_width, WINDOW_HEIGHT),
                      ((i + 1) * button_width, WINDOW_HEIGHT + BUTTON_HEIGHT),
                      color, -1)

        # Добавляем текст номера камеры
        cv2.putText(frame, f'Cam {i + 1}',
                    (i * button_width + 10, WINDOW_HEIGHT + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    return frame


def mouse_callback(event, x, y, flags, param):
    """
    Обрабатывает нажатие на кнопку мыши.
    :param event: Событие нажатия
    :param x: x-координата точки нажатия
    :param y: y-координата точки нажатия
    :return:
    """
    global current_cam

    # Если клик в области кнопок (ниже основного изображения)
    if event == cv2.EVENT_LBUTTONDOWN and WINDOW_HEIGHT <= y <= WINDOW_HEIGHT + BUTTON_HEIGHT:
        button_width = WINDOW_WIDTH // NUM_CAMERAS
        cam_num = x // button_width
        if cam_num < NUM_CAMERAS:
            current_cam = cam_num
            print(f"Переключено на камеру {current_cam + 1}")


# Отрисовка отладочного окна
cv2.setMouseCallback('Пульт управления конвейером', mouse_callback)

while True:
    # Получаем кадр с текущей камеры
    ret, frame = cameras[current_cam].read()

    if not ret:
        # Если не удалось получить кадр, создаем черное изображение с сообщением об ошибке
        frame = np.zeros((WINDOW_HEIGHT, WINDOW_WIDTH, 3), dtype=np.uint8)
        cv2.putText(frame, f'Ошибка камеры {current_cam + 1}', (50, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 3)

    # Изменяем размер кадра под размер окна
    frame = cv2.resize(frame, (WINDOW_WIDTH, WINDOW_HEIGHT))

    # Добавляем панель с кнопками
    display_frame = cv2.copyMakeBorder(frame, 0, BUTTON_HEIGHT, 0, 0,
                                       cv2.BORDER_CONSTANT, value=(50, 50, 50))
    display_frame = draw_buttons(display_frame, current_cam)

    # Отображаем
    cv2.imshow('Пульт управления конвейером', display_frame)

    # Выход по ESC
    if cv2.waitKey(30) == 27:
        break

# Освобождаем ресурсы
for cam in cameras:
    cam.release()
cv2.destroyAllWindows()