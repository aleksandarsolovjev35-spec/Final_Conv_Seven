"""Контракт belt.path.v1 — инварианты, валидация и путь корпуса.

Запуск из корня репозитория:  python -m pytest belt_editor/tests
"""

import copy
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import belt_model  # noqa: E402

ERROR = belt_model.ERROR


def belt_with(reset_index=-1, n=5, cameras=True, primary=True):
    positions = []
    for i in range(n):
        pos = {"label": f"П{i}", "inspection": None,
               "reset": i == reset_index}
        if i == 0:
            pos["inspection"] = {
                "cameras": ["CAM_A"] if cameras else [],
                "primary": primary,
            }
        positions.append(pos)
    return belt_model.normalize_belt(
        {"name": "t", "path_type": "linear", "positions": positions})


def codes(belt):
    return [x["code"] for x in belt_model.validate_belt(belt)]


def levels(belt):
    return [x["level"] for x in belt_model.validate_belt(belt)]


# ─── пресеты ─────────────────────────────────────────────────────────────


def test_current7_preset_is_clean_and_matches_line():
    belt = belt_model.preset_current7()
    assert belt_model.validate_belt(belt) == []
    assert len(belt["positions"]) == 9
    assert belt_model.primary_index(belt) == 0
    assert belt_model.find_reset_index(belt) == 8
    steps = belt_model.case_path(belt)
    assert [s["index"] for s in steps] == list(range(9))
    assert steps[0]["primary"] is True
    assert steps[4]["cameras"] == ["SPIDER_LEFT", "SPIDER_RIGHT",
                                   "SPIDER_IN", "SPIDER_OUT", "TOP"]
    assert steps[8]["reset"] is True


def test_single_inspection_becomes_primary_automatically():
    raw = {"path_type": "linear", "positions": [
        {"label": "вход"},
        {"label": "инспекция", "inspection": {"cameras": ["CAM_A"]}},
        {"label": "выход", "reset": True},
    ]}
    belt = belt_model.normalize_belt(raw)
    assert belt["positions"][1]["inspection"]["primary"] is True
    assert belt_model.primary_index(belt) == 1


def test_multiple_inspections_keep_one_primary():
    raw = {"path_type": "linear", "positions": [
        {"inspection": {"cameras": ["CAM_A"], "primary": True}},
        {"inspection": {"cameras": ["CAM_B"], "primary": True}},
        {"reset": True},
    ]}
    belt = belt_model.normalize_belt(raw)
    primaries = [p for p in belt["positions"]
                 if p["inspection"] and p["inspection"]["primary"]]
    assert len(primaries) == 1


# ─── ошибки конфигурации ─────────────────────────────────────────────────


def test_missing_reset_is_error():
    belt = belt_with(reset_index=-1)
    assert "RESET_MISSING" in codes(belt)
    assert belt_model.case_path(belt) is None


def test_positions_after_reset_unreachable_on_linear():
    belt = belt_with(reset_index=1, n=5)
    assert "UNREACHABLE_AFTER_RESET" in codes(belt)


def test_positions_after_reset_ok_on_loop():
    belt = belt_with(reset_index=1, n=5)
    belt["path_type"] = "loop"
    assert "UNREACHABLE_AFTER_RESET" not in codes(belt)
    steps = belt_model.case_path(belt)
    # вход за сбросом (2), полный оборот до сброса (1) включительно
    assert [s["index"] for s in steps] == [2, 3, 4, 0, 1]


def test_duplicate_camera_role_rejected():
    belt = belt_model.normalize_belt({"positions": [
        {"inspection": {"cameras": ["CAM_A"]}},
        {"inspection": {"cameras": ["CAM_A"]}},
        {"reset": True},
    ]})
    assert "CAM_DUP" in codes(belt)


def test_bad_camera_name_rejected():
    belt = belt_model.normalize_belt({"positions": [
        {"inspection": {"cameras": ["камера 1"]}},
        {"reset": True},
    ]})
    assert "CAM_BAD_NAME" in codes(belt)


def test_empty_belt_and_min_positions():
    empty = belt_model.normalize_belt({"positions": []})
    assert codes(empty) == ["EMPTY_BELT"]
    one = belt_with(n=1, reset_index=0, cameras=False, primary=False)
    assert "MIN_POSITIONS" in codes(one)


def test_missing_cameras_is_warning_only():
    belt = belt_with(reset_index=4, n=5, cameras=False)
    assert "CAMS_MISSING" in codes(belt)
    assert ERROR not in levels(belt)


def test_reset_flag_deduplicated_to_first():
    belt = belt_model.normalize_belt({"positions": [
        {"inspection": {"cameras": ["CAM_A"]}},
        {"reset": True},
        {"reset": True},
    ]})
    assert belt["positions"][1]["reset"] is True
    assert belt["positions"][2]["reset"] is False


# ─── файлы ───────────────────────────────────────────────────────────────


def test_save_rejects_invalid_and_load_roundtrip(tmp_path):
    target = tmp_path / "belt_path.json"
    good = belt_model.preset_current7()
    belt_model.save_belt_file(target, good)
    loaded = belt_model.load_belt_file(target)
    assert loaded == good

    broken = copy.deepcopy(good)
    broken["positions"][8]["reset"] = False
    with pytest.raises(belt_model.BeltValidationError) as exc:
        belt_model.save_belt_file(target, broken)
    assert any(x["code"] == "RESET_MISSING" for x in exc.value.issues)
    # исходный файл не тронут неудачной записью
    assert belt_model.load_belt_file(target) == good


def test_seed_file_in_folder_is_valid():
    seed = HERE.parent / "belt_path.json"
    belt = belt_model.load_belt_file(seed)
    assert belt_model.validate_belt(belt) == []
