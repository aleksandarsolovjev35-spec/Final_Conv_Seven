import math
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtGui import QColor
import json
import os
import logging
from utils.intersections import get_vertical_intersections
from utils.bounding_rectangular import bounding_rectangular
from utils.largest_rectangle import largest_rectangle
from utils.text_placement import text_placement
from processing.contours_processing import (process_flatness_contour,
                                            is_contour_inside_or_intersecting)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

STATE_COLORS = {
    0: QColor(128, 128, 128),
    1: QColor(0, 255, 0),
    2: QColor(0, 0, 255),
    3: QColor(255, 255, 0),
    4: QColor(85, 170, 255),
    5: QColor(255, 128, 0),
    6: QColor(128, 0, 255),
    7: QColor(0, 255, 255),
    8: QColor(128, 0, 0),
    9: QColor(165, 42, 42),
    10: QColor(134, 173, 39),
    11: QColor(75, 0, 130),
    12: QColor(0, 0, 0)
}


def measure_window_height(segment_np):
    """Оценка 'высоты' ячейки по сегменту (для разновысотности)."""
    import numpy as _np
    logger.debug(f"measure_window_height вызван с сегментом shape={segment_np.shape if hasattr(segment_np, 'shape') else 'unknown'}")
    seg = segment_np
    if seg.ndim == 3:
        seg = seg[:, 0, :]
    seg = _np.asarray(seg, dtype=int)
    if seg.size == 0:
        logger.warning("Получен пустой сегмент, возвращаем None")
        return None, None
    xs = seg[:, 0]
    ys = seg[:, 1]
    x_min, x_max = int(xs.min()), int(xs.max())
    y_min = int(ys.min())
    x_mid = int((x_min + x_max) / 2)

    nears = seg[(seg[:, 0] >= x_mid - 10) & (seg[:, 0] <= x_mid + 10) & (seg[:, 1] > y_min + 3)]
    if nears.size == 0:
        # fallback: используем точку на медиане по x
        y_mid = int(ys[seg[:, 0].argmin()]) if seg.shape[0] else y_min
        nears = _np.array([[x_mid, y_mid]], dtype=int)
        logger.debug(f"Не найдено точек в окрестности x_mid, использован fallback: y_mid={y_mid}")
    y_mid = int(nears[:, 1].min())
    height = y_mid - y_min
    logger.debug(f"Вычисленная высота: {height} (y_min={y_min}, y_mid={y_mid})")
    return height, (x_mid, y_min, y_mid)


def infer_model_kind(cfg: dict) -> str:
    """Пытается определить тип постобработки по имени/пути модели."""
    if not cfg:
        return ""
    if cfg.get("kind"):
        kind = str(cfg["kind"])
        logger.info(f"Явно заданный kind модели: {kind}")
        return kind
    name = (cfg.get("name") or "").lower()
    path = (cfg.get("path") or "").lower()

    s = name + " " + path
    if "стекл" in s or "glass" in s:
        kind = "bottom_glass"
    elif "свар" in s or "weld" in s:
        kind = "welding"
    elif "разнов" in s or "uneven" in s or "unfilled" in s:
        kind = "uneven_heights"
    elif "раков" in s or "sink" in s or "flatness_long" in s or "side_flatness" in s:
        kind = "window_sinks"
    else:
        kind = ""
    logger.info(f"Определён kind модели по имени/пути: {kind}")
    return kind


def _to_int_tuple_color(c):
    try:
        if isinstance(c, (list, tuple)) and len(c) == 3:
            return (int(c[0]), int(c[1]), int(c[2]))
    except Exception as e:
        logger.error(f"Ошибка преобразования цвета {c}: {e}")
    return None


