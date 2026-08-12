from pathlib import Path
import shutil


# Папка, внутри которой создаются папки партия_...
BATCHES_ROOT = Path(r"C:\Users\User\Desktop\my git\transporter\utils\Screenshots")

# Имя JSON-файла, который нужно отправлять
TARGET_JSON_NAME = "batch_statistics.json"

# Локальная папка-очередь для JSON
LOCAL_QUEUE_DIR = Path(r"C:\Users\User\Desktop\Protocols\json")

# Сетевой диск ПК аналитики
REMOTE_ROOT = Path(r"B:\\")


def is_remote_available():
    """
    Проверяет, доступен ли сетевой диск B:.
    """
    try:
        return REMOTE_ROOT.exists() and REMOTE_ROOT.is_dir()
    except OSError:
        return False


def copy_json_to_local_queue(batch_dir, json_path):
    """
    Копирует batch_statistics.json из папки партии в локальную очередь.
    В очереди создаётся папка с таким же именем партии.
    """
    batch_dir = Path(batch_dir)
    json_path = Path(json_path)

    try:
        LOCAL_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

        local_batch_dir = LOCAL_QUEUE_DIR / batch_dir.name
        local_batch_dir.mkdir(parents=True, exist_ok=True)

        local_json_path = local_batch_dir / TARGET_JSON_NAME

        # Копируем с перезаписью, чтобы локальная очередь всегда имела свежую версию JSON
        shutil.copy2(json_path, local_json_path)
        print(f"✅ JSON сохранён в локальную очередь: {local_json_path}")

        return local_json_path

    except Exception as e:
        print(f"❌ Ошибка копирования JSON в локальную очередь: {e}")
        return None


def send_json_to_analytics(local_json_path):
    """
    Отправляет JSON на ПК аналитики.
    На ПК аналитики создаётся папка партии.
    """
    local_json_path = Path(local_json_path)

    if not is_remote_available():
        print("⚠️ ПК аналитики недоступен. JSON останется локально и будет отправлен позже.")
        return False

    try:
        batch_name = local_json_path.parent.name
        remote_batch_dir = REMOTE_ROOT / batch_name
        remote_batch_dir.mkdir(parents=True, exist_ok=True)

        remote_json_path = remote_batch_dir / TARGET_JSON_NAME

        # Копируем с перезаписью, чтобы на ПК аналитики была свежая финальная версия
        shutil.copy2(local_json_path, remote_json_path)
        print(f"✅ JSON отправлен на ПК аналитики: {remote_json_path}")

        return True

    except Exception as e:
        print(f"❌ Ошибка отправки JSON на ПК аналитики: {e}")
        return False


def send_batch_json(batch_dir):
    """
    Основная функция для автоматического вызова после окончания проверки.
    Ей нужно передать путь к папке партии.
    """
    batch_dir = Path(batch_dir)

    if not batch_dir.exists():
        print(f"❌ Папка партии не найдена: {batch_dir}")
        return False

    json_path = batch_dir / TARGET_JSON_NAME

    if not json_path.exists():
        print(f"❌ Файл {TARGET_JSON_NAME} не найден в партии: {batch_dir}")
        return False

    local_json_path = copy_json_to_local_queue(batch_dir, json_path)

    if local_json_path is None:
        return False

    return send_json_to_analytics(local_json_path)


def sync_local_queue():
    """
    Догружает все JSON из локальной очереди на ПК аналитики.
    Если раньше ПК аналитики был выключен, файлы отправятся позже.
    """
    LOCAL_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    json_files = sorted(LOCAL_QUEUE_DIR.rglob(TARGET_JSON_NAME))

    if not json_files:
        print("ℹ️ В локальной очереди JSON нет.")
        return

    if not is_remote_available():
        print("⚠️ ПК аналитики недоступен. Догрузка JSON невозможна.")
        return

    print("🔄 Проверяю локальную очередь JSON...")

    for json_file in json_files:
        send_json_to_analytics(json_file)


def scan_and_send_all_batches():
    """
    Ручная проверка всех папок партия_...
    Можно запускать отдельно.
    """
    if not BATCHES_ROOT.exists():
        print(f"❌ Папка с партиями не найдена: {BATCHES_ROOT}")
        return

    batch_dirs = sorted(
        path for path in BATCHES_ROOT.iterdir()
        if path.is_dir() and path.name.lower().startswith("партия")
    )

    if not batch_dirs:
        print(f"ℹ️ Папки партий не найдены: {BATCHES_ROOT}")
        return

    print("=== Ручная отправка batch_statistics.json на ПК аналитики ===")

    for batch_dir in batch_dirs:
        json_path = batch_dir / TARGET_JSON_NAME

        if json_path.exists():
            send_batch_json(batch_dir)
        else:
            print(f"⚠️ В партии нет {TARGET_JSON_NAME}: {batch_dir}")

    print("=== Ручная отправка завершена ===")


if __name__ == "__main__":
    scan_and_send_all_batches()