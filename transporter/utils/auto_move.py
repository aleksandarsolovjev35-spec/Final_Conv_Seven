import threading
from datetime import datetime
import time
import os
import cv2
import serial
import serial.tools.list_ports

def flush_serial(ser_port):
    """
    Вычитывает всё из входного буфера serial.
    Не блокируется — читает только то, что уже есть.
    """
    try:
        while ser_port.in_waiting > 0:
            line = ser_port.readline().decode(errors='ignore').strip()
            if line:
                print(f"  [Arduino flush]: {line}")
    except Exception as e:
        print(f"  [flush_serial ошибка]: {e}")


def send_command(ser_port, command):
    """
    Отправляет G-код и читает ответ. Паттерн из мануала convey14 (раздел 8):
      write → sleep(0.05) → readline пока есть данные

    ВАЖНО: НЕ блокируется на 2 секунды! readline ограничен
    таймаутом serial-порта (0.1с из main.py).
    Общее время выполнения: ~100-200мс.
    """
    try:
        # 1) Сбрасываем старые данные
        flush_serial(ser_port)

        # 2) Отправляем
        ser_port.write((command + '\n').encode('utf-8'))
        print(f"Команда отправлена: {command}")

        # 3) Читаем ответ (readline с таймаутом порта = 0.1с)
        time.sleep(0.05)
        response_lines = []
        while True:
            line = ser_port.readline().decode(errors='ignore').strip()
            if not line:
                break  # таймаут порта — данных больше нет
            response_lines.append(line)
            print(f"  [Arduino]: {line}")

        return '\n'.join(response_lines) if response_lines else None

    except Exception as e:
        print(f"Ошибка при отправке команды {command}: {e}")
        return None


def wait_for_move_complete(ser_port, timeout=15.0, poll_interval=0.3):
    """
    Ожидает завершения хода, опрашивая I1 (0=стоит, 1=движется).
    После завершения в режиме autoPause Arduino выведет "Paused (wait G3)".
    """
    start = time.time()
    while (time.time() - start) < timeout:
        try:
            ser_port.write(b'I1\n')
            time.sleep(0.05)
            response = ser_port.readline().decode(errors='ignore').strip()

            if response == '0':
                flush_serial(ser_port)
                return True

            time.sleep(poll_interval)
        except Exception as e:
            print(f"  [wait_for_move ошибка]: {e}")
            time.sleep(poll_interval)

    print(f"  [wait_for_move]: таймаут {timeout}с")
    flush_serial(ser_port)
    return False

def find_arduino_port():
    """
    Выполняет поиск активных COM-портов.
    :return: Активный COM-порт
    """
    ports = serial.tools.list_ports.comports()
    for ser_port in ports:
        if 'USB-SERIAL' in ser_port.description.upper():
            return ser_port.device
        print("проблемы")
    return None


def create_camera_folders(base_dir, num_cameras=3):
    """
    Создаёт папку Screenshots и поддиректории для каждой камеры.
    :param base_dir: Корневая директория для скриншотов
    :param num_cameras: Число камер
    :return: Список путей до директорий под скриншоты каждой камеры
    """
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    camera_dirs = []
    for cam_id in range(num_cameras):
        cam_dir = os.path.join(base_dir, f"Camera_{cam_id}")
        if not os.path.exists(cam_dir):
            os.makedirs(cam_dir)
        camera_dirs.append(cam_dir)

    return camera_dirs


