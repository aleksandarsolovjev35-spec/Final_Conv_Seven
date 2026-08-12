# import subprocess
# import time
#
#
# def safe_disable_com_port(port_name="COM4"):
#     """Безопасно освобождает COM порт без физического отключения"""
#     logger.info("подключение к порту...")
#     print(f"\n🛡️  Безопасное освобождение порта {port_name}")
#
#     # Шаг 1: Закрыть все программы, использующие порт
#     try:
#         # Получаем список процессов, использующих порт
#         cmd = f'netstat -ano | findstr :{port_name.replace("COM", "")}'
#         result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
#
#         if result.stdout:
#             print("   Найдены процессы, использующие порт:")
#             for line in result.stdout.strip().split('\n'):
#                 if 'LISTENING' in line or 'ESTABLISHED' in line:
#                     parts = line.split()
#                     pid = parts[-1]
#
#                     # Получаем имя процесса
#                     try:
#                         task_cmd = f'tasklist /FI "PID eq {pid}" /FO CSV'
#                         task_result = subprocess.run(task_cmd, shell=True, capture_output=True, text=True)
#                         if task_result.stdout:
#                             process_name = task_result.stdout.split('\n')[1].split(',')[0].strip('"')
#                             print(f"   - {process_name} (PID: {pid})")
#                     except:
#                         print(f"   - Неизвестный процесс (PID: {pid})")
#
#                     # Вежливо закрываем (не убиваем!)
#                     try:
#                         subprocess.run(f'taskkill /PID {pid}', shell=True)
#                         print(f"   ✓ Процесс {pid} закрыт")
#                     except:
#                         pass
#
#             time.sleep(2)
#     except Exception as e:
#         print(f"   ⚠️  Ошибка поиска процессов: {e}")
#
#     # Шаг 2: Использовать devcon для мягкого перезапуска
#     try:
#         # Devcon - утилита от Microsoft
#         devcon_path = r"C:\Windows\System32\devcon.exe"
#
#         # Ищем ID устройства Arduino
#         find_cmd = f'{devcon_path} find *CH340*' if 'CH340' in port_name else f'{devcon_path} find *Arduino*'
#         result = subprocess.run(find_cmd, shell=True, capture_output=True, text=True)
#
#         if result.stdout and 'USB\\VID_' in result.stdout:
#             # Нашли Arduino, делаем disable/enable
#             for line in result.stdout.split('\n'):
#                 if 'USB\\VID_' in line and 'PID_' in line:
#                     device_id = line.strip()
#                     print(f"   Найдено устройство: {device_id}")
#
#                     # Отключаем
#                     disable_cmd = f'{devcon_path} disable "{device_id}"'
#                     subprocess.run(disable_cmd, shell=True)
#                     print("   ✓ Устройство отключено программно")
#                     time.sleep(1)
#
#                     # Включаем
#                     enable_cmd = f'{devcon_path} enable "{device_id}"'
#                     subprocess.run(enable_cmd, shell=True)
#                     print("   ✓ Устройство включено")
#                     time.sleep(2)
#                     break
#     except Exception as e:
#         print(f"   ⚠️  Devcon не доступен: {e}")
#
#     # Шаг 3: Ожидание восстановления
#     print("   Ожидание 3 секунды для восстановления...")
#     time.sleep(3)
#
#     return True