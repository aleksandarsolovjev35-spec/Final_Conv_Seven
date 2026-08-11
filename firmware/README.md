# Firmware convey15

Прошивка Arduino Mega 2560 + RAMPS 1.6 для управления конвейером и двухосевым распределителем.

- **Файл прошивки:** `convey15.ino` (`FW convey15 v2.4.0`)
- **Зависимости:** `GyverStepper2`, `Servo` (Arduino IDE Library Manager)
- **Плата:** Arduino Mega 2560, baud 115200

## Оборудование

| Устройство | Подключение |
|---|---|
| Конвейер NEMA 23 (57HSE2N-D25) + SSD2505 | STEP=16, DIR=17 (мимо RAMPS, 24V) |
| NEMA 17 #0 (слот X, TMC2209) | STEP=54, DIR=55, EN=38 |
| NEMA 17 #1 (слот Y, TMC2209) | STEP=60, DIR=61, EN=56 |
| Концевики | D3 (X-), D14 (Y-), INPUT_PULLUP LOW |
| Серво ×5 | 23, 25, 27, 29, 31 (резисторы 10к к GND от наводок) |

## Протокол

G-коды конвейера `G0..G13`, оси `G20..G33`, информация `I0..I12`. Подробно — в шапке `convey15.ino`.

Хост-софт (`hardware/conveyor.py`, `hardware/axis.py`, `hardware/distributor.py`) работает поверх `SerialTransport` и использует `G3`/`I1`/`I2` для шага, `G28` для хоминга и `G20`/`G27` для движения осей.

## Загрузка

1. Открыть `firmware/convey15.ino` в Arduino IDE
2. Установить библиотеки: `GyverStepper2` (GyverLibs), `Servo`
3. Выбрать плату *Arduino Mega 2560*, порт COM
4. Загрузить

## Версионирование

Версия в шапке файла: `FW_VERSION = "2.4.0"` + `FW_DATE = __DATE__ " " __TIME__`. При изменении прошивки обновляйте `FW_VERSION` и документируйте в git-коммите.
