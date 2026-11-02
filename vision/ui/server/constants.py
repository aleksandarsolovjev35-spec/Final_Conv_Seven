"""Общие ограничения HMI для скорости ленты и паузы инспекции.

Модуль не импортирует ``server.py`` (иначе получился бы цикл: сервер
подключает маршруты, а маршруты — константы). Значения совпадают с
проверками ``hardware.conveyor.Conveyor`` и ``config.calibration_loader``.
"""

CONVEYOR_SPEED_MIN = 5000
CONVEYOR_SPEED_MAX = 20000

SETTLE_TIME_MIN = 0.0
SETTLE_TIME_MAX = 5.0
REVIEW_TIME_MIN = 0.0
REVIEW_TIME_MAX = 30.0

# Ползунок скорости показывает проценты от максимальной скорости ленты.
# 5000 шаг/с — это 25 % от 20000 шаг/с, ниже аппаратный минимум опускаться
# нельзя.
CONVEYOR_SPEED_PERCENT_MIN = round(
    CONVEYOR_SPEED_MIN / CONVEYOR_SPEED_MAX * 100,
)


def percent_to_speed(percent: int) -> int:
    """Проценты от максимума -> шаги/с с округлением до целого."""
    speed = round(CONVEYOR_SPEED_MAX * percent / 100)
    return max(CONVEYOR_SPEED_MIN, min(CONVEYOR_SPEED_MAX, speed))
