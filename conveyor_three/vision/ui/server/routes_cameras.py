"""Маршруты мастера назначения камер ролям линии.

Мастер живёт в HMI и работает поверх уже открытых приложением камер:
перед сканированием захваты освобождаются, после закрытия мастера
(и после сохранения) камеры открываются заново по новому mapping.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
from fastapi.responses import Response


def setup_camera_routes(app, server):

    @app.get("/api/cameras/devices")
    async def api_camera_devices(limit: int = 8):
        try:
            devices = await asyncio.to_thread(
                server.scan_camera_devices, limit,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {
            "devices": devices,
            "mapping": dict(server.camera_mapping or {}),
            "roles": list(server.camera_required_roles()),
        }

    @app.get("/api/cameras/devices/{index}/frame")
    async def api_camera_device_frame(index: int):
        jpeg = await asyncio.to_thread(server.camera_device_frame, index)
        if jpeg is None:
            raise HTTPException(404, f"Камера {index} недоступна")
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store"},
        )

    @app.post("/api/cameras/mapping")
    async def api_save_camera_mapping(payload: dict | None = None):
        mapping = (payload or {}).get("mapping")
        try:
            return await asyncio.to_thread(
                server.save_camera_mapping, mapping,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/cameras/wizard")
    async def api_camera_wizard(payload: dict | None = None):
        active = bool((payload or {}).get("active"))
        try:
            return await asyncio.to_thread(
                server.set_camera_wizard_active, active,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
