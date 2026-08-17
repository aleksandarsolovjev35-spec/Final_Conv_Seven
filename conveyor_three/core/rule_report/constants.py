"""Константы контракта отчёта по правилам (3 камеры)."""

PART_PRESENCE_RULE = "part_presence"

# Названия правил -> человекочитаемые заголовки.
RULE_LABELS = {
    "part_presence": "НАЛИЧИЕ ДЕТАЛИ",
    "uneven_heights": "РАЗНОВЫСОТНОСТЬ ОКОН",
    "window_sinks": "РАКОВИНЫ ОКОН",
    "bottom_glass": "СТЕКЛО НА ДНЕ",
    "welding": "БРАК СВАРКИ",
}

# Камеры, для которых правило имеет смысл в анализе кадра.
RULE_CAMERA_ROLES = {
    "part_presence": ("NEAR", "FAR"),
    "uneven_heights": ("NEAR", "FAR"),
    "window_sinks": ("NEAR", "FAR"),
    "bottom_glass": ("MIDDLE",),
    "welding": ("MIDDLE",),
}

# Правила с развёрнутым detail в панели.
DETAILED_RULES = ("uneven_heights",)

# Подписи метрик замеров (как в панели «Пороги правил»).
METRIC_PARAM_LABELS = {
    ("uneven_heights", "height_px"): "Высота ячейки, px",
    ("uneven_heights", "height_max_px"): "Высота ячейки: макс., px",
    ("uneven_heights", "height_min_px"): "Высота ячейки: мин., px",
    ("uneven_heights", "height_difference_px"): "Макс. разброс высот ячеек, px",
    ("window_sinks", "found"): "Число раковин, шт",
    ("bottom_glass", "found"): "Число стёкол, шт",
    ("welding", "found"): "Число дефектов сварки, шт",
}

# Короткие человеческие причины дефектов.
HUMAN_CAUSE_MAP = {
    ("uneven_heights", True): "РАЗНОВЫСОТНОСТЬ ОКОН",
    ("window_sinks", True): "РАКОВИНА В ОКНЕ",
    ("bottom_glass", True): "СТЕКЛО НА ДНЕ ИЗДЕЛИЯ",
    ("welding", True): "БРАК СВАРКИ",
}

# Поля part_presence, привязанные к конкретной камере.
PRESENCE_ROLE_FIELDS = {
    "NEAR": {"windows": "windows_near"},
    "FAR": {"windows": "windows_far"},
}

NO_MEASUREMENT = "—"
SUMMARY_LINES_LIMIT = 6
