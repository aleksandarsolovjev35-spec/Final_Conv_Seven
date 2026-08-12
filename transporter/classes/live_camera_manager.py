import threading
import time
from utils.logs.logger import logger

class LiveCameraManager:
    def __init__(self, cam_manager):
        """
        Принимает экземпляр CameraManager, а не ID камер.
        Это гарантирует, что камеры управляются только одним объектом.
        """
        self.cam_manager = cam_manager
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        # Разрешаем CameraManager захватывать кадры для превью
        self.cam_manager.preview_active = True
        logger.info("Режим прямого эфира включён")

    def stop(self):
        self.running = False
        # Запрещаем захват, если не работает инспекция
        self.cam_manager.preview_active = False
        if self.thread:
            self.thread.join(timeout=2)
        logger.info("Прямой эфир остановлен")

    def get_frame(self, index):
        """Безопасно возвращает последний кадр (RGB) из общего буфера."""
        if not self.running:
            return None
        # get_frame() в CameraManager уже содержит блокировку и конвертацию
        return self.cam_manager.get_frame(index)

    def release(self):
        """Корректное освобождение ресурсов."""
        self.stop()