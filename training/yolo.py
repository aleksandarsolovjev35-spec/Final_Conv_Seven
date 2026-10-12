"""YOLO-совместимая разметка и экспорт собранной партии."""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class YoloExport:
    """Результат подготовки структуры для Ultralytics/YOLO."""

    dataset_folder: str
    yaml_path: str
    train_count: int
    validation_count: int
    skipped_count: int
    class_names: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_folder": self.dataset_folder,
            "yaml_path": self.yaml_path,
            "train_count": self.train_count,
            "validation_count": self.validation_count,
            "skipped_count": self.skipped_count,
            "class_names": list(self.class_names),
        }


def normalise_box(
    box: Any,
    *,
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float]:
    """Вернуть clipped ``x1, y1, x2, y2`` и проверить площадь.

    Координаты UI могут выйти за границы картинки на несколько пикселей, а
    при рисовании мышью ширина/высота иногда отрицательны. Нормализация
    делает такие случаи безопасными, но не принимает область нулевой площади.
    """
    try:
        x = float(box.x)
        y = float(box.y)
        width = float(box.width)
        height = float(box.height)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Некорректная bounding box") from exc
    if not all(np.isfinite(value) for value in (x, y, width, height)):
        raise ValueError("Координаты bounding box должны быть конечными")
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Размер изображения должен быть положительным")
    x1, x2 = sorted((x, x + width))
    y1, y2 = sorted((y, y + height))
    x1 = max(0.0, min(float(image_width), x1))
    y1 = max(0.0, min(float(image_height), y1))
    x2 = max(0.0, min(float(image_width), x2))
    y2 = max(0.0, min(float(image_height), y2))
    if x2 - x1 < 1.0 or y2 - y1 < 1.0:
        raise ValueError("Область дефекта слишком мала")
    return x1, y1, x2, y2


def annotation_to_yolo_lines(
    annotations: Sequence[Any],
    *,
    image_width: int,
    image_height: int,
    class_names: Sequence[str],
) -> list[str]:
    """Преобразовать пиксельные прямоугольники в строки YOLO."""
    indices = {name: index for index, name in enumerate(class_names)}
    lines = []
    for box in annotations:
        class_name = str(getattr(box, "class_name", "")).strip()
        if class_name not in indices:
            raise ValueError(f"Неизвестный класс YOLO: {class_name}")
        x1, y1, x2, y2 = normalise_box(
            box,
            image_width=image_width,
            image_height=image_height,
        )
        center_x = ((x1 + x2) / 2.0) / image_width
        center_y = ((y1 + y2) / 2.0) / image_height
        width = (x2 - x1) / image_width
        height = (y2 - y1) / image_height
        lines.append(
            f"{indices[class_name]} {center_x:.6f} {center_y:.6f} "
            f"{width:.6f} {height:.6f}"
        )
    return lines


