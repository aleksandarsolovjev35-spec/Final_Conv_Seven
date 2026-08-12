from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QLabel, QDialogButtonBox
from datetime import datetime


class ReportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Параметры отчёта")
        layout = QVBoxLayout()

        # Поле для имени файла
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("Имя файла (без расширения)")
        default_name = f"report_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        self.filename_edit.setText(default_name)
        layout.addWidget(QLabel("Имя файла:"))
        layout.addWidget(self.filename_edit)

        # Поле для количества записей
        self.count_edit = QLineEdit()
        self.count_edit.setPlaceholderText("Количество последних деталей (оставьте пустым для всех)")
        self.count_edit.setText("100")
        layout.addWidget(QLabel("Количество записей:"))
        layout.addWidget(self.count_edit)

        # Кнопки OK/Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def get_values(self):
        return self.filename_edit.text().strip(), self.count_edit.text().strip()
