from PyQt5.QtCore import QRect, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QPen, QColor, QPainter
from PyQt5.QtWidgets import QWidget, QPushButton, QLabel, QSizePolicy
from PyQt5.QtCore import QRect, QSize

from classes.statistics_manager import StatisticsManager

STATE_COLORS = {
    0: QColor(0xD9, 0xD9, 0xD9),      # Серый - годная деталь
    1: QColor(0, 255, 0),             # Зеленый - годно
    2: QColor(0, 0, 255),             # Синий - разновысотность/плоскостность
    3: QColor(255, 255, 0),           # Желтый - раковины/провал
    4: QColor(85, 170, 255),          # Голубой - стекло
    5: QColor(255, 128, 0),           # Оранжевый - contacts_area
    6: QColor(128, 0, 255),           # Фиолетовый - platform size
    7: QColor(0, 255, 255),           # Бирюзовый - omission
    8: QColor(101, 67, 33),           # Коричневый - брак сварки
    9: QColor(165, 42, 42),           # Коричневый - flatness_short
    10: QColor(134, 173, 39),         # Оливковый - platform_area_max
    11: QColor(75, 0, 130),           # Индиго - contacts_long
    12: QColor(0, 0, 0),              # Черный - mechanics
}

STATE_PRIORITY = {
    0: 0,       # нет детали
    1: 1,       # годная палета
    2: 99,      # разновысотность / плоскостность
    3: 100,     # раковины/провал
    8: 70,      # брак сварки (welding)
    4: 80,      # стекло
}


class SquaresWidget(QWidget):
    def __init__(self, cam_manager):
        super().__init__()
        self.cam_manager = cam_manager
        self.stats_manager = self.cam_manager.stats_manager
        self.stats = StatisticsManager.get_stats(self.stats_manager)

        self.clear_button = QPushButton("Очистить статистику", self)
        self.clear_button.clicked.connect(self.reset_stats)

        # Устанавливаем политику размера: фиксированный размер
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Таймер для периодического обновления статистики
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.refresh_stats)
        self.update_timer.start(100)  # Обновлять каждые 100 мс

    def reset_stats(self):
        """Сброс статистики"""
        self.stats_manager.reset_stats()
        self.refresh_stats()

    def refresh_stats(self):
        """Обновление статистики из менеджера"""
        try:
            # Получаем свежие данные из менеджера статистики
            new_stats = self.stats_manager.get_stats_snapshot()

            # Проверяем, изменились ли данные
            if (new_stats["total_good"] != self.stats.get("total_good", -1) or
                    new_stats["total_bad"] != self.stats.get("total_bad", -1) or
                    new_stats["total_checked"] != self.stats.get("total_checked", -1)):
                self.stats = new_stats
                self.update()  # Запрашиваем перерисовку

        except Exception as e:
            print(f"Ошибка обновления статистики: {e}")

    def check_and_update(self):
        """Проверяет изменения и обновляет виджет"""
        # Получаем свежие данные
        try:
            new_stats = self.stats_manager.get_stats_snapshot()
            if new_stats != self.stats:
                self.stats = new_stats
                self.update()
        except Exception as e:
            print(f"Ошибка в check_and_update: {e}")

    def sizeHint(self):
        """Возвращает предпочтительный размер виджета."""
        square_size = 72
        margin = 32
        required_width = 5 * square_size + 4 * margin + 2
        required_height = square_size
        return QSize(required_width, required_height)

    def paintEvent(self, event):
        """
        Обработчик события paint. Обновляет цифровой двойник
        конвейера в соответствии с данными о годности.
        :param event: Событие рисования окна.
        :return: None
        """
        try:
            squares_state = self.cam_manager.get_squares_state()
            self.stats = StatisticsManager.get_stats(self.stats_manager)

            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            square_size = 72
            margin = 32
            radius = 12

            # Вычисляем общую ширину всех квадратов
            total_width = 5 * square_size + 4 * margin
            # Вычисляем отступ слева для центрирования
            start_x = (self.width() - total_width) // 2
            if start_x < 0:
                start_x = 0  # Если виджет слишком узок, начинаем с края

            for i, state in enumerate(squares_state):
                rect_x = start_x + i * (square_size + margin)
                rect = QRect(rect_x, 5, square_size, square_size)

                color = STATE_COLORS.get(state, QColor(255, 0, 0))

                painter.setBrush(color)
                painter.setPen(QPen(QColor(0x34, 0x3E, 0x43), 2))
                painter.drawRoundedRect(rect, radius, radius)

            # Обновление минимальных размеров (опционально)
            required_width = total_width + 2
            required_height = square_size + 10
            self.setMinimumWidth(required_width)
            self.setMinimumHeight(required_height)

        except Exception as e:
            print(f"Ошибка в paintEvent: {e}")