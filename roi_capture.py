"""Мини-приложение разметки зон ROI по семи камерам линии.

Отдельный файл рядом с production-приложением: не требует браузера,
pywebview, моделей и нейросетей — только OpenCV, NumPy и (для кириллицы
в интерфейсе) Pillow.

Что делает
----------

1. По кнопке ``НАЧАТЬ`` открывает камеры из ``camera_mapping.json`` и
   показывает кадр текущей камеры.
2. Оператор обводит нужную область (прямоугольник или полигон).
3. ``Enter`` — пара кадров сохраняется на диск: чистый кадр ``*.jpg`` и
   тот же кадр с нарисованной зоной ``*_roi.jpg`` плюс ``*.json`` с
   координатами.
4. Приложение само переходит к следующей камере. Когда все семь камер
   размечены, предлагается шаг конвейера (``Conveyor.move_step`` +
   ``wait_stop`` с подтверждением STEP по COM-порту).
5. После подтверждённого шага начинается новый круг: семь свежих кадров,
   снова по одной камере. В конце сеанса пишется ``session.json``.

Запуск (из корня репозитория, как остальные bat-файлы)::

    run_roi_capture.bat
    python roi_capture.py --out roi_dataset

Без железа (проверка интерфейса и сохранения)::

    python roi_capture.py --source synthetic --step sim
    python roi_capture.py --source folder --frames-dir shots --step none

Горячие клавиши
---------------

=============  ==========================================
ЛКМ            обвести прямоугольник / поставить точку
ПКМ            убрать последнюю точку полигона
Двойной клик   замкнуть полигон
``Пробел``/``1``/``2``  переключить прямоугольник / полигон
``Enter``/``S``  сохранить текущую камеру и перейти дальше
``R``          сбросить зону
``C``          переснять кадр текущей камеры
``A``/``D``    предыдущая / следующая камера
``N``          продолжить без шага конвейера
``F``          завершить сеанс и записать ``session.json``
``Esc``/``Q``  выход (сохранённые кадры остаются на диске)
=============  ==========================================

Структура результата
--------------------

::

    <out>/<session_id>/
      session.json                   манифест сеанса (OPEN/CLOSED)
      round_01/
        01_INPUT_LEFT.jpg            чистый кадр
        01_INPUT_LEFT_roi.jpg        кадр с нарисованной зоной
        01_INPUT_LEFT.json           координаты зоны и метаданные
        ...
      round_02/
        ...

Безопасность
------------

Шаг ленты отправляется один раз: если контроллер не подтвердил приём или
выполнение, повтор команды запрещён (состояние механики неизвестно).
Приложение переходит в состояние с ошибкой и блокирует дальнейшие шаги до
перезапуска — та же политика, что у production-цикла.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

try:                                    # кириллица в интерфейсе OpenCV
    from PIL import Image, ImageDraw, ImageFont
    _HAVE_PIL = True
except ImportError:                     # pragma: no cover - зависит от окружения
    Image = ImageDraw = ImageFont = None
    _HAVE_PIL = False


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

WINDOW_NAME = "ConveyerSeven · Разметка зон ROI"

CAMERA_MAPPING_FILE = "camera_mapping.json"
CALIBRATION_FILE = "calibration.json"

ROLE_ORDER = (
    "INPUT_LEFT",
    "INPUT_RIGHT",
    "SPIDER_LEFT",
    "SPIDER_RIGHT",
    "SPIDER_IN",
    "SPIDER_OUT",
    "TOP",
)

ROLE_LABELS = {
    "INPUT_LEFT": "ВХОД · ЛЕВО",
    "INPUT_RIGHT": "ВХОД · ПРАВО",
    "SPIDER_LEFT": "КОНТАКТЫ · ЛЕВО",
    "SPIDER_RIGHT": "КОНТАКТЫ · ПРАВО",
    "SPIDER_IN": "ВНУТРЕННИЕ КОНТАКТЫ",
    "SPIDER_OUT": "НАРУЖНЫЕ КОНТАКТЫ",
    "TOP": "ВЕРХ · ГЕОМЕТРИЯ",
}

# Палитра HMI проекта (BGR).
COL_BG = (23, 19, 15)
COL_PANEL = (39, 32, 24)
COL_PANEL_RAISED = (45, 37, 28)
COL_BORDER = (68, 59, 48)
COL_BORDER_STRONG = (92, 81, 68)
COL_TEXT = (233, 229, 224)
COL_TEXT_DIM = (173, 165, 154)
COL_TEXT_MUTED = (124, 116, 105)
COL_ACCENT = (165, 153, 120)
COL_OK = (126, 163, 114)
COL_BAD = (118, 118, 201)
COL_WARN = (106, 166, 193)

EXPECTED_FRAME_SIZE = (1280, 720)
JPEG_QUALITY = 95

PANEL_WIDTH = 380
PANEL_PAD = 18
MIN_CANVAS_HEIGHT = 620
MIN_DRAW_SIZE = 8

# Коды стрелок различаются между бэкендами OpenCV; поддерживаем оба.
ARROW_LEFT = (65361, 2424832, 63234)
ARROW_RIGHT = (65363, 2555072, 63235)


def ui(key: str) -> str:
    """Подпись интерфейса: кириллица при наличии Pillow, иначе ASCII."""
    russian, ascii_ = UI_STRINGS[key]
    return russian if _HAVE_PIL else ascii_


UI_STRINGS = {
    "title": ("РАЗМЕТКА ЗОН ROI", "ROI MARKUP"),
    "start": ("НАЧАТЬ", "START"),
    "session": ("СЕССИЯ", "SESSION"),
    "round": ("КРУГ", "ROUND"),
    "shot": ("КАДР", "FRAME"),
    "camera": ("КАМЕРА", "CAMERA"),
    "mode": ("РЕЖИМ", "MODE"),
    "rect": ("ПРЯМОУГОЛЬНИК", "RECTANGLE"),
    "poly": ("ПОЛИГОН", "POLYGON"),
    "zone": ("ЗОНА", "ZONE"),
    "area": ("ПЛОЩАДЬ", "AREA"),
    "saved": ("СОХРАНЕНО", "SAVED"),
    "step": ("ШАГ ЛЕНТЫ", "STEP"),
    "controls": ("УПРАВЛЕНИЕ", "CONTROLS"),
    "output": ("СОХРАНЕНИЕ", "OUTPUT"),
    "no_frame": ("НЕТ КАДРА", "NO FRAME"),
    "no_zone": ("ЗОНА НЕ ЗАДАНА — ОБВЕДИТЕ ОБЛАСТЬ", "NO ZONE YET"),
    "press_start": ("Нажмите НАЧАТЬ", "Press START"),
    "press_start_hint": ("Семь камер · обводка зоны · пары кадров на диск",
                         "Seven cameras / draw zone / frame pairs"),
    "round_done": ("КРУГ ЗАВЕРШЁН", "ROUND COMPLETE"),
    "round_done_text": ("Все 7 камер размечены и сохранены.",
                        "All 7 cameras saved."),
    "round_done_hint": ("Сделать шаг конвейера и снять новый круг?",
                        "Move the conveyor and start a new round?"),
    "make_step": ("ШАГ КОНВЕЙЕРА", "MOVE CONVEYOR"),
    "without_step": ("БЕЗ ШАГА", "NO STEP"),
    "finish": ("ЗАВЕРШИТЬ", "FINISH"),
    "exit": ("ВЫХОД", "EXIT"),
    "finished": ("СЕАНС ЗАВЕРШЁН", "SESSION FINISHED"),
    "stepping": ("ШАГ КОНВЕЙЕРА", "CONVEYOR STEP"),
    "stepping_hint": ("Ожидание подтверждения контроллера…",
                      "Waiting for controller confirmation..."),
    "keys_draw": ("ЛКМ — обвести", "LMB - draw"),
    "keys_point": ("ПКМ — убрать точку", "RMB - undo point"),
    "keys_mode": ("ПРОБЕЛ — режим", "SPACE - mode"),
    "keys_save": ("ENTER — сохранить", "ENTER - save"),
    "keys_nav": ("A / D — камера", "A / D - camera"),
    "keys_reset": ("R — сбросить, C — переснять", "R - reset, C - recapture"),
    "keys_finish": ("F — завершить, ESC — выход", "F - finish, ESC - exit"),
    "rect_hint": ("Тяните ЛКМ от угла до угла", "Drag LMB corner to corner"),
    "poly_hint": ("Точки ЛКМ, двойной клик — замкнуть", "LMB points, dbl-click closes"),
}


# ---------------------------------------------------------------------------
# Текст с кириллицей
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = {
    False: (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ),
    True: (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
}


@dataclass
class TextItem:
    """Одна строка для пакетной отрисовки."""

    text: str
    xy: tuple[int, int]
    size: int = 16
    color: tuple = COL_TEXT
    bold: bool = False
    anchor: str = "lt"          # l|c|r + t|m|b
    max_width: int | None = None


class TextRenderer:
    """Отрисовка текста: Pillow (кириллица) или cv2.putText (ASCII)."""

    def __init__(self) -> None:
        self._fonts: dict = {}
        self._font_paths: dict = {}

    # ---------- шрифты ----------

    def _font_path(self, bold: bool) -> str | None:
        if bold in self._font_paths:
            return self._font_paths[bold]
        path = None
        for candidate in _FONT_CANDIDATES[bold]:
            if os.path.exists(candidate):
                path = candidate
                break
        self._font_paths[bold] = path
        return path

    def _font(self, size: int, bold: bool):
        key = (size, bold)
        font = self._fonts.get(key)
        if font is not None:
            return font
        if not _HAVE_PIL:
            return None
        path = self._font_path(bold)
        try:
            font = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
        except Exception:
            font = ImageFont.load_default()
        self._fonts[key] = font
        return font

    # ---------- измерение ----------

    def measure(self, text: str, size: int = 16, bold: bool = False) -> tuple[int, int]:
        if not text:
            return 0, 0
        if _HAVE_PIL:
            font = self._font(size, bold)
            draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            return right - left, bottom - top
        scale, thickness = self._cv_scale(size)
        (width, height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX,
                                             scale, thickness)
        return width, height

    @staticmethod
    def _cv_scale(size: int) -> tuple[float, int]:
        return max(0.3, size / 30.0), max(1, size // 14)

    # ---------- отрисовка ----------

    def draw(self, img, item: TextItem) -> None:
        self.draw_many(img, [item])

    def draw_many(self, img, items: list[TextItem]) -> None:
        prepared = [self._truncate(item) for item in items if item.text]
        if not prepared:
            return
        if not _HAVE_PIL:
            for item in prepared:
                self._draw_cv(img, item)
            return

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        surface = Image.fromarray(rgb)
        draw = ImageDraw.Draw(surface)
        for item in prepared:
            font = self._font(item.size, item.bold)
            left, top, right, bottom = draw.textbbox((0, 0), item.text, font=font)
            width, height = right - left, bottom - top
            x, y = item.xy
            dx = -left if item.anchor[0] == "l" else (
                -left - width // 2 if item.anchor[0] == "c" else -left - width)
            dy = -top if item.anchor[1] == "t" else (
                -top - height // 2 if item.anchor[1] == "m" else -top - height)
            draw.text((x + dx, y + dy), item.text, font=font, fill=item.color)
        img[:, :, :] = cv2.cvtColor(np.asarray(surface), cv2.COLOR_RGB2BGR)

    def _truncate(self, item: TextItem) -> TextItem:
        if item.max_width is None or not item.text:
            return item
        text = item.text
        width, _ = self.measure(text, item.size, item.bold)
        if width <= item.max_width:
            return item
        ellipsis = "…" if _HAVE_PIL else "..."
        while text and width > item.max_width:
            text = text[:-1]
            width, _ = self.measure(text + ellipsis, item.size, item.bold)
        return TextItem(text + ellipsis, item.xy, item.size, item.color,
                        item.bold, item.anchor)

    def _draw_cv(self, img, item: TextItem) -> None:
        scale, thickness = self._cv_scale(item.size)
        (width, height), _ = cv2.getTextSize(item.text, cv2.FONT_HERSHEY_SIMPLEX,
                                             scale, thickness)
        x, y = item.xy
        dx = 0 if item.anchor[0] == "l" else (
            -width // 2 if item.anchor[0] == "c" else -width)
        dy = height if item.anchor[1] == "t" else (
            height // 2 if item.anchor[1] == "m" else 0)
        cv2.putText(img, item.text, (x + dx, y + dy), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, item.color, thickness, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Геометрия зоны
# ---------------------------------------------------------------------------

def _distance(a: tuple[int, int], b: tuple[int, int]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


@dataclass
class Roi:
    """Область интереса: прямоугольник или полигон в координатах кадра."""

    mode: str = "rect"
    points: list[tuple[int, int]] = field(default_factory=list)
    closed: bool = False

    # ---------- фабрики ----------

    @classmethod
    def rect(cls, a: tuple[int, int], b: tuple[int, int]) -> "Roi":
        x1, y1 = int(min(a[0], b[0])), int(min(a[1], b[1]))
        x2, y2 = int(max(a[0], b[0])), int(max(a[1], b[1]))
        return cls("rect", [(x1, y1), (x2, y1), (x2, y2), (x1, y2)], True)

    @classmethod
    def from_rect(cls, bbox: tuple[int, int, int, int]) -> "Roi":
        x, y, w, h = bbox
        return cls.rect((x, y), (x + w, y + h))

    # ---------- свойства ----------

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        xs = [p[0] for p in self.points] or [0]
        ys = [p[1] for p in self.points] or [0]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    @property
    def area(self) -> float:
        if len(self.points) < 3:
            return 0.0
        contour = np.array(self.points, dtype=np.float32)
        if self.mode == "rect":
            x, y, w, h = self.bbox
            return float(w * h)
        return float(abs(cv2.contourArea(contour)))

    def is_valid(self) -> bool:
        if len(self.points) < 3:
            return False
        if self.mode == "rect":
            _, _, w, h = self.bbox
            return w >= MIN_DRAW_SIZE and h >= MIN_DRAW_SIZE
        return self.area >= MIN_DRAW_SIZE ** 2

    # ---------- преобразования ----------

    def clamp(self, width: int, height: int) -> "Roi":
        self.points = [
            (max(0, min(width - 1, int(x))), max(0, min(height - 1, int(y))))
            for x, y in self.points
        ]
        return self

    def to_polygon(self) -> "Roi":
        if self.mode == "poly":
            return self
        return Roi("poly", list(self.points), True)

    def to_rect(self) -> "Roi":
        if self.mode == "rect":
            return self
        return Roi.from_rect(self.bbox)

    def as_dict(self, frame_width: int, frame_height: int) -> dict:
        x, y, w, h = self.bbox
        area = self.area
        frame_area = max(1, frame_width * frame_height)
        return {
            "mode": self.mode,
            "points": [[int(px), int(py)] for px, py in self.points],
            "bbox": [int(x), int(y), int(w), int(h)],
            "area_px": int(round(area)),
            "area_pct": round(area / frame_area * 100.0, 3),
            "centre": [int(x + w / 2), int(y + h / 2)],
        }


# ---------------------------------------------------------------------------
# Источники кадров
# ---------------------------------------------------------------------------

class CameraSource:
    """Базовый источник кадров по роли камеры."""

    name = "camera"

    def __init__(self, mapping: dict):
        self.mapping = mapping

    def open(self) -> list[str]:
        """Подготовить источник; вернуть список замечаний для консоли."""
        return []

    def capture(self, role: str) -> np.ndarray:
        raise NotImplementedError

    def advance(self) -> None:
        """Сообщить источнику о новом круге (после шага ленты)."""

    def close(self) -> None:
        pass

    def describe(self) -> str:
        return self.name


class HardwareCameraSource(CameraSource):
    """Семь USB-камер через ``cv2.VideoCapture`` (как в production)."""

    name = "camera"
    DRAIN_FRAMES = 3

    def __init__(self, mapping: dict, backend: int | None = None):
        super().__init__(mapping)
        self._backend = backend
        self._captures: dict = {}
        self._errors: dict = {}

    def open(self) -> list[str]:
        notes = []
        for role in ROLE_ORDER:
            camera_id = self.mapping.get(role)
            if camera_id is None:
                self._errors[role] = "роль отсутствует в camera_mapping.json"
                notes.append(f"{role}: роль отсутствует в camera_mapping.json")
                continue
            print(f"[ROI] Открытие {role} id={camera_id}")
            try:
                cap = self._open_capture(camera_id)
                if cap is None or not cap.isOpened():
                    raise RuntimeError("VideoCapture не открыл устройство")
                self._configure(cap)
                self._captures[role] = cap
            except Exception as exc:                    # noqa: BLE001
                self._errors[role] = str(exc)
                notes.append(f"{role} (id={camera_id}): {exc}")
        opened = len(self._captures)
        print(f"[ROI] Открыто камер: {opened} из {len(ROLE_ORDER)}")
        return notes

    def _open_capture(self, camera_id: int):
        if self._backend is None:
            return cv2.VideoCapture(camera_id)
        return cv2.VideoCapture(camera_id, self._backend)

    @staticmethod
    def _configure(cap) -> None:
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, EXPECTED_FRAME_SIZE[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, EXPECTED_FRAME_SIZE[1])
        cap.set(cv2.CAP_PROP_FPS, 30)
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def capture(self, role: str) -> np.ndarray:
        error = self._errors.get(role)
        if error is not None:
            raise RuntimeError(f"{role}: камера недоступна ({error})")
        cap = self._captures.get(role)
        if cap is None:
            raise RuntimeError(f"{role}: камера не открыта")

        frame = None
        for _ in range(self.DRAIN_FRAMES):
            ok, candidate = cap.read()
            if ok and candidate is not None:
                frame = candidate
        if frame is None:
            raise RuntimeError(f"{role}: камера не вернула кадр")

        height, width = frame.shape[:2]
        if (width, height) != EXPECTED_FRAME_SIZE:
            print(f"[ROI] {role}: разрешение {width}x{height} "
                  f"вместо {EXPECTED_FRAME_SIZE[0]}x{EXPECTED_FRAME_SIZE[1]}")
        return frame

    def close(self) -> None:
        for role, cap in list(self._captures.items()):
            try:
                cap.release()
            except Exception as exc:                    # noqa: BLE001
                print(f"[ROI] Ошибка освобождения {role}: {exc}")
        self._captures.clear()

    def describe(self) -> str:
        return f"камеры ({len(self._captures)}/{len(ROLE_ORDER)} открыто)"


class FolderCameraSource(CameraSource):
    """Кадры из папки: ``<frames-dir>/<ROLE>.jpg`` или ``<dir>/<круг>/<ROLE>.jpg``."""

    name = "folder"
    EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp")

    def __init__(self, mapping: dict, frames_dir: str):
        super().__init__(mapping)
        self.frames_dir = Path(frames_dir)
        self.round_index = 0

    def open(self) -> list[str]:
        if not self.frames_dir.is_dir():
            raise RuntimeError(f"Папка кадров не найдена: {self.frames_dir}")
        return []

    def advance(self) -> None:
        self.round_index += 1

    def capture(self, role: str) -> np.ndarray:
        candidates = [
            self.frames_dir / str(self.round_index + 1) / name
            for name in (f"{role}{ext}" for ext in self.EXTENSIONS)
        ]
        candidates += [
            self.frames_dir / name
            for name in (f"{role}{ext}" for ext in self.EXTENSIONS)
        ]
        for path in candidates:
            if path.exists():
                frame = _read_image(path)
                if frame is not None:
                    return frame
        raise RuntimeError(f"{role}: кадр не найден в {self.frames_dir}")

    def describe(self) -> str:
        return f"папка {self.frames_dir}"


class SyntheticCameraSource(CameraSource):
    """Синтетические кадры: проверка интерфейса без камер и без ленты."""

    name = "synthetic"

    def __init__(self, mapping: dict, seed: int = 7):
        super().__init__(mapping)
        self.seed = seed
        self.round_index = 0
        self._text = TextRenderer()
        self._rng = np.random.default_rng(seed)
        self._base = self._build_background()

    def advance(self) -> None:
        self.round_index += 1

    def _build_background(self) -> np.ndarray:
        width, height = EXPECTED_FRAME_SIZE
        canvas = np.zeros((height, width, 3), np.uint8)
        for y in range(height):
            shade = int(26 + 18 * y / height)
            canvas[y, :] = (shade + 4, shade + 2, shade)
        for x in range(0, width, 80):
            cv2.line(canvas, (x, 0), (x, height), (44, 38, 30), 1)
        for y in range(0, height, 80):
            cv2.line(canvas, (0, y), (width, y), (44, 38, 30), 1)
        return canvas

    def capture(self, role: str) -> np.ndarray:
        width, height = EXPECTED_FRAME_SIZE
        frame = self._base.copy()
        role_index = ROLE_ORDER.index(role) if role in ROLE_ORDER else 0
        offset = int(self.round_index * 46 + role_index * 7)

        # «лента» с насечкой, сдвигается на каждом круге
        cv2.rectangle(frame, (0, height - 190), (width, height), (34, 40, 46), -1)
        for x in range(-200, width + 200, 64):
            px = x + offset % 64
            cv2.line(frame, (px, height - 190), (px - 40, height),
                     (58, 66, 74), 6)

        # «корпус» с окнами, сдвигается по ленте
        part_x = int(320 + (offset * 3) % 220)
        part_y = int(150 + role_index * 4)
        cv2.rectangle(frame, (part_x, part_y), (part_x + 520, part_y + 300),
                      (96, 104, 112), -1)
        cv2.rectangle(frame, (part_x, part_y), (part_x + 520, part_y + 300),
                      (150, 158, 166), 3)
        for index in range(3):
            wx = part_x + 46 + index * 150
            cv2.rectangle(frame, (wx, part_y + 60), (wx + 110, part_y + 165),
                          (40, 46, 54), -1)
            cv2.rectangle(frame, (wx, part_y + 60), (wx + 110, part_y + 165),
                          (178, 186, 194), 2)
        cv2.rectangle(frame, (part_x + 60, part_y + 205),
                      (part_x + 460, part_y + 250), (70, 78, 86), -1)

        noise = self._rng.integers(-6, 7, frame.shape, dtype=np.int16)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        self._text.draw(frame, TextItem(
            "СИНТЕТИЧЕСКИЙ КАДР" if _HAVE_PIL else "SYNTHETIC FRAME",
            (width - 28, height - 24), 18, COL_TEXT_MUTED, True, "rb",
        ))
        return frame

    def describe(self) -> str:
        return "синтетика (без камер)"


# ---------------------------------------------------------------------------
# Шаг конвейера
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Итог одной попытки шага ленты."""

    ok: bool
    step: int | None = None
    message: str = ""


