from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QLineEdit, QVBoxLayout, QGroupBox, QFormLayout, QPushButton, QLabel, QMessageBox, QSizePolicy, QSpacerItem


class ThresholdsEditor(QWidget):
    def __init__(self, cam_manager):
        """
        Конструктор класса.
        :param cam_manager: Объект управления камерами.
        """
        super().__init__()
        self.save_button = None
        self.far_cam_minimum_edit = QLineEdit()
        self.far_cam_maximum_edit = QLineEdit()
        self.far_cam_difference_edit = QLineEdit()
        self.near_cam_minimum_edit = QLineEdit()
        self.near_cam_maximum_edit = QLineEdit()
        self.near_cam_difference_edit = QLineEdit()
        self.delay_after_distribution_edit = QLineEdit()
        self.output_slot_index_edit = QLineEdit()

        for edit in [self.far_cam_minimum_edit, self.far_cam_maximum_edit, self.far_cam_difference_edit,
                     self.near_cam_minimum_edit, self.near_cam_maximum_edit, self.near_cam_difference_edit,
                     self.delay_after_distribution_edit, self.output_slot_index_edit]:
            edit.setFixedSize(96, 36)
            edit.setAlignment(Qt.AlignCenter)
            edit.setStyleSheet("""
                QLineEdit {
                    background-color: #d9d9d9;
                    border: 2px solid #343e43;
                    border-radius: 12px;
                    font-family: "Montserrat";
                    font-size: 16px;
                    font-weight: bold;
                    color: #343e43;
                    padding: 8px 12px;
                    selection-background-color: #a0a0a0;
                }

                QLineEdit:focus {
                    border: 2px solid #505c62;
                    background-color: #e0e0e0;
                }
            """)

        self.cam_manager = cam_manager
        self.init_ui()
        self.load_thresholds()

    def init_ui(self):
        """
        Формирование области изменения допусков в графическом окне.
        :return: None
        """
        self.group = QGroupBox("Пороговые значения брака")
        self.group.setFixedSize(480, 528)
        self.group.setStyleSheet("""
            QGroupBox {
                font-family: "Montserrat";
                font-weight: bold;
                font-size: 20px;
                color: #343e43;
                background-color: #f5f5f5;
                border: 4px solid #d9d9d9;
                border-radius: 16px;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                top: -4px;
                padding: 0 16px;
                background-color: #f5f5f5;
            }
        """)

        group_layout = QVBoxLayout()
        group_layout.setContentsMargins(12, 32, 12, 12)
        form_layout = QFormLayout()
        form_layout.setSpacing(16)

        far_cam_minimum_label = QLabel("Мин. высота, мкм (даль. камеры)")
        far_cam_maximum_label = QLabel("Макс. высота, мкм (даль. камеры)")
        far_cam_difference_label = QLabel("Макс. разница, мкм (даль. камеры)")
        near_cam_minimum_label = QLabel("Мин. высота, мкм (ближн. камеры)")
        near_cam_maximum_label = QLabel("Макс. высота, мкм (ближн. камеры)")
        near_cam_difference_label = QLabel("Макс. разница, мкм (ближн. камеры)")
        delay_after_distribution_label = QLabel("Время переключения, сек")
        output_slot_index_label = QLabel("Позиция распределения")

        form_items = [
            (far_cam_minimum_label, self.far_cam_minimum_edit),
            (far_cam_maximum_label, self.far_cam_maximum_edit),
            (far_cam_difference_label, self.far_cam_difference_edit),
            (near_cam_minimum_label, self.near_cam_minimum_edit),
            (near_cam_maximum_label, self.near_cam_maximum_edit),
            (near_cam_difference_label, self.near_cam_difference_edit),
            (delay_after_distribution_label, self.delay_after_distribution_edit),
            (output_slot_index_label, self.output_slot_index_edit)
        ]

        for label, edit in form_items:
            label.setFixedSize(338, 36)
            label.setStyleSheet("""
                QLabel {
                    font-family: "Montserrat";
                    font-size: 14px;
                    font-weight: bold;
                    color: #343e43;
                }
            """)
            form_layout.addRow(label, edit)

        group_layout.addLayout(form_layout)

        self.save_button = QPushButton("Сохранить настройки")
        self.save_button.setFixedSize(448, 48)
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #D9D9D9;
                color: #343E43;
                font-family: Montserrat;
                font-weight: bold;
                font-size: 20px;
                border: none;
                border-radius: 12px;
                padding: 8px;
            }
            QPushButton:disabled {
                background-color: #B0B0B0;
            }
            QPushButton:hover {
                background-color: #3997E4;
                color: #FFFFFF;
            }
        """)
        self.save_button.clicked.connect(self.save_thresholds)
        group_layout.addWidget(self.save_button)

        self.group.setLayout(group_layout)

    def load_thresholds(self):
        """
        Загружает из объекта управления статистическими данными информацию о допусках.
        :return: None
        """
        thresholds = self.cam_manager.stats_manager.thresholds
        self.far_cam_minimum_edit.setText(str(thresholds.get('far_cam_minimum', 1400.0)))
        self.far_cam_maximum_edit.setText(str(thresholds.get('far_cam_maximum', 48500.0)))
        self.far_cam_difference_edit.setText(str(thresholds.get('far_cam_difference', 110.0)))
        self.near_cam_minimum_edit.setText(str(thresholds.get('near_cam_minimum', 270.0)))
        self.near_cam_maximum_edit.setText(str(thresholds.get('near_cam_maximum', 20.0)))
        self.near_cam_difference_edit.setText(str(thresholds.get('near_cam_difference', 25.0)))
        self.delay_after_distribution_edit.setText(str(thresholds.get('delay_after_distribution', 4.5)))
        self.output_slot_index_edit.setText(str(thresholds.get('output_slot_index', 5.0)))

    def save_thresholds(self):
        """
        Сохраняет словарь с данными о допусках в объект управления статистическими данными.
        :return: None
        """
        # Список полей и их названий для сообщения об ошибке
        fields = [
            (self.far_cam_minimum_edit, "Мин. высота даль."),
            (self.far_cam_maximum_edit, "Макс. высота даль."),
            (self.far_cam_difference_edit, "Разн. высот даль."),
            (self.near_cam_minimum_edit, "Мин. высота ближн."),
            (self.near_cam_maximum_edit, "Макс. высота ближн."),
            (self.near_cam_difference_edit, "Разн. высот ближн."),
            (self.delay_after_distribution_edit, "Время переключения"),
            (self.output_slot_index_edit, "Позиция распред.")
        ]

        # Проверяем каждое поле
        errors = []
        values = {}
        for edit, name in fields:
            text = edit.text().strip()
            if not text:
                errors.append(f"{name} — пустое поле")
            else:
                try:
                    value = float(text)
                    values[name] = value
                except ValueError:
                    errors.append(f"{name} — должно быть числом")

        if errors:
            # Формируем сообщение об ошибке
            error_msg = "Некорректные данные:\n" + "\n".join(errors)
            QMessageBox.warning(self, "Ошибка ввода", error_msg)
            return

        # Если все поля валидны, собираем словарь с ключами, которые ожидает менеджер
        thresholds = {
            'far_cam_minimum': values["Мин. высота даль."],
            'far_cam_maximum': values["Макс. высота даль."],
            'far_cam_difference': values["Разн. высот даль."],
            'near_cam_minimum': values["Мин. высота ближн."],
            'near_cam_maximum': values["Макс. высота ближн."],
            'near_cam_difference': values["Разн. высот ближн."],
            'delay_after_distribution': values["Время переключения"],
            'output_slot_index': int(values["Позиция распред."])
        }

        try:
            self.cam_manager.stats_manager.save_thresholds(thresholds)
            self.cam_manager.thresholds = thresholds
            QMessageBox.information(self, "Успех", "Пороговые значения сохранены")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить: {str(e)}")
