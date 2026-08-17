"""Один шаг ленты и инспекции (3 камеры).

Часть ``ProductionCycle``: фазы MOTION/SETTLE/CAPTURE/ANALYSIS/REVIEW/
PUBLISH, единственная стадия INSPECT на +0, пауза и архив детали.
"""

from __future__ import annotations

import time

from core.state_machine import State
from domain.part import (
    CATEGORY_BAD,
    CATEGORY_CLEANUP,
    CATEGORY_GOOD,
    CATEGORY_UNKNOWN,
    Part,
)

class CycleStepMixin:
    """Механика одного производственного шага."""

    def _stage_motion(self):
        """MOTION: подготовить маршрут и переместить ленту на шаг."""
        self.stages.enter_motion()
        self._inspection_display_roles = ()
        # Разметка прошлого шага построена по статичному кадру и на
        # движущемся изображении указывала бы мимо детали.
        self.live.clear_overlays()

        if self._await_initial_inspection:
            # Деталь уже стоит под камерами: сначала её контроль,
            # движение ленты начнётся со следующего шага. Счётчик шагов не
            # увеличивается — физическая позиция не изменилась.
            self._await_initial_inspection = False
            self._set_process(
                "INITIAL_INSPECTION",
                "Корпус уже под камерами: контроль без движения ленты",
                positions=[self.OFFSET_INSPECT],
            )
            self._check_motion_cancelled()
            return None

        self._pending_drop = self._find_pending_drop()
        pending_id = self._pending_drop.id if self._pending_drop else None
        self._set_process(
            "ROUTE_PREPARE",
            "Подготовка маршрута распределителя",
            part_id=pending_id,
            positions=[self.OFFSET_REJECT] if pending_id else [],
        )
        self._prepare_drop()
        self._check_motion_cancelled()

        self._set_process(
            "CONVEYOR_COMMAND",
            "Команда движения ленты отправлена",
            part_id=pending_id,
            positions=range(self.OFFSET_REJECT + 1),
        )
        self.conveyor.move_step()
        self.conveyor.wait_stop(progress_callback=self._on_conveyor_progress)
        self._check_motion_cancelled()
        # Логическая позиция фиксируется только после подтверждения
        # физического завершения движения.
        self.current_step += 1
        return pending_id

    def _stage_settle(self, pending_id, accept_input_for_this_step: bool = False):
        """SETTLE: подтвердить передачу корпуса и погасить вибрацию."""
        self._set_process(
            "CONVEYOR_CONFIRMED", "Позиции корпусов подтверждены контроллером",
            part_id=pending_id, positions=range(self.OFFSET_REJECT + 1),
        )
        if self._pending_drop is not None:
            self._set_process(
                "PART_TRANSFER", "Корпус прошёл распределитель",
                part_id=pending_id, positions=[self.OFFSET_REJECT],
            )
        self._execute_drop()
        self._check_motion_cancelled()
        active_cam_positions = [self.OFFSET_INSPECT] if accept_input_for_this_step else []
        self._set_process("SETTLE", "Ожидание затухания вибрации перед съёмкой", positions=active_cam_positions)
        self.stages.enter_settle()
        self._check_motion_cancelled()

    def _capture_roles_for_current_step(self, accept_input_for_this_step: bool = False) -> tuple[str, ...]:
        """Вернуть камеры зоны инспекции (+0).

        Все три камеры смотрят в одну зону, поэтому при работающем приёме
        (accept_new_parts) захватываются все три роли. Решение о пустой
        ячейке принимается тем же свежим кадром внутри общего pipeline.
        """
        if accept_input_for_this_step:
            return tuple(self.inspector.INSPECT_ROLES)
        return ()

    def _stage_capture(self, accept_input_for_this_step: bool = False):
        """CAPTURE: получить frozen snapshot для текущей инспекции."""
        roles = self._capture_roles_for_current_step(accept_input_for_this_step)
        self._inspection_display_roles = roles
        # Пауза только у ролей, которые сейчас дают inspection-кадр.
        self.stages.enter_capture(roles)
        active_cam_positions = [self.OFFSET_INSPECT] if roles else []

        self._set_process(
            "CAMERA_CAPTURE",
            (f"Синхронный захват камер: {', '.join(roles)}" if roles
             else "Нет корпуса под инспекционными камерами"),
            positions=active_cam_positions,
            capture_roles=roles,
        )
        if not roles:
            return [{}]

        # Драйвер может отдать старый кадр из буфера после движения. Дренируем
        # нужные роли, затем получаем один свежий набор.
        drain = getattr(self.cameras, "drain_buffers", None)
        if callable(drain):
            drain(roles=roles)
        capture_roles = getattr(self.cameras, "capture_roles", None)
        if callable(capture_roles):
            frames = capture_roles(roles)
        else:
            frames = self.cameras.capture_all()
            frames = {role: frames[role] for role in roles}
        if set(frames) != set(roles):
            raise RuntimeError(
                f"Неполный набор кадров для инспекции: ожидались {sorted(roles)}, "
                f"получены {sorted(frames)}"
            )
        self._check_motion_cancelled()
        # Нейросети используют только frames в памяти. Освобождаем камеры
        # немедленно, чтобы live-просмотр продолжался во время анализа.
        release_capture = getattr(self.stages, "release_capture_roles", None)
        if callable(release_capture):
            release_capture()
        # Публикуем frozen snapshot отдельным inspection-слоем.
        self._refresh_monitor(run_frames=[frames], run_rule_results=[[]])
        return [frames]

    def _stage_analysis(self, frame_runs, accept_input_for_this_step):
        """ANALYSIS: модели -> геометрия -> решение по уже снятым кадрам."""
        self.stages.enter_analysis()

        display_frames = dict(frame_runs[-1])
        markup_frames = {}
        markup_rules = []

        active_positions = []
        if accept_input_for_this_step:
            active_positions.append(self.OFFSET_INSPECT)

        if accept_input_for_this_step:
            self._set_process(
                "INSPECT_ANALYSIS",
                "Инспекция: модели и правила по свежему кадру",
                positions=active_positions,
            )
            inspect_result = self._process_inspect_stage(frame_runs)
            if inspect_result is not None:
                display_frames.update(inspect_result.raw_frames)
                markup_frames.update(inspect_result.raw_frames)
                # Для разметки используются только defect-правила
                # (run_rule_results), служебный part_presence не рисует.
                if inspect_result.run_rule_results:
                    markup_rules.extend(inspect_result.run_rule_results[0])
                # Если деталь не обнаружена, убираем подсветку позиции.
                if inspect_result.is_empty_tray and self.OFFSET_INSPECT in active_positions:
                    active_positions.remove(self.OFFSET_INSPECT)
            self._check_motion_cancelled()

        # Набор кадров стадии уходит в UI одним снимком.
        if markup_frames:
            self._refresh_monitor(
                display_frames,
                run_frames=[markup_frames],
                run_rule_results=[markup_rules],
            )
        return display_frames

    def _stage_review(self, display_frames):
        """REVIEW: пауза на просмотр работы нейросетей после анализа.

        Кадры со статичной разметкой уже опубликованы и остаются на
        экране, а лента стоит: оператор успевает отсмотреть результат
        до начала следующего шага. Паузу можно прервать остановкой или
        выходом из программы.
        """
        if self.review_seconds <= 0:
            return
        self._refresh_monitor(display_frames)
        deadline = time.monotonic() + self.review_seconds
        shown_seconds = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if (
                self._cancel_motion.is_set()
                or self.sm.force_exit
                or self.sm.exit_requested
                or self.sm.state != State.RUNNING
            ):
                break
            whole = int(remaining + 0.999)
            if whole != shown_seconds:
                shown_seconds = whole
                self._set_process(
                    "ANALYSIS_REVIEW",
                    "Просмотр результатов анализа: "
                    f"{whole} с до следующего шага",
                    positions=[self.OFFSET_INSPECT],
                )
            time.sleep(min(0.1, max(remaining, 0.01)))
        # FORCE EXIT во время паузы сбрасывает цепочку фаз: выходить нужно
        # штатной ошибкой отмены до входа в PUBLISH, а не сбросом шага.
        self._check_motion_cancelled()

    def _stage_publish(self, display_frames):
        """PUBLISH: вывод результата на экран."""
        self.stages.enter_publish()

        self._set_process("STEP_COMPLETE", "Шаг полностью завершён")
        self._refresh_monitor(display_frames)

    # Пауза в рабочем цикле

    def _check_pause_barrier(self):
        """Пауза после полной остановки шага и до работы нейронок.

        Оператор может поправить линию с помощью jog без ограничений.
        """
        if (
            self.sm.state == State.RUNNING
            and self._pause_requested.is_set()
            and not self.sm.exit_requested
        ):
            if self.sm.request_pause():
                self._enter_pause_frame()
            else:
                self._pause_requested.clear()

        while self.sm.state == State.PAUSED:
            if self.sm.exit_requested or self.sm.force_exit:
                self._pause_requested.clear()
                self._stop_pause_frame_loop()
                self.sm.request_stop()
                break
            if self.live.error:
                self._handle_fault(
                    "Ошибка камеры во время паузы: "
                    f"{self.live.error}"
                )
                break
            jog_error = (
                self.jog.status.get("error")
                if self.jog is not None else None
            )
            if jog_error:
                self._handle_fault(f"Ошибка ручного управления (JOG): {jog_error}")
                break
            self._refresh_monitor()
            time.sleep(0.05)

        if self._pause_frame_active:
            self._stop_pause_frame_loop()

    def _enter_pause_frame(self):
        """Включить режим JOG и отображение состояния паузы."""
        if not self._pause_frame_active:
            self._pause_frame_active = True
        self.enter_jog()
        # Пауза происходит ДО анализа изображения. Разметка предыдущего
        # шага построена по статичному кадру и на live-изображении из JOG
        # указывала бы мимо детали — убираем её немедленно.
        self.live.clear_overlays()
        print("[PAUSE] линия остановлена на границе шага после полной остановки")
        self._set_process(
            "PAUSED",
            "Пауза: доступна ручная коррекция ленты с помощью JOG",
            positions=range(self.OFFSET_REJECT + 1),
        )

    def _stop_pause_frame_loop(self):
        if not self._pause_frame_active:
            return
        self._pause_frame_active = False
        self.exit_jog()

    # Inspect stage (единственная стадия инспекции, +0)

    def _process_inspect_stage(self, frame_runs):
        """Обработать зону инспекции по свежему кадру."""

        candidate_id = self.part_counter + 1

        self._set_process(
            "INSPECT_ANALYSIS",
            f"Инспекция: анализ кандидата #{candidate_id}",
            part_id=candidate_id,
            positions=[self.OFFSET_INSPECT],
        )

        inspect_consensus = getattr(
            self.inspector,
            "inspect_consensus",
            None,
        )
        if not callable(inspect_consensus):
            raise RuntimeError(
                "Inspector не поддерживает обязательную инспекцию"
            )
        result = inspect_consensus(
            part_id=candidate_id,
            step=self.current_step,
            frame_runs=frame_runs,
            force_bad=self.force_all_bad,
        )
        if result.is_empty_tray:
            self._record_frame_analysis("INPUT", None, result)
            self.empty_count += 1
            # Очищаем детекции, чтобы не рисовать разметку на пустой ячейке.
            for role in self.inspector.INSPECT_ROLES:
                self._last_vision_results[role] = []
            self._last_rule_results.extend(result.rule_results)
            self._set_process(
                "INSPECT_RESULT_RECORDED",
                "Инспекция: пустая ячейка записана",
                positions=[self.OFFSET_INSPECT],
            )
            print(
                f"[EMPTY] Пустая ячейка на step {self.current_step} "
                f"(total empty: {self.empty_count})"
            )
            # Пустая ячейка остаётся нейтральной: Part и архив не создаются.
            return result

        self.part_counter += 1
        part = Part(self.part_counter, self.current_step)
        part.inspection_consensus["inspect"] = dict(result.consensus)
        for defect in result.defects:
            part.add_input_defect(defect)
        # Результат правил становится состоянием Part только после того,
        # как модели и геометрия отработали для этого же набора кадров.
        part.mark_input_done()
        self.parts.append(part)
        self._record_frame_analysis("INPUT", part.id, result)
        print(f"[INSPECT] Деталь #{part.id}")

        self._last_vision_results.update(result.vision_results)
        self._last_rule_results.extend(result.rule_results)

        if self.archive:
            self.archive.store_frames(
                part_id=part.id,
                stage="inspect",
                raw_frames=result.raw_frames,
                annotated_frames=result.annotated,
                raw_overlay_frames=result.raw_overlay_frames,
                run_frames=getattr(result, "run_frames", None),
                run_rule_results=getattr(result, "run_rule_results", None),
                run_vision_results=getattr(result, "run_vision_results", None),
            )
        self._set_process(
            "INSPECT_RESULT_RECORDED",
            "Инспекция: решение стадии записано",
            part_id=part.id,
            positions=[self.OFFSET_INSPECT],
        )

        print(
            f"[INSPECT] Деталь #{part.id} "
            f"дефекты: {result.defects or ['none']} "
            f"категория={part.route_category}"
        )
        return result

    # Distributor flow

    def _find_pending_drop(self):
        """Вернуть корпус на +3, который на следующем шаге пройдёт заслонки."""
        for part in self.parts:
            if part.step_created + self.OFFSET_REJECT == self.current_step:
                return part
        return None

    def _prepare_drop(self):
        part = self._pending_drop
        if part is None:
            self.distributor.reset_target()
            return
        category = part.route_category
        if category == CATEGORY_UNKNOWN:
            print(f"[WARN] Деталь #{part.id} не прошла полную инспекцию -> принудительно BAD")
            part.route_category, part.final_decision, category = CATEGORY_BAD, "incomplete_inspection", CATEGORY_BAD
        # GOOD: DIST1=0. BAD/CLEANUP: сначала DIST2, затем DIST1=340.
        self.distributor.prepare_route(category, part.id)

    def _execute_drop(self):
        part = self._pending_drop
        if part is None:
            return
        category = part.route_category
        self.distributor.confirm_transfer(part.id, category)
        if category == CATEGORY_GOOD:
            self.good_count += 1
            print(f"[PASS] #{part.id} -> GOOD ({self.good_count})")
        elif category == CATEGORY_BAD:
            self.bad_count += 1
            print(f"[REJECT] #{part.id} -> BAD ({self.bad_count})")
        elif category == CATEGORY_CLEANUP:
            self.cleanup_count += 1
            print(f"[CLEANUP] #{part.id} -> CLEANUP ({self.cleanup_count})")
        self._archive_part(part)
        self._set_process(
            "FINAL_DECISION_ARCHIVED",
            f"Финальное решение #{part.id}: {category} записано в архив",
            part_id=part.id,
            positions=[self.OFFSET_REJECT],
        )
        self._register_finished(part)
        self._remove_part(part)
        self._pending_drop = None

    # Archive

    def _archive_part(self, part, extra=None):
        if not self.archive:
            return
        kwargs = {
            "part_id": part.id,
            "category": part.route_category,
            "decision": part.final_decision,
            "defects": part.get_all_defects(),
            "step": part.step_created,
        }
        archive_extra = {}
        consensus = getattr(part, "inspection_consensus", None)
        if consensus:
            archive_extra["inspection_consensus"] = consensus
        if extra:
            archive_extra.update(extra)
        if archive_extra:
            kwargs["extra"] = archive_extra
        self.archive.finalize(**kwargs)

    def _archive_inflight(self, reason: str):
        for part in list(self.parts):
            if part.route_category == CATEGORY_UNKNOWN:
                part.route_category = CATEGORY_BAD
            part.final_decision = f"aborted_{reason}"
            try:
                self._archive_part(
                    part,
                    extra={"aborted": True, "abort_reason": reason},
                )
            except Exception as e:
                print(f"[ARCHIVE] Failed to archive aborted part #{part.id}: {e}")
            self._remove_part(part)
        self._pending_drop = None

    # Helpers

    def _remove_part(self, part):
        if part in self.parts:
            self.parts.remove(part)

    def _register_finished(self, part):
        record = {
            "id":       part.id,
            "decision": part.final_decision,
            "category": part.route_category,
            "time":      time.time(),
        }
        # UI получает только лёгкую ссылку на архивную запись.
        if self.archive:
            archive_info = self.archive.get_part_info(part.id)
            if archive_info:
                record["batch_id"] = self.archive.batch_id
                record["archive_folder"] = archive_info.get("relative_folder")
        self.recent_parts.append(record)

    # Анализ кадра зоны инспекции
