"""Тестер скорости нейросетей ``vision.model_benchmark`` с фейковым ultralytics.

Проверяются: выбор устройств по доступности CUDA, отбор моделей по группам,
параметры predict (совпадают с production), прогон замера на фейковом
кластере, оценка шага линии, отчёт и CLI-выход без весов.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

import numpy as np

# Фейковый ultralytics ставится до импорта vision.vision_cluster.
_FAKE_ULTRALYTICS = types.ModuleType("ultralytics")
_FAKE_ULTRALYTICS.YOLO = object
_FAKE_ULTRALYTICS.__version__ = "fake"
sys.modules.setdefault("ultralytics", _FAKE_ULTRALYTICS)

import vision.model_benchmark as bench  # noqa: E402
from vision.model_config import MODEL_GROUPS  # noqa: E402
from vision.vision_cluster import INFERENCE_IMGSZ  # noqa: E402


class TensorLike:
    def __init__(self, array):
        self.array = array

    def cpu(self):
        return self

    def numpy(self):
        return self.array


class FakeBoxes:
    def __init__(self):
        self.xyxy = TensorLike(np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32))
        self.conf = TensorLike(np.array([0.8], dtype=np.float32))
        self.cls = TensorLike(np.array([0], dtype=np.float32))


class FakeResult:
    def __init__(self):
        self.names = {0: "x"}
        self.boxes = FakeBoxes()
        self.masks = None


class FakeModel:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def predict(self, frame, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("cuda oom")
        return [FakeResult()]


class FakeCluster:
    """Минимальный дублёр VisionCluster: models + _parse_predictions."""

    created = []

    def __init__(self, device, fail=False, verbose=False):
        self.device = device
        self.models = {
            entry["path"]: FakeModel(fail=fail)
            for group in MODEL_GROUPS.values()
            for entry in group
        }
        FakeCluster.created.append(self)

    def _parse_predictions(self, preds):
        out = []
        for result in preds:
            for _ in range(len(result.boxes.xyxy.cpu().numpy())):
                out.append({"class": "x", "confidence": 0.8})
        return out


class StaticSource:
    def __init__(self):
        self.grabs = 0

    def grab(self):
        self.grabs += 1
        return np.zeros((720, 1280, 3), dtype=np.uint8)

    def close(self):
        pass


def fake_torch(cuda_available: bool, cuda_build="12.6"):
    torch = types.SimpleNamespace()
    torch.__version__ = "2.6.0+cu126" if cuda_build else "2.6.0+cpu"
    torch.version = types.SimpleNamespace(cuda=cuda_build)
    torch.get_num_threads = lambda: 8
    torch.cuda = types.SimpleNamespace(
        is_available=lambda: cuda_available,
        device_count=lambda: 1 if cuda_available else 0,
        get_device_name=lambda i: "Fake RTX",
        get_device_properties=lambda i: types.SimpleNamespace(total_memory=8 * 1024 ** 3),
        synchronize=lambda: None,
        reset_peak_memory_stats=lambda: None,
        max_memory_allocated=lambda: 512 * 1024 ** 2,
        empty_cache=lambda: None,
    )
    return torch


class EnvironmentAndDevicesTest(unittest.TestCase):
    def test_environment_without_torch(self):
        env = bench.collect_environment(None)
        self.assertIsNone(env["torch"])
        self.assertFalse(env["cuda_available"])

    def test_environment_with_cuda(self):
        env = bench.collect_environment(fake_torch(True))
        self.assertTrue(env["cuda_available"])
        self.assertEqual(env["cuda_devices"][0]["name"], "Fake RTX")
        self.assertEqual(env["cuda_devices"][0]["memory_gb"], 8.0)
        self.assertEqual(env["torch_threads"], 8)

    def test_default_devices_with_cuda(self):
        env = bench.collect_environment(fake_torch(True))
        devices, warnings = bench.resolve_devices(None, env)
        self.assertEqual(devices, ["cpu", "cuda:0"])
        self.assertEqual(warnings, [])

    def test_default_devices_without_cuda_warns_about_cpu_build(self):
        env = bench.collect_environment(fake_torch(False, cuda_build=None))
        devices, warnings = bench.resolve_devices(None, env)
        self.assertEqual(devices, ["cpu"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("собран без CUDA", warnings[0])
        self.assertIn(bench.CUDA_INSTALL_HINT, warnings[0])

    def test_default_devices_without_cuda_driver(self):
        env = bench.collect_environment(fake_torch(False, cuda_build="12.6"))
        _, warnings = bench.resolve_devices(None, env)
        self.assertIn("драйвер", warnings[0])

    def test_explicit_cuda_skipped_when_unavailable(self):
        env = bench.collect_environment(None)
        devices, warnings = bench.resolve_devices(["cuda:0", "cpu", "cpu"], env)
        self.assertEqual(devices, ["cpu"])
        self.assertIn("cuda:0", warnings[0])
        self.assertIn("torch не установлен", warnings[0])


class SelectModelsTest(unittest.TestCase):
    def test_all_groups_by_default(self):
        entries = bench.select_models(None)
        self.assertEqual(len(entries), 13)
        self.assertEqual(len({e["path"] for e in entries}), 13)
        self.assertTrue(all("group" in e for e in entries))

    def test_single_group(self):
        entries = bench.select_models(["GROUP_4"])
        self.assertEqual(len(entries), 6)
        self.assertTrue(all(e["group"] == "GROUP_4" for e in entries))

    def test_unknown_group(self):
        with self.assertRaises(ValueError):
            bench.select_models(["GROUP_X"])

    def test_group_camera_count(self):
        self.assertEqual(bench.GROUP_CAMERA_COUNT, {
            "GROUP_1_6": 2, "GROUP_2_7": 2, "GROUP_3_5": 2, "GROUP_4": 1,
        })


class PredictKwargsTest(unittest.TestCase):
    def test_matches_production_parameters(self):
        entry = {"path": "p", "conf": 0.3}
        kwargs = bench._predict_kwargs(entry, "cpu", half=False)
        self.assertEqual(kwargs["imgsz"], INFERENCE_IMGSZ)
        self.assertTrue(kwargs["retina_masks"])
        self.assertEqual(kwargs["conf"], 0.3)
        # TOP — агрессивный IoU, как в VisionCluster.
        self.assertEqual(kwargs["iou"], bench.AGGRESSIVE_IOU)
        self.assertEqual(kwargs["device"], "cpu")
        self.assertNotIn("half", kwargs)

    def test_half_only_on_cuda(self):
        entry = {"path": "p", "conf": 0.3}
        self.assertNotIn("half", bench._predict_kwargs(entry, "cpu", half=True))
        self.assertTrue(bench._predict_kwargs(entry, "cuda:0", half=True)["half"])


class BenchmarkDeviceTest(unittest.TestCase):
    def setUp(self):
        FakeCluster.created = []
        self.entries = bench.select_models(None)
        self.source = StaticSource()

    def run_device(self, device="cpu", fail=False, **kwargs):
        return bench.benchmark_device(
            device=device,
            entries=self.entries,
            source=self.source,
            iterations=kwargs.pop("iterations", 3),
            warmup=kwargs.pop("warmup", 1),
            torch_module=kwargs.pop("torch_module", None),
            cluster_factory=lambda dev: FakeCluster(dev, fail=fail),
            log=lambda *a, **k: None,
            **kwargs,
        )

    def test_collects_samples_for_every_model(self):
        result = self.run_device()
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["models"]), 13)
        for row in result["models"]:
            self.assertEqual(row["n"], 3)
            self.assertIsNotNone(row["median"])
            self.assertEqual(row["detections"], 1)
        self.assertEqual(result["pass_ms"]["n"], 3)
        self.assertIsNotNone(result["pass_median_ms"])
        # warmup 1 + iterations 3 = 4 вызова каждой модели
        for model in FakeCluster.created[0].models.values():
            self.assertEqual(len(model.calls), 4)
            self.assertEqual(model.calls[0]["imgsz"], INFERENCE_IMGSZ)

    def test_warmup_zero(self):
        result = self.run_device(warmup=0, iterations=2)
        self.assertEqual(result["pass_ms"]["n"], 2)
        for model in FakeCluster.created[0].models.values():
            self.assertEqual(len(model.calls), 2)

    def test_same_frame_unless_fresh(self):
        self.run_device(iterations=3)
        self.assertEqual(self.source.grabs, 1)
        self.source = StaticSource()
        self.run_device(iterations=3, fresh_frames=True)
        self.assertEqual(self.source.grabs, 3)

    def test_inference_error_is_reported_not_raised(self):
        result = self.run_device(fail=True)
        self.assertIn("inference", result["error"])
        self.assertIn("cuda oom", result["error"])
        self.assertEqual(result["models"], [])

    def test_load_error_is_reported(self):
        def broken(_device):
            raise FileNotFoundError("weights/x.pt")

        result = bench.benchmark_device(
            device="cpu", entries=self.entries, source=self.source,
            iterations=1, warmup=0, cluster_factory=broken, log=lambda *a: None,
        )
        self.assertIn("загрузка моделей", result["error"])

    def test_cuda_memory_and_half(self):
        torch = fake_torch(True)
        result = self.run_device(device="cuda:0", torch_module=torch, half=True)
        self.assertTrue(result["half"])
        self.assertAlmostEqual(result["gpu_peak_memory_mb"], 512.0)
        self.assertTrue(FakeCluster.created[0].models[self.entries[0]["path"]].calls[0]["half"])

    def test_line_cycle_estimate(self):
        result = self.run_device()
        totals = bench.group_totals(result)
        self.assertEqual(set(totals), set(MODEL_GROUPS))
        expected = sum(totals[g] * bench.GROUP_CAMERA_COUNT[g] for g in totals)
        self.assertAlmostEqual(bench.estimate_line_cycle_ms(result), expected)

    def test_line_cycle_estimate_requires_all_groups(self):
        self.entries = bench.select_models(["GROUP_4"])
        result = self.run_device()
        self.assertIsNone(bench.estimate_line_cycle_ms(result))


class ReportTest(unittest.TestCase):
    def make_result(self, device, scale):
        entries = bench.select_models(None)
        models = [
            {"path": e["path"], "group": e["group"], "detections": 1,
             "median": 100.0 * scale, "mean": 100.0 * scale,
             "min": 90.0 * scale, "max": 110.0 * scale, "n": 5}
            for e in entries
        ]
        return {
            "device": device, "half": False, "load_s": 1.0, "warmup_s": 2.0,
            "models": models,
            "pass_ms": {"median": 1300.0 * scale, "mean": 1300.0 * scale,
                        "min": 1200.0 * scale, "max": 1400.0 * scale, "n": 5},
            "pass_median_ms": 1300.0 * scale,
            "gpu_peak_memory_mb": 300.0 if device != "cpu" else None,
            "error": None,
        }

    def test_report_contains_speedup(self):
        env = bench.collect_environment(fake_torch(True))
        meta = {"frame_source": "файл x.png", "frame_size": "1280x720",
                "model_count": 13, "iterations": 5, "warmup": 3, "warnings": []}
        results = [self.make_result("cpu", 1.0), self.make_result("cuda:0", 0.1)]
        report = bench.build_report(env, meta, results)
        self.assertIn("Fake RTX", report)
        self.assertIn("10.0x", report)
        self.assertIn("ИТОГ: cuda:0 быстрее cpu в 10.0x", report)
        self.assertIn("Оценка шага линии на 7 камер", report)
        self.assertIn("пик видеопамяти 300 МБ", report)

    def test_report_with_errors_only(self):
        env = bench.collect_environment(None)
        meta = {"frame_source": "камера id=0", "frame_size": "1280x720",
                "model_count": 13, "iterations": 5, "warmup": 3,
                "warnings": ["CUDA недоступна"]}
        results = [{"device": "cpu", "error": "inference: RuntimeError: boom"}]
        report = bench.build_report(env, meta, results)
        self.assertIn("ОШИБКА", report)
        self.assertIn("Ни одно устройство", report)
        self.assertIn("ВНИМАНИЕ: CUDA недоступна", report)

    def test_report_single_device(self):
        env = bench.collect_environment(None)
        meta = {"frame_source": "камера id=0", "frame_size": "1280x720",
                "model_count": 13, "iterations": 5, "warmup": 3, "warnings": []}
        report = bench.build_report(env, meta, [self.make_result("cpu", 1.0)])
        self.assertNotIn("ИТОГ", report)
        self.assertIn("Полный проход всех моделей", report)


class CliTest(unittest.TestCase):
    def test_missing_weights_exit_1(self):
        with mock.patch.object(bench.os.path, "isfile", return_value=False), \
                mock.patch.object(bench, "_import_torch", return_value=None):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = bench.main(["--device", "cpu"])
        self.assertEqual(code, 1)
        self.assertIn("Не найдены файлы весов", buffer.getvalue())

    def test_unknown_group_exit_1(self):
        with mock.patch.object(bench, "_import_torch", return_value=None):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = bench.main(["--group", "NOPE"])
        self.assertEqual(code, 1)

    def test_only_cuda_requested_without_cuda_exit_1(self):
        with mock.patch.object(bench, "_import_torch", return_value=None):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = bench.main(["--device", "cuda:0"])
        self.assertEqual(code, 1)
        self.assertIn("Нет ни одного устройства", buffer.getvalue())

    def test_full_run_from_image_with_fake_cluster(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        image = os.path.join(tmp.name, "frame.png")
        bench.cv2.imwrite(image, np.full((720, 1280, 3), 128, dtype=np.uint8))
        json_path = os.path.join(tmp.name, "out", "bench.json")
        frame_copy = os.path.join(tmp.name, "copy.png")

        with mock.patch.object(bench.os.path, "isfile", return_value=True), \
                mock.patch.object(bench, "_import_torch", return_value=None), \
                mock.patch.object(bench, "VisionCluster", FakeCluster):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = bench.main([
                    "--image", image, "--iterations", "2", "--warmup", "1",
                    "--json", json_path, "--save-frame", frame_copy, "--quiet",
                ])
        output = buffer.getvalue()
        self.assertEqual(code, 0, output)
        self.assertIn("ТЕСТ СКОРОСТИ", output)
        self.assertIn("cpu", output)
        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(frame_copy))
        import json
        with open(json_path, encoding="utf-8") as stream:
            payload = json.load(stream)
        self.assertEqual(payload["results"][0]["device"], "cpu")
        self.assertEqual(len(payload["results"][0]["models"]), 13)
        self.assertIn("cpu", payload["line_cycle_estimate_ms"])

    def test_image_resized_to_camera_format(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        image = os.path.join(tmp.name, "small.png")
        bench.cv2.imwrite(image, np.full((100, 200, 3), 128, dtype=np.uint8))
        with redirect_stdout(io.StringIO()):
            frame = bench.load_image(image)
        self.assertEqual(frame.shape[:2], (720, 1280))

    def test_parse_args_validation(self):
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                bench.parse_args(["--iterations", "0"])


if __name__ == "__main__":
    unittest.main()
