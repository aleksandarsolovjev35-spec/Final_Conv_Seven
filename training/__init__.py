"""Сбор датасета для ручной разметки дефектов и обучения YOLO.

Модуль намеренно отделён от производственного цикла: он не запускает
модели и не меняет ``PartArchive``. Шаг ленты между деталями подключается
опционально через ``belt`` (``training.motion``): оператор завершил все
камеры → «ДАЛЕЕ» → лента сдвинулась на шаг → новая деталь и новые кадры.
Мастер можно запустить отдельным процессом, когда линия остановлена, или
подключить к другому интерфейсу через :class:`TrainingCollector` и
:func:`training.server.create_app`.
"""

from training.collector import (
    DEFAULT_CAMERA_ROLES,
    DEFAULT_DEFECT_CLASSES,
    BoundingBox,
    CameraFrameSource,
    CollectorCameraSource,
    CollectorError,
    FrameRecord,
    TrainingCollector,
    TrainingConfig,
    TrainingDatasetCollector,
    TrainingDatasetStore,
    ValidationError,
)
from training.motion import (
    BeltStepSource,
    ConveyorBeltStep,
    VirtualBeltStep,
)
from training.yolo import (
    PolygonAnnotation,
    YoloExport,
    export_yolo_dataset,
)

__all__ = [
    "DEFAULT_CAMERA_ROLES",
    "DEFAULT_DEFECT_CLASSES",
    "BoundingBox",
    "BeltStepSource",
    "CameraFrameSource",
    "CollectorCameraSource",
    "CollectorError",
    "ConveyorBeltStep",
    "FrameRecord",
    "TrainingCollector",
    "TrainingConfig",
    "TrainingDatasetCollector",
    "TrainingDatasetStore",
    "ValidationError",
    "VirtualBeltStep",
    "PolygonAnnotation",
    "YoloExport",
    "export_yolo_dataset",
]
