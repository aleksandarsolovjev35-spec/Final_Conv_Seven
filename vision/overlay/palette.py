"""
Единый каталог цветов и стилей отрисовки кадров.

Один и тот же физический объект (стекло, платформа, контакты, пропуски
и т.д.) отрисовывается одинаково в обоих режимах кадра:

- режим «МОДЕЛИ» (``RawOverlay``) — все детекции нейросетей рисуются
  цветом своего класса из ``CLASS_COLORS``;
- режим «ПРАВИЛА» (``DebugOverlay``) — объекты правил берут тот же
  объектный цвет, статус правила (OK/FAIL/SKIP) сохраняет свои цвета.

Модуль — единственный источник объектных цветов: ``raw_overlay``
и рендереры правил ссылаются на константы отсюда и не дублируют
палитры локальными переменными.
"""

# —— Статусные цвета (режим «ПРАВИЛА») ——
COLOR_PASS  = (0,   200, 0)     # правило OK
COLOR_FAIL  = (0,   0,   255)   # правило FAIL / дефект
COLOR_SKIP  = (128, 128, 128)   # проигнорированные объекты и нейтральная геометрия

# —— Объектные цвета: класс детекции модели -> цвет (BGR) ——
CLASS_COLORS = {
    "mechanics":        (0,   0,   255),
    "sinks":            (0,   100, 255),
    "contacts":         (0,   255, 0),
    "contacts-long":    (0,   200, 100),
    "flatness_short":   (255, 200, 0),
    "flatness":         (255, 150, 0),
    "platform":         (255, 0,   255),
    "glass":            (200, 100, 0),
    "output_glass":     (100, 0,   0),
    "omission-long":    (0,   255, 255),
    "omission-short":   (255, 255, 0),
    "black-spot":       (200,   0, 200),
    "shells":           (255, 255, 0),
    "objects":          (0,   100, 255),
    "pin":              (80,   100, 255),
    "case":             (100,   100, 255),
    "case_central":     (200,   100, 255),
}

DEFAULT_COLOR = (180, 180, 180)

# Номенклатурные объектные цвета для рендереров правил.
COLOR_GLASS          = CLASS_COLORS["glass"]
COLOR_PLATFORM       = CLASS_COLORS["platform"]
COLOR_CONTACTS       = CLASS_COLORS["contacts"]
COLOR_CONTACTS_LONG  = CLASS_COLORS["contacts-long"]
COLOR_FLATNESS       = CLASS_COLORS["flatness"]
COLOR_OBJECTS        = CLASS_COLORS["objects"]
COLOR_SHELLS         = CLASS_COLORS["shells"]
COLOR_CASE           = CLASS_COLORS["case"]
COLOR_CASE_CENTRAL   = CLASS_COLORS["case_central"]
COLOR_PIN            = CLASS_COLORS["pin"]
COLOR_BLACK_SPOT     = CLASS_COLORS["black-spot"]
COLOR_OMISSION_LONG  = CLASS_COLORS["omission-long"]
COLOR_OMISSION_SHORT = CLASS_COLORS["omission-short"]

# —— Общий стиль отрисовки в обоих режимах: единая толщина линий
#    и единая прозрачность заливок (включая брак) ——
LINE_THIN  = 1
MASK_ALPHA = 0.15
