# Отдельный мастер сбора датасета

`training` — самостоятельный модуль для ручной подготовки данных для YOLO.
Он не запускает производственный цикл и не меняет `inspection/part_archive.py`.
Использовать мастер нужно при остановленной линии: отдельный процесс
занимает USB-камеры.

## Запуск

Из корня проекта Windows:

```bat
training.bat
```

Или напрямую:

```bat
.venv\Scripts\python.exe -m training --open-browser
```

По умолчанию веб-интерфейс доступен на `http://127.0.0.1:8010/`, данные
пишутся в `training_datasets/<имя партии>_<дата>_<идентификатор>/`. Параметры:

```text
--root training_datasets       корень наборов
--mapping camera_mapping.json  соответствие ролей и USB ID
--config training_config.json  список ролей и классов
--host 0.0.0.0 --port 8010
```

`training_config.example.json` можно скопировать в свой конфигурационный файл
и изменить список классов под конкретную модель.

## Рабочий процесс

1. Введите имя набора, классы дефектов и отметьте камеры. Порядок чекбоксов —
   порядок показа кадров.
2. Нажмите **Новая деталь**. Мастер снимает кадр только следующей камеры и
   сохраняет его с индивидуальным `image_id`.
3. Выберите класс и обведите дефект прямоугольником мышью. Если дефекта нет,
   нажмите **Дефекта нет**. Затем сохраните разметку и перейдите к следующей
   камере.
4. После всех камер завершите деталь и начните следующую.
5. **Завершить набор** создаёт готовую структуру YOLO.

Для каждого кадра сохраняются:

```text
images/frame_000001_TOP.jpg       оригинал без изменений
annotated/frame_000001_TOP.jpg   отдельная копия с прямоугольником и подписью
labels/frame_000001_TOP.txt      строки YOLO; для «дефекта нет» файл пустой
```

Связь кадра с деталью и камерой находится в `manifest.jsonl`. `frame_uid`
включает имя партии и номер, поэтому картинки можно однозначно сопоставить
даже после копирования набора.

## Результат для YOLO

После завершения партии:

```text
yolo/
  dataset.yaml
  classes.json
  split.json
  images/train/*.jpg
  images/val/*.jpg
  labels/train/*.txt
  labels/val/*.txt
```

Разбиение train/val выполняется **по деталям**, а не по кадрам: изображения
одной детали с разных камер не оказываются одновременно в обучении и проверке.
Для одной детали `val` в `dataset.yaml` указывает на `train`, потому что
искусственная копия не является честной валидацией.

Пример запуска Ultralytics после сбора:

```python
from ultralytics import YOLO

model = YOLO("weights/base.pt")
model.train(data="training_datasets/my_set_.../yolo/dataset.yaml", epochs=50)
```

## Программный API

Без веб-интерфейса модуль можно использовать через `TrainingCollector`:

```python
from training import TrainingCollector, TrainingConfig

collector = TrainingCollector(config, frame_source=my_camera_source)
collector.start_session("contacts_may")
collector.begin_part()
frame = collector.capture_next()       # кадр одной камеры, image_id
collector.annotate_current(
    defect_class="missing_contact",
    boxes=[{"x": 100, "y": 80, "width": 140, "height": 90}],
)
# повторить capture_next/annotate_current для всех камер
collector.finish_part()
collector.finish_session()
```

`frame_source` должен иметь единственный метод
`capture_single(role) -> numpy.ndarray`. Для существующего `CameraManager`
можно использовать `CollectorCameraSource`.
