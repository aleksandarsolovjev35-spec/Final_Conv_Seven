# Простой тест сохранения
import cv2
import numpy as np
import os
from utils.logs.logger import logger

# Создаем тестовое изображение
test_image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

# Пробуем сохранить
test_dir = "./utils/Screenshots/Camera_0"
os.makedirs(test_dir, exist_ok=True)
cv2.imwrite(f"{test_dir}/test.jpg", test_image)
print(f"Тестовый файл сохранен: {os.path.abspath(f'{test_dir}/test.jpg')}")


logger.info("Привет, мир!")
logger.debug("Отладочное сообщение")
logger.error("Произошла ошибка")


def process_file(filepath):
    """Пример функции с обработкой ошибок"""
    try:
        logger.info(f"Начинаем обработку файла: {filepath}")

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Файл не найден: {filepath}")

        # Чтение файла
        with open(filepath, 'r') as f:
            content = f.read()

        # Опасная операция
        result = len(content) / 0  # Намеренная ошибка!

        logger.info(f"Обработка завершена успешно")
        return result

    except FileNotFoundError as e:
        # Используем exception() для получения traceback
        logger.exception(f"Ошибка файловой системы:")
        return None

    except ZeroDivisionError as e:
        logger.exception(f"Математическая ошибка при обработке {filepath}:")
        return None

    except Exception as e:
        # Для любых других ошибок
        logger.exception(f"Неожиданная ошибка:")
        return None


def analyze_crystal(crystal_id, data):
    """Другой пример"""
    try:
        logger.debug(f"Анализ кристалла {crystal_id}")

        if not data:
            raise ValueError("Нет данных для анализа")

        # Какая-то логика анализа
        if crystal_id < 0:
            raise ValueError(f"Некорректный ID кристалла: {crystal_id}")

        return data * 2

    except ValueError as e:
        # Покажем где именно произошла ошибка
        logger.exception(f"Ошибка валидации кристалла {crystal_id}:")
        return None


# Тестируем
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Тест логирования с traceback")
    logger.info("=" * 60)

    # Тест 1: Ошибка с файлом
    process_file("несуществующий_файл.txt")

    # Тест 2: Математическая ошибка
    try:
        result = 100 / 0
    except Exception as e:
        logger.exception("Деление на ноль в основном коде:")

    # Тест 3: Ошибка в функции
    analyze_crystal(-1, [1, 2, 3])


    # Тест 4: Вложенные вызовы
    def inner_function():
        raise RuntimeError("Ошибка во вложенной функции")


    def outer_function():
        try:
            inner_function()
        except Exception as e:
            logger.exception("Ошибка в цепочке вызовов:")


    outer_function()