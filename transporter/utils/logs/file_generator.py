# import cv2
# import datetime
# import shutil
# from pathlib import Path
# from typing import Optional
# from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
# from openpyxl import Workbook, load_workbook
# from openpyxl.utils import get_column_letter
#
# from project.application.addition.exception import KnownSystemException
# from project.application.addition.logger import logger
# from project.application.data_work.wafer_map_parser import MapWaferParser
#
#
#
# class ProtocolPaths:
#     """
#     Класс для хранения названий папок и файлов и их генерации
#     """
#     DESTINATION_BASE_DIR = "C:/Users/user/Desktop/Карты годности"
#     MAIN_FOLDER = "Пластина" # + _(wafer_id)
#     AFTER_AOI_FOLDER = "После_АОИ"
#     BEFORE_AOI_FOLDER = "До_АОИ"
#     AFTER_AOI_EXCEL_PROTOCOL_FILE = "Карта_годности_после_АОИ.xlsx"
#     BEFORE_AOI_EXCEL_PROTOCOL_FILE = "Карта_годности_до_АОИ.xlsx"
#     DEFECTIVE_CRYSTAL_FOLDER = "Бракованные_кристаллы_Фотографии"
#
#     @classmethod
#     def create_protocol_folders(cls, file_wafer_map_path: str, base_dir: Optional[str] = None) -> str:
#         """
#         Создание структуры папок для сохранения протокола проверки кристаллов
#
#         Args:
#             file_wafer_map_path: Путь к файлу wafer map
#             base_dir: Базовый каталог для сохранения (если None, используется DESTINATION_BASE_DIR)
#         Returns:
#             str: Путь к созданной папке пластины
#
#         Raises:
#             ValueError: Если парсинг файла не удался
#         """
#         if base_dir:
#             cls.DESTINATION_BASE_DIR = base_dir
#
#         # Парсим файл
#         parser = MapWaferParser(file_path=file_wafer_map_path)
#         parser.parse()
#
#         parser.print_header_info()
#         parser.print_die_info()
#
#         current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
#         wafer_id = parser.header_info.get('wafer_ID', None)
#         if not wafer_id:
#             wafer_id = current_time
#             print(f"Wafer ID не найден в заголовке. Для идентификации используется дата создания: {wafer_id}")
#         else:
#             wafer_id += current_time
#
#         wafer_folder_name = f"{cls.MAIN_FOLDER}_{wafer_id}"
#         wafer_folder_path = Path(cls.DESTINATION_BASE_DIR) / wafer_folder_name
#         before_aoi_path = wafer_folder_path / cls.BEFORE_AOI_FOLDER
#         after_aoi_path = wafer_folder_path / cls.AFTER_AOI_FOLDER
#         defective_crystals_path = after_aoi_path / cls.DEFECTIVE_CRYSTAL_FOLDER
#
#         try:
#             wafer_folder_path.mkdir(parents=True, exist_ok=True)
#             before_aoi_path.mkdir(exist_ok=True)
#             after_aoi_path.mkdir(exist_ok=True)
#             defective_crystals_path.mkdir(exist_ok=True)
#             logger.debug(f"Созданы все необходимые папки для протоколов")
#         except Exception as e:
#             logger.error(f"Ошибка создания папок с протоколами: {e}")
#             raise KnownSystemException(message=f"Ошибка создания папок с протоколами")
#
#         try:
#             src_path = Path(file_wafer_map_path)
#             dest_file_path = before_aoi_path / src_path.name
#             if dest_file_path.exists():
#                 logger.warning(f"Файл уже существует в папке 'До_АОИ': {dest_file_path}")
#             else:
#                 shutil.copy2(file_wafer_map_path, dest_file_path)
#                 logger.debug(f"Файл с картой годности скопирован в папку 'До_АОИ': {dest_file_path}")
#         except Exception as e:
#             logger.warning(f"Не удалось скопировать файл: {e}")
#
#         # Создаем файлы Excel
#         cls._create_excel_files(before_aoi_path, after_aoi_path, wafer_id, parser)
#
#         logger.info(f"Структура протокольных папок со всеми необходимыми данными успешно создана")
#         return str(wafer_folder_path)
#
#     @classmethod
#     def _create_excel_files(cls, before_aoi_path: Path, after_aoi_path: Path, wafer_id: str,
#                             parser: MapWaferParser):
#         """
#         Создает Excel файлы с сеткой кристаллов для протоколов
#
#         Args:
#             before_aoi_path: Путь к папке "До_АОИ"
#             after_aoi_path: Путь к папке "После_АОИ"
#             wafer_id: ID пластины
#             parser: Объект MapWaferParser с распарсенными данными
#         """
#         # Путь к файлу Excel "До_АОИ"
#         before_excel_path = before_aoi_path / cls.BEFORE_AOI_EXCEL_PROTOCOL_FILE
#
#         # Путь к файлу Excel "После_АОИ"
#         after_excel_path = after_aoi_path / cls.AFTER_AOI_EXCEL_PROTOCOL_FILE
#
#         try:
#             # Создаем Excel файл с сеткой кристаллов
#             cls._create_wafer_map_excel(before_excel_path, parser)
#             logger.debug(f"Excel файл карты годности до_АОИ создан: {before_excel_path}")
#         except Exception as e:
#             logger.error(f"Не удалось создать Excel файл карты годности до_АОИ: {e}")
#             raise KnownSystemException(message="Ошибка создания Excel файла карты годности до АОИ")
#
#         try:
#             # Копируем файл в папку "После_АОИ"
#             shutil.copy2(before_excel_path, after_excel_path)
#             logger.debug(f"Excel файл карты годности до_АОИ скопирован в папку После_АОИ: {after_excel_path}")
#         except Exception as e:
#             logger.error(f"Ошибка создания Excel файла карты годности после АОИ: {e}")
#             raise KnownSystemException(message="Ошибка создания Excel файла карты годности после АОИ")
#
#     @classmethod
#     def _create_wafer_map_excel(cls, excel_path: Path, parser: MapWaferParser):
#         """
#         Создает Excel файл с сеткой кристаллов
#
#         Args:
#             excel_path: Путь к файлу Excel
#             parser: Отпарсенные данные карты годности кристаллов до АОИ
#         """
#         die_data = parser.die_data
#         header_info = parser.header_info
#
#         col_size = header_info.get('map_area_col_size', 0)  # количество столбцов
#         row_size = header_info.get('map_area_row_size', 0)  # количество строк
#
#         wb = Workbook()
#         ws = wb.active
#         ws.title = "Карта годности кристаллов"
#         wafer_grid = [[None for _ in range(col_size)] for _ in range(row_size)]
#
#         for die in die_data:
#             row = die.get('row', 0)
#             col = die.get('col', 0)
#             symbol = die.get('symbol', '')
#
#             if 0 <= row < row_size and 0 <= col < col_size:
#                 wafer_grid[row][col] = symbol
#
#         thin_border = Border(
#             left=Side(style='thin'),
#             right=Side(style='thin'),
#             top=Side(style='thin'),
#             bottom=Side(style='thin')
#         )
#
#         center_alignment = Alignment(horizontal='center', vertical='center')
#         default_fill = PatternFill(
#             start_color="FFFFFF",
#             end_color="FFFFFF",
#             fill_type="solid"
#         )
#
#         for row_idx in range(row_size):
#             for col_idx in range(col_size):
#                 cell = ws.cell(row=row_idx + 1, column=col_idx + 1)
#                 symbol = wafer_grid[row_idx][col_idx]
#
#                 cell.value = symbol if symbol else ""
#                 cell.alignment = center_alignment
#                 cell.border = thin_border
#                 cell.fill = default_fill
#                 cell.font = Font(size=10)
#
#         # Настройка ширины столбцов для компактного отображения
#         for col_idx in range(1, col_size + 1):
#             column_letter = get_column_letter(col_idx)
#             ws.column_dimensions[column_letter].width = 4
#
#         # Настройка высоты строк для квадратных ячеек
#         for row_idx in range(1, row_size + 1):
#             ws.row_dimensions[row_idx].height = 20
#
#         try:
#             wb.save(excel_path)
#             logger.debug(f"Excel файл карты годности перед АОИ сохранен: {excel_path}")
#         except Exception as e:
#             logger.error(f"Ошибка сохранения Excel файла карты годности перед АОИ: {e}")
#             raise KnownSystemException(message="Ошибка сохранения Excel файла карты годности перед АОИ")
#
#
#
#
# def save_crystal_photo(frame, crystal_name, defect_type, dest_dir=None):
#     """
#     Сохранение фотографии кристалла
#
#     :param frame: Кадр из видеопотока (numpy array)
#     :param dest_dir: Папка для сохранения (по умолчанию DEFECTIVE_CRYSTAL_FOLDER)
#     :param crystal_name: Название конкретного кристалла в формате "crystal_{row}_{column}"
#     :param defect_type: Тип дефекта (0-годный, 1-бракованный, 2-пропуск)
#
#     :return Имя директории, куда был сохранён файл
#     """
#     if frame is None:
#         return None
#
#     if dest_dir is None:
#         dest_dir = ProtocolPaths.DEFECTIVE_CRYSTAL_FOLDER
#
#     match defect_type:
#         case 0:
#             prefix = "P"
#         case 1:
#             prefix = "F"
#         case _:
#             prefix = "S"
#
#     timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
#     filename = f"{prefix}_{crystal_name}_{timestamp}.jpg"
#     dest_path = Path(dest_dir) / filename
#
#     try:
#         success = cv2.imwrite(str(dest_path), frame)
#         if success:
#             return str(dest_path)
#         else:
#             return None
#     except Exception as e:
#         logger.warning(f"Ошибка сохранения изображения кристалла {filename}: {e}")
#         return None
#
#
# def update_excel_cell(row_index, col_index, defect_type, photo_path=None):
#     """
#     Обновление конкретной ячейки в Excel файле с использованием кэша позиций
#
#     :param row_index: Индекс строки в snake_buttons (начиная с 0)
#     :param col_index: Индекс кнопки в строке snake_buttons (начиная с 0)
#     :param defect_type: Тип дефекта (0-годный, 1-бракованный, 2-пропуск)
#     :param photo_path: Путь к фотографии (для дефектных кристаллов)
#     """
#     if ProtocolPaths.EXCEL_FILE_PATH is None or not ProtocolPaths.EXCEL_FILE_PATH.exists():
#         logger.warning("Excel файл не найден для обновления")
#         return
#
#     try:
#         if (row_index, col_index) not in ProtocolPaths.POSITION_CACHE:
#             logger.warning(f"Позиция не найдена в кэше: строка {row_index}, столбец {col_index}")
#             return
#
#         excel_col = ProtocolPaths.POSITION_CACHE[(row_index, col_index)]
#         wb = load_workbook(ProtocolPaths.EXCEL_FILE_PATH)
#         ws = wb.active
#
#         yellow_fill = PatternFill(start_color="F0E68C", end_color="F0E68C", fill_type="solid")
#         white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
#         thick_border = Side(style="thick", color="000000")
#
#         cell = ws.cell(row=row_index + 1, column=excel_col + 1, value=" ")
#         if defect_type == 0:
#             cell.fill = yellow_fill
#         elif defect_type == 1:
#             cell.fill = white_fill
#             cell.border = Border(diagonal=thick_border, diagonalDown=True, diagonalUp=True)
#             if photo_path and Path(photo_path).exists():
#                 cell.hyperlink = photo_path
#
#         wb.save(ProtocolPaths.EXCEL_FILE_PATH)
#         logger.debug(f"Обновлена ячейка Excel: [{row_index},{col_index}] -> значение {defect_type}")
#
#     except Exception as e:
#         logger.error(f"Ошибка обновления Excel ячейки [{row_index},{col_index}]: {e}")
#
#
# def save_crystal_photo_and_update_excel_cell(row_index, col_index, frame=None,
#                                              crystal_name=None, defect_type=None,
#                                              dest_dir=None):
#     """
#     Сохранение фотографии кристалла и обновление Excel файла
#
#     :param row_index: Индекс строки
#     :param col_index: Индекс столбца
#     :param frame: Кадр с изображением кристалла
#     :param crystal_name: Название кристалла
#     :param defect_type: Тип дефекта (0-годный, 1-бракованный, 2-пропуск)
#     :param dest_dir: Директория для сохранения фото
#     :return: Путь к сохраненному фото или None
#     """
#     photo_path = None
#
#     # Сохранение фото только бракованных кристаллов
#     if defect_type == 1 and frame is not None and crystal_name is not None:
#         photo_path = save_crystal_photo(
#             frame=frame,
#             crystal_name=crystal_name,
#             defect_type=defect_type,
#             dest_dir=dest_dir
#         )
#
#     # Обновляем Excel для ВСЕХ типов дефектов
#     if defect_type is not None:
#         update_excel_cell(
#             row_index=row_index,
#             col_index=col_index,
#             defect_type=defect_type,
#             photo_path=photo_path
#         )
#
#     return photo_path
#
