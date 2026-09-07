"""Тестер скорости нейросетей: CPU против GPU на стенде с одной камерой.

Запуск (Windows):
    model_benchmark.bat
    .venv\\Scripts\\python.exe -m vision.model_benchmark
    .venv\\Scripts\\python.exe -m vision.model_benchmark --camera 0 --iterations 20
    .venv\\Scripts\\python.exe -m vision.model_benchmark --image frame.png --device cuda:0
    .venv\\Scripts\\python.exe -m vision.model_benchmark --group GROUP_4 --half
    .venv\\Scripts\\python.exe -m vision.model_benchmark --json bench.json

Сценарий стенда: подключена одна камера (роль ``TOP``). С неё берётся
кадр 1280x720, и через него прогоняются ВСЕ модели из
``vision/model_config.py`` — не только группа ``TOP``, а все 13 весов
линии. Каждая модель вызывается с теми же параметрами, что и в
production (``VisionCluster``: ``imgsz``, ``retina_masks``, ``conf``,
``iou``), поэтому цифры напрямую переносятся на реальную линию.

Для каждого устройства (``cpu``, ``cuda:0`` …) модели загружаются
заново: ultralytics привязывает predictor к устройству при первом
вызове, и «переключить» уже созданный кластер на GPU нельзя. Время
замеряется вокруг ``predict`` + разбор результата (``.cpu()``), то есть
включает пересылку данных с видеокарты — как в ``process_all``.

По умолчанию сравниваются ``cpu`` и ``cuda:0`` (если CUDA доступна).
Если torch собран без CUDA, инструмент сообщает об этом и печатает
команду переустановки — ``requirements.txt`` ставит CPU-сборку torch.

Инструмент ничего не изменяет и не требует контроллера, полного набора
камер или ``camera_mapping.json``.

Код выхода: 0 — замер выполнен; 1 — не удалось получить кадр, загрузить
модели или ни одно устройство не отработало.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from vision.camera_manager import CameraManager
from vision.model_config import MODEL_GROUPS, ROLE_TO_GROUP
from vision.vision_cluster import (
    AGGRESSIVE_IOU,
    AGGRESSIVE_IOU_ROLES,
    DEFAULT_IOU,
    INFERENCE_IMGSZ,
    VisionCluster,
)

BENCH_ROLE = "TOP"
DEFAULT_ITERATIONS = 10
DEFAULT_WARMUP = 3
DEFAULT_CAMERA_ID = 0
EXPECTED_SIZE = (1280, 720)
CAPTURE_DRAIN_COUNT = 5
CAPTURE_READ_ATTEMPTS = 30
CAPTURE_READ_INTERVAL = 0.03

CUDA_INSTALL_HINT = (
    "pip install --force-reinstall torch torchvision "
    "--index-url https://download.pytorch.org/whl/cu126"
)

# Сколько камер линии работает на каждой группе: сумма времён по группам с
# этими множителями даёт оценку inference одного полного шага на 7 камер.
GROUP_CAMERA_COUNT = {}
for _role, _group in ROLE_TO_GROUP.items():
    GROUP_CAMERA_COUNT[_group] = GROUP_CAMERA_COUNT.get(_group, 0) + 1


def _import_torch():
    """Ленивый импорт torch: тесты подменяют функцию, без torch — None."""
    try:
        import torch  # noqa: WPS433
    except Exception:  # noqa: BLE001
        return None
    return torch


def _import_ultralytics_version() -> str:
    try:
        import ultralytics  # noqa: WPS433
        return str(getattr(ultralytics, "__version__", "?"))
    except Exception:  # noqa: BLE001
        return "недоступен"


# ---------------------------------------------------------------------------
# Окружение и устройства
# ---------------------------------------------------------------------------

def collect_environment(torch_module) -> dict:
    """Собрать сведения о Python/torch/CUDA для шапки отчёта."""
    info = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "ultralytics": _import_ultralytics_version(),
        "torch": None,
        "torch_cuda_build": None,
        "cuda_available": False,
        "cuda_devices": [],
        "cpu_threads": os.cpu_count(),
        "torch_threads": None,
    }
    if torch_module is None:
        return info
    info["torch"] = str(getattr(torch_module, "__version__", "?"))
    version = getattr(torch_module, "version", None)
    info["torch_cuda_build"] = getattr(version, "cuda", None)
    try:
        info["torch_threads"] = int(torch_module.get_num_threads())
    except Exception:  # noqa: BLE001
        pass
    cuda = getattr(torch_module, "cuda", None)
    try:
        available = bool(cuda is not None and cuda.is_available())
    except Exception:  # noqa: BLE001
        available = False
    info["cuda_available"] = available
    if not available:
        return info
    try:
        count = int(cuda.device_count())
    except Exception:  # noqa: BLE001
        count = 0
    for index in range(count):
        entry = {"index": index, "name": f"cuda:{index}", "memory_gb": None}
        try:
            entry["name"] = str(cuda.get_device_name(index))
            props = cuda.get_device_properties(index)
            entry["memory_gb"] = round(props.total_memory / 1024 ** 3, 1)
        except Exception:  # noqa: BLE001
            pass
        info["cuda_devices"].append(entry)
    return info


def resolve_devices(requested: list[str] | None, env: dict) -> tuple[list[str], list[str]]:
    """Список устройств для замера и предупреждения.

    Без ``--device`` берутся ``cpu`` и ``cuda:0`` (если доступна). Явно
    запрошенные CUDA-устройства при отсутствии CUDA пропускаются с
    предупреждением, а не роняют весь замер: CPU-часть всё равно полезна.
    """
    warnings = []
    if not requested:
        devices = ["cpu"]
        if env.get("cuda_available"):
            devices.append("cuda:0")
        else:
            warnings.append(
                "CUDA недоступна: сравнение выполняется только на CPU. "
                + _cuda_reason(env)
            )
        return devices, warnings

    devices = []
    for device in dict.fromkeys(d.strip() for d in requested if d.strip()):
        if _is_cuda_device(device) and not env.get("cuda_available"):
            warnings.append(
                f"Устройство {device} пропущено: CUDA недоступна. " + _cuda_reason(env)
            )
            continue
        devices.append(device)
    return devices, warnings


def _is_cuda_device(device: str) -> bool:
    lowered = device.lower()
    return lowered.startswith("cuda") or lowered.isdigit()


def _cuda_reason(env: dict) -> str:
    if env.get("torch") is None:
        return "torch не установлен (pip install -r requirements.txt)."
    if not env.get("torch_cuda_build"):
        return (
            f"torch {env['torch']} собран без CUDA. "
            f"Поставьте CUDA-сборку: {CUDA_INSTALL_HINT}"
        )
    return (
        f"torch {env['torch']} собран с CUDA {env['torch_cuda_build']}, "
        "но драйвер/видеокарта не найдены. Проверьте nvidia-smi и драйвер NVIDIA."
    )


# ---------------------------------------------------------------------------
# Кадр
# ---------------------------------------------------------------------------

def load_image(path: str) -> np.ndarray:
    frame = cv2.imread(path, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(f"Не удалось прочитать изображение: {path}")
    height, width = frame.shape[:2]
    if (width, height) != EXPECTED_SIZE:
        print(
            f"[BENCH] Изображение {width}x{height} приведено к "
            f"{EXPECTED_SIZE[0]}x{EXPECTED_SIZE[1]} (формат камер линии)"
        )
        frame = cv2.resize(frame, EXPECTED_SIZE, interpolation=cv2.INTER_AREA)
    return frame


def open_camera(camera_id: int):
    """Открыть одну камеру в том же формате, что и CameraManager линии."""
    cap = cv2.VideoCapture(camera_id)
    if cap is None or not cap.isOpened():
        raise RuntimeError(f"Камера id={camera_id} не открылась (VideoCapture)")
    try:
        CameraManager._configure_capture(cap)
    except Exception as exc:  # noqa: BLE001
        print(f"[BENCH] Камера {camera_id}: настройки не применены: {exc}")
    return cap


def read_frame(cap, camera_id: int, drain: int = CAPTURE_DRAIN_COUNT) -> np.ndarray:
    """Сбросить буфер драйвера и вернуть первый валидный кадр 1280x720."""
    for _ in range(drain):
        cap.read()
    last_error = "кадр не получен"
    for _ in range(CAPTURE_READ_ATTEMPTS):
        ok, frame = cap.read()
        if not ok or frame is None:
            last_error = "read вернул пустой кадр"
            time.sleep(CAPTURE_READ_INTERVAL)
            continue
        error = CameraManager._frame_error(frame)
        if error is None:
            return frame
        last_error = error
        time.sleep(CAPTURE_READ_INTERVAL)
    raise RuntimeError(f"Камера id={camera_id}: {last_error}")


class FrameSource:
    """Источник кадров: файл или камера; закрывается через ``close``."""

    def __init__(self, image: str | None, camera_id: int):
        self.description = ""
        self._cap = None
        self._camera_id = camera_id
        self._static = None
        if image:
            self._static = load_image(image)
            self.description = f"файл {image}"
        else:
            self._cap = open_camera(camera_id)
            self.description = f"камера id={camera_id}"

    def grab(self) -> np.ndarray:
        if self._static is not None:
            return self._static
        return read_frame(self._cap, self._camera_id)

    def close(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None


class _StaticSource:
    """Замороженный кадр: одинаковый вход для всех устройств."""

    def __init__(self, frame: np.ndarray, description: str):
        self._frame = frame
        self.description = description

    def grab(self) -> np.ndarray:
        return self._frame

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Замер
# ---------------------------------------------------------------------------

def select_models(groups: list[str] | None) -> list[dict]:
    """Список записей моделей для замера, без дублей, в порядке конфига."""
    chosen = list(MODEL_GROUPS) if not groups else list(dict.fromkeys(groups))
    unknown = [g for g in chosen if g not in MODEL_GROUPS]
    if unknown:
        raise ValueError(
            f"Неизвестные группы: {unknown}; доступны: {list(MODEL_GROUPS)}"
        )
    entries = []
    seen = set()
    for group in chosen:
        for entry in MODEL_GROUPS[group]:
            if entry["path"] in seen:
                continue
            seen.add(entry["path"])
            entries.append({**entry, "group": group})
    return entries


def _predict_kwargs(entry: dict, device: str, half: bool) -> dict:
    """Параметры predict — один в один с ``VisionCluster.process_all``."""
    iou = AGGRESSIVE_IOU if BENCH_ROLE in AGGRESSIVE_IOU_ROLES else DEFAULT_IOU
    kwargs = {
        "device": device,
        "conf": entry["conf"],
        "imgsz": INFERENCE_IMGSZ,
        "iou": iou,
        "retina_masks": True,
        "verbose": False,
    }
    if half and _is_cuda_device(device):
        kwargs["half"] = True
    return kwargs


def _sync(torch_module, device: str):
    if torch_module is None or not _is_cuda_device(device):
        return
    try:
        torch_module.cuda.synchronize()
    except Exception:  # noqa: BLE001
        pass


def _summary(samples_ms: list[float]) -> dict:
    if not samples_ms:
        return {"median": None, "mean": None, "min": None, "max": None, "n": 0}
    return {
        "median": statistics.median(samples_ms),
        "mean": statistics.fmean(samples_ms),
        "min": min(samples_ms),
        "max": max(samples_ms),
        "n": len(samples_ms),
    }


def benchmark_device(
    device: str,
    entries: list[dict],
    source: FrameSource,
    iterations: int,
    warmup: int,
    half: bool = False,
    fresh_frames: bool = False,
    torch_module=None,
    cluster_factory=None,
    log=print,
) -> dict:
    """Загрузить все модели на ``device`` и прогнать замер.

    Возвращает словарь с временем загрузки, прогрева, выборками по каждой
    модели и суммарными показателями. Ошибка загрузки или inference
    возвращается полем ``error`` — остальные устройства продолжают замер.
    """
    factory = cluster_factory or (lambda dev: VisionCluster(device=dev, verbose=False))
    result = {
        "device": device,
        "half": bool(half and _is_cuda_device(device)),
        "load_s": None,
        "warmup_s": None,
        "models": [],
        "pass_ms": None,
        "pass_median_ms": None,
        "gpu_peak_memory_mb": None,
        "error": None,
    }

    log(f"[BENCH] === {device} ===")
    started = time.perf_counter()
    try:
        cluster = factory(device)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"загрузка моделей: {type(exc).__name__}: {exc}"
        log(f"[BENCH] {device}: {result['error']}")
        return result
    result["load_s"] = time.perf_counter() - started
    log(f"[BENCH] {device}: загружено {len(cluster.models)} моделей за {result['load_s']:.1f} с")

    if torch_module is not None and _is_cuda_device(device):
        try:
            torch_module.cuda.reset_peak_memory_stats()
        except Exception:  # noqa: BLE001
            pass

    try:
        frame = source.grab()

        # Прогрев: первый вызов predict создаёт predictor, компилирует ядра
        # CUDA и выделяет память — его время в статистику не попадает.
        started = time.perf_counter()
        for _ in range(max(0, warmup)):
            for entry in entries:
                model = cluster.models[entry["path"]]
                preds = model.predict(frame, **_predict_kwargs(entry, device, half))
                cluster._parse_predictions(preds)
                _sync(torch_module, device)
        result["warmup_s"] = time.perf_counter() - started
        log(f"[BENCH] {device}: прогрев {warmup}x за {result['warmup_s']:.1f} с")

        samples = {entry["path"]: [] for entry in entries}
        detections = {entry["path"]: 0 for entry in entries}
        pass_samples = []
        for iteration in range(iterations):
            if fresh_frames and iteration > 0:
                frame = source.grab()
            pass_started = time.perf_counter()
            for entry in entries:
                model = cluster.models[entry["path"]]
                kwargs = _predict_kwargs(entry, device, half)
                tick = time.perf_counter()
                preds = model.predict(frame, **kwargs)
                parsed = cluster._parse_predictions(preds)
                _sync(torch_module, device)
                samples[entry["path"]].append((time.perf_counter() - tick) * 1000.0)
                detections[entry["path"]] = len(parsed)
            pass_samples.append((time.perf_counter() - pass_started) * 1000.0)
            log(
                f"[BENCH] {device}: итерация {iteration + 1}/{iterations} — "
                f"{pass_samples[-1]:.0f} мс на {len(entries)} моделей"
            )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"inference: {type(exc).__name__}: {exc}"
        log(f"[BENCH] {device}: {result['error']}")
    else:
        for entry in entries:
            path = entry["path"]
            result["models"].append({
                "path": path,
                "group": entry["group"],
                "detections": detections[path],
                **_summary(samples[path]),
            })
        result["pass_ms"] = _summary(pass_samples)
        result["pass_median_ms"] = result["pass_ms"]["median"]

    if torch_module is not None and _is_cuda_device(device):
        try:
            result["gpu_peak_memory_mb"] = (
                torch_module.cuda.max_memory_allocated() / 1024 ** 2
            )
        except Exception:  # noqa: BLE001
            pass

    # Освобождение перед следующим устройством: модели предыдущего кластера
    # не должны занимать видеопамять или мешать замеру CPU.
    del cluster
    gc.collect()
    if torch_module is not None and _is_cuda_device(device):
        try:
            torch_module.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
    return result


def group_totals(device_result: dict) -> dict:
    """Сумма медиан по группам моделей (мс)."""
    totals = {}
    for row in device_result.get("models", []):
        if row.get("median") is None:
            continue
        totals[row["group"]] = totals.get(row["group"], 0.0) + row["median"]
    return totals


def estimate_line_cycle_ms(device_result: dict) -> float | None:
    """Оценка inference одного шага линии на 7 камер по сумме медиан.

    Каждая группа выполняется столько раз, сколько камер на неё замкнуто
    (``ROLE_TO_GROUP``): INPUT/SPIDER — по две камеры, TOP — одна. Оценка
    доступна только если замерены все группы конфига.
    """
    totals = group_totals(device_result)
    if set(totals) != set(MODEL_GROUPS):
        return None
    return sum(totals[g] * GROUP_CAMERA_COUNT[g] for g in totals)


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------

def _fmt_ms(value) -> str:
    return "—" if value is None else f"{value:8.1f} мс"


def _fmt_speedup(base, other) -> str:
    if base is None or other is None or other <= 0:
        return "—"
    return f"{base / other:5.1f}x"


def _short(path: str, width: int = 44) -> str:
    name = path.replace("weights/", "")
    return name if len(name) <= width else "…" + name[-(width - 1):]


def build_report(env: dict, meta: dict, results: list[dict]) -> str:
    """Человекочитаемый отчёт: шапка, таблица по моделям, итоги, ускорение."""
    lines = []
    lines.append("=" * 100)
    lines.append("ТЕСТ СКОРОСТИ НЕЙРОСЕТЕЙ — стенд с одной камерой (роль TOP)")
    lines.append("=" * 100)
    cuda_label = "нет"
    if env.get("cuda_available"):
        names = ", ".join(
            f"{d['name']}"
            + (f" ({d['memory_gb']} ГБ)" if d.get("memory_gb") else "")
            for d in env.get("cuda_devices", [])
        )
        cuda_label = f"да — {names}" if names else "да"
    lines.append(
        f"Python {env.get('python')} | torch {env.get('torch') or 'не установлен'}"
        f" (CUDA build: {env.get('torch_cuda_build') or 'нет'})"
        f" | ultralytics {env.get('ultralytics')}"
    )
    lines.append(
        f"CUDA: {cuda_label} | CPU: {env.get('cpu_threads')} лог. ядер, "
        f"torch threads: {env.get('torch_threads')}"
    )
    lines.append(
        f"Кадр: {meta.get('frame_source')} {meta.get('frame_size')} | "
        f"моделей: {meta.get('model_count')} | imgsz={INFERENCE_IMGSZ}, "
        f"retina_masks=True | итераций: {meta.get('iterations')}, "
        f"прогрев: {meta.get('warmup')}"
        + (" | half (FP16) на GPU" if meta.get("half") else "")
        + (" | новый кадр на каждой итерации" if meta.get("fresh_frames") else "")
    )
    for warning in meta.get("warnings", []):
        lines.append(f"ВНИМАНИЕ: {warning}")
    lines.append("")

    ok_results = [r for r in results if not r.get("error")]
    for row in results:
        if row.get("error"):
            lines.append(f"{row['device']}: ОШИБКА — {row['error']}")
    if not ok_results:
        lines.append("Ни одно устройство не отработало замер.")
        return "\n".join(lines)

    devices = [r["device"] for r in ok_results]
    header = f"{'Модель':<46}" + "".join(f"{d + ' медиана':>18}" for d in devices)
    baseline = ok_results[0]
    if len(ok_results) > 1:
        header += "".join(f"{'x к ' + baseline['device']:>12}" for _ in ok_results[1:])
    lines.append(header)
    lines.append("-" * len(header))

    for index, base_row in enumerate(baseline["models"]):
        line = f"{_short(base_row['path']):<46}"
        medians = []
        for res in ok_results:
            row = res["models"][index]
            medians.append(row["median"])
            line += f"{_fmt_ms(row['median']):>18}"
        for other in medians[1:]:
            line += f"{_fmt_speedup(medians[0], other):>12}"
        lines.append(line)

    lines.append("-" * len(header))
    line = f"{'Полный проход всех моделей (медиана)':<46}"
    pass_values = [r["pass_median_ms"] for r in ok_results]
    line += "".join(f"{_fmt_ms(v):>18}" for v in pass_values)
    line += "".join(f"{_fmt_speedup(pass_values[0], v):>12}" for v in pass_values[1:])
    lines.append(line)

    per_group = [group_totals(r) for r in ok_results]
    for group in MODEL_GROUPS:
        if not any(group in totals for totals in per_group):
            continue
        values = [totals.get(group) for totals in per_group]
        line = f"{'  группа ' + group + ' (x' + str(GROUP_CAMERA_COUNT[group]) + ' камер)':<46}"
        line += "".join(f"{_fmt_ms(v):>18}" for v in values)
        line += "".join(f"{_fmt_speedup(values[0], v):>12}" for v in values[1:])
        lines.append(line)

    cycle = [estimate_line_cycle_ms(r) for r in ok_results]
    if all(v is not None for v in cycle):
        line = f"{'Оценка шага линии на 7 камер (inference)':<46}"
        line += "".join(f"{_fmt_ms(v):>18}" for v in cycle)
        line += "".join(f"{_fmt_speedup(cycle[0], v):>12}" for v in cycle[1:])
        lines.append(line)

    lines.append("")
    for res in ok_results:
        extra = ""
        if res.get("gpu_peak_memory_mb") is not None:
            extra = f", пик видеопамяти {res['gpu_peak_memory_mb']:.0f} МБ"
        lines.append(
            f"{res['device']}: загрузка {res['load_s']:.1f} с, "
            f"прогрев {res['warmup_s']:.1f} с, "
            f"проход min/median/max = {res['pass_ms']['min']:.0f}/"
            f"{res['pass_ms']['median']:.0f}/{res['pass_ms']['max']:.0f} мс{extra}"
        )

    if len(ok_results) > 1:
        lines.append("")
        base_pass = baseline["pass_median_ms"]
        for res in ok_results[1:]:
            speed = _fmt_speedup(base_pass, res["pass_median_ms"]).strip()
            lines.append(
                f"ИТОГ: {res['device']} быстрее {baseline['device']} в {speed} "
                f"на полном проходе ({base_pass:.0f} мс -> {res['pass_median_ms']:.0f} мс)"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m vision.model_benchmark",
        description="Сравнение скорости всех моделей линии на CPU и GPU по кадру одной камеры.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--camera", type=int, default=None,
        help=f"индекс камеры OpenCV (по умолчанию {DEFAULT_CAMERA_ID})",
    )
    source.add_argument(
        "--image", type=str, default=None,
        help="взять кадр из файла вместо камеры (воспроизводимый замер)",
    )
    parser.add_argument(
        "--device", action="append", default=None,
        help="устройство torch: cpu, cuda:0 … (повторяемый; по умолчанию cpu и cuda:0)",
    )
    parser.add_argument(
        "--group", action="append", default=None,
        help=f"ограничить группы моделей ({', '.join(MODEL_GROUPS)}); по умолчанию все",
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS,
                        help=f"итераций замера (по умолчанию {DEFAULT_ITERATIONS})")
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP,
                        help=f"прогревочных проходов (по умолчанию {DEFAULT_WARMUP})")
    parser.add_argument("--half", action="store_true",
                        help="FP16 на CUDA-устройствах (production работает в FP32)")
    parser.add_argument("--fresh-frames", action="store_true",
                        help="брать новый кадр с камеры на каждой итерации")
    parser.add_argument("--save-frame", type=str, default=None,
                        help="сохранить использованный кадр в файл (для --image)")
    parser.add_argument("--json", type=str, default=None,
                        help="записать полный результат в JSON")
    parser.add_argument("--quiet", action="store_true",
                        help="не печатать ход итераций, только отчёт")
    args = parser.parse_args(argv)
    if args.iterations < 1:
        parser.error("--iterations должен быть >= 1")
    if args.warmup < 0:
        parser.error("--warmup должен быть >= 0")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    log = (lambda *_a, **_k: None) if args.quiet else print

    torch_module = _import_torch()
    env = collect_environment(torch_module)
    devices, warnings = resolve_devices(args.device, env)
    for warning in warnings:
        print(f"[BENCH] ВНИМАНИЕ: {warning}")
    if not devices:
        print("[BENCH] Нет ни одного устройства для замера.")
        return 1

    try:
        entries = select_models(args.group)
    except ValueError as exc:
        print(f"[BENCH] {exc}")
        return 1
    missing = [e["path"] for e in entries if not os.path.isfile(e["path"])]
    if missing:
        print("[BENCH] Не найдены файлы весов (см. README, раздел «Файлы весов»):")
        for path in missing:
            print(f"  - {path}")
        return 1

    camera_id = DEFAULT_CAMERA_ID if args.camera is None else args.camera
    try:
        source = FrameSource(args.image, camera_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[BENCH] Кадр не получен: {exc}")
        return 1

    results = []
    try:
        frame = source.grab()
        frame_size = f"{frame.shape[1]}x{frame.shape[0]}"
        print(f"[BENCH] Кадр: {source.description}, {frame_size}")
        if args.save_frame:
            Path(args.save_frame).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(args.save_frame, frame)
            print(f"[BENCH] Кадр сохранён: {args.save_frame}")
        if args.image:
            static = source
        else:
            # Один и тот же кадр для всех устройств — иначе сравнение
            # нечестное. Свежие кадры включаются только по --fresh-frames.
            static = source if args.fresh_frames else _StaticSource(frame, source.description)

        for device in devices:
            results.append(benchmark_device(
                device=device,
                entries=entries,
                source=static,
                iterations=args.iterations,
                warmup=args.warmup,
                half=args.half,
                fresh_frames=args.fresh_frames,
                torch_module=torch_module,
                log=log,
            ))
    except Exception as exc:  # noqa: BLE001
        print(f"[BENCH] Ошибка: {type(exc).__name__}: {exc}")
        return 1
    finally:
        source.close()

    meta = {
        "frame_source": source.description,
        "frame_size": frame_size,
        "model_count": len(entries),
        "iterations": args.iterations,
        "warmup": args.warmup,
        "half": args.half,
        "fresh_frames": args.fresh_frames,
        "warnings": warnings,
        "imgsz": INFERENCE_IMGSZ,
        "groups": [e["group"] for e in entries],
    }
    report = build_report(env, meta, results)
    print()
    print(report)

    if args.json:
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "environment": env,
            "meta": meta,
            "results": results,
            "line_cycle_estimate_ms": {
                r["device"]: estimate_line_cycle_ms(r) for r in results if not r.get("error")
            },
        }
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        print(f"[BENCH] JSON сохранён: {args.json}")

    return 0 if any(not r.get("error") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
