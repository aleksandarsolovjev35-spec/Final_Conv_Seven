import serial
import time
import threading


class SerialTransport:
    """
    Потокобезопасная обёртка над Serial-портом.
    Операции выполняются один раз: после ошибки состояние движения неизвестно,
    поэтому приложение должно перейти в FAULT, а не переподключаться и повторять.
    """

    # Общий предел ожидания ответа на query.
    QUERY_TIMEOUT = 1.0
    # Пауза в потоке данных, после которой ответ считается полным.
    QUIET_PERIOD = 0.03
    # Шаг опроса порта.
    POLL_INTERVAL = 0.01

    def __init__(self, port: str = "COM4", baudrate: int = 115200):
        self.lock     = threading.Lock()
        self.ser      = self._open(port, baudrate)

    def send(self, command: str):
        """Отправить команду один раз, добавив перевод строки.

        Запись могла дойти до контроллера даже если host получил ошибку.
        Поэтому motion/config commands никогда не повторяются автоматически.
        """
        with self.lock:
            self._do_send(command)

    def query(self, command: str, delay: float = 0.15) -> str:
        """Один атомарный request/response без reconnect во время цикла.

        ``delay`` — минимальное окно ожидания ответа, а не фиксированная
        пауза: чтение продолжается, пока контроллер присылает строки.
        """
        with self.lock:
            return self._do_query(command, delay)

    def close(self):
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception as exc:
                    print(f"[SERIAL] Ошибка закрытия порта: {exc}")

    # Internal

    @staticmethod
    def _open(port: str, baudrate: int) -> serial.Serial:
        ser = serial.Serial(
            port,
            baudrate,
            timeout=0.5,
            write_timeout=2.0,
        )
        time.sleep(2)
        return ser

    def _do_send(self, command: str):
        self.ser.write(f"{command}\n".encode())
        self.ser.flush()

    def _do_query(self, command: str, delay: float) -> str:
        """Отправить команду и собрать ответ целиком.

        Прошивка отвечает построчно (``Serial.println``), а многострочные
        ответы вроде ``I10``/``I11`` печатают по строке на ось. Чтение
        фиксированным ``sleep(delay)`` + ``read_all()`` обрезало ответ,
        если контроллер отвечал чуть позже или длиннее одного окна: ACK не
        совпадал с ожидаемым и шаг уходил в FAULT. Поэтому данные
        накапливаются, пока порт их отдаёт, и чтение заканчивается только
        после паузы в потоке (``QUIET_PERIOD``) или по общему дедлайну.
        """
        self.ser.reset_input_buffer()
        self.ser.write(f"{command}\n".encode())
        self.ser.flush()

        deadline = time.monotonic() + max(float(delay), self.QUERY_TIMEOUT)
        chunks = []
        last_data_at = None

        while time.monotonic() < deadline:
            time.sleep(self.POLL_INTERVAL)
            chunk = self.ser.read_all()
            if chunk:
                chunks.append(chunk)
                last_data_at = time.monotonic()
                continue
            if chunks is not None and last_data_at is not None:
                # Ответ начал приходить и поток затих — сообщение целиком.
                if time.monotonic() - last_data_at >= self.QUIET_PERIOD:
                    break

        return b"".join(chunks).decode(errors="ignore").strip()
