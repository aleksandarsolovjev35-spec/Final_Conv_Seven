"""VisionCluster с подменённым ultralytics.

Модуль ``ultralytics`` заменяется фейком через ``sys.modules``, веса —
временными файлами. Проверяются загрузка моделей, верификация классов,
warmup, прогон детекций и ошибки inference.
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


NAMES_BY_PATH = {
    "weights/1,6/uneven_heights_and_unfilled_windows_new1.pt": {0: "flatness"},
    "weights/1,6/window_sinks.pt": {0: "objects"},
    "weights/2,7/long_omission_v.1.2.pt": {0: "omission-long"},
    "weights/2,7/contacts_long_v.1.pt": {0: "contacts-long"},
    "weights/3,5/short_omission_v.1.2.pt": {0: "omission-short"},
    "weights/3,5/contacts_short.pt": {0: "flatness_short"},
    "weights/4/contacts.pt": {0: "contacts"},
    "weights/4/platform_old.pt": {0: "platform"},
    "weights/4/sinks_v.1_m.pt": {0: "shells"},
    "weights/4/glass_v.1.pt": {0: "glass"},
    "weights/4/well_v.1.pt": {0: "case", 1: "case_central"},
    "weights/4/pins.pt": {0: "pin"},
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
        self.assertEqual(len(cluster.models), 12)
        self.assertIn("weights/1,6/uneven_heights_and_unfilled_windows_new1.pt",
                      cluster.models)

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
            "TOP": self.frame(),
            "INPUT_LEFT": self.frame(),
        })
        self.assertEqual(set(results), {"TOP", "INPUT_LEFT"})
        # TOP: 6 моделей группы 4; INPUT_LEFT: 2 модели группы 1_6.
        self.assertEqual(len(results["TOP"]), 6)
        self.assertEqual(len(results["INPUT_LEFT"]), 2)
        detection = results["TOP"][0]
        self.assertEqual(detection["class"], "contacts")
        self.assertAlmostEqual(detection["confidence"], 0.9, places=6)
        self.assertEqual(len(detection["bbox"]), 4)
        self.assertIsNotNone(detection["mask"])
        self.assertIn("model_path", detection)
        self.assertEqual(results["INPUT_LEFT"][0]["class"], "flatness")

    def test_process_all_health_rows(self):
        cluster = self.make_cluster()
        cluster.process_all({"TOP": self.frame()})
        self.assertEqual(len(cluster.last_health), 6)
        self.assertTrue(all(row["ok"] for row in cluster.last_health))
        self.assertEqual(cluster.last_health[0]["role"], "TOP")

    def test_process_all_unknown_role(self):
        cluster = self.make_cluster()
        with self.assertRaisesRegex(ValueError, "Unknown camera role"):
            cluster.process_all({"NOPE": self.frame()})

    def test_process_all_small_frame(self):
        cluster = self.make_cluster()
        with self.assertRaisesRegex(ValueError, "Invalid frame"):
            cluster.process_all({"TOP": np.zeros((100, 100, 3), dtype=np.uint8)})

    def test_inference_failure_raises_and_health(self):
        cluster = self.make_cluster(yolo_class=FailingYOLO)
        with self.assertRaisesRegex(RuntimeError, "Model inference failed"):
            cluster.process_all({"TOP": self.frame()})
        self.assertFalse(cluster.last_health[0]["ok"])
        self.assertIn("RuntimeError", cluster.last_health[0]["error"])

    def test_aggressive_iou_for_side_roles(self):
        cluster = self.make_cluster()
        cluster.process_all({
            "TOP": self.frame(),
            "SPIDER_LEFT": self.frame(),
            "INPUT_LEFT": self.frame(),
        })
        top_model = cluster.models["weights/4/contacts.pt"]
        spider_model = cluster.models["weights/2,7/contacts_long_v.1.pt"]
        input_model = cluster.models["weights/1,6/window_sinks.pt"]
        top_call = top_model.predict_calls[-1]
        spider_call = spider_model.predict_calls[-1]
        input_call = input_model.predict_calls[-1]
        self.assertEqual(top_call["iou"], 0.10)
        self.assertEqual(spider_call["iou"], 0.10)
        self.assertEqual(input_call["iou"], 0.45)

    def test_parse_predictions_without_masks(self):
        cluster = self.make_cluster()
        preds = [FakeResult(
            {0: "flatness"},
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

    def test_detection_class_mismatch_raises(self):
        class WrongNamesYOLO(FakeYOLO):
            def __init__(self, path):
                super().__init__(path)
                self.names = {0: "other"}

        with mock.patch.object(
            vision_cluster, "YOLO", WrongNamesYOLO,
        ), mock.patch.object(
            vision_cluster.os.path, "isfile", return_value=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "class mismatch"):
                vision_cluster.VisionCluster(device="cpu", verbose=False)


if __name__ == "__main__":
    unittest.main()
