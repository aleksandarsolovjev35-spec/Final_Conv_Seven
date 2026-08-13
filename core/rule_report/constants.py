"""Константы отчёта по правилам: лейблы метрик для UI, списки
правил с детальной телеметрией, привязка правил к ролям камер."""



# Названия порогов для анализа кадра: (правило, ключ метрики) -> понятный
# оператору label (как в панели «Пороги правил»). UI показывает порог
# рядом с названием правила и замер под ним.
# Новый блок анализа кадра полностью повторяет блок порогов правил:
#   Геометрия входного окна
#     B после перекладины: макс., px [Значение]
#       [Значение] [Значение] [Значение]
METRIC_PARAM_LABELS = {
    # Здесь ключ метрики не всегда совпадает с ключом файла порогов:
    # например, max_excess_depth_px — вычисленный замер, а не порог. Подписи
    # согласованы с панелью «Пороги правил», но описывают именно то значение,
    # которое оператор видит в карточке анализа.
    ("long_omission", "excess_component_min_px"):
        "Мин. число пикселей в компоненте избытка, px",
    ("long_omission", "top_line_max_residual_px"):
        "Макс. остаточное отклонение верхней линии, px",
    ("short_omission", "excess_component_min_px"):
        "Мин. число пикселей в компоненте избытка, px",
    ("short_omission", "top_line_max_residual_px"):
        "Макс. остаточное отклонение верхней линии, px",
    ("contacts_long", "damper_open_max_px"):
        "Макс. перепад заслонки по ряду, px",
    ("contacts_short", "damper_open_max_px"):
        "Макс. открытие заслонки, px",
    ("contacts_long", "gap_dev_max_px"):
        "Макс. разброс расстояний до пропуска, px",
    # Дополнительные метрики контактов и omission для карточек замера
    ("long_omission", "max_excess_depth_px"):
        "Макс. глубина избытка, px",
    ("long_omission", "largest_component_px"):
        "Крупнейший фрагмент, px",
    ("short_omission", "max_excess_depth_px"):
        "Макс. глубина избытка, px",
    ("short_omission", "largest_component_px"):
        "Крупнейший фрагмент, px",
    ("contacts_long", "rect_width_px"):
        "Ширина эталона контакта, px",
    ("contacts_long", "rect_height_px"):
        "Высота эталона контакта, px",
    ("contacts_short", "rect_width_px"):
        "Ширина эталона контакта, px",
    ("contacts_short", "rect_height_px"):
        "Высота эталона контакта, px",
    ("top_contacts", "edge_distance_deviation_ratio"):
        "Допуск разброса отступа до края, доля размера контакта",
    # top_contacts групповой
    ("top_contacts", "found"):
        "Валидных контактов, шт",
    ("top_contacts", "found_raw"):
        "Найдено контактов (сырые), шт",
    ("top_contacts", "group_L_median_px"):
        "Группа L: медиана дистанции, px",
    ("top_contacts", "group_R_median_px"):
        "Группа R: медиана дистанции, px",
    ("top_contacts", "group_T_median_px"):
        "Группа T: медиана дистанции, px",
    ("top_contacts", "group_B_median_px"):
        "Группа B: медиана дистанции, px",
    ("top_contacts", "group_L_deviation_px"):
        "Группа L: макс. отклонение, px",
    ("top_contacts", "group_R_deviation_px"):
        "Группа R: макс. отклонение, px",
    ("top_contacts", "group_T_deviation_px"):
        "Группа T: макс. отклонение, px",
    ("top_contacts", "group_B_deviation_px"):
        "Группа B: макс. отклонение, px",
    # top_contacts по контактам
    ("top_contacts", "contact_1_distance_px"):
        "Контакт #1: дистанция до края, px",
    ("top_contacts", "contact_2_distance_px"):
        "Контакт #2: дистанция до края, px",
    ("top_contacts", "contact_3_distance_px"):
        "Контакт #3: дистанция до края, px",
    ("top_contacts", "contact_4_distance_px"):
        "Контакт #4: дистанция до края, px",
    ("top_contacts", "contact_5_distance_px"):
        "Контакт #5: дистанция до края, px",
    ("top_contacts", "contact_6_distance_px"):
        "Контакт #6: дистанция до края, px",
    ("top_contacts", "contact_7_distance_px"):
        "Контакт #7: дистанция до края, px",
    ("top_contacts", "contact_8_distance_px"):
        "Контакт #8: дистанция до края, px",
    ("top_contacts", "contact_9_distance_px"):
        "Контакт #9: дистанция до края, px",
    ("top_contacts", "contact_10_distance_px"):
        "Контакт #10: дистанция до края, px",
    ("top_contacts", "contact_11_distance_px"):
        "Контакт #11: дистанция до края, px",
    ("top_contacts", "contact_12_distance_px"):
        "Контакт #12: дистанция до края, px",
    ("top_contacts", "contact_13_distance_px"):
        "Контакт #13: дистанция до края, px",
    ("top_contacts", "contact_14_distance_px"):
        "Контакт #14: дистанция до края, px",
    ("top_contacts", "contact_1_deviation_px"):
        "Контакт #1: отклонение, px",
    ("top_contacts", "contact_2_deviation_px"):
        "Контакт #2: отклонение, px",
    ("top_contacts", "contact_3_deviation_px"):
        "Контакт #3: отклонение, px",
    ("top_contacts", "contact_4_deviation_px"):
        "Контакт #4: отклонение, px",
    ("top_contacts", "contact_5_deviation_px"):
        "Контакт #5: отклонение, px",
    ("top_contacts", "contact_6_deviation_px"):
        "Контакт #6: отклонение, px",
    ("top_contacts", "contact_7_deviation_px"):
        "Контакт #7: отклонение, px",
    ("top_contacts", "contact_8_deviation_px"):
        "Контакт #8: отклонение, px",
    ("top_contacts", "contact_9_deviation_px"):
        "Контакт #9: отклонение, px",
    ("top_contacts", "contact_10_deviation_px"):
        "Контакт #10: отклонение, px",
    ("top_contacts", "contact_11_deviation_px"):
        "Контакт #11: отклонение, px",
    ("top_contacts", "contact_12_deviation_px"):
        "Контакт #12: отклонение, px",
    ("top_contacts", "contact_13_deviation_px"):
        "Контакт #13: отклонение, px",
    ("top_contacts", "contact_14_deviation_px"):
        "Контакт #14: отклонение, px",
    ("top_contacts", "contact_1_rect_fits"):
        "Контакт #1: прямоугольник",
    ("top_contacts", "contact_2_rect_fits"):
        "Контакт #2: прямоугольник",
    ("top_contacts", "contact_3_rect_fits"):
        "Контакт #3: прямоугольник",
    ("top_contacts", "contact_4_rect_fits"):
        "Контакт #4: прямоугольник",
    ("top_contacts", "contact_5_rect_fits"):
        "Контакт #5: прямоугольник",
    ("top_contacts", "contact_6_rect_fits"):
        "Контакт #6: прямоугольник",
    ("top_contacts", "contact_7_rect_fits"):
        "Контакт #7: прямоугольник",
    ("top_contacts", "contact_8_rect_fits"):
        "Контакт #8: прямоугольник",
    ("top_contacts", "contact_9_rect_fits"):
        "Контакт #9: прямоугольник",
    ("top_contacts", "contact_10_rect_fits"):
        "Контакт #10: прямоугольник",
    ("top_contacts", "contact_11_rect_fits"):
        "Контакт #11: прямоугольник",
    ("top_contacts", "contact_12_rect_fits"):
        "Контакт #12: прямоугольник",
    ("top_contacts", "contact_13_rect_fits"):
        "Контакт #13: прямоугольник",
    ("top_contacts", "contact_14_rect_fits"):
        "Контакт #14: прямоугольник",
    # top_platform
    ("top_platform", "placement"):
        "Положение эталона",
    ("top_platform", "shift_distance_px"):
        "Смещение центра, px",
    ("top_platform", "angle_deg"):
        "Угол платформы, °",
    ("top_platform", "rect_width_px"):
        "Ширина эталона платформы, px",
    ("top_platform", "rect_height_px"):
        "Высота эталона платформы, px",
    # platform_contacts_overlap
    ("platform_contacts_overlap", "excess_component_min_px"):
        "Мин. число пикселей в компоненте заплыва, px",
    ("platform_contacts_overlap", "largest_component_px"):
        "Крупнейший компонент заплыва, px",
    ("platform_contacts_overlap", "used_contacts"):
        "Контактов в области, шт",
    ("platform_contacts_overlap", "boundary_width_px"):
        "Ширина границы области, px",
    ("platform_contacts_overlap", "boundary_height_px"):
        "Высота границы области, px",
    # sinks (TOP)
    ("sinks", "sinks_hits"):
        "Пересечений раковин, шт",
    ("sinks", "shell_1_forbidden_px"):
        "Раковина #1: запрещ. пиксели, px",
    ("sinks", "shell_2_forbidden_px"):
        "Раковина #2: запрещ. пиксели, px",
    ("sinks", "shell_1_central_px"):
        "Раковина #1: центр. перехл., px",
    ("sinks", "shell_2_central_px"):
        "Раковина #2: центр. перехл., px",
    ("sinks", "shell_1_platform_px"):
        "Раковина #1: платформа, px",
    ("sinks", "shell_2_platform_px"):
        "Раковина #2: платформа, px",
    ("sinks", "shell_1_contacts_px"):
        "Раковина #1: контакты, px",
    ("sinks", "shell_2_contacts_px"):
        "Раковина #2: контакты, px",
    # glass
    ("glass", "glass_hits"):
        "Совпадений стекла, шт",
    ("glass", "glass_1_platform_px"):
        "Стекло #1: платформа, px",
    ("glass", "glass_2_platform_px"):
        "Стекло #2: платформа, px",
    ("glass", "glass_1_pin_px"):
        "Стекло #1: пины, px",
    ("glass", "glass_2_pin_px"):
        "Стекло #2: пины, px",
    ("glass", "glass_1_ring_px"):
        "Стекло #1: кольцо, px",
    ("glass", "glass_2_ring_px"):
        "Стекло #2: кольцо, px",
    ("glass", "glass_1_union_px"):
        "Стекло #1: union, px",
    ("glass", "glass_2_union_px"):
        "Стекло #2: union, px",
    # glass_on_contacts
    ("glass_on_contacts", "glass_count"):
        "Стекол, шт",
    ("glass_on_contacts", "pins_found"):
        "Пинов, шт",
    ("glass_on_contacts", "glass_contact_pairs"):
        "Пар стекло/контакт, шт",
    ("glass_on_contacts", "glass_1_contact_1_overlap_px"):
        "Стекло #1 → контакт #1: перехл., px",
    ("glass_on_contacts", "glass_1_contact_2_overlap_px"):
        "Стекло #1 → контакт #2: перехл., px",
    ("glass_on_contacts", "glass_2_contact_1_overlap_px"):
        "Стекло #2 → контакт #1: перехл., px",
    ("glass_on_contacts", "glass_2_contact_2_overlap_px"):
        "Стекло #2 → контакт #2: перехл., px",
    ("window_geometry", "top_px_min"): "T до перекладины: мин., px",
    ("window_geometry", "top_px_max"): "T до перекладины: макс., px",
    ("window_geometry", "bottom_px_min"): "B после перекладины: мин., px",


    ("window_geometry", "bottom_px_max"): "B после перекладины: макс., px",
}

