"""Последовательность фоновой инициализации production-системы (3 камеры).

Сохранена проверенная на линии последовательность трёхкамерника:
открытие камер -> стартовый прогрев с восстановлением слабых ролей ->
загрузка и прогрев моделей -> настройка контроля -> контроллер ->
оборудование -> homing -> создание цикла -> повторный прогрев перед
preview -> получение начальных кадров -> запуск цикла.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Callable

from application.callbacks import (
    bind_cycle_callbacks,
    bind_inspection_callbacks,
)
from application.status import make_idle_status


_FAILED = object()
INITIAL_CAMERA_FRAMES_TIMEOUT = 20.0


class StartupDisplayError(RuntimeError):
    """Ошибка, текст которой уже подготовлен для splash-экрана."""


def env_clamped_float(
    name: str, default: float, minimum: float, maximum: float,
) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        print(f"[CONFIG] {name}={raw!r} не число, используется {default}")
        value = default
    return max(minimum, min(maximum, value))


def weak_camera_warmup_reasons(stats: dict) -> dict:
    """Вернуть роли, не отдавшие ни одного кадра во время прогрева."""
    reasons = {}
    for role, row in (stats or {}).items():
        try:
            reads = int(row.get("reads", 0) or 0)
        except Exception:
            reads = 0
        if reads <= 0:
            reasons[role] = "нет кадров"
    return reasons


def format_warmup_reasons(reasons: dict) -> str:
    return "; ".join(
        f"{role}: {reason}" for role, reason in sorted(reasons.items())
    )


def recover_weak_cameras_after_warmup(cameras, stats: dict, phase: str) -> dict:
    """Повторно прогреть роли без кадров и проверить их готовность.

    Если менеджер поддерживает ``reopen_roles``, после неудачного прогрева
    выполняется попытка переоткрытия. Текущий CameraManager возвращает
    неуспех и запуск завершается ошибкой.
    """
    reasons = weak_camera_warmup_reasons(stats)
    if not reasons:
        return stats

    roles = tuple(reasons)
    retry_seconds = env_clamped_float(
        "CAMERA_RECOVERY_WARMUP_SECONDS", 2.5, 0.2, 10.0,
    )
    print(
        f"[CAMERA] {phase}: слабый прогрев "
        f"({format_warmup_reasons(reasons)}); повторно прогреваем "
        f"{', '.join(roles)} {retry_seconds:.1f}с"
    )
    retry_stats = cameras.warmup_roles(roles, duration=retry_seconds)
    retry_reasons = weak_camera_warmup_reasons(retry_stats)
    merged = dict(stats or {})
    merged.update(retry_stats)
    if not retry_reasons:
        return merged

    reopen = getattr(cameras, "reopen_roles", None)
    if reopen is None:
        raise RuntimeError(
            f"Камеры не стабилизировались после прогрева ({phase}): "
            f"{format_warmup_reasons(retry_reasons)}"
        )
    stuck = tuple(retry_reasons)
    print(
        f"[CAMERA] {phase}: повторный прогрев не помог "
        f"({format_warmup_reasons(retry_reasons)}); "
        f"пересоздаём потоки {', '.join(stuck)}"
    )
    reopened = reopen(stuck)
    final_stats = cameras.warmup_roles(stuck, duration=retry_seconds)
    merged.update(final_stats)
    final_reasons = weak_camera_warmup_reasons(final_stats)
    if final_reasons:
        not_reopened = ", ".join(
            role for role in stuck if not reopened.get(role)
        )
        hint = (
            f" (поток не пересоздался: {not_reopened})"
            if not_reopened
            else ""
        )
        raise RuntimeError(
            f"Камеры не стабилизировались после прогрева ({phase}): "
            f"{format_warmup_reasons(final_reasons)}{hint}"
        )
    recovered = ", ".join(role for role in stuck if reopened.get(role))
    print(
        f"[CAMERA] {phase}: камеры восстановлены пересозданием "
        f"потока: {recovered or '—'}"
    )
    return merged


class SystemInitializer:
    """Выполняет startup-этапы и публикует их состояние в HMI."""

    def __init__(
        self,
        runtime,
        factory,
        exit_coordinator,
        *,
        thread_factory=threading.Thread,
        sleep: Callable[[float], None] = time.sleep,
        initial_camera_frames_timeout: float = INITIAL_CAMERA_FRAMES_TIMEOUT,
    ):
        self.runtime = runtime
        self.factory = factory
        self.exit_coordinator = exit_coordinator
        self._thread_factory = thread_factory
        self._sleep = sleep
        self.initial_camera_frames_timeout = max(
            0.0, float(initial_camera_frames_timeout)
        )

    @property
    def monitor(self):
        return self.runtime.monitor

    def run(self) -> None:
        try:
            self._ensure_active()
            calibration = self.factory.load_calibration()
            self._ensure_active()

            cameras = self._run_step(
                "cameras",
                "Открытие камер",
                self._initialize_cameras,
                done=lambda value: f"Открыто камер: {len(value.cameras)}",
                error=lambda exc: f"Ошибка камеры: {exc}",
                on_error=self._log_camera_error,
            )
            if cameras is _FAILED:
                return

            warmed = self._run_step(
                "camera_warmup",
                "Прогрев камер",
                self._warmup_cameras,
                done=lambda stats: (
                    f"Прогрев камер: "
                    f"{sum(s.get('reads', 0) for s in stats.values())} кадров"
                ),
                error=lambda exc: f"Ошибка прогрева камер: {exc}",
            )
            if warmed is _FAILED:
                return

            vision = self._run_step(
                "models_load",
                "Загрузка моделей",
                self.factory.create_vision,
                done=lambda value: f"Загружено моделей: {len(value.models)}",
                error=lambda exc: f"Ошибка загрузки моделей: {exc}",
            )
            if vision is _FAILED:
                return

            warmed_models = self._run_step(
                "models_warm",
                "Прогрев моделей",
                lambda: self._warmup_models(vision),
                done="Прогрев завершён",
                error=lambda exc: f"Ошибка прогрева моделей: {exc}",
            )
            if warmed_models is _FAILED:
                return

            inspection = self._run_step(
                "inspection",
                "Настройка системы контроля",
                lambda: self._initialize_inspection(vision),
                done=lambda value: (
                    f"Настроено правил: {len(value.decision.rules)}"
                ),
                error=lambda exc: f"Ошибка настройки контроля: {exc}",
            )
            if inspection is _FAILED:
                return

            serial_info = self._run_step(
                "serial",
                "Поиск контроллера",
                self._initialize_serial,
                done=lambda value: f"Контроллер: {value[0]} @ {value[1]}",
                error=self._serial_error,
            )
            if serial_info is _FAILED:
                return

            hardware = self._run_step(
                "hardware",
                "Инициализация оборудования",
                lambda: self.factory.create_hardware(
                    self.runtime.transport,
                    calibration,
                    self.runtime.shutdown_requested.is_set,
                ),
                done="Лента и две оси инициализированы",
                error=lambda exc: f"Ошибка оборудования: {exc}",
            )
            if hardware is _FAILED:
                return

            cycle = self._run_step(
                "cycle",
                "Создание производственного цикла",
                lambda: self._initialize_cycle(
                    cameras=cameras,
                    inspection=inspection,
                    hardware=hardware,
                    calibration=calibration,
                ),
                error=lambda exc: f"Ошибка создания цикла: {exc}",
            )
            if cycle is _FAILED:
                return

            pre_preview = self._run_step(
                "preview",
                "Получение начальных кадров",
                self._initial_preview,
                done="Начальные кадры получены",
                error=lambda exc: f"Ошибка получения начальных кадров: {exc}",
            )
            if pre_preview is _FAILED:
                return

            self._ensure_active()

            ready = self._run_step(
                "ready",
                "Запуск системы",
                lambda: self._start_cycle(cycle),
                done="Система готова к работе",
                error=str,
            )
            if ready is _FAILED:
                return

            self._sleep(0.6)
            self.monitor.boot_complete()
        except Exception as exc:
            traceback.print_exc()
            current = self.monitor.server.boot_current or "init"
            self.monitor.boot_step_error(current, str(exc))
            self._report_failure()

    def _run_step(
        self,
        key: str,
        label: str,
        action: Callable[[], object],
        *,
        done=None,
        error: Callable[[Exception], str],
        on_error: Callable[[Exception], None] | None = None,
    ):
        self.monitor.boot_step_start(key, label)
        try:
            result = action()
        except Exception as exc:
            if on_error is not None:
                on_error(exc)
            self.monitor.boot_step_error(key, error(exc))
            self._report_failure()
            return _FAILED

        message = done(result) if callable(done) else done
        self.monitor.boot_step_done(key, message)
        self._ensure_active()
        return result

    def _initialize_cameras(self):
        cameras = self.factory.create_cameras()
        self.runtime.cameras = cameras
        self.monitor.set_camera_roles(cameras.mapping)
        return cameras

    def _warmup_cameras(self):
        warmup_seconds = env_clamped_float(
            "CAMERA_WARMUP_SECONDS", 2.5, 0.5, 10.0,
        )
        stats = self.runtime.cameras.warmup_all(duration=warmup_seconds)
        return recover_weak_cameras_after_warmup(
            self.runtime.cameras, stats, "стартовый прогрев",
        )

    @staticmethod
    def _warmup_models(vision):
        vision.warmup()
        return vision

    def _initialize_inspection(self, vision):
        services = self.factory.create_inspection(vision)
        self.runtime.archive = services.archive
        bind_inspection_callbacks(self.runtime, services)
        return services

    def _initialize_serial(self) -> tuple[str, int]:
        serial_baud = int(os.environ.get("SERIAL_BAUD", "115200"))
        preferred_port = os.environ.get("SERIAL_PORT")
        found_port, port_message = self.factory.discover_controller(
            baudrate=serial_baud,
            preferred_port=preferred_port,
        )
        if found_port is None:
            raise StartupDisplayError(port_message)

        transport = self.factory.create_transport(
            port=found_port,
            baudrate=serial_baud,
        )
        self.runtime.transport = transport
        transport.send("G1")
        transport.send("G25")
        return found_port, serial_baud

    @staticmethod
    def _serial_error(exc: Exception) -> str:
        if isinstance(exc, StartupDisplayError):
            return str(exc)
        return f"Ошибка последовательного порта: {exc}"

    def _initialize_cycle(
        self,
        *,
        cameras,
        inspection,
        hardware,
        calibration: dict,
    ):
        self._ensure_active()
        print("[HARDWARE] Homing distributor axes...")
        hardware.distributor.initialize()
        self._ensure_active()

        cycle = self.factory.create_cycle(
            hardware=hardware,
            cameras=cameras,
            inspector=inspection.inspector,
            monitor=self.monitor,
            archive=inspection.archive,
            calibration=calibration,
        )
        self.runtime.cycle = cycle
        bind_cycle_callbacks(
            self.monitor,
            cycle,
            self.exit_coordinator.request_exit,
        )
        return cycle

    def _initial_preview(self):
        # Некоторые UVC-камеры после простоя снова отдают пустые/тёмные
        # кадры; короткой паузы боковой камеры не всегда хватало.
        quick = env_clamped_float(
            "CAMERA_PRE_PREVIEW_WARMUP_SECONDS", 2.5, 0.0, 5.0,
        )
        if quick > 0.0:
            stats = self.runtime.cameras.warmup_all(duration=quick)
            recover_weak_cameras_after_warmup(
                self.runtime.cameras, stats, "прогрев перед preview",
            )

        preview_frames = self.runtime.cameras.capture_all()
        self.monitor.update(
            frames=preview_frames,
            vision_results={},
            rule_results=[],
            line_status=make_idle_status(self.runtime.cycle.distributor),
            recent_parts=[],
        )
        return preview_frames

    def _start_cycle(self, cycle):
        cycle_thread = self._thread_factory(
            target=cycle.start,
            daemon=True,
        )
        self.runtime.cycle_thread = cycle_thread
        cycle_thread.start()

        # В IDLE цикл автоматически входит в JOG для live-вида. Делаем это
        # до снятия splash, чтобы готовность означала не только три открытых
        # VideoCapture, но и первый корректный кадр от каждой роли.
        if not cycle.enter_jog():
            raise RuntimeError("Не удалось запустить стартовый просмотр камер")
        camera_roles = tuple(self.runtime.cameras.mapping)
        missing = cycle.live.wait_for_roles(
            camera_roles,
            timeout=self.initial_camera_frames_timeout,
        )
        if missing:
            detail = cycle.live.error
            message = "Нет первого кадра: " + ", ".join(missing)
            if detail:
                message += f"; {detail}"
            raise RuntimeError(message)

        self._ensure_active()
        return cycle_thread

    def _ensure_active(self) -> None:
        if self.runtime.shutdown_requested.is_set():
            raise RuntimeError("initialization cancelled by operator")

    @staticmethod
    def _log_camera_error(exc: Exception) -> None:
        print(
            f"[CAMERA] Ошибка инициализации: "
            f"{type(exc).__name__}: {exc}"
        )

    @staticmethod
    def _report_failure() -> None:
        """Оставить startup-ошибку на splash до решения оператора."""
        print("[INIT] Startup failed; waiting for operator to close the UI")
