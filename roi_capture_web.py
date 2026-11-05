"""Веб-интерфейс разметки зон ROI поверх семи камер.

Тот же сценарий, что у окна OpenCV (``roi_capture``), но в браузере и в
стиле HMI основной программы: превью камер, основной кадр, панель
параметров и кнопки внизу.

Запуск из корня репозитория::

    run_roi_web.bat
    python roi_capture_web.py --host 0.0.0.0 --web-port 8077

Без железа::

    python roi_capture_web.py --source synthetic --step sim

Логика сеанса, камеры, сохранение пар кадров и шаг конвейера не
дублируются: всё берётся из :class:`roi_capture.RoiSessionController`.
Здесь только HTTP-слой, отдача кадров и страница.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import threading
from pathlib import Path

import cv2
import uvicorn
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import roi_capture as core
from roi_capture import (
    CALIBRATION_FILE,
    CAMERA_MAPPING_FILE,
    ROLE_LABELS,
    ROLE_ORDER,
    Phase,
    RoiSession,
    RoiSessionController,
    build_source,
    build_step_driver,
    load_mapping,
)

WEB_DIR = Path(__file__).parent / "roi_web"
NO_CACHE = "no-store, no-cache, must-revalidate"
PREVIEW_WIDTH = 320
FRAME_JPEG_QUALITY = 88
PREVIEW_JPEG_QUALITY = 70


# ---------------------------------------------------------------------------
# Сервис: сериализует доступ к контроллеру из HTTP-потоков
# ---------------------------------------------------------------------------

class RoiWebService:
    """Обёртка над контроллером с блокировкой на время операций."""

    def __init__(self, controller: RoiSessionController):
        self.controller = controller
        self.lock = threading.RLock()

    # ---------- вызовы ----------

    def call(self, func, *args, **kwargs):
        with self.lock:
            return func(*args, **kwargs)

    def snapshot(self) -> dict:
        with self.lock:
            return build_state(self.controller)

    # ---------- кадры ----------

    def frame_jpeg(self, role: str, preview: bool = False) -> bytes | None:
        with self.lock:
            frame = self.controller.ensure_frame(role)
            if frame is None:
                return None
            image = frame
            if preview:
                height, width = frame.shape[:2]
                if width > PREVIEW_WIDTH:
                    scale = PREVIEW_WIDTH / float(width)
                    image = cv2.resize(
                        frame, (PREVIEW_WIDTH, int(round(height * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
        quality = PREVIEW_JPEG_QUALITY if preview else FRAME_JPEG_QUALITY
        ok, buffer = cv2.imencode(".jpg", image,
                                  [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok or buffer is None:
            return None
        return buffer.tobytes()

    def frame_token(self, role: str) -> str:
        with self.lock:
            frame = self.controller.frames.get(role)
            return "0" if frame is None else str(id(frame))


def build_state(controller: RoiSessionController) -> dict:
    """Полное состояние сеанса для страницы (строится под блокировкой)."""
    counts = controller.session.counts()
    cameras = []
    for index, role in enumerate(ROLE_ORDER):
        frame = controller.frames.get(role)
        roi = controller.rois.get(role)
        cameras.append({
            "index": index,
            "role": role,
            "label": ROLE_LABELS.get(role, role),
            "camera_id": controller.mapping.get(role),
            "saved": bool(controller.saved.get(role)),
            "captured": frame is not None,
            "error": controller.errors.get(role, ""),
            "token": "0" if frame is None else str(id(frame)),
            "roi": None if roi is None or not roi.is_valid() else {
                "mode": roi.mode,
                "points": [[int(x), int(y)] for x, y in roi.points],
                "closed": bool(roi.closed),
            },
        })

    frame_size = controller.frame_size or core.EXPECTED_FRAME_SIZE
    driver = controller.step_driver
    return {
        "phase": controller.phase,
        "round": controller.round_no,
        "cursor": controller.cursor,
        "mode": controller.mode,
        "progress": round(controller.progress(), 4),
        "notice": controller.notice_text,
        "frame_size": {"width": frame_size[0], "height": frame_size[1]},
        "session": {
            "id": controller.session.session_id,
            "folder": controller.session.folder.as_posix(),
            "shots": counts["shots"],
            "rounds": counts["rounds"],
            "steps": controller.session.steps_made,
        },
        "step": {
            "mode": driver.mode,
            "status": controller.step_status,
            "fault": getattr(driver, "fault", ""),
            "number": controller.conveyor_step,
            "running": controller.stepping,
        },
        "source": controller.source.describe(),
        "cameras": cameras,
        "can_step": controller.phase in (Phase.ROUND_DONE, Phase.MARKUP)
        and not controller.stepping,
    }


# ---------------------------------------------------------------------------
# HTTP-приложение
# ---------------------------------------------------------------------------

def create_app(service: RoiWebService) -> FastAPI:
    app = FastAPI(title="ConveyerSeven · Разметка зон ROI", docs_url=None,
                  redoc_url=None)

    if (WEB_DIR / "static").is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")),
                  name="static")

    def respond(ok: bool = True, message: str = "", status_code: int = 200):
        payload = {"ok": ok, "message": message, "state": service.snapshot()}
        return JSONResponse(payload, status_code=status_code)

    async def run(func, *args, **kwargs):
        return await asyncio.to_thread(functools.partial(func, *args, **kwargs))

    # ---------- страница ----------

    @app.get("/")
    async def index():
        return FileResponse(
            str(WEB_DIR / "templates" / "index.html"),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": NO_CACHE},
        )

    @app.get("/favicon.ico")
    async def favicon():
        return Response(status_code=204)

    # ---------- состояние ----------

    @app.get("/api/state")
    async def get_state():
        state = await run(service.snapshot)
        return JSONResponse(state, headers={"Cache-Control": NO_CACHE})

    # ---------- действия ----------

    @app.post("/api/start")
    async def start_session():
        controller = service.controller
        if controller.phase == Phase.FINISHED:
            return respond(False, "сеанс уже завершён", 409)
        # Повторный старт начал бы круг заново и потерял уже снятые кадры.
        if controller.phase != Phase.READY:
            return respond(False, "сеанс уже запущен", 409)
        await run(service.call, controller.start)
        return respond(True, "сеанс запущен")

    @app.post("/api/camera/{index}")
    async def select_camera(index: int):
        controller = service.controller
        await run(service.call, controller.select_camera, index)
        return respond(True)

    @app.post("/api/capture")
    async def recapture():
        controller = service.controller
        if controller.phase != Phase.MARKUP:
            return respond(False, "съёмка доступна только в разметке", 409)
        frame = await run(service.call, controller.recapture)
        if frame is None:
            error = controller.errors.get(controller.current_role, "")
            return respond(False, error or "кадр не получен", 503)
        return respond(True, "кадр переснят")

    @app.post("/api/save")
    async def save(payload: dict | None = None):
        controller = service.controller
        data = payload or {}
        roi_payload = data.get("roi") or {}
        points = roi_payload.get("points") or []
        mode = roi_payload.get("mode") or controller.mode
        closed = bool(roi_payload.get("closed", True))

        if controller.phase != Phase.MARKUP:
            return respond(False, "разметка недоступна в этом состоянии", 409)
        if len(points) < 2:
            return respond(False, "зона не задана — обведите область", 400)

        def save_current():
            controller.set_roi_points(points, mode, closed)
            return controller.save_current()

        saved = await run(service.call, save_current)
        if not saved:
            return respond(False, controller.notice_text or "не удалось сохранить",
                           400)
        return respond(True, f"сохранено: {controller.current_role}")

    @app.post("/api/step")
    async def step():
        controller = service.controller
        if not service.call(lambda: controller.phase in (Phase.ROUND_DONE,
                                                         Phase.MARKUP)
                            and not controller.stepping):
            return respond(False, "шаг сейчас недоступен", 409)
        result = await run(service.call, controller.make_step)
        if result is None:
            return respond(False, "шаг сейчас недоступен", 409)
        if not result.ok:
            return respond(False, result.message or "шаг не подтверждён", 502)
        return respond(True, f"шаг выполнен: {result.message}")

    @app.post("/api/skip")
    async def skip_step():
        controller = service.controller
        if controller.phase != Phase.ROUND_DONE:
            return respond(False, "круг ещё не завершён", 409)
        await run(service.call, controller.continue_without_step)
        return respond(True, "новый круг без шага")

    @app.post("/api/finish")
    async def finish():
        controller = service.controller
        if controller.phase == Phase.FINISHED:
            return respond(True, "сеанс уже завершён")
        await run(service.call, controller.finish)
        return respond(True, "сеанс завершён")

    # ---------- кадры ----------

    @app.get("/api/frame/{index}")
    async def frame(index: int):
        role = _role_by_index(index)
        if role is None:
            return Response(status_code=404)
        data = await run(service.frame_jpeg, role, False)
        if data is None:
            return Response(status_code=204, headers={"Cache-Control": NO_CACHE})
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": NO_CACHE},
        )

    @app.get("/api/preview/{index}")
    async def preview(index: int):
        role = _role_by_index(index)
        if role is None:
            return Response(status_code=404)
        data = await run(service.frame_jpeg, role, True)
        if data is None:
            return Response(status_code=204, headers={"Cache-Control": NO_CACHE})
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": NO_CACHE},
        )

    return app


def _role_by_index(index: int) -> str | None:
    if 0 <= index < len(ROLE_ORDER):
        return ROLE_ORDER[index]
    return None


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Веб-интерфейс разметки зон ROI по семи камерам.",
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
    parser.add_argument("--baud", type=int, default=115200,
                        help="Скорость COM-порта")
    parser.add_argument("--calibration", default=CALIBRATION_FILE,
                        help="Файл calibration.json для параметров ленты")
    parser.add_argument("--settle", type=float, default=0.35,
                        help="Пауза после подтверждённой остановки, с")
    parser.add_argument("--step-timeout", type=float, default=20.0,
                        help="Ожидание подтверждения шага, с")
    parser.add_argument("--auto-step", action="store_true",
                        help="Шагать без подтверждения оператора")
    parser.add_argument("--quality", type=int, default=core.JPEG_QUALITY,
                        help="Качество JPEG для сохраняемых кадров")
    parser.add_argument("--seed", type=int, default=7,
                        help="Зерно генератора для --source synthetic")
    parser.add_argument("--host", default="0.0.0.0", help="Адрес веб-сервера")
    parser.add_argument("--web-port", type=int, default=8077,
                        help="Порт веб-сервера")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    print("=" * 66)
    print(" ConveyerSeven · разметка зон ROI (веб)")
    print("=" * 66)

    source = None
    step_driver = None
    try:
        mapping = load_mapping(args.mapping,
                               required=args.source in ("auto", "camera"))
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
        controller = RoiSessionController(
            mapping=mapping,
            source=source,
            step_driver=step_driver,
            session=session,
            auto_step=args.auto_step,
        )
        service = RoiWebService(controller)
        app = create_app(service)
        print(f"[ROI] Источник: {source.describe()} · шаг: {step_driver.describe()}")
        print(f"[ROI] Откройте http://{args.host}:{args.web_port}/")
        uvicorn.run(app, host=args.host, port=args.web_port, log_level="warning")
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
    raise SystemExit(main())
