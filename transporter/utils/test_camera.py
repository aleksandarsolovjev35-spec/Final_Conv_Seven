import os
import cv2
import numpy as np
from pathlib import Path

class TestVideoCapture:
    """
    Имитирует VideoCapture, возвращая изображения из указанной папки.
    Поддерживает зацикливание.
    """
    def __init__(self, image_folder, loop=True):
        self.image_folder = Path(image_folder)
        self.image_files = sorted(self.image_folder.glob("*.jpg")) + sorted(self.image_folder.glob("*.png"))
        if not self.image_files:
            raise FileNotFoundError(f"No images found in {image_folder}")
        self.index = 0
        self.loop = loop

    def read(self):
        """Возвращает (True, image) или (False, None) если изображения кончились и loop=False."""
        if self.index >= len(self.image_files):
            if self.loop:
                self.index = 0
            else:
                return False, None
        img_path = self.image_files[self.index]
        img = cv2.imread(str(img_path))
        if img is None:
            return False, None
        self.index += 1
        return True, img

    def release(self):
        pass

    def set(self, prop_id, value):
        # Игнорируем установку свойств
        pass

    def get(self, prop_id):
        # Возвращаем фиктивные значения
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return 1280
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return 720
        return 0

    def isOpened(self):
        return True

    def grab(self):
        # Для совместимости с capture_all_frames
        return True

    def retrieve(self):
        ret, frame = self.read()
        return ret, frame