import asyncio

from fastapi import HTTPException
from fastapi.responses import JSONResponse


def setup_api_routes(app, server):

    async def invoke(name, callback, *args):
        if callback is None:
            return JSONResponse(
                {"ok": False, "error": "Система ещё не готова"},
                status_code=503,
            )
        try:
            accepted = await asyncio.to_thread(callback, *args)
        except Exception as exc:
            print(f"[API] {name} error: {exc}")
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=500,
            )
        if accepted is False:
            return JSONResponse(
                {"ok": False, "error": f"Команда «{name}» недоступна в текущем состоянии"},
                status_code=409,
            )
        return JSONResponse({"ok": True})

    async def _batch_action(action, payload, key: str = "batch"):
        """Действие менеджера партий или входа: 400 — данные, 409 — состояние."""
        try:
            if payload is None:
                result = await asyncio.to_thread(action)
            else:
                result = await asyncio.to_thread(action, payload)
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)}, status_code=400,
            )
        except RuntimeError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)}, status_code=409,
            )
        except Exception as exc:
            print(f"[API] {key} error: {exc}")
            return JSONResponse(
                {"ok": False, "error": str(exc)}, status_code=500,
            )
        return JSONResponse({"ok": True, key: result})

    @app.get("/api/cameras")
    async def get_cameras():
        with server.lock:
            roles = list(dict.fromkeys(
                [*server.camera_roles, *server.frames.keys()]
            ))
            camera_ids = dict(server.camera_mapping)
        sorted_roles = server._sort_by_order(roles)
        return JSONResponse({
            "cameras": sorted_roles,
            "camera_ids": camera_ids,
        })

    @app.get("/api/boot")
    async def get_boot():
        with server.lock:
            steps = [
                {
                    "key":    key,
                    "label":  label,
                    "status": server.boot_steps.get(
                        key, "pending",
                    ),
                }
                for key, label in server.BOOT_STEPS
            ]
            done_count = sum(
                1 for s in steps if s["status"] == "done"
            )
            total = len(steps)
            return JSONResponse({
                "active":   server.splash_active,
                "steps":    steps,
                "current":  server.boot_current,
                "message":  server.boot_message,
                "error":    server.boot_error,
                "progress": (
                    done_count / total if total else 0
                ),
                "log": list(server.splash_log[-12:]),
            })

    @app.get("/api/status")
    async def get_status():
        # Автоподхват порогов: если thresholds.json изменился вручную,
        # перечитываем его (в рабочем потоке) до отдачи статуса.
        if server.thresholds_file_mtime_changed():
            await asyncio.to_thread(server.reload_thresholds_from_file)
        with server.lock:
            return JSONResponse({
                "splash_active": server.splash_active,
                "line_status":   server.line_status,
                "recent_parts":  server.recent_parts,
                "mode":          server.mode,
                "frame_version": server._cache_version,
                "frame_versions": dict(server._latest_frames_ver),
                "active_camera": server.active_camera_role,
                "thresholds_revision": server.thresholds_revision,
                "archive": server.archive_status_payload(),
                "batch": server.batch_status_payload(),
                "operator": server.operator_status_payload(),
            })

    @app.get("/api/mode")
    async def get_mode():
        return JSONResponse({"mode": server.mode})

    @app.post("/api/mode/{mode}")
    async def set_mode(mode: str):
        if mode not in ("RAW", "RULES"):
            raise HTTPException(400, "Недопустимый режим отображения")
        with server.lock:
            server.mode = mode
            server._jpeg_cache.clear()
            server._latest_stream_jpeg.clear()
            server._cache_version += 1
            frame_version = server._cache_version
        return JSONResponse({
            "mode": server.mode,
            "frame_version": frame_version,
        })

    @app.post("/api/active_camera/{role}")
    async def set_active_camera(role: str):
        if not role:
            raise HTTPException(400, "Роль камеры не указана")
        if not server.set_active_camera_role(role):
            raise HTTPException(400, "Камера не найдена или недоступна")
        return JSONResponse({
            "ok": True,
            "active_camera": server.active_camera_role,
        })

    # Пороги правил (редактирование до пуска и после полной остановки)

    @app.get("/api/thresholds")
    async def api_get_thresholds(role: str | None = None):
        return JSONResponse(
            await asyncio.to_thread(server.build_thresholds_payload, role)
        )

    @app.post("/api/thresholds")
    async def api_set_thresholds(payload: dict | None = None):
        payload = payload or {}
        role = payload.get("role")
        values = payload.get("values")
        labels = payload.get("labels")
        if not isinstance(role, str) or not role:
            raise HTTPException(400, "Роль камеры не указана")
        if not isinstance(values, dict) or not values:
            raise HTTPException(400, "Не указаны значения порогов")
        if labels is not None:
            if not isinstance(labels, dict) or any(
                not isinstance(name, str) for name in labels.values()
            ):
                raise HTTPException(
                    400, "Названия порогов должны быть объектом со строками"
                )
        if not server.thresholds_editable():
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Изменение порогов доступно только до пуска "
                             "и после полной остановки",
                },
                status_code=409,
            )
        if server.on_thresholds_apply is None:
            return JSONResponse(
                {"ok": False, "error": "Система ещё не готова"},
                status_code=503,
            )
        try:
            result = await asyncio.to_thread(
                server.apply_thresholds, role, values, labels,
            )
        except ValueError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=400,
            )
        except RuntimeError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=409,
            )
        except Exception as exc:
            print(f"[API] thresholds error: {exc}")
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=500,
            )
        return JSONResponse({"ok": True, "thresholds": result})

    # Обязательный архив партий: до начала партии меняется только корневая папка.

    @app.get("/api/archive/settings")
    async def api_get_archive_settings():
        return JSONResponse(
            await asyncio.to_thread(server.build_archive_payload, True)
        )

    @app.post("/api/archive/settings")
    async def api_set_archive_settings(payload: dict | None = None):
        try:
            result = await asyncio.to_thread(
                server.apply_archive_settings, payload or {}
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except RuntimeError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
        except OSError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            print(f"[API] archive settings error: {exc}")
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, "archive": result})

    # Оператор смены: вход в программу по ФИО и паролю. Пока оператор не
    # вошёл, партия не открывается, а значит пуск линии заблокирован.

    @app.get("/api/operator")
    async def api_get_operator():
        return JSONResponse(
            await asyncio.to_thread(server.operator_status_payload)
        )

    @app.post("/api/operator/login")
    async def api_operator_login(payload: dict | None = None):
        body = payload or {}
        login = body.get("login", "")
        password = body.get("password", "")
        if not isinstance(login, str) or not isinstance(password, str):
            raise HTTPException(400, "Некорректные данные входа")
        return await _batch_action(
            lambda data: server.operator_login(
                data["login"], data["password"],
            ),
            {"login": login, "password": password},
            key="operator",
        )

    @app.post("/api/operator/register")
    async def api_operator_register(payload: dict | None = None):
        """Первый запуск: создать оператора, пока список пуст."""
        body = payload or {}
        login = body.get("login", "")
        password = body.get("password", "")
        if not isinstance(login, str) or not isinstance(password, str):
            raise HTTPException(400, "Некорректные данные входа")
        return await _batch_action(
            lambda data: server.operator_register(
                data["login"], data["password"],
            ),
            {"login": login, "password": password},
            key="operator",
        )

    @app.post("/api/operator/logout")
    async def api_operator_logout():
        return await _batch_action(
            server.operator_logout, None, key="operator",
        )

    # Менеджер партий: номер партии и учёт корпусов в её составе.

    @app.get("/api/batch")
    async def api_get_batch():
        return JSONResponse(
            await asyncio.to_thread(server.batch_status_payload)
        )

    @app.post("/api/batch/open")
    async def api_open_batch(payload: dict | None = None):
        """Начать новую партию или продолжить открытую (batch_id)."""
        body = payload or {}
        if body.get("batch_id") is not None and not isinstance(
            body.get("batch_id"), str
        ):
            raise HTTPException(400, "Некорректный идентификатор партии")
        if not isinstance(body.get("label", ""), str):
            raise HTTPException(400, "Некорректный номер партии")
        return await _batch_action(server.open_batch, body)

    @app.post("/api/batch/finish")
    async def api_finish_batch():
        """Завершить партию: манифест CLOSED, отправка, ZIP."""
        return await _batch_action(server.finish_batch, None)

    @app.post("/api/start")
    async def api_start():
        print("[API] /api/start called")
        archive_ready, archive_error = server.archive_ready_for_start()
        if not archive_ready:
            return JSONResponse(
                {"ok": False, "error": archive_error or "Учёт недоступен"},
                status_code=409,
            )
        return await invoke("ПУСК", server.on_start)

    @app.post("/api/stop")
    async def api_stop():
        print("[API] /api/stop called")
        return await invoke("СТОП", server.on_stop)

    @app.post("/api/pause")
    async def api_pause():
        print("[API] /api/pause called")
        return await invoke("ПАУЗА", server.on_pause)

    @app.post("/api/resume")
    async def api_resume():
        print("[API] /api/resume called")
        return await invoke("ПРОДОЛЖИТЬ", server.on_resume)

    @app.post("/api/exit")
    async def api_exit():
        print("[API] /api/exit called")
        return await invoke("ВЫХОД", server.on_exit)

    @app.post("/api/diagnostics/cameras")
    async def api_diagnostic_cameras():
        return await invoke(
            "ПРОВЕРКА КАМЕР",
            server.on_camera_diagnostic,
        )

    @app.post("/api/diagnostics/vision-rules")
    async def api_diagnostic_vision_rules():
        return await invoke(
            "ПРОВЕРКА МОДЕЛЕЙ И ПРАВИЛ",
            server.on_vision_rule_diagnostic,
        )

    # JOG

    @app.post("/api/jog/enter")
    async def api_jog_enter():
        return await invoke("ВХОД В РУЧНОЙ РЕЖИМ", server.on_jog_enter)

    @app.post("/api/jog/exit")
    async def api_jog_exit():
        return await invoke("ВЫХОД ИЗ РУЧНОГО РЕЖИМА", server.on_jog_exit)

    @app.post("/api/jog/hold/start")
    async def api_jog_hold_start(payload: dict):
        direction = payload.get("direction")
        if direction not in ("+", "-"):
            raise HTTPException(400, "Недопустимое направление")
        return await invoke(
            "НАЧАЛО РУЧНОГО ДВИЖЕНИЯ", server.on_jog_hold_start, direction
        )

    @app.post("/api/jog/hold/heartbeat")
    async def api_jog_hold_heartbeat(payload: dict):
        direction = payload.get("direction")
        if direction not in ("+", "-"):
            raise HTTPException(400, "Недопустимое направление")
        return await invoke(
            "СИГНАЛ УДЕРЖАНИЯ",
            server.on_jog_hold_heartbeat,
            direction,
        )

    @app.post("/api/jog/hold/release")
    async def api_jog_hold_release(payload: dict | None = None):
        reason = "button released"
        if isinstance(payload, dict) and payload.get("reason"):
            reason = str(payload["reason"])[:100]
        return await invoke(
            "ОСТАНОВКА РУЧНОГО ДВИЖЕНИЯ", server.on_jog_hold_release, reason
        )
