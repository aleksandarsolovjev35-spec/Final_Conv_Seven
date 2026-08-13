"""Загрузчик порогов ``domain.threshold_loader``.

Проверяются: чтение реального ``thresholds.json``, валидация значений,
разворачивание секций по ролям, запись файла (roundtrip) и метаданные
параметров для экрана HMI.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from domain.threshold_loader import (
    PARAM_LABELS,
    ThresholdLoader,
    _param_meta,
    describe_role_parameters,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESHOLDS_PATH = os.path.join(REPO_ROOT, "thresholds.json")


class ThresholdLoaderFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = ThresholdLoader(THRESHOLDS_PATH)

    def test_loads_all_required_keys(self):
        data = self.loader.get_all()
        missing = [key for key in ThresholdLoader.REQUIRED_KEYS if key not in data]
        self.assertEqual(missing, [])

    def test_flattened_role_keys(self):
        data = self.loader.get_all()
        self.assertIn("INPUT_LEFT.input_window_geometry_min_confidence", data)
        self.assertIn("TOP.top_contacts_expected_count", data)

    def test_missing_file_raises(self):
        with self.assertRaisesRegex(RuntimeError, "не найден"):
            ThresholdLoader(os.path.join(tempfile.gettempdir(), "no_such_thr.json"))

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.json")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{{{")
            with self.assertRaises(RuntimeError):
                ThresholdLoader(path)


class ThresholdLoaderValidationTest(unittest.TestCase):
    def make_data(self):
        return ThresholdLoader(THRESHOLDS_PATH).get_all()

    def test_missing_key_rejected(self):
        data = self.make_data()
        del data["TOP.top_contacts_min_confidence"]
        with self.assertRaisesRegex(ValueError, "Отсутствует ключ"):
            ThresholdLoader.validate(data)

    def test_not_dict_rejected(self):
        with self.assertRaisesRegex(ValueError, "объектом"):
            ThresholdLoader.validate([1])

    def test_non_finite_value_rejected(self):
        data = self.make_data()
        data["TOP.top_contacts_min_confidence"] = float("nan")
        with self.assertRaisesRegex(ValueError, "конечным числом"):
            ThresholdLoader.validate(data)

    def test_bool_rejected_as_number(self):
        data = self.make_data()
        data["TOP.top_contacts_min_confidence"] = True
        with self.assertRaisesRegex(ValueError, "конечным числом"):
            ThresholdLoader.validate(data)

    def test_confidence_out_of_range_rejected(self):
        data = self.make_data()
        data["TOP.top_contacts_min_confidence"] = 1.5
        with self.assertRaisesRegex(ValueError, "0..1"):
            ThresholdLoader.validate(data)

    def test_expected_count_must_be_int(self):
        data = self.make_data()
        data["INPUT_LEFT.input_window_geometry_expected_count"] = 7.0
        with self.assertRaisesRegex(ValueError, "целым > 0"):
            ThresholdLoader.validate(data)

    def test_fixed_expected_count_spider_short(self):
        data = self.make_data()
        data["SPIDER_IN.spider_contacts_short_expected_count"] = 3
        with self.assertRaisesRegex(ValueError, "равен 2"):
            ThresholdLoader.validate(data)

    def test_fixed_expected_count_top_contacts(self):
        data = self.make_data()
        data["TOP.top_contacts_expected_count"] = 12
        with self.assertRaisesRegex(ValueError, "равен 14"):
            ThresholdLoader.validate(data)

    def test_excess_component_must_be_positive_int(self):
        data = self.make_data()
        data["SPIDER_LEFT.spider_long_omission_excess_component_min_px"] = 0
        with self.assertRaisesRegex(ValueError, ">= 1"):
            ThresholdLoader.validate(data)

    def test_inscribed_rect_positive(self):
        data = self.make_data()
        data["SPIDER_LEFT.spider_contacts_long_inscribed_rect_width_px"] = 0
        with self.assertRaisesRegex(ValueError, "> 0"):
            ThresholdLoader.validate(data)

    def test_min_max_pairwise_range(self):
        data = self.make_data()
        data["INPUT_LEFT.input_window_geometry_top_px_min"] = 100
        data["INPUT_LEFT.input_window_geometry_top_px_max"] = 10
        with self.assertRaisesRegex(ValueError, "не может превышать"):
            ThresholdLoader.validate(data)

    def test_expand_ratio_positive(self):
        data = self.make_data()
        data["top_platform_overlap_expand_x_ratio"] = 0
        with self.assertRaisesRegex(ValueError, "должны быть > 0"):
            ThresholdLoader.validate(data)

    def test_disabled_rules_must_be_string_list(self):
        data = self.make_data()
        data["disabled_rules"] = ["top_contacts", 42]
        with self.assertRaisesRegex(ValueError, "списком строк"):
            ThresholdLoader.validate(data)

    def test_part_presence_cannot_be_disabled(self):
        data = self.make_data()
        data["disabled_rules"] = ["part_presence"]
        with self.assertRaisesRegex(ValueError, "нельзя отключать"):
            ThresholdLoader.validate(data)

    def test_labels_validated(self):
        data = self.make_data()
        with self.assertRaisesRegex(ValueError, "непустыми строками"):
            ThresholdLoader.validate(data, labels={"TOP.x": ""})


class ThresholdLoaderFlattenTest(unittest.TestCase):
    def test_flatten_sections(self):
        raw = {
            "_comment_top": "x",
            "global": 5,
            "TOP": {
                "_comment": "y",
                "a": 1,
                "_label.a": "Метка A",
                "b": "text",
            },
        }
        flat, labels = ThresholdLoader._flatten_sections(raw)
        self.assertEqual(flat, {"global": 5, "TOP.a": 1, "TOP.b": "text"})
        self.assertEqual(labels, {"TOP.a": "Метка A"})

    def test_flatten_section_not_dict_raises(self):
        with self.assertRaisesRegex(ValueError, "объектом"):
            ThresholdLoader._flatten_sections({"TOP": [1]})

    def test_flatten_nested_value_raises(self):
        with self.assertRaisesRegex(ValueError, "простым значением"):
            ThresholdLoader._flatten_sections({"TOP": {"a": {"b": 1}}})


class ThresholdLoaderSaveTest(unittest.TestCase):
    def test_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.json")
            data = ThresholdLoader(THRESHOLDS_PATH).get_all()
            labels = {"TOP.top_contacts_min_confidence": "Уверенность контактов"}
            ThresholdLoader.save_file(path, data, labels=labels)
            reloaded = ThresholdLoader(path).get_all()
            self.assertEqual(reloaded, data)

    def test_save_grouped_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.json")
            ThresholdLoader.save_file(path, {
                "TOP.a": 1,
                "global": 2,
                "disabled_rules": ["top_glass"],
            })
            with open(path, encoding="utf-8") as stream:
                raw = json.load(stream)
            self.assertEqual(raw["TOP"]["a"], 1)
            self.assertEqual(raw["global"], 2)
            self.assertEqual(raw["disabled_rules"], ["top_glass"])


class ThresholdMetaTest(unittest.TestCase):
    def test_fixed_values_meta(self):
        meta = _param_meta("top_contacts_expected_count", 14)
        self.assertTrue(meta["readonly"])
        self.assertEqual(meta["min"], 14)
        self.assertEqual(meta["max"], 14)
        self.assertEqual(meta["step"], 1)

    def test_expected_count_meta(self):
        meta = _param_meta("input_window_geometry_expected_count", 7)
        self.assertEqual(meta["step"], 1)
        self.assertEqual(meta["min"], 1)

    def test_long_expected_count_min_two(self):
        meta = _param_meta("spider_contacts_long_expected_count", 5)
        self.assertEqual(meta["min"], 2)

    def test_min_confidence_meta(self):
        meta = _param_meta("top_contacts_min_confidence", 0.3)
        self.assertEqual((meta["min"], meta["max"], meta["step"]), (0, 1, 0.01))

    def test_ratio_meta(self):
        meta = _param_meta("input_window_geometry_center_zone_ratio", 0.5)
        self.assertEqual(meta["min"], 0.01)
        self.assertEqual(meta["max"], 1)

    def test_margin_px_meta(self):
        meta = _param_meta("top_platform_overlap_margin_px", 5)
        self.assertEqual(meta["step"], 0.1)
        self.assertNotIn("min", meta)

    def test_inscribed_rect_meta(self):
        meta = _param_meta("spider_contacts_long_inscribed_rect_width_px", 38)
        self.assertEqual(meta["min"], 0.1)

    def test_unknown_key_label_falls_back_to_key(self):
        meta = _param_meta("some_unknown_param", 1)
        self.assertEqual(meta["label"], "some_unknown_param")

    def test_known_label_used(self):
        self.assertEqual(
            _param_meta("top_contacts_min_confidence", 0.3)["label"],
            PARAM_LABELS["top_contacts_min_confidence"],
        )

    def test_suffix_label_fallback(self):
        meta = _param_meta("top_platform_overlap_margin_px", 5)
        self.assertIn("отступ", meta["label"])


class DescribeRoleParametersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = ThresholdLoader(THRESHOLDS_PATH).get_all()

    def test_returns_groups_in_canonical_order(self):
        groups = describe_role_parameters("TOP", self.data)
        names = [group["rule"] for group in groups]
        self.assertEqual(names[0], "top_contacts")
        self.assertEqual(names[1], "top_platform_overlap")
        self.assertIn("top_glass", names)

    def test_every_group_has_label_and_params(self):
        for group in describe_role_parameters("SPIDER_LEFT", self.data):
            self.assertTrue(group["label"])
            self.assertTrue(group["params"])

    def test_params_have_meta_keys(self):
        groups = describe_role_parameters("INPUT_LEFT", self.data)
        for group in groups:
            for param in group["params"]:
                for key in ("key", "label", "value"):
                    self.assertIn(key, param)

    def test_leftovers_go_to_other_group(self):
        data = dict(self.data)
        data["INPUT_LEFT.zzz_custom"] = 3.0
        groups = describe_role_parameters("INPUT_LEFT", data)
        self.assertEqual(groups[-1]["rule"], "other")
        self.assertEqual(groups[-1]["params"][-1]["key"], "zzz_custom")

    def test_unknown_role_returns_other_group(self):
        groups = describe_role_parameters("UNKNOWN", self.data)
        self.assertEqual(groups, [])


if __name__ == "__main__":
    unittest.main()
