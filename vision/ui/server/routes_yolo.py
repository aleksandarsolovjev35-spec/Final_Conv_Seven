"""HTTP-маршруты отметки пропущенных дефектов и выгрузки ZIP для YOLO."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse


def setup_yolo_routes(app, server):

    @app.get("/api/yolo-tasks/summary")
    async def api_yolo_summary():
        store = server.get_yolo_store()
        summary = await asyncio.to_thread(store.get_summary)
        return JSONResponse(summary)

    @app.get("/api/yolo-tasks/classes/{role}")
    async def api_yolo_role_classes(role: str):
        from inspection.yolo_feedback import (
            CAMERA_ROLE_LABELS_RU,
            get_role_classes,
        )
        from vision.model_config import ROLE_TO_GROUP

        normalized = str(role or "").strip().upper()
        if normalized not in ROLE_TO_GROUP:
            raise HTTPException(400, f"Неизвестная роль камеры: {role}")
        return JSONResponse({
            "role": normalized,
            "role_label": CAMERA_ROLE_LABELS_RU.get(normalized, normalized),
            "classes": get_role_classes(normalized),
        })

    @app.post("/api/yolo-tasks/snapshot")
    async def api_yolo_create_snapshot(payload: dict | None = None):
        data = payload or {}
        role = str(data.get("role") or "").strip().upper()
        try:
            snap = await asyncio.to_thread(
                server.create_yolo_snapshot,
                role=role,
            )
        except PermissionError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=409,
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=400,
            )
        except LookupError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=404,
            )
        except Exception as exc:
            print(f"[API] yolo snapshot error: {exc}")
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=500,
            )
        return JSONResponse({"ok": True, "snapshot": snap})

    @app.get("/api/yolo-tasks/snapshot/{snapshot_id}/image")
    async def api_yolo_snapshot_image(
        snapshot_id: str,
        kind: str = "overlay",
    ):
        jpeg = server.get_yolo_snapshot_jpeg(snapshot_id, kind)
        if jpeg is None:
            raise HTTPException(404, "Снимок для разметки не найден или устарел")
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    @app.post("/api/yolo-tasks/save")
    async def api_yolo_save_task(payload: dict | None = None):
        data = payload or {}
        snapshot_id = str(data.get("snapshot_id") or "").strip()
        marks = data.get("marks")
        comment = str(data.get("comment") or "")
        if not snapshot_id:
            return JSONResponse(
                {"ok": False, "error": "Не указан идентификатор снимка"},
                status_code=400,
            )
        try:
            saved = await asyncio.to_thread(
                server.save_yolo_snapshot_task,
                snapshot_id=snapshot_id,
                marks=marks,
                comment=comment,
            )
        except PermissionError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=409,
            )
        except LookupError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=404,
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=400,
            )
        except Exception as exc:
            print(f"[API] yolo save error: {exc}")
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=500,
            )
        return JSONResponse({"ok": True, **saved})

    @app.get("/api/yolo-tasks/item/{task_id}/image")
    async def api_yolo_item_image(task_id: str, kind: str = "hint"):
        store = server.get_yolo_store()
        actual_kind = "clean" if kind == "clean" else "hint"
        path = await asyncio.to_thread(
            store.get_item_image_path, task_id, actual_kind,
        )
        if not path:
            raise HTTPException(404, "Изображение задачи не найдено")
        data = await asyncio.to_thread(_read_binary, path)
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.post("/api/yolo-tasks/item/{task_id}/delete")
    async def api_yolo_delete_item(task_id: str):
        store = server.get_yolo_store()
        deleted = await asyncio.to_thread(store.delete_task, task_id)
        if not deleted:
            return JSONResponse(
                {"ok": False, "error": "Задача не найдена"},
                status_code=404,
            )
        summary = await asyncio.to_thread(store.get_summary)
        return JSONResponse({"ok": True, "summary": summary})

    @app.get("/api/yolo-tasks/export")
    async def api_yolo_export_zip(
        scope: str = "pending",
        mark_exported: int = 1,
    ):
        only_pending = str(scope or "pending").lower() != "all"
        store = server.get_yolo_store()
        try:
            zip_bytes, count, filename = await asyncio.to_thread(
                store.build_export_zip,
                only_pending=only_pending,
                mark_exported=bool(mark_exported),
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=409,
            )
        except Exception as exc:
            print(f"[API] yolo export error: {exc}")
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=500,
            )
        quoted = quote(filename)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"; '
                    f"filename*=UTF-8''{quoted}"
                ),
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "X-Exported-Count": str(count),
            },
        )


def _read_binary(path: str) -> bytes:
    with open(path, "rb") as stream:
        return stream.read()