# Правила, у которых есть развёрнутая построчная телеметрия в правой панели.
DETAILED_RULES = (
    "window_geometry",
    "contacts_long",
    "contacts_short",
    "top_contacts",
    "top_platform",


    "platform_contacts_overlap",
    "long_omission",


    "short_omission",
)

NO_MEASUREMENT = "нет измерения"

SUMMARY_LINES_LIMIT = 4

PART_PRESENCE_RULE = "part_presence"

# Камеры, для которых правило имеет смысл в анализе кадра.
# Панель «Анализ кадра» показывает только вычисления выбранной камеры,
# а не всю группу (INPUT / SPIDER / TOP).
RULE_CAMERA_ROLES = {
    "part_presence": ("INPUT_LEFT", "INPUT_RIGHT"),
    "window_geometry": ("INPUT_LEFT", "INPUT_RIGHT"),
    "window_sinks": ("INPUT_LEFT", "INPUT_RIGHT"),
    "contacts_long": ("SPIDER_LEFT", "SPIDER_RIGHT"),
    "long_omission": ("SPIDER_LEFT", "SPIDER_RIGHT"),
    "contacts_short": ("SPIDER_IN", "SPIDER_OUT"),
    "short_omission": ("SPIDER_IN", "SPIDER_OUT"),
    "top_contacts": ("TOP",),
    "top_platform": ("TOP",),
    "platform_contacts_overlap": ("TOP",),
    "sinks": ("TOP",),
    "glass": ("TOP",),
    "glass_on_contacts": ("TOP",),
}