def draw_annotations(
    image: np.ndarray,
    annotations: Sequence[Any],
    *,
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """Создать отдельную копию кадра с прямоугольниками и подписями."""
    marked = np.ascontiguousarray(image.copy())
    for index, box in enumerate(annotations):
        x1, y1, x2, y2 = normalise_box(
            box,
            image_width=image_width,
            image_height=image_height,
        )
        # Палитра повторяется для нескольких областей, но не меняет исходник.
        color = (
            int((37 * (index + 1)) % 255),
            int((97 * (index + 1)) % 255),
            int((173 * (index + 1)) % 255),
        )
        left, top, right, bottom = (
            int(round(x1)),
            int(round(y1)),
            int(round(x2)),
            int(round(y2)),
        )
        cv2.rectangle(marked, (left, top), (right, bottom), color, 3)
        label = str(getattr(box, "class_name", "defect"))
        (text_width, text_height), baseline = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            2,
        )
        label_top = max(0, top - text_height - baseline - 6)
        label_bottom = max(text_height + baseline + 2, top)
        cv2.rectangle(
            marked,
            (left, label_top),
            (left + text_width + 8, label_bottom),
            color,
            -1,
        )
        cv2.putText(
            marked,
            label,
            (left + 4, label_bottom - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return marked


def export_yolo_dataset(
    store: Any,
    *,
    validation_ratio: float | None = None,
    seed: int = 42,
) -> YoloExport:
    """Скопировать все размеченные кадры в ``yolo/images`` и ``labels``.

    Разбиение выполняется по детали, а не по отдельному кадру: семь камер
    одной детали не попадут одновременно в train и val. Для одного корпуса
    validation указывает на train, потому что Ultralytics всё равно требует
    поле ``val`` в yaml, а искусственное дублирование в другую папку не даёт
    честной проверки качества.
    """
    class_names = tuple(store.config.defect_classes)
    ratio = (
        store.config.validation_ratio
        if validation_ratio is None
        else float(validation_ratio)
    )
    if not 0.0 <= ratio < 1.0:
        raise ValueError("validation_ratio должен быть в диапазоне [0, 1)")

    yolo_root = Path(store.yolo_folder)
    if yolo_root.exists():
        shutil.rmtree(yolo_root)
    train_images = yolo_root / "images" / "train"
    train_labels = yolo_root / "labels" / "train"
    val_images = yolo_root / "images" / "val"
    val_labels = yolo_root / "labels" / "val"
    for folder in (train_images, train_labels, val_images, val_labels):
        folder.mkdir(parents=True, exist_ok=True)

    records = [
        record
        for record in store.get_frames()
        if record.status == "annotated"
    ]
    skipped_count = store.frame_count - len(records)
    groups: dict[int, list[Any]] = {}
    for record in records:
        groups.setdefault(int(record.part_id), []).append(record)
    part_ids = sorted(groups)
    random.Random(seed).shuffle(part_ids)

    validation_parts: set[int] = set()
    if ratio > 0 and len(part_ids) >= 2:
        count = max(1, int(round(len(part_ids) * ratio)))
        count = min(count, len(part_ids) - 1)
        validation_parts = set(part_ids[:count])

    train_count = 0
    validation_count = 0
    split_rows = []
    for part_id in part_ids:
        split = "val" if part_id in validation_parts else "train"
        image_folder = val_images if split == "val" else train_images
        label_folder = val_labels if split == "val" else train_labels
        for record in sorted(groups[part_id], key=lambda item: item.image_id):
            source_image = Path(store.session_folder) / record.original
            source_label = Path(store.session_folder) / record.label
            if not source_image.exists() or not source_label.exists():
                raise RuntimeError(
                    f"Файлы кадра #{record.image_id} отсутствуют перед экспортом"
                )
            shutil.copy2(source_image, image_folder / source_image.name)
            shutil.copy2(source_label, label_folder / source_label.name)
            split_rows.append(
                {
                    "image_id": record.image_id,
                    "part_id": record.part_id,
                    "camera_role": record.camera_role,
                    "split": split,
                    "image": str(
                        (image_folder / source_image.name)
                        .relative_to(store.session_folder)
                        .as_posix()
                    ),
                    "label": str(
                        (label_folder / source_label.name)
                        .relative_to(store.session_folder)
                        .as_posix()
                    ),
                }
            )
            if split == "val":
                validation_count += 1
            else:
                train_count += 1

    yaml_path = yolo_root / "dataset.yaml"
    dataset_root = str(store.session_folder.resolve()).replace("\\", "/")
    val_path = "yolo/images/val" if validation_parts else "yolo/images/train"
    yaml_lines = [
        f"path: {json.dumps(dataset_root, ensure_ascii=False)}",
        "train: yolo/images/train",
        f"val: {val_path}",
        "names:",
    ]
    yaml_lines.extend(
        f"  {index}: {json.dumps(name, ensure_ascii=False)}"
        for index, name in enumerate(class_names)
    )
    _write_text(yaml_path, "\n".join(yaml_lines) + "\n")
    _write_json(
        yolo_root / "classes.json",
        {"names": list(class_names), "nc": len(class_names)},
    )
    _write_json(
        yolo_root / "split.json",
        {
            "seed": seed,
            "validation_ratio": ratio,
            "validation_parts": sorted(validation_parts),
            "items": split_rows,
        },
    )
    return YoloExport(
        dataset_folder=str(yolo_root),
        yaml_path=str(yaml_path),
        train_count=train_count,
        validation_count=validation_count,
        skipped_count=skipped_count,
        class_names=class_names,
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, payload: Any) -> None:
    _write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
