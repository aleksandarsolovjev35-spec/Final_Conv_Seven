"""Перечисление физических камер для мастера назначения ролей.

Модуль ничего не знает про роли: он открывает устройство по индексу,
снимает один кадр и сразу освобождает захват. Так мастер может показать
оператору, что реально подключено к ПК, даже если приложение уже держит
камеры открытыми (перед сканом их освобождает ``CameraManager``).
"""

from __future__ import annotations

import cv2


DEFAULT_SCAN_LIMIT = 8
SNAPSHOT_QUALITY = 70

ERROR_NOT_OPENED = "устройство не открылось"
ERROR_NO_FRAME = "нет кадра"


def _capture_factory(factory):
    return factory or cv2.VideoCapture


def _release(capture) -> None:
    if capture is None:
        return
    try:
        capture.release()
    except Exception:
        pass


def probe_device(index: int, factory=None) -> dict:
    """Открыть устройство, снять один кадр и освободить его."""

    capture = None
    try:
        capture = _capture_factory(factory)(int(index))
        if capture is None or not capture.isOpened():
            return {
                "index": int(index),
                "ok": False,
                "width": 0,
                "height": 0,
                "error": ERROR_NOT_OPENED,
            }
        ok, frame = capture.read()
        if not ok or frame is None:
            return {
                "index": int(index),
                "ok": False,
                "width": 0,
                "height": 0,
                "error": ERROR_NO_FRAME,
            }
        height, width = frame.shape[:2]
        return {
            "index": int(index),
            "ok": True,
            "width": int(width),
            "height": int(height),
            "error": None,
        }
    except Exception as exc:
        return {
            "index": int(index),
            "ok": False,
            "width": 0,
            "height": 0,
            "error": str(exc),
        }
    finally:
        _release(capture)


def probe_devices(limit: int = DEFAULT_SCAN_LIMIT, factory=None) -> list[dict]:
    """Проверить индексы ``0..limit-1`` и вернуть отчёт по каждому."""

    return [
        probe_device(index, factory=factory)
        for index in range(max(0, int(limit)))
    ]


def grab_snapshot(
    index: int,
    factory=None,
    quality: int = SNAPSHOT_QUALITY,
) -> bytes | None:
    """JPEG-снимок с физического устройства; ``None``, если оно недоступно."""

    capture = None
    try:
        capture = _capture_factory(factory)(int(index))
        if capture is None or not capture.isOpened():
            return None
        ok, frame = capture.read()
        if not ok or frame is None:
            return None
        ok, buffer = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)],
        )
        return buffer.tobytes() if ok else None
    except Exception:
        return None
    finally:
        _release(capture)
