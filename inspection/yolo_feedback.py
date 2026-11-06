"""Хранилище и выгрузка в ZIP кадров с пропущенными дефектами для разметчика YOLO.

Оператор во время работы линии (или на паузе/остановке, либо из архива детали)
фиксирует кадр выбранной камеры, выбирает кнопкой класс дефекта и обводит
пропущенные участки.

Для каждого случая атомарно сохраняются:
- ``clean.jpg`` — чистый исходный кадр 1280×720 (JPEG quality=98, без разметки),
  готовый к прямой загрузке в инструмент разметки (CVAT / Label Studio / Roboflow);
- ``hint.jpg`` — кадр-подсказка для разметчика с детекциями текущей модели и
  пронумерованными обводками оператора;
- ``meta.json`` — координаты (в пикселях и нормализованные 0..1), выбранные
  классы, целевые ``.pt``-модели из ``vision/model_config.py``, комментарий и
  статус выгрузки.

При выгрузке формируется ZIP-архив, разложенный по целевым ``.pt``-моделям:
внутри каждой папки модели лежат ``images/`` (только чистые ``.jpg``),
``hints/`` (шпаргалки с тем же именем), ``draft_labels/`` (черновики YOLO-seg),
``classes.txt`` и ``meta/``.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import shutil
import threading
import time
import zipfile
from datetime import datetime

import cv2
import numpy as np

from vision.model_config import MODEL_GROUPS, ROLE_TO_GROUP
from vision.overlay.palette import CLASS_COLORS
from vision.overlay.raw_overlay import RawOverlay


CAMERA_ROLE_LABELS_RU = {
    "INPUT_LEFT":   "ВХОД · СЛЕВА",
    "INPUT_RIGHT":  "ВХОД · СПРАВА",
    "SPIDER_LEFT":  "КОНТРОЛЬ · СЛЕВА",
    "SPIDER_RIGHT": "КОНТРОЛЬ · СПРАВА",
    "SPIDER_IN":    "ВНУТРЕННИЙ ВИД",
    "SPIDER_OUT":   "НАРУЖНЫЙ ВИД",
    "TOP":          "ВИД СВЕРХУ",
}

CLASS_LABELS_RU = {
    "objects":        "Раковина окна",
    "flatness":       "Геометрия окна",
    "contacts-long":  "Длинный контакт",
    "omission-long":  "Полоса пропуска",
    "black-spot":     "Чёрное пятно",
    "flatness_short": "Короткий контакт",
    "omission-short": "Полоса пропуска",
    "shells":         "Раковина",
    "glass":          "Стекло",
    "contacts":       "Контакты",
    "platform":       "Платформа",
    "pin":            "Пины",
    "case":           "Корпус",
    "case_central":   "Центр колодца",
    "other":          "Другое",
}

# Приоритет кнопок классов на панели оператора: первыми идут типовые дефекты,
# которые чаще всего пропускаются на соответствующей камере.
PREFERRED_ROLE_CLASS_ORDER = {
    "INPUT_LEFT":   ("objects", "flatness"),
    "INPUT_RIGHT":  ("objects", "flatness"),
    "SPIDER_LEFT":  ("contacts-long", "omission-long"),
    "SPIDER_RIGHT": ("contacts-long", "omission-long"),
    "SPIDER_IN":    ("black-spot", "flatness_short", "omission-short"),
    "SPIDER_OUT":   ("black-spot", "flatness_short", "omission-short"),
    "TOP":          (
        "shells", "glass", "contacts", "platform",
        "pin", "case", "case_central",
    ),
}

OTHER_CLASS_KEY = "other"
OTHER_COLOR_BGR = (55, 165, 255)  # Яркий янтарный для универсальной метки


def _brighten_bgr(bgr: tuple[int, int, int]) -> tuple[int, int, int]:
    """Гарантировать контрастный цвет обводки на тёмном и светлом фоне."""
    b, g, r = int(bgr[0]), int(bgr[1]), int(bgr[2])
    peak = max(b, g, r)
    if peak < 180 and peak > 0:
        scale = 220.0 / peak
        b = min(255, int(round(b * scale)))
        g = min(255, int(round(g * scale)))
        r = min(255, int(round(r * scale)))
    return (b, g, r)


def _bgr_to_hex(bgr: tuple[int, int, int]) -> str:
    b, g, r = _brighten_bgr(bgr)
    return f"#{r:02x}{g:02x}{b:02x}"


def get_role_classes(role: str) -> list[dict]:
    """Вернуть список кнопок классов YOLO для выбранной роли камеры."""
    group_name = ROLE_TO_GROUP.get(str(role or ""))
    entries = MODEL_GROUPS.get(group_name, []) if group_name else []

    by_class: dict[str, dict] = {}
    ordered_keys: list[str] = []

    for entry in entries:
        model_path = str(entry.get("path") or "")
        classes = tuple(str(c) for c in (entry.get("classes") or ()))
        for class_id, cls_name in enumerate(classes):
            bgr = _brighten_bgr(CLASS_COLORS.get(cls_name, OTHER_COLOR_BGR))
            by_class[cls_name] = {
                "yolo_class": cls_name,
                "label": CLASS_LABELS_RU.get(cls_name, cls_name),
                "model_path": model_path,
                "class_id": int(class_id),
                "model_classes": list(classes),
                "color": _bgr_to_hex(bgr),
                "color_bgr": list(bgr),
            }
            if cls_name not in ordered_keys:
                ordered_keys.append(cls_name)

    preferred = PREFERRED_ROLE_CLASS_ORDER.get(str(role or ""), ())
    sorted_keys = [k for k in preferred if k in by_class]
    sorted_keys.extend(k for k in ordered_keys if k not in sorted_keys)

    result = [dict(by_class[k]) for k in sorted_keys]
    result.append({
        "yolo_class": OTHER_CLASS_KEY,
        "label": CLASS_LABELS_RU[OTHER_CLASS_KEY],
        "model_path": None,
        "class_id": -1,
        "model_classes": [],
        "color": _bgr_to_hex(OTHER_COLOR_BGR),
        "color_bgr": list(OTHER_COLOR_BGR),
    })
    return result


def _model_folder_slug(model_path: str | None, role: str) -> str:
    """Имя подпапки целевой модели внутри выгружаемого ZIP."""
    if not model_path:
        return f"{role}__other"
    norm = model_path.replace("\\", "/")
    parts = [p for p in norm.split("/") if p and p != "weights"]
    stem = os.path.splitext(parts[-1])[0] if parts else "model"
    group = parts[-2].replace(",", "_") if len(parts) >= 2 else role
    safe = f"{group}__{stem}"
    for ch in (" ", ":", "/", "\\"):
        safe = safe.replace(ch, "_")
    return safe


class YoloFeedbackStore:
    """Потокобезопасное хранилище кадров обратной связи для обучения YOLO."""

    CLEAN_JPEG_QUALITY = 98
    HINT_JPEG_QUALITY = 92
    SCHEMA_VERSION = 1
    SUBDIR_NAME = "yolo_tasks"

    def __init__(self, root_folder: str = "archive"):
        self._lock = threading.RLock()
        self._seq = 0
        self._cached_counts: tuple[int, int] | None = None
        self._root_folder = self._normalise_root(root_folder)
        self._sync_existing_seq()

    @staticmethod
    def _normalise_root(root_folder: str) -> str:
        text = str(root_folder or "archive").strip() or "archive"
        return os.path.abspath(os.path.expandvars(os.path.expanduser(text)))

    @property
    def root_folder(self) -> str:
        with self._lock:
            return self._root_folder

    @property
    def store_dir(self) -> str:
        return os.path.join(self.root_folder, self.SUBDIR_NAME)

    @property
    def items_dir(self) -> str:
        return os.path.join(self.store_dir, "items")

    def set_root_folder(self, root_folder: str) -> None:
        normalized = self._normalise_root(root_folder)
        with self._lock:
            if normalized == self._root_folder:
                return
            self._root_folder = normalized
            self._cached_counts = None
            self._sync_existing_seq_unlocked()

    def _sync_existing_seq(self) -> None:
        with self._lock:
            self._sync_existing_seq_unlocked()

    def _sync_existing_seq_unlocked(self) -> None:
        items_path = os.path.join(self._root_folder, self.SUBDIR_NAME, "items")
        if not os.path.isdir(items_path):
            return
        max_seq = self._seq
        try:
            for entry in os.scandir(items_path):
                if not entry.is_dir():
                    continue
                tail = entry.name.rsplit("_", 1)[-1]
                if tail.isdigit():
                    max_seq = max(max_seq, int(tail))
        except OSError:
            return
        self._seq = max_seq

    # ---------- валидация и нормализация обводок ----------

    @staticmethod
    def _clamp01(value) -> float:
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Координата обводки должна быть числом") from exc
        if not math.isfinite(num):
            raise ValueError("Координата обводки должна быть конечным числом")
        return max(0.0, min(1.0, num))

    @staticmethod
    def _polygon_area_px(pts_norm: list[list[float]], width: int, height: int) -> float:
        if len(pts_norm) < 3:
            return 0.0
        area2 = 0.0
        n = len(pts_norm)
        for i in range(n):
            x1 = pts_norm[i][0] * width
            y1 = pts_norm[i][1] * height
            x2 = pts_norm[(i + 1) % n][0] * width
            y2 = pts_norm[(i + 1) % n][1] * height
            area2 += x1 * y2 - x2 * y1
        return abs(area2) * 0.5

    @staticmethod
    def _polyline_length_px(pts_norm: list[list[float]], width: int, height: int) -> float:
        total = 0.0
        for i in range(1, len(pts_norm)):
            dx = (pts_norm[i][0] - pts_norm[i - 1][0]) * width
            dy = (pts_norm[i][1] - pts_norm[i - 1][1]) * height
            total += math.hypot(dx, dy)
        return total

    @classmethod
    def _expand_stroke_to_ribbon(
        cls,
        pts_norm: list[list[float]],
        width: int,
        height: int,
        half_width_px: float = 4.0,
    ) -> list[list[float]]:
        """Превратить одиночный росчерк вдоль царапины в замкнутую ленту."""
        pts_px: list[tuple[float, float]] = []
        for nx, ny in pts_norm:
            px, py = nx * width, ny * height
            if not pts_px or math.hypot(px - pts_px[-1][0], py - pts_px[-1][1]) >= 1.5:
                pts_px.append((px, py))
        if len(pts_px) < 2:
            cx, cy = pts_norm[0][0] * width, pts_norm[0][1] * height
            r = half_width_px
            rect = [
                (cx - r, cy - r), (cx + r, cy - r),
                (cx + r, cy + r), (cx - r, cy + r),
            ]
            return [
                [
                    round(cls._clamp01(x / width), 6),
                    round(cls._clamp01(y / height), 6),
                ]
                for x, y in rect
            ]

        seg_normals: list[tuple[float, float]] = []
        for i in range(len(pts_px) - 1):
            dx = pts_px[i + 1][0] - pts_px[i][0]
            dy = pts_px[i + 1][1] - pts_px[i][1]
            seg_len = math.hypot(dx, dy) or 1.0
            seg_normals.append((-dy / seg_len, dx / seg_len))

        left_rail: list[list[float]] = []
        right_rail: list[list[float]] = []
        for i, (px, py) in enumerate(pts_px):
            if i == 0:
                nx, ny = seg_normals[0]
            elif i == len(pts_px) - 1:
                nx, ny = seg_normals[-1]
            else:
                sx = seg_normals[i - 1][0] + seg_normals[i][0]
                sy = seg_normals[i - 1][1] + seg_normals[i][1]
                mlen = math.hypot(sx, sy)
                if mlen > 1e-3:
                    nx, ny = sx / mlen, sy / mlen
                else:
                    nx, ny = seg_normals[i]
            left_rail.append([
                round(cls._clamp01((px + nx * half_width_px) / width), 6),
                round(cls._clamp01((py + ny * half_width_px) / height), 6),
            ])
            right_rail.append([
                round(cls._clamp01((px - nx * half_width_px) / width), 6),
                round(cls._clamp01((py - ny * half_width_px) / height), 6),
            ])
        right_rail.reverse()
        return left_rail + right_rail

    @classmethod
    def _normalize_marks(
        cls,
        role: str,
        raw_marks: list,
        width: int,
        height: int,
    ) -> list[dict]:
        if not isinstance(raw_marks, list) or not raw_marks:
            raise ValueError("Добавьте хотя бы одну обводку дефекта на кадре")

        catalog = {item["yolo_class"]: item for item in get_role_classes(role)}
        normalized: list[dict] = []
        min_half_pad_x = 2.0 / max(1, width)
        min_half_pad_y = 2.0 / max(1, height)

        for raw in raw_marks:
            if not isinstance(raw, dict):
                raise ValueError("Некорректный формат обводки")

            shape = str(raw.get("shape") or "polygon").lower()
            if shape not in ("polygon", "bbox"):
                raise ValueError(f"Неизвестный тип фигуры: {shape}")

            cls_key = str(raw.get("yolo_class") or "").strip()
            if cls_key not in catalog:
                cls_key = OTHER_CLASS_KEY
            cls_info = catalog[cls_key]

            raw_points = raw.get("points")
            if not isinstance(raw_points, list) or len(raw_points) < 2:
                raise ValueError("Обводка содержит недостаточно точек")

            pts_norm: list[list[float]] = []
            for pt in raw_points:
                if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                    raise ValueError("Точка обводки должна содержать [x, y]")
                pts_norm.append([
                    round(cls._clamp01(pt[0]), 6),
                    round(cls._clamp01(pt[1]), 6),
                ])

            xs = [p[0] for p in pts_norm]
            ys = [p[1] for p in pts_norm]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            span_px = math.hypot((x2 - x1) * width, (y2 - y1) * height)
            if span_px < 3.0:
                continue

            if shape == "bbox":
                if (x2 - x1) * width < 4.0:
                    mid_x = (x1 + x2) * 0.5
                    x1 = round(cls._clamp01(mid_x - min_half_pad_x), 6)
                    x2 = round(cls._clamp01(mid_x + min_half_pad_x), 6)
                if (y2 - y1) * height < 4.0:
                    mid_y = (y1 + y2) * 0.5
                    y1 = round(cls._clamp01(mid_y - min_half_pad_y), 6)
                    y2 = round(cls._clamp01(mid_y + min_half_pad_y), 6)
                pts_norm = [
                    [x1, y1],
                    [x2, y1],
                    [x2, y2],
                    [x1, y2],
                ]
            else:
                area_px = cls._polygon_area_px(pts_norm, width, height)
                path_px = cls._polyline_length_px(pts_norm, width, height)
                # Если оператор провёл линию вдоль узкого дефекта, не замыкая
                # петлю, превращаем линию в аккуратную замкнутую полосу 8 px.
                if len(pts_norm) < 3 or area_px < max(16.0, path_px * 1.5):
                    pts_norm = cls._expand_stroke_to_ribbon(
                        pts_norm, width, height, half_width_px=4.0,
                    )
                    xs = [p[0] for p in pts_norm]
                    ys = [p[1] for p in pts_norm]
                    x1, x2 = min(xs), max(xs)
                    y1, y2 = min(ys), max(ys)

            bw_px = (x2 - x1) * width
            bh_px = (y2 - y1) * height
            if bw_px < 2.0 or bh_px < 2.0:
                continue

            pts_px = [
                [
                    int(round(p[0] * (width - 1))),
                    int(round(p[1] * (height - 1))),
                ]
                for p in pts_norm
            ]
            bbox_px = [
                int(round(x1 * (width - 1))),
                int(round(y1 * (height - 1))),
                int(round(x2 * (width - 1))),
                int(round(y2 * (height - 1))),
            ]
            cx = round((x1 + x2) / 2.0, 6)
            cy = round((y1 + y2) / 2.0, 6)
            bw = round(x2 - x1, 6)
            bh = round(y2 - y1, 6)

            normalized.append({
                "index": len(normalized) + 1,
                "shape": shape,
                "yolo_class": cls_info["yolo_class"],
                "label_ru": cls_info["label"],
                "model_path": cls_info["model_path"],
                "model_folder": _model_folder_slug(cls_info["model_path"], role),
                "class_id": cls_info["class_id"],
                "model_classes": list(cls_info["model_classes"]),
                "color": cls_info["color"],
                "color_bgr": list(cls_info["color_bgr"]),
                "bbox_norm": [round(x1, 6), round(y1, 6), round(x2, 6), round(y2, 6)],
                "bbox_px": bbox_px,
                "yolo_bbox_cxcywh": [cx, cy, bw, bh],
                "points_norm": pts_norm,
                "points_px": pts_px,
            })

        if not normalized:
            raise ValueError("Обводка слишком мала — обведите дефект крупнее")
        return normalized

    # ---------- отрисовка шпаргалки для разметчика ----------

    @staticmethod
    def render_hint_frame(
        clean_frame: np.ndarray,
        role: str,
        task_id: str,
        marks: list[dict],
        existing_detections: list[dict] | None = None,
    ) -> np.ndarray:
        """Сформировать наглядное изображение-подсказку для разметчика YOLO."""
        if existing_detections:
            canvas = RawOverlay.render(clean_frame, existing_detections)
        else:
            canvas = clean_frame.copy()

        fill_layer = canvas.copy()
        for mark in marks:
            pts = np.array(mark["points_px"], dtype=np.int32)
            bgr = tuple(int(c) for c in mark.get("color_bgr", OTHER_COLOR_BGR))
            if len(pts) >= 3:
                cv2.fillPoly(fill_layer, [pts], bgr)
        cv2.addWeighted(fill_layer, 0.22, canvas, 0.78, 0, canvas)

        h, w = canvas.shape[:2]
        for mark in marks:
            pts = np.array(mark["points_px"], dtype=np.int32)
            bgr = tuple(int(c) for c in mark.get("color_bgr", OTHER_COLOR_BGR))
            # Тёмный ореол + яркий контур читаются на любом фоне корпуса.
            cv2.polylines(
                canvas, [pts], True, (10, 14, 18), 5, lineType=cv2.LINE_AA,
            )
            cv2.polylines(
                canvas, [pts], True, bgr, 2, lineType=cv2.LINE_AA,
            )

            x1, y1, _x2, _y2 = mark["bbox_px"]
            tag = f"#{mark['index']} {mark['yolo_class']}"
            (tw, th), _ = cv2.getTextSize(
                tag, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2,
            )
            tx = max(6, min(w - tw - 14, x1))
            ty = y1 - 8 if y1 >= th + 16 else min(h - 8, y1 + th + 14)
            cv2.rectangle(
                canvas,
                (tx - 4, ty - th - 5),
                (tx + tw + 6, ty + 5),
                (12, 16, 20),
                -1,
            )
            cv2.rectangle(
                canvas,
                (tx - 4, ty - th - 5),
                (tx + tw + 6, ty + 5),
                bgr,
                1,
            )
            cv2.putText(
                canvas,
                tag,
                (tx + 1, ty),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                bgr,
                2,
                lineType=cv2.LINE_AA,
            )

        # Компактная информационная плашка в левом верхнем углу шпаргалки.
        banner = f"{role} | {task_id} | MARKS: {len(marks)}"
        (bw, bh), _ = cv2.getTextSize(
            banner, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1,
        )
        cv2.rectangle(canvas, (8, 8), (bw + 22, bh + 20), (12, 16, 20), -1)
        cv2.rectangle(canvas, (8, 8), (bw + 22, bh + 20), (120, 153, 165), 1)
        cv2.putText(
            canvas,
            banner,
            (15, bh + 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (224, 229, 233),
            1,
            lineType=cv2.LINE_AA,
        )
        return canvas

    # ---------- сохранение и чтение задач ----------

    def save_task(
        self,
        *,
        role: str,
        clean_frame: np.ndarray,
        marks: list[dict],
        comment: str = "",
        existing_detections: list[dict] | None = None,
        source_kind: str = "live",
        part_id: int | None = None,
        step: int | None = None,
    ) -> dict:
        """Сохранить чистый кадр (.jpg), шпаргалку (.jpg) и метаданные (.json)."""
        role = str(role or "").strip().upper()
        if role not in ROLE_TO_GROUP:
            raise ValueError(f"Неизвестная роль камеры: {role}")
        if clean_frame is None or not isinstance(clean_frame, np.ndarray):
            raise ValueError("Кадр камеры отсутствует")
        if clean_frame.ndim != 3 or clean_frame.shape[0] < 16 or clean_frame.shape[1] < 16:
            raise ValueError("Некорректный размер кадра камеры")

        height, width = int(clean_frame.shape[0]), int(clean_frame.shape[1])
        normalized_marks = self._normalize_marks(role, marks, width, height)
        safe_comment = str(comment or "").strip()[:500]

        now = datetime.now()
        with self._lock:
            self._seq += 1
            seq = self._seq
            items_root = os.path.join(self._root_folder, self.SUBDIR_NAME, "items")

        stamp = now.strftime("%Y%m%d_%H%M%S")
        task_id = f"{stamp}_{role}_{seq:04d}"
        task_dir = os.path.join(items_root, task_id)
        os.makedirs(task_dir, exist_ok=True)

        clean_bytes = self._encode_jpeg(clean_frame, self.CLEAN_JPEG_QUALITY)
        hint_frame = self.render_hint_frame(
            clean_frame=clean_frame,
            role=role,
            task_id=task_id,
            marks=normalized_marks,
            existing_detections=existing_detections,
        )
        hint_bytes = self._encode_jpeg(hint_frame, self.HINT_JPEG_QUALITY)

        det_summary = []
        for det in (existing_detections or []):
            if not isinstance(det, dict):
                continue
            det_summary.append({
                "class": det.get("class"),
                "confidence": (
                    round(float(det["confidence"]), 4)
                    if isinstance(det.get("confidence"), (int, float))
                    else None
                ),
                "bbox": (
                    [round(float(v), 2) for v in det["bbox"]]
                    if isinstance(det.get("bbox"), (list, tuple))
                    else None
                ),
                "model_path": det.get("model_path"),
            })

        target_models = sorted({
            m["model_path"] for m in normalized_marks if m.get("model_path")
        })
        yolo_classes = list(dict.fromkeys(
            m["yolo_class"] for m in normalized_marks
        ))

        meta = {
            "schema_version": self.SCHEMA_VERSION,
            "task_id": task_id,
            "created_at": now.isoformat(timespec="seconds"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timestamp": time.time(),
            "camera_role": role,
            "camera_label": CAMERA_ROLE_LABELS_RU.get(role, role),
            "model_group": ROLE_TO_GROUP.get(role),
            "image_width": width,
            "image_height": height,
            "source_kind": str(source_kind or "live"),
            "part_id": (
                int(part_id)
                if isinstance(part_id, int) and not isinstance(part_id, bool)
                else None
            ),
            "step": (
                int(step)
                if isinstance(step, int) and not isinstance(step, bool)
                else None
            ),
            "comment": safe_comment,
            "target_models": target_models,
            "yolo_classes": yolo_classes,
            "marks_count": len(normalized_marks),
            "marks": normalized_marks,
            "existing_detections_count": len(det_summary),
            "existing_detections": det_summary,
            "exported": False,
            "exported_at": None,
        }

        try:
            self._save_bytes(clean_bytes, os.path.join(task_dir, "clean.jpg"))
            self._save_bytes(hint_bytes, os.path.join(task_dir, "hint.jpg"))
            self._save_json(meta, os.path.join(task_dir, "meta.json"))
        except Exception:
            with contextlib.suppress(OSError):
                shutil.rmtree(task_dir)
            raise

        with self._lock:
            if self._cached_counts is not None:
                pending, total = self._cached_counts
                self._cached_counts = (pending + 1, total + 1)

        print(
            f"[YOLO-TASK] Сохранено {task_id} ({role}, "
            f"обводок: {len(normalized_marks)}, классы: {', '.join(yolo_classes)})"
        )
        return self._public_item(meta)

    def _iter_metas(self) -> list[tuple[str, dict]]:
        items_path = self.items_dir
        if not os.path.isdir(items_path):
            return []
        collected: list[tuple[str, dict]] = []
        try:
            names = sorted(os.listdir(items_path))
        except OSError:
            return []
        for name in names:
            folder = os.path.join(items_path, name)
            meta_path = os.path.join(folder, "meta.json")
            clean_path = os.path.join(folder, "clean.jpg")
            if not (os.path.isfile(meta_path) and os.path.isfile(clean_path)):
                continue
            try:
                with open(meta_path, encoding="utf-8") as stream:
                    meta = json.load(stream)
                if isinstance(meta, dict) and meta.get("task_id"):
                    collected.append((folder, meta))
            except (OSError, ValueError):
                continue
        return collected

    @staticmethod
    def _public_item(meta: dict) -> dict:
        marks = meta.get("marks") or []
        labels_ru = list(dict.fromkeys(
            str(m.get("label_ru") or m.get("yolo_class") or "")
            for m in marks
            if isinstance(m, dict)
        ))
        return {
            "task_id": meta.get("task_id"),
            "created_at": meta.get("created_at"),
            "time": meta.get("time"),
            "date": meta.get("date"),
            "camera_role": meta.get("camera_role"),
            "camera_label": meta.get("camera_label"),
            "marks_count": int(meta.get("marks_count") or len(marks)),
            "yolo_classes": list(meta.get("yolo_classes") or []),
            "labels_ru": labels_ru,
            "target_models": list(meta.get("target_models") or []),
            "comment": meta.get("comment") or "",
            "part_id": meta.get("part_id"),
            "step": meta.get("step"),
            "exported": bool(meta.get("exported")),
        }

    def status_counts(self) -> dict:
        """Быстрая сводка счётчиков для /api/status (кэшируется в памяти)."""
        with self._lock:
            if self._cached_counts is None:
                metas = self._iter_metas()
                pending = sum(
                    1 for _folder, m in metas if not m.get("exported")
                )
                self._cached_counts = (pending, len(metas))
            cached = self._cached_counts
        return {
            "available": True,
            "pending": cached[0],
            "total": cached[1],
        }

    def get_summary(self, limit: int = 30) -> dict:
        """Подробная сводка очереди для модального окна выгрузки ZIP."""
        with self._lock:
            metas = self._iter_metas()
            pending = 0
            by_model: dict[tuple[str, str], dict] = {}
            items = []

            for _folder, meta in metas:
                is_exported = bool(meta.get("exported"))
                if not is_exported:
                    pending += 1
                cam_role = str(meta.get("camera_role") or "")
                for mark in (meta.get("marks") or []):
                    if not isinstance(mark, dict):
                        continue
                    cls_key = str(mark.get("yolo_class") or "other")
                    slug = str(mark.get("model_folder") or "other")
                    bucket = by_model.setdefault((cam_role, cls_key), {
                        "model_folder": slug,
                        "model_path": mark.get("model_path"),
                        "yolo_class": cls_key,
                        "label_ru": mark.get("label_ru") or cls_key,
                        "camera_role": cam_role,
                        "total_marks": 0,
                        "pending_marks": 0,
                    })
                    bucket["total_marks"] += 1
                    if not is_exported:
                        bucket["pending_marks"] += 1

            for _folder, meta in reversed(metas[-max(1, int(limit)):]):
                items.append(self._public_item(meta))

            self._cached_counts = (pending, len(metas))
            store_dir = self.store_dir

        return {
            "available": True,
            "root_path": store_dir,
            "pending_count": pending,
            "total_count": len(metas),
            "by_model": sorted(
                by_model.values(),
                key=lambda item: (-item["pending_marks"], -item["total_marks"]),
            ),
            "items": items,
        }

    def get_item_image_path(self, task_id: str, kind: str = "hint") -> str | None:
        safe_id = os.path.basename(str(task_id or "").strip())
        if not safe_id or safe_id != task_id:
            return None
        filename = "clean.jpg" if kind == "clean" else "hint.jpg"
        candidate = os.path.join(self.items_dir, safe_id, filename)
        return candidate if os.path.isfile(candidate) else None

    def delete_task(self, task_id: str) -> bool:
        safe_id = os.path.basename(str(task_id or "").strip())
        if not safe_id or safe_id != task_id:
            return False
        with self._lock:
            target = os.path.join(self.items_dir, safe_id)
            if not os.path.isdir(target):
                return False
            shutil.rmtree(target)
            self._cached_counts = None
        return True

    # ---------- формирование ZIP для разметчика ----------

    @staticmethod
    def _format_yolo_draft_line(mark: dict) -> str | None:
        class_id = int(mark.get("class_id", -1))
        if class_id < 0:
            return None
        pts = mark.get("points_norm") or []
        if len(pts) < 3:
            return None
        coords = " ".join(f"{float(x):.6f} {float(y):.6f}" for x, y in pts)
        return f"{class_id} {coords}"

    @staticmethod
    def _readme_text(exported_count: int, generated_at: str) -> str:
        return (
            "ПАКЕТ КАДРОВ ДЛЯ ДООБУЧЕНИЯ МОДЕЛЕЙ YOLO (ConveyerSeven)\n"
            f"Сформирован: {generated_at}\n"
            f"Количество кейсов: {exported_count}\n\n"
            "Структура архива:\n"
            "  datasets/<папка_модели>/\n"
            "    images/        — ЧИСТЫЕ кадры 1280x720 (.jpg, качество 98)\n"
            "                     без рамок, сетки и надписей.\n"
            "                     Загружайте эту папку напрямую в CVAT,\n"
            "                     Label Studio, Roboflow или X-AnyLabeling.\n"
            "    hints/         — КАДРЫ-ПОДСКАЗКИ (.jpg) с тем же именем файла:\n"
            "                     показано, какие именно пропущенные дефекты\n"
            "                     обвёл оператор и какие объекты уже нашла\n"
            "                     текущая нейросеть.\n"
            "    draft_labels/  — Черновые полигоны оператора в формате YOLO-seg\n"
            "                     (<class_id> x1 y1 x2 y2 ... в координатах 0..1).\n"
            "                     Используйте только как ориентир/предразметку:\n"
            "                     контур оператора грубый и требует точной обводки.\n"
            "    classes.txt    — Точный порядок классов целевой .pt-модели\n"
            "                     (совпадает с vision/model_config.py).\n"
            "    meta/          — Полные JSON-карточки (комментарий оператора,\n"
            "                     роль камеры, путь к .pt-весам, время, шаг).\n"
        )

    def ensure_exportable(self, *, only_pending: bool = True) -> int:
        """Проверить наличие задач для выгрузки до открытия диалога файла."""
        with self._lock:
            metas = self._iter_metas()
            selected = [
                1
                for _folder, meta in metas
                if (not only_pending) or (not meta.get("exported"))
            ]
            if not selected:
                if only_pending and metas:
                    raise ValueError(
                        "Нет новых невыгруженных кадров "
                        "(используйте «Скачать все», чтобы выгрузить повторно)"
                    )
                raise ValueError("Очередь кадров для YOLO пуста")
            return len(selected)

    def _mark_selected_exported_unlocked(
        self, selected: list[tuple[str, dict]], exported_at: str,
    ) -> None:
        for folder, meta in selected:
            if meta.get("exported"):
                continue
            updated = dict(meta)
            updated["exported"] = True
            updated["exported_at"] = exported_at
            with contextlib.suppress(OSError):
                self._save_json(updated, os.path.join(folder, "meta.json"))
        self._cached_counts = None

    def _build_zip_unlocked(
        self,
        *,
        only_pending: bool,
    ) -> tuple[bytes, list[tuple[str, dict]], str, str]:
        metas = self._iter_metas()
        selected = [
            (folder, meta)
            for folder, meta in metas
            if (not only_pending) or (not meta.get("exported"))
        ]
        if not selected:
            if only_pending and metas:
                raise ValueError(
                    "Нет новых невыгруженных кадров "
                    "(используйте «Скачать все», чтобы выгрузить повторно)"
                )
            raise ValueError("Очередь кадров для YOLO пуста")

        now = datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        filename = f"yolo_tasks_{now.strftime('%Y%m%d_%H%M%S')}.zip"

        buf = io.BytesIO()
        written_classes_files: set[str] = set()
        manifest_items = []

        with zipfile.ZipFile(
            buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
        ) as zf:
            zf.writestr(
                "README_YOLO.txt",
                self._readme_text(len(selected), now_iso),
            )

            for folder, meta in selected:
                task_id = str(meta["task_id"])
                role = str(meta.get("camera_role") or "UNKNOWN")
                clean_path = os.path.join(folder, "clean.jpg")
                hint_path = os.path.join(folder, "hint.jpg")

                grouped_marks: dict[str, list[dict]] = {}
                for mark in (meta.get("marks") or []):
                    if not isinstance(mark, dict):
                        continue
                    slug = str(
                        mark.get("model_folder")
                        or _model_folder_slug(mark.get("model_path"), role)
                    )
                    grouped_marks.setdefault(slug, []).append(mark)

                if not grouped_marks:
                    grouped_marks[f"{role}__other"] = []

                for slug, slug_marks in grouped_marks.items():
                    base = f"datasets/{slug}"
                    # JPEG уже сжаты: ZIP_STORED бережёт CPU во время цикла.
                    zf.write(
                        clean_path,
                        f"{base}/images/{task_id}.jpg",
                        compress_type=zipfile.ZIP_STORED,
                    )
                    if os.path.isfile(hint_path):
                        zf.write(
                            hint_path,
                            f"{base}/hints/{task_id}.jpg",
                            compress_type=zipfile.ZIP_STORED,
                        )

                    model_classes = []
                    for m in slug_marks:
                        if m.get("model_classes"):
                            model_classes = list(m["model_classes"])
                            break
                    if model_classes and slug not in written_classes_files:
                        zf.writestr(
                            f"{base}/classes.txt",
                            "\n".join(model_classes) + "\n",
                        )
                        written_classes_files.add(slug)

                    draft_lines = [
                        line
                        for m in slug_marks
                        for line in (self._format_yolo_draft_line(m),)
                        if line
                    ]
                    if draft_lines:
                        zf.writestr(
                            f"{base}/draft_labels/{task_id}.txt",
                            "\n".join(draft_lines) + "\n",
                        )

                    zf.writestr(
                        f"{base}/meta/{task_id}.json",
                        json.dumps(meta, indent=2, ensure_ascii=False),
                    )

                manifest_items.append(self._public_item(meta))

            manifest = {
                "schema_version": self.SCHEMA_VERSION,
                "generated_at": now_iso,
                "only_pending": bool(only_pending),
                "exported_count": len(selected),
                "items": manifest_items,
            }
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False),
            )

        return buf.getvalue(), selected, filename, now_iso

    def build_export_zip(
        self,
        *,
        only_pending: bool = True,
        mark_exported: bool = True,
    ) -> tuple[bytes, int, str]:
        """Собрать ZIP в памяти и при необходимости пометить задачи выгруженными.

        Возвращает ``(zip_bytes, count, suggested_filename)``.
        Если подходящих задач нет, выбрасывает ``ValueError``.
        """
        with self._lock:
            zip_bytes, selected, filename, now_iso = self._build_zip_unlocked(
                only_pending=only_pending,
            )
            if mark_exported:
                self._mark_selected_exported_unlocked(selected, now_iso)
            return zip_bytes, len(selected), filename

    def export_zip_to_path(
        self,
        destination_path: str,
        *,
        only_pending: bool = True,
        mark_exported: bool = True,
    ) -> tuple[str, int]:
        """Атомарно записать ZIP-архив на диск и лишь затем пометить выгрузку."""
        target = os.path.abspath(
            os.path.expandvars(os.path.expanduser(str(destination_path)))
        )
        if not target.lower().endswith(".zip"):
            target += ".zip"

        with self._lock:
            zip_bytes, selected, _filename, now_iso = self._build_zip_unlocked(
                only_pending=only_pending,
            )
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            self._save_bytes(zip_bytes, target)
            if mark_exported:
                self._mark_selected_exported_unlocked(selected, now_iso)

        print(f"[YOLO-TASK] Выгружен ZIP ({len(selected)} кадров) -> {target}")
        return target, len(selected)

    # ---------- низкоуровневый ввод/вывод ----------

    @staticmethod
    def _encode_jpeg(frame: np.ndarray, quality: int) -> bytes:
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, int(quality)],
        )
        if not ok or encoded is None:
            raise RuntimeError("Не удалось закодировать кадр в JPEG")
        return encoded.tobytes()

    @staticmethod
    def _save_bytes(content: bytes, path: str) -> None:
        temp_path = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
        try:
            with open(temp_path, "xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        except Exception:
            if os.path.exists(temp_path):
                with contextlib.suppress(OSError):
                    os.remove(temp_path)
            raise

    @classmethod
    def _save_json(cls, payload: dict, path: str) -> None:
        raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        cls._save_bytes(raw, path)
