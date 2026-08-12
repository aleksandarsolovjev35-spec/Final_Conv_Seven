"""Диагностика камер, правил и распределителя.

Часть ``ProductionCycle``. Доступна только на пустой линии в IDLE/STOPPED.
"""

import time

from domain.part import CATEGORY_BAD, CATEGORY_CLEANUP
from inspection.run_report import (
    prepare_presence_result,
    prepare_rule_results,
    summarize_model_health,
)
from core.rule_report import build_rule_report_row, build_rule_report_rows


class CycleDiagnosticsMixin:
    """Предстартовые проверки без движения линии."""


    def distributor_diagnostic(self, command: str) -> bool:
        if not self._operation_lock.acquire(blocking=False):
            return False
        try:
            if (
                self.state not in ("IDLE", "STOPPED")
                or self.parts
                or self._selected_analysis_active
            ):
                return False
            if self.jog is not None and self.jog.busy:
                return False
            self._set_process(
                "DISTRIBUTOR_DIAGNOSTIC",
                f"Проверка распределителя: {command}",
            )
            if command == "DIST1_HOME":
                self.distributor.diagnostic_gate("HOME")
            elif command == "DIST1_OPEN":
                self.distributor.diagnostic_gate("OPEN")
            elif command == "DIST2_BAD":
                self.distributor.diagnostic_route(CATEGORY_BAD)
            elif command == "DIST2_CLEANUP":
                self.distributor.diagnostic_route(CATEGORY_CLEANUP)
            else:
                raise ValueError(f"Unknown distributor diagnostic: {command}")
            self._set_process(
                "DIAGNOSTIC_DONE",
                f"Положение распределителя подтверждено: {command}",
            )
            return True
        except Exception as exc:
            self._handle_fault(f"Ошибка проверки распределителя: {exc}")
            raise
        finally:
            self._operation_lock.release()


    def diagnostic_check_cameras(self) -> bool:
        if not self._operation_lock.acquire(blocking=False):
            return False
        try:
            if not self._prestart_diagnostic_allowed():
                return False
            self._set_diagnostic_running("CAMERAS", "Проверка семи камер")
            self._set_process("CAMERA_DIAGNOSTIC", "Проверка семи камер")
            # После JOG драйвер может вернуть устаревший кадр из буфера.
            # См. комментарий в _stage_capture().
            self.cameras.drain_buffers()
            frames = self.cameras.capture_all()
            camera_rows = []
            for role, frame in frames.items():
                height, width = frame.shape[:2]
                camera_rows.append({
                    "role": role,
                    "ok": True,
                    "width": int(width),
                    "height": int(height),
                })
            self._last_vision_results = {}
            self._last_rule_results = []
            self._diagnostics = {
                "status": "PASSED",
                "kind": "CAMERAS",
                "message": f"Камеры: {len(camera_rows)}/{len(camera_rows)} OK",
                "cameras": camera_rows,
                "models": [],
                "rules": [],
                "updated_at": time.time(),
            }
            self._set_process("DIAGNOSTIC_DONE", "Семь камер проверены")
            self._refresh_monitor(frames)
            return True
        except Exception as exc:
            self._set_diagnostic_error("CAMERAS", exc)
            self._handle_fault(f"Ошибка проверки камер: {exc}")
            raise
        finally:
            self._operation_lock.release()


    def diagnostic_check_vision_rules(self) -> bool:
        if not self._operation_lock.acquire(blocking=False):
            return False
        try:
            if not self._prestart_diagnostic_allowed():
                return False
            self._set_diagnostic_running(
                "VISION_RULES",
                "Камеры -> модели -> правила дефектов",
            )
            self._set_process(
                "VISION_RULE_DIAGNOSTIC",
                "Запуск всех моделей и правил дефектов без движения линии",
            )
            # После JOG драйвер может вернуть устаревший кадр из буфера.
            # См. комментарий в _stage_capture().
            self.cameras.drain_buffers()
            frames = self.cameras.capture_all()
            vision_results = self.inspector.vision.process_all(frames)
            presence_result = prepare_presence_result(
                self.inspector._evaluate_part_presence(vision_results)
            )
            rule_results = [presence_result]
            if not presence_result.details.get("empty_tray"):
                rule_results.extend(
                    prepare_rule_results(
                        self.inspector.decision.evaluate_all_detailed(
                            vision_results,
                            frames=frames,
                        )
                    )
                )
            model_rows = summarize_model_health(
                self.inspector.vision.last_health
            )
            rule_rows = [
                self._rule_report_row(result)
                for result in rule_results
            ]
            camera_rows = []
            for role, frame in frames.items():
                height, width = frame.shape[:2]
                camera_rows.append({
                    "role": role,
                    "ok": True,
                    "width": int(width),
                    "height": int(height),
                    "detections": len(vision_results.get(role, [])),
                })
            self._last_vision_results = vision_results
            self._last_rule_results = rule_results
            triggered = sum(row["triggered"] for row in rule_rows)
            self._diagnostics = {
                "status": "PASSED",
                "kind": "VISION_RULES",
                "message": (
                    f"Модели: {len(model_rows)} исправны; "
                    f"правил: {len(rule_rows)}, сработало: {triggered}"
                ),
                "cameras": camera_rows,
                "models": model_rows,
                "rules": rule_rows,
                "updated_at": time.time(),
            }
            self._set_process(
                "DIAGNOSTIC_DONE",
                "Модели и правила дефектов выполнены",
            )
            self._refresh_monitor(frames)
            return True
        except Exception as exc:
            self._set_diagnostic_error("VISION_RULES", exc)
            self._handle_fault(f"Ошибка проверки моделей и правил: {exc}")
            raise
        finally:
            self._operation_lock.release()


    def _prestart_diagnostic_allowed(self) -> bool:
        return (
            self.state in ("IDLE", "STOPPED")
            and not self.parts
            and not self.exit_requested
            and not self._cancel_motion.is_set()
            and not self._selected_analysis_active
            and not (self.jog is not None and self.jog.busy)
        )


    def _set_diagnostic_running(self, kind: str, message: str):
        self._diagnostics = {
            "status": "RUNNING",
            "kind": kind,
            "message": message,
            "cameras": [],
            "models": [],
            "rules": [],
            "updated_at": time.time(),
        }
        self._refresh_monitor()


    def _set_diagnostic_error(self, kind: str, exc: Exception):
        self._diagnostics = {
            "status": "ERROR",
            "kind": kind,
            "message": f"{type(exc).__name__}: {exc}",
            "cameras": [],
            "models": [],
            "rules": [],
            "updated_at": time.time(),
        }
        self._refresh_monitor()

    @staticmethod

    def _rule_report_row(result) -> dict:
        return build_rule_report_row(result)

    @staticmethod

    def _rule_report_rows(results, role: str | None = None) -> list:
        return build_rule_report_rows(results, role=role)


    def diagnostic_analyze_selected_camera(self, role: str) -> bool:
        if not self._operation_lock.acquire(blocking=False):
            return False
        try:
            if not self._prestart_diagnostic_allowed():
                return False
            available_roles = set(self.cameras.mapping)
            if not available_roles:
                available_roles = set(
                    self.inspector.INPUT_ROLES + self.inspector.SPIDER_ROLES
                )
            if role not in available_roles:
                raise ValueError(f"Неизвестная роль камеры: {role}")

            if not self.live.pause():
                raise RuntimeError(
                    "Live-просмотр не освободил камеры для анализа кадров"
                )
            # Сброс буфера драйвера: после паузы live cap.read()
            # может вернуть устаревший кадр. См. комментарий
            # в _stage_capture().
            self.cameras.drain_buffers((role,))

            self._selected_analysis_active = True
            self._selected_analysis_role = role
            self._set_diagnostic_running(
                "SELECTED_MODEL",
                f"Анализ кадра выбранной камеры: {role}",
            )
            self._set_process(
                "SELECTED_MODEL_ANALYSIS",
                f"Анализ кадра {role}",
            )

            decision = self.inspector.decision
            decision_rules = decision.rules_for_role(role)
            if not decision_rules:
                raise RuntimeError(
                    f"Для камеры {role} нет активных правил анализа"
                )

            is_input = role in self.inspector.INPUT_ROLES

            self._set_process(
                "SELECTED_MODEL_ANALYSIS", f"{role}: свежий кадр",
            )
            frame = self.cameras.capture_single(role)
            stage_frames = {role: frame}
            vision_results = self.inspector.vision.process_all(stage_frames)
            if role not in vision_results:
                raise RuntimeError(
                    f"Модели не вернули результат камеры {role}"
                )
            detection_count = len(vision_results.get(role, []))

            raw_model_health = [
                item
                for item in (self.inspector.vision.last_health or [])
                if isinstance(item, dict)
            ]

            presence_result = None
            rule_results = []
            if is_input:
                presence_result = prepare_presence_result(
                    self.inspector._evaluate_part_presence(vision_results)
                )
                if not presence_result.details.get("empty_tray"):
                    rule_results = prepare_rule_results(
                        decision.evaluate_rules_detailed(
                            decision_rules, vision_results, frames=stage_frames,
                        )
                    )
            else:
                rule_results = prepare_rule_results(
                    decision.evaluate_rules_detailed(
                        decision_rules, vision_results, frames=stage_frames,
                    )
                )

            model_rows = summarize_model_health(raw_model_health)
            if not model_rows or any(not row.get("ok") for row in model_rows):
                raise RuntimeError(
                    f"Нет полного комплекта model health для камеры {role}"
                )

            rule_rows = []
            if is_input and presence_result is not None:
                rule_rows.append(self._rule_report_row(presence_result))
            rule_rows.extend(
                self._rule_report_row(result) for result in rule_results
            )

            height, width = frame.shape[:2]
            camera_rows = [{
                "role": role,
                "selected": True,
                "ok": True,
                "width": int(width),
                "height": int(height),
                "detections": int(detection_count),
            }]

            self._last_vision_results = vision_results
            self._last_rule_results = rule_results
            self._diagnostics = {
                "status": "PASSED",
                "kind": "SELECTED_MODEL",
                "message": (
                    f"{role}: свежий кадр; моделей {len(model_rows)}; "
                    f"правил {len(rule_rows)}; объекты {detection_count}"
                ),
                "selected_role": role,
                "cameras": camera_rows,
                "models": model_rows,
                "rules": rule_rows,
                "updated_at": time.time(),
            }
            self._set_process(
                "SELECTED_MODEL_READY",
                f"Анализ кадра {role} завершён; поток приостановлен",
            )
            self._refresh_monitor(stage_frames)
            return True
        except Exception as exc:
            self._selected_analysis_active = False
            self._selected_analysis_role = None
            self.live.resume()
            self._set_diagnostic_error("SELECTED_MODEL", exc)
            self._handle_fault(f"Ошибка анализа выбранного кадра: {exc}")
            raise
        finally:
            self._operation_lock.release()


    def diagnostic_release_selected_camera(self) -> bool:
        if not self._operation_lock.acquire(blocking=False):
            return False
        try:
            if not self._selected_analysis_active:
                return False
            role = self._selected_analysis_role
            self._selected_analysis_active = False
            self._selected_analysis_role = None
            self._last_vision_results = {}
            self._last_rule_results = []
            self._reset_frame_analysis()
            self._diagnostics = {
                "status": "NOT_RUN",
                "kind": None,
                "message": "Анализ кадра не выполнялся",
                "cameras": [],
                "models": [],
                "rules": [],
                "updated_at": None,
            }
            self.live.resume()
            # Убрать геометрию анализа с экрана: разметка построена по
            # статичному кадру и на движущемся изображении указывала бы
            # мимо детали (эффект маркера на лобовом стекле).
            self.live.clear_overlays()
            try:
                fresh_frames = self.cameras.capture_all()
                # Публикуем свежие кадры без оверлеев — возврат к живому виду.
                self._refresh_monitor(fresh_frames)
            except Exception:
                # Если захват недоступен (камеры заняты / ошибка), хотя бы
                # гарантируем очистку оверлеев и обновление статуса.
                self._refresh_monitor()
            self._set_process(
                "LIVE_SELECTED_CAMERA",
                f"Поток восстановлен: {role}",
            )
            return True
        finally:
            self._operation_lock.release()
