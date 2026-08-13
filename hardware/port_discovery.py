"""
Автоматический поиск COM-порта контроллера.

Перебирает доступные порты, отправляет тестовую команду,
проверяет ответ.
"""

import os
import time
import serial
import serial.tools.list_ports


def _allow_legacy() -> bool:
    return os.environ.get("ALLOW_LEGACY_FIRMWARE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# Проверяем именно формат статуса Conveyor, а не любой непустой ответ.
TEST_COMMAND = "I2"

# Время ожидания ответа
TEST_TIMEOUT = 0.5
TEST_DELAY   = 0.3

# Задержка после открытия порта (Arduino reset)
OPEN_DELAY = 2.0


def is_controller_response(response: str) -> bool:
    if not response:
        return False
    # STEP is mandatory: older firmware can report idle without proving that
    # a G3 movement was physically completed.
    required_tokens = ("MOV=", "WAIT=", "STEP=", "lastErr=")
    return all(token in response for token in required_tokens)


def _looks_like_legacy_convey(response: str) -> bool:
    if not response:
        return False
    # Контроллер нашей линии почти всегда отвечает строкой с MOV= и lastErr=.
    # Если при этом есть POS/TGT или PAUSED/AUTO — это convey15, но без STEP=
    # (прошивка <2.5.0). Отличаем от чужого устройства, которое случайно
    # выдало MOV=.
    has_mov = "MOV=" in response
    has_err = "lastErr=" in response
    has_pos = "POS=" in response or "TGT=" in response
    has_wait = "WAIT=" in response
    has_paused = "PAUSED=" in response
    return has_mov and has_err and (has_pos or has_wait or has_paused)


def is_legacy_controller_response(response: str) -> bool:
    return _looks_like_legacy_convey(response) and not is_controller_response(
        response
    )


def list_available_ports() -> list[dict]:
    """
    Список всех доступных COM-портов.

    Returns:
        [{"port": "COM4", "description": "USB-SERIAL", "hwid": "..."}, ...]
    """
    ports = []
    for info in serial.tools.list_ports.comports():
        ports.append({
            "port":        info.device,
            "description": info.description or "",
            "hwid":        info.hwid or "",
            "manufacturer": info.manufacturer or "",
        })
    return ports


def try_port(
    port: str,
    baudrate: int = 115200,
    command: str = TEST_COMMAND,
) -> tuple[bool, str]:
    """
    Попробовать открыть порт и отправить тестовую команду.

    Returns:
        (success, response_or_error)
    """
    ser = None
    try:
        ser = serial.Serial(
            port,
            baudrate,
            timeout=TEST_TIMEOUT,
            write_timeout=2.0,
        )
        time.sleep(OPEN_DELAY)

        # Очистить буфер
        ser.reset_input_buffer()

        # Отправить тестовую команду
        ser.write(f"{command}\n".encode())
        ser.flush()

        time.sleep(TEST_DELAY)

        # Прочитать ответ
        response = ser.read_all().decode(errors="ignore").strip()

        if not response:
            return False, "no response"
        if is_controller_response(response):
            return True, response
        if is_legacy_controller_response(response):
            if _allow_legacy():
                print(
                    f"[PORT] WARNING: {port} legacy firmware accepted "
                    "due to ALLOW_LEGACY_FIRMWARE=1 (unsafe)"
                )
                return True, response
            return False, (
                "legacy firmware without STEP= — I2 must contain "
                "MOV=, WAIT=, STEP=, lastErr=. "
                "Please flash firmware/convey15.ino v2.5.0. "
                f"Got: {response[:160]}"
            )
        if _looks_like_legacy_convey(response):
            if _allow_legacy():
                print(
                    f"[PORT] WARNING: {port} possible legacy accepted "
                    "due to ALLOW_LEGACY_FIRMWARE=1"
                )
                return True, response
            return False, f"possible convey controller but invalid I2 format: {response[:160]}"
        return False, f"unexpected controller response: {response[:120]}"

    except serial.SerialException as e:
        return False, f"serial error: {e}"
    except Exception as e:
        return False, f"error: {e}"
    finally:
        if ser:
            try:
                ser.close()
            except Exception as exc:
                print(f"[SERIAL DISCOVERY] Ошибка закрытия порта: {exc}")


def find_controller(
    baudrate: int = 115200,
    preferred_port: str | None = None,
) -> tuple[str | None, str]:
    """
    Найти порт контроллера автоматически.

    Args:
        baudrate: скорость порта.
        preferred_port: предпочтительный порт (проверяется первым).

    Returns:
        (port, message)
        port = "COM4" или None если не найден.
        message = описание результата.
    """
    available = list_available_ports()

    if not available:
        return None, "No COM ports found on this system"

    port_names = [p["port"] for p in available]
    descriptions = [
        f"{p['port']} ({p['description']})"
        for p in available
    ]

    print(f"[PORT] Found {len(available)} port(s): "
          f"{', '.join(descriptions)}")

    # Порядок проверки: preferred первым, потом остальные
    check_order = []
    if preferred_port and preferred_port in port_names:
        check_order.append(preferred_port)
    for p in port_names:
        if p not in check_order:
            check_order.append(p)

    legacy_hits: list[str] = []
    # Проверяем каждый порт
    for port in check_order:
        info = next(
            (p for p in available if p["port"] == port), {}
        )
        desc = info.get("description", "")

        print(f"[PORT] Trying {port} ({desc})...")

        success, response = try_port(port, baudrate)

        if success:
            print(
                f"[PORT] Controller found on {port}: "
                f"'{response[:80]}'"
            )
            return port, (
                f"Found on {port} ({desc})"
            )
        else:
            print(f"[PORT]   {port}: {response}")
            if "legacy firmware" in response or "legacy" in response.lower():
                legacy_hits.append(f"{port} ({desc}) -> {response[:120]}")

    if legacy_hits:
        return None, (
            f"Controller found but firmware is outdated (no STEP=). "
            f"COM3 is your port, but I2 reply '{check_order[0] if check_order else ''}' "
            f"does not contain STEP=. Please flash firmware/convey15.ino v2.5.0 "
            f"from the repo to {check_order[0] if check_order else 'board'}. "
            f"Legacy hits: {'; '.join(legacy_hits)}. "
            f"Checked: {', '.join(check_order)}. "
            f"If you must run legacy temporarily, set env SERIAL_PORT={check_order[0] if check_order else 'COM3'} "
            f"and ALLOW_LEGACY_FIRMWARE=1, but STEP-protocol safety will be disabled."
        )

    return None, (
        f"Controller not found. "
        f"Checked: {', '.join(check_order)}"
    )