class StepDriver:
    """Интерфейс шага конвейера."""

    mode = "none"
    fault = ""

    def step(self, on_progress: Callable[[str], None] | None = None) -> StepResult:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def describe(self) -> str:
        return self.mode


class NoStepDriver(StepDriver):
    """Шаг отключён: камеры снимаются, лента стоит."""

    mode = "none"

    def step(self, on_progress: Callable[[str], None] | None = None) -> StepResult:
        if on_progress:
            on_progress("шаг отключён")
        return StepResult(True, None, "шаг отключён (--step none)")


class SimStepDriver(StepDriver):
    """Имитация шага для отладки без оборудования."""

    mode = "sim"

    def __init__(self, duration: float = 1.4):
        self.duration = max(0.1, duration)
        self.step_number = 0

    def step(self, on_progress: Callable[[str], None] | None = None) -> StepResult:
        started = time.monotonic()
        while True:
            elapsed = time.monotonic() - started
            if on_progress:
                on_progress(f"имитация · {elapsed:.1f} / {self.duration:.1f} с")
            if elapsed >= self.duration:
                break
            time.sleep(0.05)
        self.step_number += 1
        return StepResult(True, self.step_number, f"имитация шага {self.step_number}")


class SerialStepDriver(StepDriver):
    """Реальный шаг: ``Conveyor.move_step`` + ``wait_stop`` с подтверждением STEP."""

    mode = "serial"

    def __init__(
        self,
        *,
        port: str | None = None,
        baudrate: int = 115200,
        calibration_file: str = CALIBRATION_FILE,
        settle: float = 0.35,
        timeout: float = 20.0,
    ):
        self.port = port
        self.baudrate = baudrate
        self.calibration_file = calibration_file
        self.settle = max(0.0, settle)
        self.timeout = timeout
        self.fault = ""
        self.transport = None
        self.conveyor = None
        self.last_step: int | None = None
        self._calibration = None

    # ---------- подключение ----------

    def _ensure_connected(self) -> None:
        if self.conveyor is not None:
            return
        from hardware.conveyor import Conveyor
        from hardware.port_discovery import find_controller
        from hardware.serial_transport import SerialTransport

        port = self.port
        if not port:
            port, message = find_controller(
                baudrate=self.baudrate,
                preferred_port=os.environ.get("SERIAL_PORT"),
            )
            if not port:
                raise RuntimeError(f"Контроллер не найден: {message}")

        print(f"[ROI] Контроллер: {port} @ {self.baudrate}")
        transport = SerialTransport(port=port, baudrate=self.baudrate)
        # Останавливаем всё до первой команды — как в production startup.
        transport.send("G1")
        transport.send("G25")

        calibration = self._load_calibration()
        self.transport = transport
        self.conveyor = Conveyor(
            transport,
            speed=calibration["conveyor_speed"],
            accel=calibration["conveyor_accel"],
            steps_per_division=calibration["normal_steps"],
            divisions_per_movement=2,
        )
        self.port = port

    def _load_calibration(self) -> dict:
        if self._calibration is not None:
            return self._calibration
        try:
            from config.calibration_loader import load_calibration
            self._calibration = load_calibration(self.calibration_file)
            print(f"[ROI] Калибровка: {self.calibration_file}")
        except Exception as exc:                        # noqa: BLE001
            print(f"[ROI] Калибровка недоступна ({exc}); используются значения по умолчанию")
            self._calibration = {
                "conveyor_speed": 18000,
                "conveyor_accel": 60000,
                "normal_steps": 9524,
            }
        return self._calibration

    # ---------- шаг ----------

    def step(self, on_progress: Callable[[str], None] | None = None) -> StepResult:
        if self.fault:
            return StepResult(False, self.last_step,
                              f"шаг заблокирован после ошибки: {self.fault}")
        try:
            self._ensure_connected()
            self.conveyor.move_step()
            self.conveyor.wait_stop(
                timeout=self.timeout,
                progress_callback=self._progress_adapter(on_progress),
            )
            if self.settle:
                time.sleep(self.settle)
            self.last_step = self._query_step()
            print(f"[ROI] Шаг подтверждён, STEP={self.last_step}")
            return StepResult(True, self.last_step,
                              f"STEP {self.last_step if self.last_step is not None else '—'}")
        except Exception as exc:                        # noqa: BLE001
            # Повтор шага после неизвестного состояния механики запрещён.
            self.fault = str(exc)
            print(f"[ROI] Ошибка шага конвейера: {exc}")
            return StepResult(False, self.last_step, str(exc))

    def _progress_adapter(self, on_progress):
        if on_progress is None:
            return None

        def callback(status: dict) -> None:
            parts = []
            if status.get("mov") is not None:
                parts.append(f"MOV={status['mov']}")
            if status.get("pos") is not None:
                parts.append(f"POS={status['pos']}")
            if status.get("step") is not None:
                parts.append(f"STEP={status['step']}")
            on_progress(" · ".join(parts) or "движение")

        return callback

    def _query_step(self) -> int | None:
        if self.transport is None:
            return None
        try:
            reply = self.transport.query("I2", delay=0.1)
        except Exception:                               # noqa: BLE001
            return None
        match = re.search(r"\bSTEP\s*=\s*(-?\d+)", reply or "", re.IGNORECASE)
        return int(match.group(1)) if match else None

    def close(self) -> None:
        if self.transport is None:
            return
        try:
            self.transport.send("G1")
        except Exception as exc:                        # noqa: BLE001
            print(f"[ROI] Не удалось остановить ленту: {exc}")
        try:
            self.transport.close()
        except Exception as exc:                        # noqa: BLE001
            print(f"[ROI] Не удалось закрыть порт: {exc}")
        self.transport = None
        self.conveyor = None

    def describe(self) -> str:
        if self.conveyor is None:
            return "COM (подключение при первом шаге)"
        return f"COM {self.port} · STEP={self.last_step}"