def capture_camera_frames_parallel(frames_dict, batch_manager=None, camera_data_list=None, verdict=0,
                                   defect_types=None):
    """
    Сохраняет захваченные кадры в файлы параллельно.

    :param frames_dict: Словарь {cam_id: frame}
    :param batch_manager: Экземпляр BatchManager
    :param camera_data_list: Список данных с камер для каждой камеры
    :param verdict: Итоговый вердикт
    :param defect_types: Список типов браков
    """
    if defect_types is None:
        defect_types = []

    if camera_data_list is None:
        camera_data_list = []

    # Создаем временную метку для этого набора кадров
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]

    threads = []
    for cam_id, frame in frames_dict.items():
        if frame is not None:
            thread = threading.Thread(
                target=save_single_frame,
                args=(cam_id, frame, batch_manager, timestamp)
            )
            threads.append(thread)
            thread.start()

    for thread in threads:
        thread.join()

    # Сохраняем метаданные и обновляем статистику
    if batch_manager and batch_manager.is_batch_active():
        batch_manager.save_screenshot_metadata(timestamp, camera_data_list, verdict, defect_types)

        # Обновляем статистику партии
        # Получаем все object_data для детализации
        all_object_data = []
        for data in camera_data_list:
            if data:
                all_object_data.extend(data)

        batch_manager.update_batch_stats(verdict, defect_types, all_object_data)


def save_processed_frames_parallel(frames_dict, batch_manager):
    """
    Сохраняет обработанные кадры в папку screenshots_2 в структуре текущей партии.
    frames_dict: словарь {cam_id: frame} (обработанные кадры)
    batch_manager: экземпляр BatchManager (текущая партия)
    """
    if batch_manager is None or not batch_manager.is_batch_active():
        print("Нет активной партии для сохранения обработанных кадров")
        return

    # Получаем путь к папке текущей партии (например, utils/screenshots/партия_...)
    batch_path = batch_manager.current_batch_path
    # Формируем путь к screenshots_2, заменяя screenshots на screenshots_2
    # Предполагаем, что batch_path имеет вид .../screenshots/имя_партии
    base_dir = batch_path.parent.parent / "screenshots_2" / batch_path.name
    base_dir.mkdir(parents=True, exist_ok=True)

    # Генерируем единый timestamp для всех кадров этого цикла
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]

    threads = []
    for cam_id, frame in frames_dict.items():
        if frame is not None:
            camera_dir = base_dir / f"Camera_{cam_id}"
            camera_dir.mkdir(parents=True, exist_ok=True)
            filename = camera_dir / f"{timestamp}.jpg"
            thread = threading.Thread(target=cv2.imwrite, args=(str(filename), frame))
            threads.append(thread)
            thread.start()

    for thread in threads:
        thread.join()
    print(f"Обработанные кадры сохранены в {base_dir}")


def save_single_frame(cam_id, frame, batch_manager=None, timestamp=None):
    """Сохраняет один кадр в файл."""
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]

    if batch_manager and batch_manager.is_batch_active():
        # Сохраняем в папку текущей партии
        camera_dir = batch_manager.get_camera_batch_dir(cam_id)
        if camera_dir:
            filename = camera_dir / f"{timestamp}.jpg"
            if cv2.imwrite(str(filename), frame):
                print(f"✓ Камера {cam_id}: сохранено в партию")
            else:
                print(f"✗ Камера {cam_id}: ошибка сохранения в партию")
        else:
            print(f"⚠ Камера {cam_id}: нет активной партии")
    else:
        # Сохраняем в старую структуру (для обратной совместимости)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        screenshots_dir = os.path.join(script_dir, "Screenshots")
        camera_dir = os.path.join(screenshots_dir, f"Camera_{cam_id}")
        os.makedirs(camera_dir, exist_ok=True)

        filename = os.path.join(camera_dir, f"frame_{timestamp}.jpg")
        if cv2.imwrite(filename, frame):
            print(f"✓ Камера {cam_id}: сохранено в {filename}")
        else:
            print(f"✗ Камера {cam_id}: ошибка сохранения")


def save_single_frame_without_batch(cam_id, frame, screenshots_dir):
    """Сохраняет кадр без использования BatchManager."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]
    camera_dir = os.path.join(screenshots_dir, f"Camera_{cam_id}")
    os.makedirs(camera_dir, exist_ok=True)

    filename = os.path.join(camera_dir, f"frame_{timestamp}.jpg")
    if cv2.imwrite(filename, frame):
        print(f"✓ Камера {cam_id}: сохранено в {filename}")
    else:
        print(f"✗ Камера {cam_id}: ошибка сохранения")
