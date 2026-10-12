"""Один производственный шаг линии.

Часть ``ProductionCycle``: MOTION → SETTLE → инспекция по стадиям →
REVIEW → PUBLISH, плюс пауза и выброс корпуса на +7.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from core.state_machine import State
from domain.part import (
    Part,
    CATEGORY_GOOD,
    CATEGORY_BAD,
    CATEGORY_CLEANUP,
    CATEGORY_UNKNOWN,
)


class CycleStepMixin:
    """Последовательный шаг ленты, инспекции и распределителя."""

    def _check_motion_cancelled(self):
        if self._cancel_motion.is_set() or self.sm.force_exit:
            raise RuntimeError("physical operation cancelled")

    # Core step

    def _run_once(self):
        """Один шаг линии: движение, затухание, съёмка, анализ, публикация.

        Инспекция двух занятых позиций (вход и контроль) считается
        параллельно: кадры снимаются подряд, модели и правила — в двух
        потоках, записи — в порядке вход → контроль.

        Владелец камер меняется только на границах фаз, поэтому кадры для
        defect rules физически не могут быть сняты во время движения.
        """
        self._check_motion_cancelled()
        print(f"\nШАГ {self.current_step + 1}")

        # Право принять INPUT фиксируется до движения: если STOP придёт уже
        # во время проезда, вошедшая этим шагом деталь всё равно будет
        # проинспектирована и останется синхронной со своей ячейкой.
        accept_input_for_this_step = self.sm.accepts_new_parts

        self._last_vision_results = {}
        self._last_rule_results = []

        # Сначала механика, затем инспекция. Занята одна позиция — она
        # проходит целиком (кадр → модели → геометрия → решение →
        # запись). Заняты обе (вход и контроль) — кадры снимаются подряд
        # в одном блоке заморозки, а анализ обеих стадий идёт параллельно;
        # записи применяются в порядке INPUT → SPIDER.
        pending_id = self._stage_motion()
        self._stage_settle(pending_id)
        self._check_pause_barrier()
        display_frames = self._inspect_occupied_stages(
            accept_input_for_this_step,
        )
        self._stage_review(display_frames)
        self._stage_publish(display_frames)

    def _stage_motion(self):
        """MOTION: подготовить маршрут и переместить ленту на шаг."""
        self.stages.enter_motion()
        self._inspection_display_roles = ()
        # Разметка прошлого шага построена по статичному кадру и на
        # движущемся изображении указывала бы мимо детали.
        try:
            self.live.clear_overlays()
        except Exception as exc:
            print(f"[LIVE] Не удалось снять разметку: {exc}")

        if self._await_initial_inspection:
            # Деталь уже стоит под входными камерами: сначала её контроль,
            # движение ленты начнётся со следующего шага. Счётчик шагов не
            # увеличивается — физическая позиция не изменилась.
            self._await_initial_inspection = False
            self._set_process(
                "INITIAL_INSPECTION",
                "Корпус уже под камерами: контроль без движения ленты",
            )
            self._check_motion_cancelled()
            return None

        self._pending_drop = self._find_pending_drop()
        pending_id = self._pending_drop.id if self._pending_drop else None
        self._set_process(
            "ROUTE_PREPARE",
            "Подготовка маршрута распределителя",
            part_id=pending_id,
        )
        self._prepare_drop()
        self._check_motion_cancelled()

        self._set_process(
            "CONVEYOR_COMMAND",
            "Команда движения ленты отправлена",
            part_id=pending_id,
        )
        self.conveyor.move_step()
        self.conveyor.wait_stop(progress_callback=self._on_conveyor_progress)
        self._check_motion_cancelled()
        # Логическая позиция фиксируется только после подтверждения
        # физического завершения движения.
        self.current_step += 1
        return pending_id

    def _stage_settle(self, pending_id):
        """SETTLE: подтвердить передачу корпуса и погасить вибрацию."""
        self._set_process(
            "CONVEYOR_CONFIRMED", "Позиции корпусов подтверждены контроллером",
            part_id=pending_id,
        )
        if self._pending_drop is not None:
            self._set_process(
                "PART_TRANSFER", "Корпус прошёл распределитель",
                part_id=pending_id,
            )
        self._execute_drop()
        self._check_motion_cancelled()
        self._set_process("SETTLE", "Ожидание затухания вибрации перед съёмкой")
        self.stages.enter_settle()
        self._check_motion_cancelled()

    def _occupied_inspection_stages(self, accept_input_for_this_step: bool):
        """Занятые стадии этого шага в фиксированном порядке INPUT → SPIDER."""
        stages = []
        if accept_input_for_this_step:
            stages.append(("INPUT", tuple(self.inspector.INPUT_ROLES)))
        if any(
            part.step_created + self.OFFSET_SPIDER == self.current_step
            for part in self.parts
        ):
            stages.append(("SPIDER", tuple(self.inspector.SPIDER_ROLES)))
        return stages

    def _inspect_occupied_stages(self, accept_input_for_this_step: bool):
        """Инспекция занятых стадий шага.

        Занята одна позиция — прежний строгий порядок: кадр → модели →
        геометрия → решение → запись. Заняты обе (корпус на входе и
        корпус на контроле) — кадры обеих позиций снимаются подряд в
        одном блоке заморозки, а модели, геометрия и правила считаются
        параллельно; решения и записи применяются в том же порядке:
        сначала вход, затем контроль.

        Live заморожен на весь блок.
        """
        stages = self._occupied_inspection_stages(accept_input_for_this_step)
        if len(stages) > 1:
            return self._inspect_stages_parallel(stages)
        return self._inspect_stages_sequential(stages)

    def _inspect_stages_sequential(self, stages):
        """Стадии по одной: каждая целиком до старта следующей."""
        display_frames = {}
        if not stages:
            self.stages.enter_capture(())
            self.stages.enter_analysis()
            return display_frames

        for name, roles in stages:
            frames = self._stage_capture(roles)
            self.stages.enter_analysis()
            if name == "INPUT":
                self._set_process(
                    "INPUT_ANALYSIS",
                    "Вход: модели и правила по свежему кадру",
                )
                result = self._run_input_stage(frames)
            elif name == "SPIDER":
                self._set_process(
                    "SPIDER_CHECK",
                    "Проверка корпуса на +4: свежий кадр",
                )
                result = self._run_spider_stage(frames)
            else:
                raise RuntimeError(f"Неизвестная стадия инспекции: {name}")
            if result is not None:
                display_frames.update(result.raw_frames or {})
                self._refresh_monitor(display_frames)
            self._check_motion_cancelled()
        return display_frames

    def _inspect_stages_parallel(self, stages):
        """Вход и контроль одновременно: кадры подряд, анализ в два потока.

        Лента на инспекционном блоке стоит, поэтому кадры обеих позиций
        снимаются один за другим (USB-чтения всё равно последовательны),
        а модели, геометрия и правила входа и контроля считаются в двух
        потоках — стадии не ждут друг друга. Общее состояние цикла
        (Part, счётчики, архив) меняет только поток шага: результаты
        применяются после анализа и в фиксированном порядке вход →
        контроль.
        """
        roles = tuple(dict.fromkeys(
            role for _name, stage_roles in stages for role in stage_roles
        ))
        self._inspection_display_roles = tuple(dict.fromkeys(
            (*self._inspection_display_roles, *roles)
        ))
        self.stages.enter_capture(roles)
        self._set_process(
            "CAMERA_CAPTURE",
            f"Захват камер обеих позиций: {', '.join(roles)}",
            capture_roles=roles,
        )
        frames = {}
        for _name, stage_roles in stages:
            frames.update(self._capture_stage_frames(tuple(stage_roles)))
        self._check_motion_cancelled()
        self._refresh_monitor(frames)
        self.stages.enter_analysis()

        input_part = self._begin_input_stage()
        spider_part = self._find_spider_part()
        if spider_part is not None:
            self._set_process(
                "SPIDER_ANALYSIS",
                f"Контроль корпуса #{spider_part.id}",
                part_id=spider_part.id,
            )
        self._set_process(
            "PARALLEL_ANALYSIS",
            "Вход и контроль: модели и правила обеих позиций параллельно",
        )

        stage_frames = {
            name: {role: frames[role] for role in stage_roles}
            for name, stage_roles in stages
        }
        input_result, spider_result = self._analyze_stages_parallel(
            input_part,
            spider_part,
            stage_frames,
        )

        display_frames = {}
        if input_result is not None:
            self._apply_input_result(input_part, input_result)
            display_frames.update(input_result.raw_frames or {})
        if spider_result is not None:
            self._apply_spider_result(spider_part, spider_result)
            display_frames.update(spider_result.raw_frames or {})
        if display_frames:
            self._refresh_monitor(display_frames)
        self._check_motion_cancelled()
        return display_frames

    def _analyze_stages_parallel(self, input_part, spider_part, stage_frames):
        """Модели и правила входа и контроля в двух потоках.

        Потоки только считают: Part, счётчики и архив остаются у потока
        шага. Порядок обработки ошибок прежний — сбой входа отменяет
        корпус, сбой контроля оставляет результат входа записанным.
        """
        input_error = None
        spider_error = None
        input_result = None
        spider_result = None
        pool = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="inspection",
        )
        try:
            input_future = pool.submit(
                self.inspector.inspect_input,
                part_id=input_part.id,
                step=self.current_step,
                frames=stage_frames["INPUT"],
            )
            spider_future = None
            if spider_part is not None:
                spider_future = pool.submit(
                    self.inspector.inspect_spider,
                    part_id=spider_part.id,
                    step=self.current_step,
                    frames=stage_frames["SPIDER"],
                )
            try:
                input_result = input_future.result()
            except Exception as exc:                       # noqa: BLE001
                input_error = exc
            if spider_future is not None:
                try:
                    spider_result = spider_future.result()
                except Exception as exc:                   # noqa: BLE001
                    spider_error = exc
        finally:
            pool.shutdown(wait=True)

        if input_error is not None:
            # Сбой инспекции не оставляет неучтённый корпус в очереди:
            # FAULT — терминальное состояние, учёт строится с нуля.
            self.parts.remove(input_part)
            raise input_error
        if spider_error is not None:
            # Результат входа уже готов: он записывается, как и при
            # последовательном проходе, а сбой контроля уводит шаг в FAULT.
            if input_result is not None:
                self._apply_input_result(input_part, input_result)
                self._refresh_monitor(input_result.raw_frames or {})
            raise spider_error
        return input_result, spider_result

    def _stage_capture(self, roles):
        """CAPTURE: последовательный frozen snapshot одной стадии."""
        roles = tuple(roles or ())
        self._inspection_display_roles = tuple(dict.fromkeys(
            (*self._inspection_display_roles, *roles)
        ))
        self.stages.enter_capture(roles)
        self._set_process(
            "CAMERA_CAPTURE",
            (
                f"Последовательный захват камер: {', '.join(roles)}"
                if roles else "Нет корпуса под инспекционными камерами"
            ),
            capture_roles=roles,
        )
        if not roles:
            return {}
        frames = self._capture_stage_frames(roles)
        # Exclusive-блок не отпускаем: live не должен затирать стоп-кадр
        # во время моделей, геометрии и ревью.
        self._refresh_monitor(frames)
        return frames

    def _capture_stage_frames(self, roles):
        """Кадры стадии: драйверный буфер сбрасывается перед чтением.

        Драйвер может отдать старый кадр из буфера после движения,
        поэтому роли стадии дренируются и читаются строго по одной.
        """
        roles = tuple(roles)
        self.cameras.drain_buffers(roles)
        frames = self.cameras.capture_roles(roles)
        if set(frames) != set(roles):
            raise RuntimeError(
                f"Неполный набор кадров для инспекции: ожидались {sorted(roles)}, "
                f"получены {sorted(frames)}"
            )
        self._check_motion_cancelled()
        return frames

    def _stage_review(self, display_frames):
        """REVIEW: пауза на просмотр работы нейросетей после анализа.

        Кадры со статичной разметкой уже опубликованы и остаются на
        экране, а лента стоит: даётся время отсмотреть результат
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
                )
            time.sleep(min(0.1, max(remaining, 0.01)))
        # FORCE EXIT во время паузы сбрасывает цепочку фаз: выходить нужно
        # штатной ошибкой отмены до входа в PUBLISH, а не сбросом шага.
        self._check_motion_cancelled()

    def _stage_publish(self, display_frames):
        """PUBLISH: маршрут годных деталей и вывод результата на экран."""
        self.stages.enter_publish()

        self._set_process("STEP_COMPLETE", "Шаг полностью завершён")
        self._refresh_monitor(display_frames)

    # Пауза

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
        try:
            self.live.clear_overlays()
        except Exception as exc:
            print(f"[LIVE] Не удалось снять разметку: {exc}")
        print("[PAUSE] линия остановлена на границе шага после полной остановки")
        self._set_process(
            "PAUSED",
            "Пауза: доступна ручная коррекция ленты с помощью JOG",
        )

    def _stop_pause_frame_loop(self):
        if not self._pause_frame_active:
            return
        self._pause_frame_active = False
        try:
            self.exit_jog()
        except Exception as exc:
            print(f"[PAUSE] Не удалось выйти из JOG: {exc}")

    # INPUT

    def _begin_input_stage(self):
        """Корпус входит в учёт до запуска моделей.

        Корпус физически стоит на +0 с момента остановки ленты, поэтому
        попадает в учёт ДО запуска моделей: HMI видит его в зоне входа на
        весь анализ (и дальше — пока идёт SPIDER), а не «внезапно» на +1
        после следующего хода. Модель позиций не меняется: step_created
        прежний — тот же шаг, на котором лента остановила корпус на +0.
        """
        candidate_id = self.part_counter + 1
        part = Part(candidate_id, self.current_step)
        self.parts.append(part)
        self._set_process(
            "INPUT_ANALYSIS",
            f"Вход: анализ кандидата #{candidate_id}",
            part_id=candidate_id,
        )
        return part

    def _run_input_stage(self, frames):
        """INPUT одной стадией: анализ по кадру и запись решения."""
        part = self._begin_input_stage()
        try:
            result = self.inspector.inspect_input(
                part_id=part.id,
                step=self.current_step,
                frames=frames,
            )
        except Exception:
            # Сбой инспекции не оставляет неучтённый корпус в очереди:
            # FAULT — терминальное состояние, учёт строится с нуля.
            self.parts.remove(part)
            raise
        self._apply_input_result(part, result)
        return result

    def _apply_input_result(self, part, result):
        """Записать решение INPUT в учёт: только поток шага."""
        if result.is_empty_tray:
            # Пустой лоток остаётся нейтральным: Part и архив не создаются.
            self.parts.remove(part)
            self.empty_count += 1
            # Очищаем детекции для входных камер, чтобы не рисовать
            # прямоугольники на пустом лотке.
            for role in self.inspector.INPUT_ROLES:
                self._last_vision_results[role] = []
            self._last_rule_results.extend(result.rule_results or [])
            self._set_process(
                "INPUT_RESULT_RECORDED",
                "INPUT: пустой лоток записан",
            )
            print(
                f"[EMPTY] Пустой лоток на step {self.current_step} "
                f"(total empty: {self.empty_count})"
            )
            return

        self.part_counter += 1
        for defect in result.defects:
            part.add_input_defect(defect)
        # Результат правила становится состоянием Part только после того,
        # как модели и геометрия отработали для этого же набора кадров.
        part.mark_input_done()
        print(f"[INPUT] Деталь #{part.id}")

        self._last_vision_results.update(result.vision_results or {})
        self._last_rule_results.extend(result.rule_results or [])

        self._store_stage_frames(part.id, result)
        self._set_process(
            "INPUT_RESULT_RECORDED",
            "INPUT: решение стадии записано",
            part_id=part.id,
        )

        print(
            f"[INPUT] Деталь #{part.id} "
            f"дефекты: {result.defects or ['none']}"
        )

    # SPIDER/TOP

    def _find_spider_part(self):
        """Корпус на позиции контроля (+4) в этом шаге, если он есть."""
        for part in self.parts:
            if part.step_created + self.OFFSET_SPIDER == self.current_step:
                return part
        # На позиции +4 в этом шаге детали нет.
        return None

    def _run_spider_stage(self, frames):
        """SPIDER/TOP одной стадией: анализ по кадру и решение корпуса."""
        part = self._find_spider_part()
        if part is None:
            return None
        self._set_process(
            "SPIDER_ANALYSIS",
            f"Контроль корпуса #{part.id}",
            part_id=part.id,
        )
        result = self.inspector.inspect_spider(
            part_id=part.id,
            step=self.current_step,
            frames=frames,
        )
        self._apply_spider_result(part, result)
        return result

    def _apply_spider_result(self, part, result):
        """Записать решение контроля в учёт: только поток шага."""
        for defect in result.defects:
            part.add_spider_defect(defect)
        # После SPIDER это уже окончательное решение Part: обе стадии
        # прошли модели и геометрию, поэтому маршрут можно зафиксировать.
        part.mark_spider_done()

        self._last_vision_results.update(result.vision_results or {})
        self._last_rule_results.extend(result.rule_results or [])

        self._store_stage_frames(part.id, result)
        self._set_process(
            "SPIDER_RESULT_RECORDED",
            "SPIDER/TOP: окончательное решение записано",
            part_id=part.id,
        )

        print(
            f"[SPIDER] Деталь #{part.id} "
            f"дефекты: {result.defects or ['none']} "
            f"категория={part.route_category}"
        )

    # Распределитель

    def _find_pending_drop(self):
        """Вернуть корпус на +7, который на следующем шаге пройдёт заслонки."""
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
            print(
                f"[WARN] Деталь #{part.id} не прошла полную инспекцию "
                "-> принудительно BAD"
            )
            part.route_category = CATEGORY_BAD
            part.final_decision = "incomplete_inspection"
            category = CATEGORY_BAD
        # GOOD: DIST1=0. BAD/CLEANUP: DIST1=340 и DIST2->канал едут
        # одновременно (см. _move_parallel в hardware/distributor.py).
        self.distributor.prepare_route(category, part.id)

    def _execute_drop(self):
        part = self._pending_drop
        if part is None:
            return
        category = part.route_category
        # Шаг ленты уже закончился. Заслонки остаются как есть до
        # ROUTE_PREPARE следующего шага, поэтому ждать падение отдельно
        # не нужно: к следующей смене маршрута корпус давно ушёл.
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
        else:
            print(f"[WARN] Деталь #{part.id} неизвестная категория {category} -> BAD")
            part.route_category = CATEGORY_BAD
            category = CATEGORY_BAD
            self.bad_count += 1
        archived = self._archive_part(part)
        if archived:
            self._set_process(
                "FINAL_DECISION_ARCHIVED",
                f"Финальное решение #{part.id}: {category} записано в архив",
                part_id=part.id,
            )
        else:
            self._set_process(
                "FINAL_DECISION_NOT_ARCHIVED",
                f"Финальное решение #{part.id}: {category}; "
                "запись в архив не выполнена",
                part_id=part.id,
            )
        self._register_finished(part)
        self._remove_part(part)
        self._pending_drop = None

    def _store_stage_frames(self, part_id, result):
        """Кадры стадии в архив. Сбой диска не откатывает решение Part."""
        if not self.archive or result is None:
            return
        try:
            self.archive.store_frames(
                part_id=part_id,
                raw_frames=result.raw_frames or {},
                annotated_frames=result.annotated or {},
                raw_overlay_frames=result.raw_overlay_frames or {},
            )
        except Exception as exc:
            print(f"[ARCHIVE] Не удалось сохранить кадры #{part_id}: {exc}")