# ---------------------------------------------------------------------------
# Сеанс: файлы и манифест
# ---------------------------------------------------------------------------

def _read_image(path: Path) -> np.ndarray | None:
    """Прочитать изображение по любому пути (в т.ч. с кириллицей)."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:                                   # noqa: BLE001
        return None


def _write_image(path: Path, image: np.ndarray, quality: int = JPEG_QUALITY) -> None:
    """Атомарно записать JPEG по любому пути (cv2.imwrite ломается на кириллице)."""
    params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    ok, buffer = cv2.imencode(".jpg", image, params)
    if not ok or buffer is None:
        raise RuntimeError(f"Не удалось закодировать JPEG: {path}")
    _write_bytes(path, buffer.tobytes())


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _write_json(path: Path, payload) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    _write_bytes(path, text.encode("utf-8"))


class RoiSession:
    """Папка сеанса: пары кадров по кругам и манифест ``session.json``."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        root: str | Path,
        *,
        session_id: str | None = None,
        source_name: str = "camera",
        step_mode: str = "serial",
        mapping: dict | None = None,
        quality: int = JPEG_QUALITY,
    ):
        self.root = Path(root)
        self.session_id = session_id or datetime.now().strftime("roi_%Y%m%d_%H%M%S")
        self.folder = self.root / self.session_id
        suffix = 2
        while self.folder.exists():
            self.folder = self.root / f"{self.session_id}_{suffix}"
            suffix += 1
        self.session_id = self.folder.name
        self.folder.mkdir(parents=True, exist_ok=True)

        self.source_name = source_name
        self.step_mode = step_mode
        self.mapping = dict(mapping or {})
        self.quality = int(quality)
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.finished_at: str | None = None
        self.rounds: dict[int, dict] = {}
        self.steps_made = 0
        self.last_step: int | None = None
        self._write_manifest("OPEN")
        print(f"[ROI] Сеанс: {self.folder}")

    # ---------- сохранение ----------

    def save_shot(
        self,
        *,
        round_no: int,
        index: int,
        role: str,
        frame: np.ndarray,
        drawn: np.ndarray,
        roi: Roi,
        camera_id: int | None,
        conveyor_step: int | None,
    ) -> dict:
        height, width = frame.shape[:2]
        stem = f"{index:02d}_{role}"
        round_dir = self.folder / f"round_{round_no:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)

        raw_path = round_dir / f"{stem}.jpg"
        drawn_path = round_dir / f"{stem}_roi.jpg"
        meta_path = round_dir / f"{stem}.json"

        _write_image(raw_path, frame, self.quality)
        _write_image(drawn_path, drawn, self.quality)

        captured_at = datetime.now()
        meta = {
            "schema_version": self.SCHEMA_VERSION,
            "session_id": self.session_id,
            "round": round_no,
            "index": index,
            "role": role,
            "role_label": ROLE_LABELS.get(role, role),
            "camera_id": camera_id,
            "captured_at": captured_at.isoformat(timespec="seconds"),
            "captured_ts": round(captured_at.timestamp(), 3),
            "conveyor_step": conveyor_step,
            "source": self.source_name,
            "frame": {"file": raw_path.name, "width": width, "height": height},
            "drawn": drawn_path.name,
            "roi": roi.as_dict(width, height),
        }
        _write_json(meta_path, meta)

        record = {
            "round": round_no,
            "index": index,
            "role": role,
            "camera_id": camera_id,
            "captured_at": meta["captured_at"],
            "conveyor_step": conveyor_step,
            "roi_mode": roi.mode,
            "roi_bbox": meta["roi"]["bbox"],
            "roi_area_pct": meta["roi"]["area_pct"],
            "raw": f"round_{round_no:02d}/{raw_path.name}",
            "drawn": f"round_{round_no:02d}/{drawn_path.name}",
            "meta": f"round_{round_no:02d}/{meta_path.name}",
        }
        self._remember(record)
        self._write_manifest("OPEN")
        return {"meta": meta_path, "raw": raw_path, "drawn": drawn_path}

    def _remember(self, record: dict) -> None:
        bucket = self.rounds.setdefault(
            record["round"], {"round": record["round"], "shots": {}}
        )
        bucket["shots"][record["role"]] = record

    # ---------- итоги ----------

    def shots(self) -> list[dict]:
        result = []
        for round_no in sorted(self.rounds):
            bucket = self.rounds[round_no]["shots"]
            result.extend(bucket[role] for role in sorted(
                bucket, key=lambda key: bucket[key]["index"]
            ))
        return result

    def counts(self) -> dict:
        shots = self.shots()
        rounds = sorted(self.rounds)
        return {
            "rounds": len(rounds),
            "shots": len(shots),
            "last_round_shots": len(self.rounds[rounds[-1]]["shots"]) if rounds else 0,
        }

    def close(self) -> None:
        self.finished_at = datetime.now().isoformat(timespec="seconds")
        self._write_manifest("CLOSED")

    def _write_manifest(self, status: str) -> None:
        counts = self.counts()
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "session_id": self.session_id,
            "status": status,
            "started_at": self.started_at,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": self.finished_at,
            "source": self.source_name,
            "step_mode": self.step_mode,
            "camera_mapping": self.mapping,
            "totals": {
                "rounds": counts["rounds"],
                "shots": counts["shots"],
                "steps_made": self.steps_made,
                "last_step": self.last_step,
            },
            "rounds": [
                {
                    "round": round_no,
                    "shots": [
                        self.rounds[round_no]["shots"][role]
                        for role in sorted(
                            self.rounds[round_no]["shots"],
                            key=lambda key: self.rounds[round_no]["shots"][key]["index"],
                        )
                    ],
                }
                for round_no in sorted(self.rounds)
            ],
        }
        _write_json(self.folder / "session.json", payload)


