"""VisionCluster с подменённым ultralytics (трёхкамерная линия).

Модуль ``ultralytics`` заменяется фейком через ``sys.modules``, веса —
временными файлами. Проверяются загрузка моделей, warmup, прогон
детекций, per-entry iou из model_config, проставление ``kind`` и ошибки
inference.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

# Фейковый ultralytics ставится в sys.modules ДО импорта vision.vision_cluster,
# иначе реальный импорт `from ultralytics import YOLO` упадёт без пакета.
_FAKE_ULTRALYTICS = types.ModuleType("ultralytics")


class FakeYOLO:
    instances = []

    def __init__(self, path):
        self.path = path
        self.names = dict(NAMES_BY_PATH[path])
        self.predict_calls = []
        FakeYOLO.instances.append(self)

    def predict(self, frame, **kwargs):
        self.predict_calls.append(kwargs)
        boxes = FakeBoxes(
            xyxy=np.array([[10.0, 20.0, 30.0, 40.0]], dtype=np.float32),
            conf=np.array([0.9], dtype=np.float32),
            cls=np.array([0], dtype=np.float32),
        )
        masks = FakeMasks([np.array([[10, 20], [30, 20], [30, 40], [10, 40]],
                                    dtype=np.float32)])
        return [FakeResult(self.names, boxes, masks)]


_FAKE_ULTRALYTICS.YOLO = FakeYOLO
sys.modules["ultralytics"] = _FAKE_ULTRALYTICS

import vision.vision_cluster as vision_cluster  # noqa: E402


def restore_modules(saved):
    for name in list(sys.modules):
        if name not in saved:
            del sys.modules[name]


class TensorLike:
    """Имитация torch-тензора: .cpu() -> .numpy() -> ndarray."""

    def __init__(self, array):
        self.array = array

    def cpu(self):
        return self

    def numpy(self):
        return self.array


class FakeBoxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = TensorLike(xyxy)
        self.conf = TensorLike(conf)
        self.cls = TensorLike(cls)


class FakeMasks:
    def __init__(self, polys):
        self.xy = polys

    def cpu(self):
        return self


class FakeResult:
    def __init__(self, names, boxes, masks=None):
        self.names = names
        self.boxes = boxes
        self.masks = masks


# Имена классов внутри весов трёхкамерника не используются: постобработка
# определяется полем ``kind`` из model_config. Для фейка достаточно любых
# имён; конфигурация c3 не содержит ``classes`` и верификацию не запускает.
NAMES_BY_PATH = {
    "weights/windows_4.pt": {0: "windows"},
    "weights/shells.pt": {0: "shells"},
    "weights/bottom_glass_new_v3.pt": {0: "glass"},
    "weights/welding_new_2.pt": {0: "welding"},
}


class FailingYOLO(FakeYOLO):
    def predict(self, frame, **kwargs):
        self.predict_calls.append(kwargs)
        raise RuntimeError("cuda oom")


class VisionClusterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for group in vision_cluster.MODEL_GROUPS.values():
            for entry in group:
                full = os.path.join(cls.tmp.name, entry["path"])
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as stream:
                    stream.write(b"fake weights")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.saved_modules = set(sys.modules)
        self.addCleanup(restore_modules, self.saved_modules)
        self.weights = self.tmp.name

    def make_cluster(self, yolo_class=None, verbose=False):
        with mock.patch.object(
            vision_cluster, "YOLO", yolo_class or FakeYOLO,
        ), mock.patch.object(
            vision_cluster.os.path, "isfile", return_value=True,
        ):
            return vision_cluster.VisionCluster(
                device="cpu", verbose=verbose,
            )

    def frame(self):
        return np.zeros((720, 1280, 3), dtype=np.uint8)

    def test_loads_all_models_once(self):
        cluster = self.make_cluster()
        self.assertEqual(len(cluster.models), 4)
        self.assertIn("weights/windows_4.pt", cluster.models)
        self.assertIn("weights/welding_new_2.pt", cluster.models)

    def test_missing_model_file_raises(self):
        with mock.patch.object(
            vision_cluster, "YOLO", FakeYOLO,
        ), mock.patch.object(
            vision_cluster.os.path, "isfile", return_value=False,
        ):
            with self.assertRaises(FileNotFoundError):
                vision_cluster.VisionCluster(device="cpu")

    def test_warmup(self):
        cluster = self.make_cluster()
        cluster.warmup()
        for model in cluster.models.values():
            self.assertGreaterEqual(len(model.predict_calls), 1)

    def test_warmup_error_raises(self):
        cluster = self.make_cluster(yolo_class=FailingYOLO)
        with self.assertRaisesRegex(RuntimeError, "warmup failed"):
            cluster.warmup()

    def test_process_all_returns_detections(self):
        cluster = self.make_cluster()
        results = cluster.process_all({
            "NEAR": self.frame(),
            "MIDDLE": self.frame(),
        })
        self.assertEqual(set(results), {"NEAR", "MIDDLE"})
        # NEAR: 2 модели группы GROUP_NEAR_FAR; MIDDLE: 2 модели GROUP_MIDDLE.
        self.assertEqual(len(results["NEAR"]), 2)
        self.assertEqual(len(results["MIDDLE"]), 2)
        kinds_near = {detection["kind"] for detection in results["NEAR"]}
        kinds_middle = {detection["kind"] for detection in results["MIDDLE"]}
        self.assertEqual(kinds_near, {"uneven_heights", "window_sinks"})
        self.assertEqual(kinds_middle, {"bottom_glass", "welding"})
        detection = results["NEAR"][0]
        self.assertEqual(detection["class"], "windows")
        self.assertAlmostEqual(detection["confidence"], 0.9, places=6)
        self.assertEqual(len(detection["bbox"]), 4)
        self.assertIsNotNone(detection["mask"])
        self.assertIn("model_path", detection)

    def test_process_all_health_rows(self):
        cluster = self.make_cluster()
        cluster.process_all({"NEAR": self.frame()})
        self.assertEqual(len(cluster.last_health), 2)
        self.assertTrue(all(row["ok"] for row in cluster.last_health))
        self.assertEqual(cluster.last_health[0]["role"], "NEAR")

    def test_process_all_unknown_role(self):
        cluster = self.make_cluster()
        with self.assertRaisesRegex(ValueError, "Unknown camera role"):
            cluster.process_all({"NOPE": self.frame()})

    def test_process_all_small_frame(self):
        cluster = self.make_cluster()
        with self.assertRaisesRegex(ValueError, "Invalid frame"):
            cluster.process_all({"NEAR": np.zeros((100, 100, 3), dtype=np.uint8)})

    def test_inference_failure_raises_and_health(self):
        cluster = self.make_cluster(yolo_class=FailingYOLO)
        with self.assertRaisesRegex(RuntimeError, "Model inference failed"):
            cluster.process_all({"NEAR": self.frame()})
        self.assertFalse(cluster.last_health[0]["ok"])
        self.assertIn("RuntimeError", cluster.last_health[0]["error"])

    def test_per_entry_iou_disabled_nms(self):
        """Трёхкамерник работает с iou=0.0 (без NMS-подавления)."""
        cluster = self.make_cluster()
        cluster.process_all({
            "NEAR": self.frame(),
            "FAR": self.frame(),
            "MIDDLE": self.frame(),
        })
        for model in cluster.models.values():
            call = model.predict_calls[-1]
            self.assertEqual(call["iou"], 0.0)

    def test_parse_predictions_without_masks(self):
        cluster = self.make_cluster()
        preds = [FakeResult(
            {0: "windows"},
            FakeBoxes(
                xyxy=np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32),
                conf=np.array([0.8], dtype=np.float32),
                cls=np.array([0], dtype=np.float32),
            ),
            None,
        )]
        parsed = cluster._parse_predictions(preds)
        self.assertEqual(len(parsed), 1)
        self.assertIsNone(parsed[0]["mask"])

    def test_parse_predictions_empty_boxes(self):
        cluster = self.make_cluster()
        self.assertEqual(cluster._parse_predictions([]), [])

    def test_is_valid(self):
        self.assertTrue(vision_cluster.VisionCluster._is_valid(
            {"class": "a", "confidence": 0.5},
        ))
        self.assertFalse(vision_cluster.VisionCluster._is_valid(None))
        self.assertFalse(vision_cluster.VisionCluster._is_valid({"class": "a"}))
        self.assertFalse(vision_cluster.VisionCluster._is_valid(
            {"class": "a", "confidence": float("nan")},
        ))
        self.assertFalse(vision_cluster.VisionCluster._is_valid(
            {"class": "a", "confidence": 0.5, "bbox": [1, 2]},
        ))


if __name__ == "__main__":
    unittest.main()