def process_frame(frame, model, manager, model_cfg=None, conf=0.3, draw_area=0, contour_storage=None, camera_index=None):
    logger.info("Начало обработки кадра")
    if contour_storage is None:
        contour_storage = {"contacts": [], "platform": None}
        logger.debug("Создан новый contour_storage")

    try:
        results_detect = model.predict(frame, iou=0, conf=conf, imgsz=1280, verbose=False, task="segment")
        logger.debug(f"Предсказание выполнено, найдено масок: {len(results_detect[0].masks.xy) if results_detect[0].masks else 0}")
    except Exception as e:
        logger.error(f"Ошибка при предсказании модели: {e}")
        return frame, [], []

    object_data = []
    lengths = []
    rectangle = []
    glass_detected = False
    glass_contour = None

    if results_detect[0].masks is not None and len(results_detect[0].masks.xy) > 0:
        masks = results_detect[0].masks
        segments = masks.xy
        classes = results_detect[0].boxes.cls.cpu().numpy().astype(int)
        confidences = results_detect[0].boxes.conf.cpu().numpy().astype(float)
        names = results_detect[0].names

        kind = infer_model_kind(model_cfg or {})
        cfg_color = _to_int_tuple_color((model_cfg or {}).get("color"))
        if cfg_color is not None:
            draw_color = (cfg_color[2], cfg_color[1], cfg_color[0])
        else:
            draw_color = None

        points = []
        uneven_heights_vals = []
        uneven_coords = []
        uneven_segments = []

        for idx, (segment, clss, confidence) in enumerate(zip(segments, classes, confidences)):
            if len(segment) == 0:
                continue

            segment = segment.astype(int)
            class_name = names[clss]
            logger.debug(f"Обработка сегмента {idx}: класс={class_name}, уверенность={confidence:.3f}")
            thickness = 2
            distance = None

            # ---------- НОВЫЕ МОДЕЛИ ----------
            if kind == "bottom_glass":
                color = draw_color or (STATE_COLORS[4].blue(), STATE_COLORS[4].green(), STATE_COLORS[4].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=2)
                manager.update_slot_state(4)
                object_data.append({
                    "class_name": "bottom_glass",
                    "distance": None,
                    "segment": segment.tolist(),
                    "area": float(cv2.contourArea(segment)),
                    "confidence": float(confidence),
                })
                logger.info(f"Обнаружено стекло (bottom_glass), установлено состояние 4")
                continue

            if kind == "welding":
                color = draw_color or (STATE_COLORS[8].blue(), STATE_COLORS[8].green(), STATE_COLORS[8].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=2)
                manager.update_slot_state(8)
                object_data.append({
                    "class_name": "welding",
                    "distance": None,
                    "segment": segment.tolist(),
                    "area": float(cv2.contourArea(segment)),
                    "confidence": float(confidence),
                })
                logger.info("Обнаружен дефект сварки (welding), состояние 8")
                continue

            if kind == "window_sinks":
                color = draw_color or (STATE_COLORS[3].blue(), STATE_COLORS[3].green(), STATE_COLORS[3].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=2)
                manager.update_slot_state(3)
                object_data.append({
                    "class_name": "window_sinks",
                    "distance": None,
                    "segment": segment.tolist(),
                    "area": float(cv2.contourArea(segment)),
                    "confidence": float(confidence),
                })
                logger.info("Обнаружены раковины окон (window_sinks), состояние 3")
                continue

            if kind == "uneven_heights":
                h_val, h_coord = measure_window_height(segment)
                if h_val is not None:
                    uneven_heights_vals.append(float(h_val))
                    uneven_coords.append(h_coord)
                    uneven_segments.append(segment.copy())
                    logger.debug(f"Разновысотность: значение {h_val}")
                object_data.append({
                    "class_name": "uneven_heights",
                    "distance": float(h_val) if h_val is not None else None,
                    "segment": segment.tolist(),
                    "area": float(cv2.contourArea(segment)),
                    "confidence": float(confidence),
                })
                continue
            # -------------------------------------------------

            # Сохраняем контуры контактов и платформы
            if class_name == "contacts":
                contour_storage["contacts"].append(segment.tolist())
                logger.debug("Сохранён контур contacts")
            elif class_name == "platform":
                contour_storage["platform"] = segment.tolist()
                logger.debug("Сохранён контур platform")
            elif class_name == "glass":
                glass_detected = True
                glass_contour = segment.tolist()
                logger.debug("Обнаружено стекло (glass)")

            # Обработка разных классов
            if class_name == "mechanics":
                color = (STATE_COLORS[12].blue(), STATE_COLORS[12].green(), STATE_COLORS[12].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=thickness)
                cv2.putText(frame, "MECHANICS", (segment[0][0][0], segment[0][0][1]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                manager.update_slot_state(12)
                logger.info("Обнаружена механика (mechanics), состояние 12")

            elif class_name.lower() == "omission":
                color = (STATE_COLORS[7].blue(), STATE_COLORS[7].green(), STATE_COLORS[7].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=thickness)
                distance = bounding_rectangular(float('-inf'), float('inf'), segment, frame)
                logger.debug(f"Обработка omission, расстояние={distance}")

            elif class_name == "flatness":
                color = (STATE_COLORS[2].blue(), STATE_COLORS[2].green(), STATE_COLORS[2].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=thickness)
                process_flatness_contour(frame, segment, manager, camera_index=camera_index)  # передаём инд
                logger.debug("Обработка flatness")

            elif class_name == "platform":
                rectangle, _ = largest_rectangle(segment)
                color = (STATE_COLORS[6].blue(), STATE_COLORS[6].green(), STATE_COLORS[6].red())
                cv2.polylines(frame, [rectangle], True, color, 1)
                logger.debug("Отрисовка платформы с прямоугольником")

            elif class_name == "flatness_short":
                color = (STATE_COLORS[9].blue(), STATE_COLORS[9].green(), STATE_COLORS[9].red())
                M = cv2.moments(segment)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    points.append((cX, cY))
                    cv2.circle(frame, (cX, cY), 3, color, -1)

                if len(points) == 2:
                    pt1, pt2 = points[0], points[1]
                    cv2.line(frame, pt1, pt2, color, 2)

                    delta_y = pt2[1] - pt1[1]
                    delta_x = pt2[0] - pt1[0]
                    angle = math.degrees(math.atan2(delta_y, delta_x)) % 360
                    if angle > 180:
                        angle = 360 - angle
                    angle_display = 180 - angle if angle > 90 else angle

                    mid_point = ((pt1[0] + pt2[0]) // 2, (pt1[1] + pt2[1]) // 2)
                    text_pos = (mid_point[0], mid_point[1] - 50)
                    cv2.putText(frame, f"{angle_display:.1f}", text_pos, cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, color, 2)

                    if angle_display > manager.thresholds.get('flatness_short_angle', 4.5):
                        manager.update_slot_state(9)
                        logger.info(f"Обнаружен дефект flatness_short с углом {angle_display:.1f}, состояние 9")

            elif class_name == "contacts_long":
                color = (STATE_COLORS[11].blue(), STATE_COLORS[11].green(), STATE_COLORS[11].red())
                M = cv2.moments(segment)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    points.append((cX, cY))
                    cv2.circle(frame, (cX, cY), 3, color, -1)

                if len(points) == 5:
                    sorted_points = sorted(points, key=lambda p: p[0])
                    leftmost = sorted_points[0]
                    rightmost = sorted_points[-1]

                    cv2.circle(frame, leftmost, 3, color, -1)
                    cv2.circle(frame, rightmost, 3, color, -1)
                    cv2.line(frame, leftmost, rightmost, color, 2)

                    delta_x = rightmost[0] - leftmost[0]
                    delta_y = rightmost[1] - leftmost[1]
                    angle_rad = np.arctan2(delta_y, delta_x)
                    angle_deg = np.degrees(angle_rad) % 180
                    if angle_deg > 90:
                        angle_deg = 180 - angle_deg
                    angle_deg = abs(angle_deg)

                    text_pos = ((leftmost[0] + rightmost[0]) // 2, (leftmost[1] + rightmost[1]) // 2 - 10)
                    cv2.putText(frame, f"{angle_deg:.1f}", text_pos,
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                    points.clear()

                    if angle_deg > manager.thresholds.get('contacts_long_angle', 5):
                        manager.update_slot_state(11)
                        logger.info(f"Обнаружен дефект contacts_long с углом {angle_deg:.1f}, состояние 11")

            elif class_name == "contacts":
                color = (STATE_COLORS[5].blue(), STATE_COLORS[5].green(), STATE_COLORS[5].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=1)

            elif class_name == "sinks":
                color = (STATE_COLORS[3].blue(), STATE_COLORS[3].green(), STATE_COLORS[3].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=thickness)

            elif class_name == "glass" or class_name == "output_glass":
                color = (STATE_COLORS[4].blue(), STATE_COLORS[4].green(), STATE_COLORS[4].red())
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=thickness)

            else:
                color = (255, 0, 0)
                cv2.polylines(frame, [segment], isClosed=True, color=color, thickness=thickness)

            text_placement(moment=cv2.moments(segment), draw_area=draw_area, area=cv2.contourArea(segment), frame=frame)

            area = cv2.contourArea(segment)
            object_info = {
                "class_name": class_name,
                "distance": distance,
                "segment": segment.tolist(),
                "area": area,
                "confidence": float(confidence)
            }
            if class_name == "contacts":
                object_info["contact_id"] = len([o for o in object_data if o["class_name"] == "contacts"]) + 1

            object_data.append(object_info)

        # Постобработка разновысотности
        if kind == "uneven_heights" and len(uneven_segments) > 0:
            th = manager.get_heights_thresholds(camera_index)  # вместо load_heights_thresholds()
            heights_for_brak = []  # длины проведённых линий
            intersection_counts = []

            # Очищаем старые списки
            uneven_heights_vals = []
            uneven_coords = []

            for seg in uneven_segments:
                # Вычисляем середину по x (не центр масс)
                if seg.ndim == 3:
                    xs = seg[:, 0, 0]
                else:
                    xs = seg[:, 0]
                x_min = int(np.min(xs))
                x_max = int(np.max(xs))
                x_center = x_min + (x_max - x_min) // 2

                # Получаем все пересечения вертикали
                ys = get_vertical_intersections(seg, x_center)
                intersection_counts.append(len(ys))

                if len(ys) >= 2:
                    ys_sorted = sorted(ys)
                    y_top = int(ys_sorted[0])
                    # Ищем подходящую нижнюю точку
                    y_bottom = None
                    if len(ys_sorted) == 2:
                        y_bottom = int(ys_sorted[1])
                    else:
                        for y in ys_sorted[1:]:
                            if y - y_top > 7:
                                y_bottom = int(y)
                                break
                        if y_bottom is None:
                            y_bottom = int(ys_sorted[-1])
                    # Длина проведённой линии
                    line_length = y_bottom - y_top
                    heights_for_brak.append(line_length)
                    uneven_heights_vals.append(line_length)
                    uneven_coords.append((x_center, y_top, y_bottom))
                else:
                    # Резервный вариант (если вдруг не нашлось двух пересечений)
                    h_val, coord = measure_window_height(seg)
                    if h_val is not None:
                        heights_for_brak.append(h_val)
                        uneven_heights_vals.append(h_val)
                        uneven_coords.append(coord)
                        intersection_counts[-1] = -1

            # Отладка (если передан camera_index)
            if camera_index is not None:
                print(f"Camera_{camera_index}: пересечений = {intersection_counts}")

            if heights_for_brak:
                # Определяем брак по длине проведённой линии
                h_max = max(heights_for_brak)
                h_min = min(heights_for_brak)
                not_normal = False
                if h_max >= th["max"] or h_min <= th["min"]:
                    not_normal = True
                elif abs(h_max - h_min) >= th["avg"]:
                    not_normal = True

                if not_normal:
                    manager.update_slot_state(2)
                    color = draw_color or (STATE_COLORS[2].blue(), STATE_COLORS[2].green(), STATE_COLORS[2].red())
                else:
                    color = (0, 255, 0)

                # Рисуем контуры
                for seg in uneven_segments:
                    cv2.polylines(frame, [seg], isClosed=True, color=color, thickness=2)

                # Рисуем вертикальные линии и подписи
                for (coord, h_val) in zip(uneven_coords, uneven_heights_vals):
                    x_mid, y_top, y_bottom = coord
                    cv2.line(frame, (x_mid, y_top), (x_mid, y_bottom), (255, 0, 0), 1, cv2.LINE_AA)
                    cv2.putText(
                        frame,
                        f"H:{h_val:.0f}",
                        (x_mid + 5, (y_top + y_bottom) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        1,
                        cv2.LINE_AA,
                    )#функция устанавливается лицом компетентным и уполномочненным
#устанавливать в мм изменение перемещения
        # Проверяем пересечение стекла с контактами или платформой
        if glass_detected and glass_contour is not None:
            glass_intersects = False

            if contour_storage["platform"] is not None:
                if is_contour_inside_or_intersecting(glass_contour, contour_storage["platform"]):
                    glass_intersects = True
                    logger.debug("Стекло пересекается с платформой")

            if not glass_intersects and len(contour_storage["contacts"]) > 0:
                for contact_contour in contour_storage["contacts"]:
                    if is_contour_inside_or_intersecting(glass_contour, contact_contour):
                        glass_intersects = True
                        logger.debug("Стекло пересекается с контактом")
                        break

            if glass_intersects:
                manager.update_slot_state(4)
                logger.info("Обнаружено пересечение стекла, установлено состояние 4")

        # Обновление состояний по другим объектам
        for obj in object_data:
            cname = obj["class_name"]
            if cname == "sinks":
                manager.update_slot_state(3)
            elif cname == "contacts":
                if obj.get('area', 0) < manager.thresholds.get('contacts_area', 1400):
                    manager.update_slot_state(5)
                    logger.debug(f"Площадь контакта мала ({obj['area']}), состояние 5")
            elif cname == "platform":
                if obj.get('area', 0) >= manager.thresholds.get('platform_area_max', 48500):
                    manager.update_slot_state(10)
                    logger.debug(f"Площадь платформы велика ({obj['area']}), состояние 10")
                else:
                    if rectangle is not None and len(rectangle) > 0:
                        x, y, w, h = cv2.boundingRect(np.array(rectangle))
                        min_width = manager.thresholds.get('platform_min_width', 110)
                        min_length = manager.thresholds.get('platform_min_length', 270)
                        if w <= min_width or h <= min_length:
                            manager.update_slot_state(6)
                            logger.debug(f"Платформа мала (w={w}, h={h}), состояние 6")
            elif cname.lower() == "omission":
                if obj.get("distance", 0) > manager.thresholds.get('omission_distance', 20):
                    manager.update_slot_state(7)
                    logger.debug(f"Пропуск (omission) с расстоянием {obj.get('distance')}, состояние 7")
            elif cname == "objects":
                manager.update_slot_state(3)
            elif cname == "mechanics":
                manager.update_slot_state(12)
            elif cname == "output_glass":
                manager.update_slot_state(4)

    else:
        logger.debug("Нет обнаруженных масок на кадре")

    logger.info(f"Обработка кадра завершена, обнаружено {len(object_data)} объектов")
    return frame, object_data, lengths