import time
from utils.auto_move import send_command

import cv2
import numpy as np
from pathlib import Path
from ultralytics import YOLO


def draw_part_contour(cam_manager, image_path, model_path = "new_weights/best.pt", output_dir = "test_picc", class_name=None, conf_threshold=0.5):
    """
    Обнаруживает контур детали на изображении с помощью YOLO segmentation,
    рисует его и сохраняет результат в output_dir.

    Args:
        image_path (str or Path): путь к входному изображению.
        model_path (str or Path): путь к весам модели YOLO (сегментационной).
        output_dir (str or Path): папка для сохранения результата.
        class_name (str, optional): имя класса для фильтрации (если None, берётся первый найденный сегмент).
        conf_threshold (float): порог уверенности.

    Returns:
        Path: путь к сохранённому файлу или None, если ничего не найдено.
        :param cam_manager:
    """
    # Загружаем модель
    model = YOLO(model_path)
    # Читаем изображение
    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Не удалось загрузить изображение: {image_path}")

    # Выполняем предсказание (сегментация)
    results = model.predict(img, conf=conf_threshold, imgsz=640, verbose=False)

    # Ищем сегменты
    masks = results[0].masks
    if masks is None or len(masks.xy) == 0:
        print("\nКонтуры не обнаружены")
        send_command(cam_manager.ser, "G8 S1")
        send_command(cam_manager.ser, f"G7 S{3000}")
        send_command(cam_manager.ser, "G3")
        time.sleep(2.2 * 2)
        return 0

    # Получаем классы и уверенности
    classes = results[0].boxes.cls.cpu().numpy().astype(int)
    confidences = results[0].boxes.conf.cpu().numpy()
    names = results[0].names

    # Выбираем подходящий сегмент (если задан class_name, фильтруем, иначе берём первый)
    selected_segment = None
    for i, seg in enumerate(masks.xy):
        if class_name is not None:
            if names[classes[i]] == class_name:
                selected_segment = seg
                break
        else:
            selected_segment = seg
            break

    if selected_segment is None:
        print("Не найден сегмент с указанным классом")
        return 0


    # Преобразуем в int32 для OpenCV
    segment = selected_segment.astype(np.int32).reshape(-1, 1, 2)

    # Рисуем контур на копии изображения
    out_img = img.copy()
    cv2.polylines(out_img, [segment], isClosed=True, color=(0, 255, 0), thickness=3)

    # (Опционально) Рисуем ограничивающий прямоугольник
    x, y, w, h = cv2.boundingRect(segment)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / Path(image_path).name
    cv2.imwrite(str(out_path), out_img)
    print(f"Результат сохранён: {out_path}")
    print(f"\n {x} {y} {w} {h}\n{confidences}")
    if y < 15 and 440 > w > 400:
        print("деталь смещена назад\n")
        distance = 90 - y
        if y == 0:
            distance += (620 - h) * 2
        send_command(cam_manager.ser, "G8 S0")
        send_command(cam_manager.ser, f"G7 S{distance * 4}")
        send_command(cam_manager.ser, "G3")
        time.sleep(1 + distance * 4 * 2 / 2500)
        return 0

    elif y > 65 and 440 > w > 400:
        print("деталь смещена вперёд\n")
        distance = y - 65
        send_command(cam_manager.ser, "G8 S1")
        send_command(cam_manager.ser, f"G7 S{distance * 4}")
        send_command(cam_manager.ser, "G3")
        time.sleep(1 + distance * 4 * 2 / 2500)
        return 0
    # elif w >= 440:
    #     print("положите деталь на палету")
    #     return 1
    elif 440 > w > 400 and 15 <= y <= 65:
        print("деталь под камерой\n")
        send_command(cam_manager.ser, "G8 S1")
        send_command(cam_manager.ser, f"G7 S50")
        send_command(cam_manager.ser, "G3")
        time.sleep(0.3)
        send_command(cam_manager.ser, f"G7 S{18803}")
        return 1
    else:
        print("ложные контуры")
        send_command(cam_manager.ser, "G8 S1")
        send_command(cam_manager.ser, f"G7 S{3000}")
        send_command(cam_manager.ser, "G3")
        time.sleep(2.2 * 2)
        return 0

    # Сохраняем результат

    return out_path