# ---------------------------------------------------------------------------
# Состояния приложения
# ---------------------------------------------------------------------------

class Phase:
    READY = "READY"
    MARKUP = "MARKUP"
    ROUND_DONE = "ROUND_DONE"
    STEPPING = "STEPPING"
    FINISHED = "FINISHED"


@dataclass
class Button:
    """Кликабельная кнопка на канве (координаты канвы)."""

    action: str
    label: str
    kind: str = "primary"           # primary | secondary | ghost
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)

    def hit(self, x: int, y: int) -> bool:
        bx, by, bw, bh = self.rect
        return bx <= x < bx + bw and by <= y < by + bh


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

class RoiApp:
    """Окно OpenCV: кнопка «Начать», обводка зоны, сохранение, шаг ленты."""

    def __init__(
        self,
        *,
        mapping: dict,
        source: CameraSource,
        step_driver: StepDriver,
        session: RoiSession,
        scale: float | None = None,
        auto_step: bool = False,
    ):
        self.mapping = dict(mapping)
        self.source = source
        self.step_driver = step_driver
        self.session = session
        self.auto_step = auto_step
        self.text = TextRenderer()

        self.phase = Phase.READY
        self.mode = "rect"
        self.cursor = 0
        self.round_no = 0

        self.frames: dict[str, np.ndarray] = {}
        self.rois: dict[str, Roi] = {}
        self.saved: dict[str, bool] = {}
        self.errors: dict[str, str] = {}

        self.buttons: list[Button] = []
        self.mouse = (-1, -1)
        self.dirty = True
        self.notice = ""
        self.notice_until = 0.0
        self.step_status = ""
        self.conveyor_step: int | None = None
        self.stepping = False

        self._drag_origin: tuple[int, int] | None = None
        self._dragging = False
        self._running = True
        self._can_present = True
        self._frame_base_cache: tuple | None = None
        self._panel_cache: tuple | None = None

        self.scale, self.canvas_size = self._compute_geometry(scale)
        self.frame_size: tuple[int, int] | None = None

    # ---------- геометрия окна ----------

    def _compute_geometry(self, scale: float | None) -> tuple[float, tuple[int, int]]:
        frame_w, frame_h = EXPECTED_FRAME_SIZE
        if scale is None:
            screen_w, screen_h = screen_size()
            available_w = max(640, screen_w - PANEL_WIDTH - 120)
            available_h = max(360, screen_h - 160)
            scale = min(1.0, available_w / frame_w, available_h / frame_h)
            scale = max(0.4, round(scale, 2))
        scale = max(0.2, min(3.0, float(scale)))
        display_w, display_h = int(frame_w * scale), int(frame_h * scale)
        canvas_h = max(display_h, MIN_CANVAS_HEIGHT)
        return scale, (display_w + PANEL_WIDTH, canvas_h)

    @property
    def display_size(self) -> tuple[int, int]:
        return (self.canvas_size[0] - PANEL_WIDTH, self.canvas_size[1])

    def _ensure_frame_geometry(self, frame: np.ndarray) -> None:
        """Пересчитать масштаб, если камера отдаёт другое разрешение."""
        height, width = frame.shape[:2]
        if self.frame_size == (width, height):
            return
        first = self.frame_size is None
        self.frame_size = (width, height)
        if first and (width, height) == EXPECTED_FRAME_SIZE:
            return
        screen_w, screen_h = screen_size()
        available_w = max(480, screen_w - PANEL_WIDTH - 120)
        available_h = max(320, screen_h - 160)
        scale = min(1.0, available_w / width, available_h / height)
        self.scale = max(0.2, round(scale, 3))
        display_w, display_h = int(width * self.scale), int(height * self.scale)
        self.canvas_size = (display_w + PANEL_WIDTH,
                            max(display_h, MIN_CANVAS_HEIGHT))
        self._frame_base_cache = None
        if not first:
            self._resize_window()

    def _to_image(self, x: int, y: int) -> tuple[int, int]:
        if self.frame_size is None:
            return 0, 0
        width, height = self.frame_size
        image_x = int(x / self.scale)
        image_y = int(y / self.scale)
        return (max(0, min(width - 1, image_x)),
                max(0, min(height - 1, image_y)))

    def _in_frame(self, x: int, y: int) -> bool:
        display_w, display_h = self.display_size
        return 0 <= x < display_w and 0 <= y < display_h

    # ---------- запуск ----------

    def run(self) -> None:
        try:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        except cv2.error as exc:
            raise RuntimeError(
                "OpenCV собран без поддержки окон (headless). "
                "Установите пакет opencv-python вместо opencv-python-headless "
                "или запустите приложение на машине с графикой. "
                f"Подробности: {exc}"
            ) from exc
        cv2.setMouseCallback(WINDOW_NAME, self._on_mouse)
        self._resize_window()
        print("[ROI] Окно открыто. ПРОБЕЛ — режим, ENTER — сохранить, ESC — выход.")
        try:
            self._loop()
        finally:
            self._shutdown()

    def _resize_window(self) -> None:
        try:
            cv2.resizeWindow(WINDOW_NAME, *self.canvas_size)
        except Exception:                               # noqa: BLE001
            pass

    def _loop(self) -> None:
        while self._running:
            if self.dirty:
                self._present()
                self.dirty = False
            read_key = getattr(cv2, "waitKeyEx", cv2.waitKey)
            key = read_key(20)
            if key == -1:
                if not self._window_alive():
                    self._running = False
                continue
            if self._expire_notice():
                self.dirty = True
            self._handle_key(key)

    def _present(self) -> None:
        """Показать текущий кадр; при сбое GUI работа продолжается."""
        if not self._can_present:
            return
        try:
            cv2.imshow(WINDOW_NAME, self._compose())
        except Exception as exc:                        # noqa: BLE001
            self._can_present = False
            print(f"[ROI] Отрисовка окна недоступна: {exc}")

    def _window_alive(self) -> bool:
        try:
            return cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) >= 1
        except Exception:                               # noqa: BLE001
            return False

    def _shutdown(self) -> None:
        if self.phase != Phase.FINISHED:
            self._finish_session(silent=True)
        self.source.close()
        self.step_driver.close()
        try:
            cv2.destroyAllWindows()
        except Exception:                               # noqa: BLE001
            pass
        self._print_summary()

    # ---------- клавиши ----------

    def _handle_key(self, key: int) -> None:
        code = key & 0xFF
        special = key
        if code in (27, ord("q"), ord("Q")):
            self._running = False
        elif code in (13, 10, ord("s"), ord("S")):
            self._on_enter()
        elif code in (32, ord("m"), ord("M"), 9):
            self._toggle_mode()
        elif code in (ord("1"), ord("o"), ord("O")):
            self._set_mode("rect")
        elif code in (ord("2"), ord("p"), ord("P")):
            self._set_mode("poly")
        elif code in (ord("r"), ord("R"), 8):
            self._reset_roi()
        elif code in (ord("c"), ord("C")):
            self._recapture()
        elif code in (ord("d"), ord("D"), ord("]")) or special in ARROW_RIGHT:
            self._move_cursor(+1)
        elif code in (ord("a"), ord("A"), ord("[")) or special in ARROW_LEFT:
            self._move_cursor(-1)
        elif code in (ord("n"), ord("N")):
            self._continue_without_step()
        elif code in (ord("f"), ord("F")):
            self._finish_session()

    def _on_enter(self) -> None:
        if self.phase == Phase.READY:
            self.start()
        elif self.phase == Phase.MARKUP:
            self.save_current()
        elif self.phase == Phase.ROUND_DONE:
            self.make_step()

    # ---------- действия ----------

    def start(self) -> None:
        notes = self.source.open()
        if notes:
            self._notify(f"не все камеры доступны: {len(notes)}")
        self.round_no = 1
        self.phase = Phase.MARKUP
        self._reset_round()
        print(f"[ROI] Старт. Круг 1, камеры: {', '.join(ROLE_ORDER)}")
        self._ensure_frame(ROLE_ORDER[self.cursor])

    def _reset_round(self) -> None:
        self.cursor = 0
        self.frames.clear()
        self.rois.clear()
        self.saved = {role: False for role in ROLE_ORDER}
        self.errors.clear()
        self._drag_origin = None
        self._dragging = False
        self._frame_base_cache = None
        self._panel_cache = None
        self.dirty = True

    @property
    def current_role(self) -> str:
        return ROLE_ORDER[self.cursor]

    def _ensure_frame(self, role: str) -> np.ndarray | None:
        frame = self.frames.get(role)
        if frame is not None:
            return frame
        try:
            print(f"[ROI] Кадр {role}…")
            frame = self.source.capture(role)
        except Exception as exc:                        # noqa: BLE001
            self.errors[role] = str(exc)
            print(f"[ROI] Ошибка кадра {role}: {exc}")
            self._notify(f"{role}: {exc}")
            self.dirty = True
            return None
        self.errors.pop(role, None)
        self.frames[role] = frame
        self._ensure_frame_geometry(frame)
        self.dirty = True
        return frame

    def _move_cursor(self, delta: int) -> None:
        if self.phase not in (Phase.MARKUP,):
            return
        self.cursor = (self.cursor + delta) % len(ROLE_ORDER)
        self._drag_origin = None
        self._dragging = False
        print(f"[ROI] Камера {self.current_role} "
              f"({self.cursor + 1}/{len(ROLE_ORDER)})")
        self._ensure_frame(self.current_role)

    def _set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        roi = self.rois.get(self.current_role)
        if roi is not None:
            self.rois[self.current_role] = (
                roi.to_polygon() if mode == "poly" else roi.to_rect()
            )
        self._drag_origin = None
        self._dragging = False
        print(f"[ROI] Режим: {'полигон' if mode == 'poly' else 'прямоугольник'}")
        self.dirty = True

    def _toggle_mode(self) -> None:
        self._set_mode("poly" if self.mode == "rect" else "rect")

    def _reset_roi(self) -> None:
        if self.phase != Phase.MARKUP:
            return
        self.rois.pop(self.current_role, None)
        self._drag_origin = None
        self._dragging = False
        self._notify("зона сброшена")
        print(f"[ROI] Зона {self.current_role} сброшена")

    def _recapture(self) -> None:
        if self.phase != Phase.MARKUP:
            return
        role = self.current_role
        self.frames.pop(role, None)
        self.rois.pop(role, None)
        self.saved[role] = False
        self._frame_base_cache = None
        self._notify(f"кадр {role} снят заново")
        self._ensure_frame(role)

    def save_current(self) -> None:
        role = self.current_role
        frame = self.frames.get(role)
        if frame is None:
            self._notify("нет кадра: нажмите C")
            return
        roi = self.rois.get(role)
        if roi is None or not roi.is_valid():
            self._notify(ui("no_zone").lower())
            print("[ROI] Зона не задана — сохранение отменено")
            return

        roi.clamp(frame.shape[1], frame.shape[0])
        if roi.mode == "poly":
            roi.closed = True
        drawn = frame.copy()
        self._paint_roi(drawn, roi, 1.0, label=self._image_label(role))

        try:
            paths = self.session.save_shot(
                round_no=self.round_no,
                index=self.cursor + 1,
                role=role,
                frame=frame,
                drawn=drawn,
                roi=roi,
                camera_id=self.mapping.get(role),
                conveyor_step=self.conveyor_step,
            )
        except Exception as exc:                        # noqa: BLE001
            self._notify(f"ошибка записи: {exc}")
            print(f"[ROI] Ошибка сохранения {role}: {exc}")
            return

        self.saved[role] = True
        print(f"[ROI] Сохранено: круг {self.round_no}, "
              f"{self.cursor + 1}/{len(ROLE_ORDER)} {role} → {paths['raw'].name}")
        self._notify(f"сохранено: {role}")

        if all(self.saved.values()):
            self._close_round()
        else:
            self._advance_to_next_unsaved()
        self.dirty = True

    def _advance_to_next_unsaved(self) -> None:
        for offset in range(1, len(ROLE_ORDER) + 1):
            index = (self.cursor + offset) % len(ROLE_ORDER)
            role = ROLE_ORDER[index]
            if not self.saved.get(role):
                self.cursor = index
                self._ensure_frame(role)
                return

    def _close_round(self) -> None:
        print(f"[ROI] Круг {self.round_no} завершён: 7/7 кадров сохранено.")
        if self.step_driver.mode == "none":
            self._start_next_round("шаг отключён")
            return
        self.phase = Phase.ROUND_DONE
        if self.auto_step:
            self.make_step()
        self.dirty = True

    def make_step(self) -> None:
        if self.phase not in (Phase.ROUND_DONE, Phase.MARKUP):
            return
        self.phase = Phase.STEPPING
        self.stepping = True
        self.step_status = ""
        self.dirty = True
        print("[ROI] Шаг конвейера…")

        result = self.step_driver.step(on_progress=self._on_step_progress)
        self.stepping = False
        if not result.ok:
            self.phase = Phase.ROUND_DONE
            self._notify("ШАГ НЕ ПОДТВЕРЖДЁН — проверьте линию")
            print(f"[ROI] Шаг не выполнен: {result.message}")
            self.dirty = True
            return

        self.conveyor_step = result.step if result.step is not None else self.conveyor_step
        self.session.steps_made += 1
        self.session.last_step = self.conveyor_step
        self._start_next_round(result.message)

    def _on_step_progress(self, message: str) -> None:
        self.step_status = message
        self.dirty = True
        self._present_now()

    def _present_now(self) -> None:
        """Показать кадр немедленно (прогресс шага), не роняя шаг при сбое GUI."""
        if not self._can_present:
            return
        try:
            cv2.imshow(WINDOW_NAME, self._compose())
            cv2.waitKey(1)
        except Exception as exc:                        # noqa: BLE001
            self._can_present = False
            print(f"[ROI] Немедленная отрисовка недоступна: {exc}")

    def _continue_without_step(self) -> None:
        if self.phase != Phase.ROUND_DONE:
            return
        self._start_next_round("без шага")

    def _start_next_round(self, reason: str) -> None:
        self.round_no += 1
        self.source.advance()
        self.phase = Phase.MARKUP
        self._reset_round()
        print(f"[ROI] Круг {self.round_no} ({reason})")
        self._notify(f"круг {self.round_no}")
        self._ensure_frame(ROLE_ORDER[0])

    def _finish_session(self, silent: bool = False) -> None:
        if self.phase == Phase.FINISHED:
            return
        self.phase = Phase.FINISHED
        try:
            self.session.close()
        except Exception as exc:                        # noqa: BLE001
            print(f"[ROI] Не удалось записать session.json: {exc}")
        if not silent:
            self._print_summary()
        self.dirty = True

    def _print_summary(self) -> None:
        counts = self.session.counts()
        print("")
        print("[ROI] Сеанс завершён")
        print(f"[ROI] Папка:   {self.session.folder}")
        print(f"[ROI] Кругов:  {counts['rounds']}")
        print(f"[ROI] Кадров:  {counts['shots']}")
        print(f"[ROI] Шагов:   {self.session.steps_made}")

    # ---------- уведомления ----------

    def _notify(self, message: str, seconds: float = 2.5) -> None:
        self.notice = message
        self.notice_until = time.monotonic() + seconds
        self.dirty = True

    def _expire_notice(self) -> bool:
        if self.notice and time.monotonic() > self.notice_until:
            self.notice = ""
            return True
        return False

    # ---------- мышь ----------

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param) -> None:
        self.mouse = (x, y)
        self.dirty = True

        if event == cv2.EVENT_LBUTTONDOWN:
            if self._click_button(x, y):
                return
            self._start_draw(x, y)
        elif event == cv2.EVENT_MOUSEMOVE:
            self._drag_to(x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            self._finish_draw(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            self._undo_point()
        elif event == cv2.EVENT_LBUTTONDBLCLK:
            self._close_polygon()

    def _click_button(self, x: int, y: int) -> bool:
        for button in self.buttons:
            if not button.hit(x, y):
                continue
            action = button.action
            if action == "start":
                self.start()
            elif action == "step":
                self.make_step()
            elif action == "skip":
                self._continue_without_step()
            elif action == "finish":
                self._finish_session()
            elif action == "exit":
                self._running = False
            return True
        return False

    def _start_draw(self, x: int, y: int) -> None:
        if self.phase != Phase.MARKUP or not self._in_frame(x, y):
            return
        if self.frames.get(self.current_role) is None:
            self._notify("нет кадра: нажмите C")
            return
        point = self._to_image(x, y)
        role = self.current_role

        if self.mode == "rect":
            self._drag_origin = point
            self._dragging = True
            self.rois[role] = Roi.rect(point, point)
            return

        roi = self.rois.get(role)
        if roi is None or roi.mode != "poly" or roi.closed:
            roi = Roi("poly", [], False)
            self.rois[role] = roi
        if len(roi.points) >= 3 and _distance(roi.points[0], point) <= 14:
            roi.closed = True
        elif roi.points and _distance(roi.points[-1], point) <= 6:
            return                      # тот же клик, повторно пришедший после dblclick
        else:
            roi.points.append(point)
        self.dirty = True

    def _drag_to(self, x: int, y: int) -> None:
        if self.phase != Phase.MARKUP:
            return
        if self.mode == "rect" and self._dragging and self._drag_origin:
            if not self._in_frame(x, y):
                return
            point = self._to_image(x, y)
            self.rois[self.current_role] = Roi.rect(self._drag_origin, point)

    def _finish_draw(self, x: int, y: int) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self._drag_origin = None
        roi = self.rois.get(self.current_role)
        if roi is None or not roi.is_valid():
            self.rois.pop(self.current_role, None)
            self._notify("зона слишком мала")
        self.dirty = True

    def _undo_point(self) -> None:
        if self.phase != Phase.MARKUP or self.mode != "poly":
            return
        roi = self.rois.get(self.current_role)
        if roi is None:
            return
        if roi.points:
            roi.points.pop()
        roi.closed = False
        if not roi.points:
            self.rois.pop(self.current_role, None)
        self.dirty = True

    def _close_polygon(self) -> None:
        if self.phase != Phase.MARKUP or self.mode != "poly":
            return
        roi = self.rois.get(self.current_role)
        if roi is not None and len(roi.points) >= 3:
            roi.closed = True
            self.dirty = True

    # ---------- отрисовка ----------

    def _paint_roi(
        self,
        image: np.ndarray,
        roi: Roi,
        scale: float,
        label: str | None = None,
        color: tuple = COL_ACCENT,
    ) -> None:
        """Затемнить всё вне зоны, обвести её и подписать."""
        height, width = image.shape[:2]
        points = np.array(
            [[int(round(x * scale)), int(round(y * scale))] for x, y in roi.points],
            dtype=np.int32,
        )
        if len(points) < 3:
            return

        mask = np.zeros((height, width), np.uint8)
        cv2.fillPoly(mask, [points], 255)
        outside = mask == 0

        darkened = cv2.convertScaleAbs(image, alpha=0.42, beta=0)
        image[outside] = darkened[outside]

        tint = np.zeros_like(image)
        tint[:] = color
        blended = cv2.addWeighted(image, 0.9, tint, 0.1, 0)
        image[mask > 0] = blended[mask > 0]

        cv2.polylines(image, [points], True, color, 2, cv2.LINE_AA)
        radius = 4 if scale >= 1 else 3
        for point in points:
            cv2.circle(image, (int(point[0]), int(point[1])), radius + 2,
                       COL_BG, -1, cv2.LINE_AA)
            cv2.circle(image, (int(point[0]), int(point[1])), radius,
                       color, -1, cv2.LINE_AA)

        if label:
            self._draw_label(image, label, (points[0][0], points[0][1]), scale)

        if roi.mode == "poly" and not roi.closed and self.mouse[0] >= 0:
            cursor = (int(self.mouse[0]), int(self.mouse[1]))
            if self._in_frame(*cursor):
                self._dashed_line(image, points[-1], cursor, color)

    def _draw_label(self, image, text: str, xy: tuple[int, int], scale: float) -> None:
        size = max(12, int(15 * max(0.6, scale)))
        width, height = self.text.measure(text, size, True)
        pad = max(4, int(6 * scale))
        box_w = min(image.shape[1] - 2, width + pad * 2)
        box_h = height + pad * 2
        x = max(0, min(image.shape[1] - box_w, int(xy[0])))
        y = int(xy[1]) - box_h - pad
        if y < 4:
            # сверху нет места (зона у края кадра) — подпись внутри зоны
            y = min(image.shape[0] - box_h - 2, int(xy[1]) + pad)
        cv2.rectangle(image, (x, y), (x + box_w, y + box_h), COL_BG, -1)
        cv2.rectangle(image, (x, y), (x + box_w, y + box_h), COL_ACCENT, 1)
        self.text.draw(image, TextItem(text, (x + pad, y + pad), size,
                                       COL_TEXT, True))

    @staticmethod
    def _dashed_line(image, start, end, color, dash: int = 9, gap: int = 7) -> None:
        x1, y1 = int(start[0]), int(start[1])
        x2, y2 = int(end[0]), int(end[1])
        length = max(1, int(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5))
        step = dash + gap
        for offset in range(0, length, step):
            a = (x1 + int((x2 - x1) * offset / length),
                 y1 + int((y2 - y1) * offset / length))
            b_offset = min(length, offset + dash)
            b = (x1 + int((x2 - x1) * b_offset / length),
                 y1 + int((y2 - y1) * b_offset / length))
            cv2.line(image, a, b, color, 1, cv2.LINE_AA)

    def _image_label(self, role: str) -> str:
        camera_id = self.mapping.get(role)
        suffix = f" · id {camera_id}" if camera_id is not None else ""
        return f"{self.round_no:02d} · {role}{suffix}"

    # ---------- компоновка канвы ----------

    def _compose(self) -> np.ndarray:
        width, height = self.canvas_size
        canvas = np.zeros((height, width, 3), np.uint8)
        canvas[:] = COL_BG
        self.buttons = []

        self._draw_image_area(canvas)
        self._draw_panel(canvas)

        if self.phase == Phase.READY:
            self._draw_ready(canvas)
        elif self.phase == Phase.ROUND_DONE:
            self._draw_round_done(canvas)
        elif self.phase == Phase.STEPPING:
            self._draw_stepping(canvas)
        elif self.phase == Phase.FINISHED:
            self._draw_finished(canvas)

        if self.notice:
            self._draw_banner(canvas, self.notice, COL_ACCENT)
        return canvas

    def _draw_image_area(self, canvas) -> None:
        display_w, display_h = self.display_size
        frame = self.frames.get(self.current_role)
        if frame is None:
            cv2.rectangle(canvas, (0, 0), (display_w, display_h), COL_PANEL, -1)
            if self.phase in (Phase.READY, Phase.ROUND_DONE):
                self._draw_backdrop(canvas, display_w, display_h)
                return
            message = self.errors.get(self.current_role) or ui("no_frame")
            self.text.draw_many(canvas, [
                TextItem(ui("no_frame"), (display_w // 2, display_h // 2 - 18),
                         26, COL_TEXT_MUTED, True, "cm"),
                TextItem(message[:110], (display_w // 2, display_h // 2 + 20),
                         15, COL_TEXT_MUTED, False, "cm"),
            ])
            return

        cache_key = (id(frame), display_w, display_h)
        if self._frame_base_cache is None or self._frame_base_cache[0] != cache_key:
            base = cv2.resize(frame, (display_w, display_h),
                              interpolation=cv2.INTER_AREA)
            self._frame_base_cache = (cache_key, base)
        canvas[:display_h, :display_w] = self._frame_base_cache[1]

        roi = self.rois.get(self.current_role)
        if roi is not None and roi.is_valid():
            self._paint_roi(canvas[:display_h, :display_w], roi, self.scale,
                            label=self._image_label(self.current_role))

        self._draw_corner_badge(canvas, self.current_role)
        if self.mode == "poly" and self.phase == Phase.MARKUP:
            hint = ui("poly_hint")
        elif self.phase == Phase.MARKUP:
            hint = ui("rect_hint")
        else:
            hint = ""
        if hint:
            self.text.draw(canvas, TextItem(hint, (16, display_h - 16), 15,
                                            COL_TEXT_DIM, False, "lb"))

    @staticmethod
    def _draw_backdrop(canvas, display_w: int, display_h: int) -> None:
        """Спокойная сетка вместо пустого экрана до первого кадра."""
        step = 64
        for x in range(0, display_w, step):
            cv2.line(canvas, (x, 0), (x, display_h), COL_PANEL_RAISED, 1)
        for y in range(0, display_h, step):
            cv2.line(canvas, (0, y), (display_w, y), COL_PANEL_RAISED, 1)

    def _draw_corner_badge(self, canvas, role: str) -> None:
        display_w, _ = self.display_size
        label = ROLE_LABELS.get(role, role)
        camera_id = self.mapping.get(role)
        suffix = f" · камера {camera_id}" if camera_id is not None else ""
        text = f"{role} · {label}{suffix}"
        width, height = self.text.measure(text, 17, True)
        box = (0, 0, min(display_w, width + 32), height + 20)
        cv2.rectangle(canvas, (box[0], box[1]), (box[2], box[3]), COL_BG, -1)
        cv2.rectangle(canvas, (box[0], box[1]), (box[2], box[3]), COL_BORDER, 1)
        self.text.draw(canvas, TextItem(text, (16, 10), 17, COL_TEXT, True))

    # ---------- панель ----------

    def _panel_signature(self) -> tuple:
        roi = self.rois.get(self.current_role)
        geometry = (roi.mode, tuple(roi.points), roi.closed) if roi else None
        counts = self.session.counts()
        return (
            self.phase, self.round_no, self.cursor, self.mode, geometry,
            tuple(self.saved.get(role, False) for role in ROLE_ORDER),
            self.step_status, self.conveyor_step, counts["shots"],
            self.step_driver.describe(), self.session.session_id, self.frame_size,
        )

    def _draw_panel(self, canvas) -> None:
        display_w, display_h = self.display_size
        signature = self._panel_signature()
        if self._panel_cache is None or self._panel_cache[0] != signature:
            panel = np.zeros((display_h, PANEL_WIDTH, 3), np.uint8)
            panel[:] = COL_PANEL
            self._paint_panel(panel, display_h)
            self._panel_cache = (signature, panel)
        canvas[:display_h, display_w:display_w + PANEL_WIDTH] = self._panel_cache[1]
        cv2.line(canvas, (display_w, 0), (display_w, display_h), COL_BORDER_STRONG, 1)

    def _paint_panel(self, panel: np.ndarray, height: int) -> None:
        x = PANEL_PAD
        content_w = PANEL_WIDTH - PANEL_PAD * 2
        items: list[TextItem] = []
        y = 22

        items.append(TextItem(ui("title"), (x, y), 20, COL_TEXT, True,
                              max_width=content_w))
        y += 34
        cv2.line(panel, (x, y), (x + content_w, y), COL_BORDER, 1)
        y += 16

        rows = [
            (ui("session"), self.session.session_id),
            (ui("round"), str(self.round_no) if self.round_no else "—"),
            (ui("shot"), f"{self.cursor + 1} / {len(ROLE_ORDER)}"),
            (ui("camera"), self.current_role),
            (ui("mode"), ui("poly") if self.mode == "poly" else ui("rect")),
        ]
        for label, value in rows:
            items.append(TextItem(label, (x, y), 13, COL_TEXT_MUTED))
            items.append(TextItem(value, (x + 108, y), 15, COL_TEXT, True,
                                  max_width=content_w - 108))
            y += 26

        y += 4
        cv2.line(panel, (x, y), (x + content_w, y), COL_BORDER, 1)
        y += 14

        # прогресс круга
        items.append(TextItem(ui("round"), (x, y), 13, COL_TEXT_MUTED))
        y += 22
        segment_gap = 4
        segment_w = (content_w - segment_gap * (len(ROLE_ORDER) - 1)) // len(ROLE_ORDER)
        for index, role in enumerate(ROLE_ORDER):
            sx = x + index * (segment_w + segment_gap)
            color = COL_OK if self.saved.get(role) else (
                COL_ACCENT if index == self.cursor else COL_BORDER)
            cv2.rectangle(panel, (sx, y), (sx + segment_w, y + 8), color, -1)
        self.text.draw_many(panel, items)
        items = []
        y += 20

        roi = self.rois.get(self.current_role)
        if roi is not None and roi.is_valid():
            bx, by, bw, bh = roi.bbox
            frame_w, frame_h = self.frame_size or EXPECTED_FRAME_SIZE
            area_pct = roi.area / max(1, frame_w * frame_h) * 100.0
            items.extend([
                TextItem(ui("zone"), (x, y), 13, COL_TEXT_MUTED),
                TextItem(f"x {bx}   y {by}", (x + 108, y), 15, COL_TEXT, True),
            ])
            y += 24
            items.extend([
                TextItem(f"w {bw}   h {bh}", (x + 108, y), 15, COL_TEXT),
            ])
            y += 24
            items.append(TextItem(f"{ui('area')}: {area_pct:.2f} %",
                                  (x + 108, y), 15, COL_TEXT_DIM))
            y += 26
        else:
            items.append(TextItem(ui("no_zone"), (x, y), 13, COL_WARN,
                                  max_width=content_w))
            y += 28

        counts = self.session.counts()
        step_text = "—" if self.conveyor_step is None else f"STEP={self.conveyor_step}"
        items.extend([
            TextItem(ui("saved"), (x, y), 13, COL_TEXT_MUTED),
            TextItem(f"{counts['shots']} · {counts['rounds']} кр.",
                     (x + 108, y), 15, COL_TEXT, True),
        ])
        y += 24
        items.extend([
            TextItem(ui("step"), (x, y), 13, COL_TEXT_MUTED),
            TextItem(step_text, (x + 108, y), 15, COL_TEXT, True,
                     max_width=content_w - 108),
        ])
        y += 28

        # Блок подсказок прижат к низу и укорачивается при нехватке высоты,
        # чтобы не наезжать на данные зоны и счётчики.
        hints = [
            ui("keys_draw") if self.mode == "rect" else ui("keys_point"),
            ui("keys_mode"),
            ui("keys_save"),
            ui("keys_nav"),
            ui("keys_reset"),
            ui("keys_finish"),
        ]
        line_h = 22
        available = height - (y + 16) - 24
        max_hints = max(0, (available - 34) // line_h)
        if max_hints >= 2:
            hints = hints[:max_hints]
            hint_y = height - 24 - len(hints) * line_h
            cv2.line(panel, (x, hint_y - 14), (x + content_w, hint_y - 14),
                     COL_BORDER, 1)
            items.append(TextItem(ui("controls"), (x, hint_y - 34), 13,
                                  COL_TEXT_MUTED))
            for index, hint in enumerate(hints):
                items.append(TextItem(hint, (x, hint_y + index * line_h), 14,
                                      COL_TEXT_DIM, max_width=content_w))
        self.text.draw_many(panel, items)

    # ---------- оверлеи ----------

    def _overlay_card(
        self,
        canvas,
        title: str,
        lines: list[str],
        buttons: list[Button],
        accent: tuple = COL_ACCENT,
        subtitle: str = "",
    ) -> None:
        # Карточка центрируется по области изображения, чтобы панель
        # с параметрами оставалась читаемой.
        area_w, area_h = self.display_size
        card_w = max(420, min(area_w - 80, 780))
        card_h = 150 + len(lines) * 30 + 70
        x0 = (area_w - card_w) // 2
        y0 = max(16, (area_h - card_h) // 2)

        dimmed = cv2.convertScaleAbs(canvas, alpha=0.32, beta=0)
        canvas[:area_h, :area_w, :] = dimmed[:area_h, :area_w, :]
        cv2.rectangle(canvas, (x0, y0), (x0 + card_w, y0 + card_h),
                      COL_PANEL_RAISED, -1)
        cv2.rectangle(canvas, (x0, y0), (x0 + card_w, y0 + card_h),
                      COL_BORDER_STRONG, 1)
        cv2.rectangle(canvas, (x0, y0), (x0 + card_w, y0 + 4), accent, -1)

        items = [TextItem(title, (x0 + 30, y0 + 28), 24, COL_TEXT, True)]
        y = y0 + 76
        if subtitle:
            items.append(TextItem(subtitle, (x0 + 30, y), 16, COL_TEXT_DIM))
            y += 32
        for line in lines:
            items.append(TextItem(line, (x0 + 30, y), 15, COL_TEXT_DIM))
            y += 30
        self.text.draw_many(canvas, items)

        button_y = y0 + card_h - 68
        button_x = x0 + 30
        for button in buttons:
            label_w, _ = self.text.measure(button.label, 16, True)
            button_w = max(150, label_w + 48)
            button.rect = (button_x, button_y, button_w, 46)
            self._draw_button(canvas, button)
            button_x += button_w + 14
            self.buttons.append(button)

    def _draw_button(self, canvas, button: Button) -> None:
        x, y, w, h = button.rect
        hovered = button.hit(*self.mouse)
        if button.kind == "primary":
            fill = COL_ACCENT if not hovered else (185, 173, 140)
            text_color = COL_BG
            border = fill
        elif button.kind == "secondary":
            fill = COL_PANEL if not hovered else COL_PANEL_RAISED
            text_color = COL_ACCENT
            border = COL_ACCENT
        else:
            fill = COL_PANEL if not hovered else COL_PANEL_RAISED
            text_color = COL_TEXT_DIM
            border = COL_BORDER
        cv2.rectangle(canvas, (x, y), (x + w, y + h), fill, -1)
        cv2.rectangle(canvas, (x, y), (x + w, y + h), border, 1)
        self.text.draw(canvas, TextItem(button.label, (x + w // 2, y + h // 2),
                                        16, text_color, True, "cm"))

    def _draw_ready(self, canvas) -> None:
        display_w, display_h = self.display_size
        self.text.draw_many(canvas, [
            TextItem(ui("title"), (display_w // 2, display_h // 2 - 120),
                     34, COL_TEXT, True, "cm"),
            TextItem(ui("press_start_hint"), (display_w // 2, display_h // 2 - 74),
                     17, COL_TEXT_DIM, False, "cm"),
            TextItem(self.session.folder.as_posix(), (display_w // 2,
                                                      display_h // 2 - 44),
                     14, COL_TEXT_MUTED, False, "cm"),
            TextItem(f"{self.source.describe()} · {self.step_driver.describe()}",
                     (display_w // 2, display_h // 2 - 20), 14, COL_TEXT_MUTED,
                     False, "cm"),
        ])
        button_w = 260
        button = Button("start", ui("start"), "primary",
                        ((display_w - button_w) // 2, display_h // 2 + 18,
                         button_w, 58))
        self._draw_button(canvas, button)
        self.buttons.append(button)
        self.text.draw_many(canvas, [
            TextItem(ui("keys_finish"), (display_w // 2, display_h - 34),
                     14, COL_TEXT_MUTED, False, "cm"),
        ])

    def _draw_round_done(self, canvas) -> None:
        counts = self.session.counts()
        lines = [
            ui("round_done_text"),
            ui("round_done_hint"),
            f"сохранено кадров: {counts['shots']} · кругов: {counts['rounds']}"
            if _HAVE_PIL else f"saved {counts['shots']} frames",
        ]
        footer = "" if self.step_driver.mode != "none" else "режим: без шага"
        if self.step_driver.fault:
            footer = f"ошибка: {self.step_driver.fault}"[:120]
        self._overlay_card(
            canvas,
            f"{ui('round_done')} · {self.round_no}",
            lines,
            [
                Button("step", ui("make_step"), "primary"),
                Button("skip", ui("without_step"), "secondary"),
                Button("finish", ui("finish"), "ghost"),
            ],
            accent=COL_OK,
            subtitle=footer,
        )

    def _draw_stepping(self, canvas) -> None:
        lines = [ui("stepping_hint"), self.step_status or "…"]
        self._overlay_card(canvas, ui("stepping"), lines, [], accent=COL_WARN)

    def _draw_finished(self, canvas) -> None:
        counts = self.session.counts()
        lines = [
            f"папка: {self.session.folder.as_posix()}",
            f"кругов: {counts['rounds']} · кадров: {counts['shots']} "
            f"· шагов: {self.session.steps_made}",
            "session.json записан" if _HAVE_PIL else "session.json written",
        ]
        self._overlay_card(
            canvas, ui("finished"), lines,
            [Button("exit", ui("exit"), "primary")], accent=COL_OK,
        )

    def _draw_banner(self, canvas, text: str, color: tuple) -> None:
        display_w, display_h = self.display_size
        width, height = self.text.measure(text, 15, True)
        box_w = min(display_w - 32, width + 36)
        x0, y0 = 16, display_h - 62
        cv2.rectangle(canvas, (x0, y0), (x0 + box_w, y0 + 34), COL_BG, -1)
        cv2.rectangle(canvas, (x0, y0), (x0 + box_w, y0 + 34), color, 1)
        self.text.draw(canvas, TextItem(text, (x0 + 14, y0 + 17), 15, color,
                                        True, "lm", max_width=box_w - 28))


# ---------------------------------------------------------------------------
# Вспомогательные функции окружения
# ---------------------------------------------------------------------------

def screen_size() -> tuple[int, int]:
    """Размер экрана: DPI-aware на Windows, иначе tkinter или 1920x1080."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        except Exception:                               # noqa: BLE001
            pass
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        size = (int(root.winfo_screenwidth()), int(root.winfo_screenheight()))
        root.destroy()
        return size
    except Exception:                                   # noqa: BLE001
        return 1920, 1080


def load_mapping(path: str, required: bool) -> dict:
    """Прочитать camera_mapping.json; при отсутствии вернуть пустой словарь."""
    try:
        with open(path, encoding="utf-8") as stream:
            mapping = json.load(stream)
    except FileNotFoundError:
        if required:
            raise RuntimeError(f"{path} не найден — запустите калибровку камер")
        print(f"[ROI] {path} не найден: индексы камер неизвестны")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ошибка чтения {path}: {exc}") from exc
    if not isinstance(mapping, dict):
        raise RuntimeError(f"{path} должен содержать объект")
    missing = [role for role in ROLE_ORDER if role not in mapping]
    if missing and required:
        raise RuntimeError(f"{path}: нет ролей {', '.join(missing)}")
    return {role: mapping[role] for role in ROLE_ORDER if role in mapping}


def build_source(args, mapping: dict) -> CameraSource:
    if args.source == "synthetic":
        return SyntheticCameraSource(mapping, seed=args.seed)
    if args.source == "folder":
        if not args.frames_dir:
            raise RuntimeError("Для --source folder нужен --frames-dir")
        return FolderCameraSource(mapping, args.frames_dir)
    return HardwareCameraSource(mapping)


def build_step_driver(args) -> StepDriver:
    if args.step == "none":
        return NoStepDriver()
    if args.step == "sim":
        return SimStepDriver()
    return SerialStepDriver(
        port=args.port,
        baudrate=args.baud,
        calibration_file=args.calibration,
        settle=args.settle,
        timeout=args.step_timeout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Разметка зон ROI по семи камерам с шагом конвейера.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--out", default="roi_dataset",
                        help="Папка для сессий разметки")
    parser.add_argument("--session", default=None, help="Имя сессии")
    parser.add_argument("--mapping", default=CAMERA_MAPPING_FILE,
                        help="Файл camera_mapping.json")
    parser.add_argument("--source", choices=("auto", "camera", "folder", "synthetic"),
                        default="auto", help="Источник кадров")
    parser.add_argument("--frames-dir", default=None,
                        help="Папка с кадрами для --source folder")
    parser.add_argument("--step", choices=("serial", "sim", "none"),
                        default="serial", help="Способ шага конвейера")
    parser.add_argument("--port", default=None,
                        help="COM-порт контроллера (иначе автопоиск)")
    parser.add_argument("--baud", type=int, default=115200, help="Скорость порта")
    parser.add_argument("--calibration", default=CALIBRATION_FILE,
                        help="Файл calibration.json для параметров ленты")
    parser.add_argument("--settle", type=float, default=0.35,
                        help="Пауза после подтверждённой остановки, с")
    parser.add_argument("--step-timeout", type=float, default=20.0,
                        help="Ожидание подтверждения шага, с")
    parser.add_argument("--auto-step", action="store_true",
                        help="Шагать без подтверждения оператора")
    parser.add_argument("--scale", default="auto",
                        help="Масштаб окна: auto или число, например 0.8")
    parser.add_argument("--quality", type=int, default=JPEG_QUALITY,
                        help="Качество JPEG для сохраняемых кадров")
    parser.add_argument("--seed", type=int, default=7,
                        help="Зерно генератора для --source synthetic")
    parser.add_argument("--headless", action="store_true",
                        help="Без окна: собрать PNG-снимки интерфейса и выйти")
    parser.add_argument("--headless-shot", default="roi_headless_check.png",
                        help="Куда сохранить PNG при --headless")
    return parser


HEADLESS_SCALE = 0.75


def run_headless(app: "RoiApp", shot_path: str) -> int:
    """Проверка интерфейса без окна: PNG стартового экрана и разметки.

    Используется на машинах без графики и в предпросмотре, где нельзя
    открыть окно OpenCV. Ничего не двигает: шаг ленты не вызывается.
    """
    if app.scale > HEADLESS_SCALE:
        app.scale = HEADLESS_SCALE
        width, height = app.frame_size or EXPECTED_FRAME_SIZE
        display_w, display_h = int(width * app.scale), int(height * app.scale)
        app.canvas_size = (display_w + PANEL_WIDTH, max(display_h, MIN_CANVAS_HEIGHT))
        app._frame_base_cache = None
        app._panel_cache = None

    app.phase = Phase.READY
    ready = app._compose()
    app.start()
    app._start_draw(int(140 * app.scale), int(90 * app.scale))
    app._drag_to(int(980 * app.scale), int(620 * app.scale))
    app._finish_draw(int(980 * app.scale), int(620 * app.scale))
    marked = app._compose()

    out = Path(shot_path)
    _write_png(out.with_name(out.stem + "_ready" + out.suffix), ready)
    _write_png(out, marked)
    print(f"[ROI] PNG сохранены: {out.stem}_ready{out.suffix}, {out.name}")
    return 0


def _write_png(path: Path, image: np.ndarray) -> None:
    ok, buffer = cv2.imencode(".png", image)
    if not ok or buffer is None:
        raise RuntimeError(f"Не удалось закодировать PNG: {path}")
    _write_bytes(path, buffer.tobytes())


def parse_scale(value: str) -> float | None:
    if not value or value == "auto":
        return None
    try:
        scale = float(value)
    except ValueError as exc:
        raise SystemExit(f"--scale: ожидалось 'auto' или число, получено {value!r}") from exc
    if not 0.2 <= scale <= 3.0:
        raise SystemExit("--scale: допустимый диапазон 0.2…3.0")
    return scale


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scale = parse_scale(args.scale)

    if not _HAVE_PIL:
        print("[ROI] Pillow не установлен: подписи интерфейса будут латиницей.")
        print("[ROI] Кириллица: pip install pillow")

    print("=" * 66)
    print(" ConveyerSeven · разметка зон ROI")
    print("=" * 66)

    source = None
    step_driver = None
    try:
        required_mapping = args.source in ("auto", "camera")
        mapping = load_mapping(args.mapping, required=required_mapping)
        source = build_source(args, mapping)
        step_driver = build_step_driver(args)
        session = RoiSession(
            args.out,
            session_id=args.session,
            source_name=source.name,
            step_mode=step_driver.mode,
            mapping=mapping,
            quality=args.quality,
        )
        app = RoiApp(
            mapping=mapping,
            source=source,
            step_driver=step_driver,
            session=session,
            scale=scale,
            auto_step=args.auto_step,
        )
        if args.headless:
            return run_headless(app, args.headless_shot)
        app.run()
        return 0
    except KeyboardInterrupt:
        print("\n[ROI] Прервано пользователем")
        return 130
    except Exception as exc:                            # noqa: BLE001
        print(f"[ROI] Ошибка: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if source is not None:
            source.close()
        if step_driver is not None:
            step_driver.close()


if __name__ == "__main__":
    sys.exit(main())
