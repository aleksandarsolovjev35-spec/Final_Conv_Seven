// =====================================================================
// convey15.ino — управление конвейером + 2 оси NEMA 17 (RAMPS 1.6)
// =====================================================================
//
// Оборудование:
//   Arduino Mega 2560 + RAMPS 1.6
//   NEMA 17 (US-17HS4401S) × 2  — драйверы TMC2209 v2.0 (слоты X, Y)
//   NEMA 23 (57HSE2N-D25)       — драйвер SSD2505 (STEP/DIR мимо RAMPS)
//
// Распиновка:
//   Конвейер (большой шаговик):  STEP=16, DIR=17  (мимо RAMPS, драйвер SSD2505)
//   NEMA 0 (слот X RAMPS):      STEP=54, DIR=55, EN=38
//   NEMA 1 (слот Y RAMPS):      STEP=60, DIR=61, EN=56
//   Концевик X-:  D3   (INPUT_PULLUP, активный LOW)
//   Концевик Y-:  D14  (INPUT_PULLUP, активный LOW)
//   Сервоприводы:  23, 25, 27, 29, 31
//
// ВАЖНО (серво): для защиты от дёрганья при включении установите
//   подтягивающие резисторы 10 кОм от каждого сигнального пина серво к GND.
//   Во время загрузчика (~2 сек) пины Arduino в состоянии INPUT (висят),
//   серво ловят наводки и дёргаются. Резисторы удерживают LOW на сигнале.
//
// G-коды (управление конвейером)
//   G0  — мягкая остановка (stop), затем reset позиции (когда мотор остановится)
//   G1  — аварийная остановка (brake) + reset позиции
//   G2  — поставить следующий цикл в паузу (одноразово)
//   G3  — старт/продолжить (движение на steps_per_division * divisions_per_movement, RELATIVE)
//   G4  S<n>  — ускорение
//   G5  S<n>  — максимальная скорость
//   G6  S<n>  — делений за ход (divisions_per_movement)
//   G7  S<n>  — микрошагов на деление (steps_per_division)
//   G8  S0/1  — направление (1 прямое, 0 инверсия)
//   G9  S<ms> — пауза между автономными ходами (НЕ блокирует, работает на millis())
//   G10 S<°> [P<i>] — повернуть серво (без P = все серво); угол ограничен 43..133°
//   G11 S<ms> — заглушка (плавность серво не реализована)
//   G12 S0/1  — режим автопауз (1 — после хода ждём G3; 0 — автономный цикл)
//   G13 S<ms> — время удержания серво до detach после G10
//
// G-коды (оси NEMA 17) — без P применяется ко ВСЕМ осям
//   G20 S<steps> [P<axis>] — переместить ось RELATIVE (P0=X, P1=Y, без P=все)
//   G21 S<speed> [P<axis>] — максимальная скорость оси (шаг/с)
//   G22 S<accel> [P<axis>] — ускорение оси (шаг/с²)
//   G23 S0/1 [P<axis>]     — направление оси (1 прямое, 0 инверсия)
//   G24 [P<axis>]           — мягкая остановка оси (stop + reset после остановки)
//   G25 [P<axis>]           — аварийная остановка оси (brake + reset)
//   G26 S0/1 [P<axis>]     — включить/выключить драйвер (S1=вкл, S0=выкл)
//   G27 S<steps> [P<axis>] — переместить ось ABSOLUTE
//   G28 [P<axis>]           — умный хоминг (3 фазы: быстрый→отскок→точный)
//   G29 S<speed> [P<axis>] — скорость хоминга оси (шаг/с, по умолчанию 400)
//   G30 S<steps> [P<axis>] — шагов отскока от концевика (по умолчанию 200)
//   G31 S<min> [P<axis>]   — нижняя граница движения (шаги, после хоминга)
//   G32 S<max> [P<axis>]   — верхняя граница движения (шаги, после хоминга)
//   G33 S0/1 [P<axis>]     — включить/выключить программные лимиты оси
//
// I-коды (информация)
//   I0  — Motion: 0/1 (конвейер)
//   I1  — движение? 0/1 (конвейер, короткий ответ)
//   I2  — расширенный статус конвейера одной строкой
//   I3  — текущая конфигурация конвейера (speed/accel/steps/div/pause/...)
//   I4  — состояние сервоприводов (угол/attach/таймер detach)
//   I5  — uptime (сек)
//   I6  — версия прошивки
//   I7  — последняя ошибка (если была)
//   I8  — помощь по I-командам
//   I10 — статус осей NEMA (позиция/цель/движение/драйвер/концевик/хоминг/homed)
//   I11 — конфигурация осей NEMA (speed/accel/dir/homeSpeed/backoff/limits)
//   I12 — состояние концевиков (0=свободен, 1=нажат)
//
// ---------------------------------------------------------------------

#include "GyverStepper2.h"
#include <Servo.h>
#include <math.h>

// ==================== ВЕРСИЯ ====================
static const char* FW_NAME    = "convey15";
static const char* FW_VERSION = "2.4.0";
static const char* FW_DATE    = __DATE__ " " __TIME__;

// ==================== КОНФИГУРАЦИЯ ====================
// ---------- Конвейер (большой шаговик) — пины 16/17, мимо RAMPS ----------
// Драйвер SSD2505, подключён напрямую к БП 24V
GStepper2<STEPPER2WIRE> stepper(20000, 16, 17);

// ---------- Оси NEMA 17 на RAMPS 1.6 (TMC2209 v2.0) ----------
//   Слот X: STEP=54, DIR=55, EN=38
//   Слот Y: STEP=60, DIR=61, EN=56
const uint8_t NUM_NEMA = 2;
GStepper2<STEPPER2WIRE> nema[NUM_NEMA] = {
  GStepper2<STEPPER2WIRE>(200, 54, 55),   // ось 0 (X) — 200 шагов/оборот (1.8°)
  GStepper2<STEPPER2WIRE>(200, 60, 61)    // ось 1 (Y)
};
const uint8_t nemaEnPin[NUM_NEMA]    = {38, 56};   // EN пины TMC2209 (LOW = включён)
const uint8_t nemaEndstopPin[NUM_NEMA] = {3, 14};  // концевики: D3 (X-), D14 (Y-)

// Параметры осей по умолчанию
float    nemaSpeed[NUM_NEMA]     = {1000.0, 1000.0};   // шаг/с
float    nemaAccel[NUM_NEMA]     = {500.0,  500.0};     // шаг/с²
bool     nemaDir[NUM_NEMA]       = {true,   true};       // true = прямое
bool     nemaEnabled[NUM_NEMA]   = {true,   true};       // драйвер включён
float    nemaHomeSpeed[NUM_NEMA] = {400.0,  400.0};     // скорость хоминга (шаг/с)
long     nemaBackoff[NUM_NEMA]   = {200,    200};        // шагов отскока от концевика

// Программные лимиты осей (активны только после хоминга)
long     nemaLimitMin[NUM_NEMA]     = {-15,   -15};      // нижняя граница (шаги)
long     nemaLimitMax[NUM_NEMA]     = {300,   300};      // верхняя граница (шаги)
bool     nemaLimitsEnabled[NUM_NEMA] = {false, false};   // лимиты включены?
bool     nemaHomed[NUM_NEMA]        = {false, false};    // ось прошла хоминг?

// Мягкая остановка для осей NEMA (аналог stopPendingReset конвейера)
bool     nemaStopPending[NUM_NEMA] = {false, false};

// ---------- Хоминг: трёхфазный автомат состояний ----------
enum HomingPhase : uint8_t {
  HOME_IDLE    = 0,
  HOME_SEEK    = 1,
  HOME_BACKOFF = 2,
  HOME_FINE    = 3
};
HomingPhase nemaHomingPhase[NUM_NEMA] = {HOME_IDLE, HOME_IDLE};

// ---------- Сервоприводы — пины 23, 25, 27, 29, 31 ----------
const uint8_t NUM_SERVOS               = 5;
const uint8_t servoPins[NUM_SERVOS]    = {23, 25, 27, 29, 31};

// -------------------- Параметры движения конвейера ------------------
long        steps_per_division          = 19048;
float       speed                       = 30000.0;
float       acceleration                = 10000.0;
bool        direction                   = 1;
int         divisions_per_movement      = 2;
uint32_t    pause_between_movements     = 2000;
bool        autoPauseMode               = true;
bool        pause_checker               = false;

// -------------------- Состояние сервоприводов ----------------------
Servo        servos[NUM_SERVOS];
int          servoPosition[NUM_SERVOS]        = {90, 90, 90, 90, 90};
bool         servoAttached[NUM_SERVOS]        = {false, false, false, false, false};
bool         servoDetachAfterDone[NUM_SERVOS] = {false, false, false, false, false};
unsigned long servoDetachTime[NUM_SERVOS]     = {0, 0, 0, 0, 0};
uint32_t     servoDetachDelayMs              = 300;

// ==================== ВНУТРЕННЕЕ СОСТОЯНИЕ ====================
bool        isMoving        = false;
bool        isPaused        = false;
int32_t     targetSteps     = 0;
bool        interMoveWaitActive = false;
uint32_t    interMoveWaitUntil  = 0;
bool        stopPendingReset = false;
uint32_t    lastArrivedAtMs  = 0;
bool        lastArrivedPulse = false;
String      rxLine;

// -------------------- Ошибки/диагностика --------------------
enum ErrorCode : uint8_t {
  ERR_NONE            = 0,
  ERR_INTEGER_NEEDED  = 1,
  ERR_ANGLE_RANGE     = 2,
  ERR_BAD_SERVO_INDEX = 3,
  ERR_BAD_PARAMS      = 4,
  ERR_UNKNOWN_CMD     = 5,
  ERR_LINE_OVERFLOW   = 6,
  ERR_BAD_AXIS_INDEX  = 7,
  ERR_HOMING_BUSY     = 8,
  ERR_OUT_OF_LIMITS   = 9    // выход за программные лимиты
};
ErrorCode   lastError     = ERR_NONE;
uint32_t    lastErrorAtMs = 0;

void setError(ErrorCode code) {
  lastError = code;
  lastErrorAtMs = millis();
}

// ==================== ПРОТОТИПЫ =========================
void   parseCommands(String input);
void   parseCommand(String cmd);
void   serviceSerial();
void   handleMotionState(bool arrived);
void   handleNemaStopPending();
void   handleNemaHoming();
void   homingStartSeek(uint8_t i);
void   homingStartBackoff(uint8_t i);
void   homingStartFine(uint8_t i);
void   homingFinish(uint8_t i);
void   homingAbort(uint8_t i);
void   startOneMove();
void   detachAllServos();
void   updateServoStates();
long   clampToLimits(uint8_t axis, long absTarget);
float  extractParameter(String cmd, char param);
bool   checkParameter(int caseNumber, float value);
bool   getNemaRange(float axisF, int &startIdx, int &endIdx);
bool   readEndstop(uint8_t axis);
bool   isWhitespace(char c);
bool   isDigit(char c);
bool   isInteger(float v);

// ==================== SETUP =============================
void setup() {
  // *** Сервоприводы — OUTPUT + LOW как можно раньше ***
  // Минимизируем время «висящих» пинов после загрузчика.
  // Для полной защиты: внешние резисторы 10 кОм от пина к GND.
  for (uint8_t i = 0; i < NUM_SERVOS; i++) {
    digitalWrite(servoPins[i], LOW);
    pinMode(servoPins[i], OUTPUT);
    digitalWrite(servoPins[i], LOW);
  }

  // Инициализация осей NEMA 17 (TMC2209 EN) и концевиков
  for (uint8_t i = 0; i < NUM_NEMA; i++) {
    pinMode(nemaEnPin[i], OUTPUT);
    digitalWrite(nemaEnPin[i], LOW);            // LOW = драйвер включён
    pinMode(nemaEndstopPin[i], INPUT_PULLUP);   // концевик: подтяжка к VCC
    nema[i].setMaxSpeed(nemaSpeed[i]);
    nema[i].setAcceleration(nemaAccel[i]);
    nema[i].reverse(!nemaDir[i]);
  }

  Serial.begin(115200);
  stepper.setAcceleration(acceleration);
  stepper.setMaxSpeed(speed);
  stepper.reverse(!direction);
  rxLine.reserve(128);

  Serial.print("FW ");
  Serial.print(FW_NAME);
  Serial.print(" v");
  Serial.print(FW_VERSION);
  Serial.print(" (");
  Serial.print(FW_DATE);
  Serial.println(")");
  Serial.print("NEMA axes: ");
  Serial.println(NUM_NEMA);
}

// ==================== LOOP ==============================
void loop() {
  isMoving = stepper.tick();
  for (uint8_t i = 0; i < NUM_NEMA; i++) {
    nema[i].tick();
  }
  updateServoStates();

  bool arrived = stepper.ready();
  if (arrived) {
    lastArrivedAtMs = millis();
    lastArrivedPulse = true;
    Serial.println("Movement on pause...");
    stepper.reset();
    interMoveWaitActive = true;
    interMoveWaitUntil  = millis() + pause_between_movements;
  }

  handleMotionState(arrived);
  handleNemaStopPending();
  handleNemaHoming();
  serviceSerial();
}

// ========================================================
//                     СЕРВИС Serial (НЕ БЛОКИРУЕТ)
// ========================================================
void serviceSerial() {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      rxLine.trim();
      if (rxLine.length()) parseCommands(rxLine);
      rxLine = "";
      continue;
    }
    if (rxLine.length() < 180) {
      rxLine += ch;
    } else {
      rxLine = "";
      Serial.println("Err: line too long");
      setError(ERR_LINE_OVERFLOW);
    }
  }
}

// ========================================================
//          ЛОГИКА ПОСЛЕ ОКОНЧАНИЯ ХОДА / ОСТАНОВОК (КОНВЕЙЕР)
// ========================================================
void handleMotionState(bool arrived) {
  if (interMoveWaitActive) {
    if ((int32_t)(millis() - interMoveWaitUntil) >= 0) {
      interMoveWaitActive = false;
      if (autoPauseMode || pause_checker) {
        stepper.pause();
        isPaused = true;
        pause_checker = false;
        Serial.println("Paused (wait G3)");
      } else {
        startOneMove();
      }
    }
  }

  if (stopPendingReset) {
    if (!isMoving) {
      stepper.reset();
      stopPendingReset = false;
      Serial.println("G0: stopped, reset done");
    }
  }
}

// ========================================================
//          МЯГКАЯ ОСТАНОВКА ОСЕЙ NEMA (G24)
// ========================================================
void handleNemaStopPending() {
  for (uint8_t i = 0; i < NUM_NEMA; i++) {
    if (nemaStopPending[i]) {
      if (!nema[i].tick()) {
        nema[i].reset();
        nemaStopPending[i] = false;
        Serial.print("G24: axis ");
        Serial.print(i);
        Serial.println(" stopped, reset done");
      }
    }
  }
}

// ========================================================
//     ТРЁХФАЗНЫЙ НЕБЛОКИРУЮЩИЙ ХОМИНГ ОСЕЙ NEMA (G28)
// ========================================================
void handleNemaHoming() {
  for (uint8_t i = 0; i < NUM_NEMA; i++) {
    switch (nemaHomingPhase[i]) {
      case HOME_IDLE:
        break;
      case HOME_SEEK:
        if (readEndstop(i)) {
          nema[i].brake();
          nema[i].reset();
          Serial.print("G28: axis ");
          Serial.print(i);
          Serial.println(" endstop hit (seek), backing off...");
          homingStartBackoff(i);
        }
        break;
      case HOME_BACKOFF:
        if (nema[i].ready()) {
          nema[i].reset();
          if (readEndstop(i)) {
            Serial.print("G28: axis ");
            Serial.print(i);
            Serial.println(" still on endstop, backing off more...");
            homingStartBackoff(i);
          } else {
            Serial.print("G28: axis ");
            Serial.print(i);
            Serial.println(" backed off, fine approach...");
            homingStartFine(i);
          }
        }
        break;
      case HOME_FINE:
        if (readEndstop(i)) {
          nema[i].brake();
          homingFinish(i);
        }
        break;
    }
  }
}

void homingStartSeek(uint8_t i) {
  nemaHomingPhase[i] = HOME_SEEK;
  nemaStopPending[i] = false;
  nema[i].setMaxSpeed(nemaHomeSpeed[i]);
  nema[i].setAcceleration(nemaAccel[i]);
  nema[i].setTarget(-2000000L, RELATIVE);
  Serial.print("G28: axis ");
  Serial.print(i);
  Serial.print(" seeking at speed ");
  Serial.println((long)nemaHomeSpeed[i]);
}

void homingStartBackoff(uint8_t i) {
  nemaHomingPhase[i] = HOME_BACKOFF;
  nema[i].setMaxSpeed(nemaHomeSpeed[i]);
  nema[i].setAcceleration(nemaAccel[i]);
  nema[i].setTarget(nemaBackoff[i], RELATIVE);
}

void homingStartFine(uint8_t i) {
  nemaHomingPhase[i] = HOME_FINE;
  float fineSpeed = nemaHomeSpeed[i] / 4.0;
  if (fineSpeed < 10.0) fineSpeed = 10.0;
  nema[i].setMaxSpeed(fineSpeed);
  nema[i].setAcceleration(nemaAccel[i]);
  nema[i].setTarget(-2000000L, RELATIVE);
  Serial.print("G28: axis ");
  Serial.print(i);
  Serial.print(" fine at speed ");
  Serial.println((long)fineSpeed);
}

void homingFinish(uint8_t i) {
  nema[i].reset();                              // позиция = 0
  nemaHomingPhase[i] = HOME_IDLE;
  nemaHomed[i] = true;                          // ось захомлена
  nemaLimitsEnabled[i] = true;                  // автоматически включаем лимиты
  nema[i].setMaxSpeed(nemaSpeed[i]);
  nema[i].setAcceleration(nemaAccel[i]);
  Serial.print("G28: axis ");
  Serial.print(i);
  Serial.print(" homed OK (pos=0), limits ON [");
  Serial.print(nemaLimitMin[i]);
  Serial.print("; ");
  Serial.print(nemaLimitMax[i]);
  Serial.println("]");
}

void homingAbort(uint8_t i) {
  if (nemaHomingPhase[i] != HOME_IDLE) {
    nemaHomingPhase[i] = HOME_IDLE;
    nema[i].setMaxSpeed(nemaSpeed[i]);
    nema[i].setAcceleration(nemaAccel[i]);
    Serial.print("G28: axis ");
    Serial.print(i);
    Serial.println(" homing aborted");
  }
}

bool readEndstop(uint8_t axis) {
  if (axis >= NUM_NEMA) return false;
  return digitalRead(nemaEndstopPin[axis]) == LOW;
}

// ========================================================
//     ПРОГРАММНЫЕ ЛИМИТЫ — ограничение целевой позиции
// ========================================================
// Возвращает скорректированный absTarget.
// Если лимиты выключены или ось не захомлена — возвращает как есть.
long clampToLimits(uint8_t axis, long absTarget) {
  if (!nemaLimitsEnabled[axis] || !nemaHomed[axis]) return absTarget;
  if (absTarget < nemaLimitMin[axis]) {
    Serial.print("Warn: axis ");
    Serial.print(axis);
    Serial.print(" clamped to min=");
    Serial.println(nemaLimitMin[axis]);
    setError(ERR_OUT_OF_LIMITS);
    return nemaLimitMin[axis];
  }
  if (absTarget > nemaLimitMax[axis]) {
    Serial.print("Warn: axis ");
    Serial.print(axis);
    Serial.print(" clamped to max=");
    Serial.println(nemaLimitMax[axis]);
    setError(ERR_OUT_OF_LIMITS);
    return nemaLimitMax[axis];
  }
  return absTarget;
}

void startOneMove() {
  if (isPaused) {
    stepper.resume();
    isPaused = false;
  }
  interMoveWaitActive = false;
  targetSteps = (int32_t)(steps_per_division * (long)divisions_per_movement);
  stepper.setTarget(targetSteps, RELATIVE);
  Serial.println("Move start (RELATIVE)");
}

// ========================================================
//              ПАРСИНГ СТРОКИ КОМАНД
// ========================================================
void parseCommands(String input) {
  input.trim();
  int pos = 0;
  int len = (int)input.length();
  while (pos < len) {
    while (pos < len && isWhitespace(input[pos])) pos++;
    if (pos >= len) break;
    char c = input[pos];
    if (c == 'G' || c == 'I' || isDigit(c)) {
      int cmdStart = pos;
      if (isDigit(c)) {
        input = "G" + input.substring(pos);
        cmdStart = 0;
        pos = 1;
        len = (int)input.length();
      } else {
        pos++;
      }
      while (pos < len && isDigit(input[pos])) pos++;
      while (pos < len && input[pos] != 'G' && input[pos] != 'I') pos++;
      String cmd = input.substring(cmdStart, pos);
      parseCommand(cmd);
    } else {
      pos++;
    }
  }
}

// ========================================================
//    Диапазон осей NEMA: P указан → одна ось; P не указан → все
// ========================================================
// Возвращает true если диапазон валиден.
// startIdx/endIdx задают полуоткрытый интервал [start, end).
bool getNemaRange(float axisF, int &startIdx, int &endIdx) {
  if (isnan(axisF)) {
    // P не указан → все оси
    startIdx = 0;
    endIdx = NUM_NEMA;
    return true;
  }
  int idx = (int)axisF;
  if (idx < 0 || idx >= NUM_NEMA) {
    Serial.println("Err: axis 0-" + String(NUM_NEMA - 1));
    setError(ERR_BAD_AXIS_INDEX);
    return false;
  }
  startIdx = idx;
  endIdx = idx + 1;
  return true;
}

// ========================================================
//                ПАРСИНГ ОДНОЙ G/I-КОМАНДЫ
// ========================================================
void parseCommand(String cmd) {
  cmd.trim();
  if (!cmd.length()) return;
  char prefix = cmd.charAt(0);
  int numEnd = 1;
  while (numEnd < (int)cmd.length() && isDigit(cmd[numEnd])) numEnd++;
  int cmdNumber = cmd.substring(1, numEnd).toInt();
  String params = cmd.substring(numEnd);
  params.trim();

  // ================= G-КОДЫ ============================
  if (prefix == 'G') {
    switch (cmdNumber) {
      // ------------- КОНВЕЙЕР (G0..G13) -------------
      case 0:
        interMoveWaitActive = false;
        stepper.stop();
        stopPendingReset = true;
        Serial.println("G0: smooth stop");
        break;
      case 1:
        interMoveWaitActive = false;
        stopPendingReset = false;
        stepper.brake();
        stepper.reset();
        isPaused = false;
        Serial.println("G1: emergency stop");
        break;
      case 2:
        pause_checker = true;
        Serial.println("G2: next pause enabled");
        break;
      case 3:
        startOneMove();
        break;
      case 4: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && checkParameter(4, v)) {
          acceleration = v;
          stepper.setAcceleration(acceleration);
          Serial.println("G4: accel=" + String((long)v));
        } else if (isnan(v)) {
          Serial.println("Err: G4 needs S<n>");
          setError(ERR_BAD_PARAMS);
        }
      } break;
      case 5: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && checkParameter(5, v)) {
          speed = v;
          stepper.setMaxSpeed(speed);
          Serial.println("G5: speed=" + String((long)v));
        } else if (isnan(v)) {
          Serial.println("Err: G5 needs S<n>");
          setError(ERR_BAD_PARAMS);
        }
      } break;
      case 6: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && checkParameter(6, v)) {
          divisions_per_movement = (int)v;
          Serial.println("G6: divisions=" + String(divisions_per_movement));
        } else if (isnan(v)) {
          Serial.println("Err: G6 needs S<n>");
          setError(ERR_BAD_PARAMS);
        }
      } break;
      case 7: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && checkParameter(7, v)) {
          steps_per_division = (long)v;
          Serial.println("G7: steps/div=" + String(steps_per_division));
        } else if (isnan(v)) {
          Serial.println("Err: G7 needs S<n>");
          setError(ERR_BAD_PARAMS);
        }
      } break;
      case 8: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && (v == 0 || v == 1)) {
          direction = (bool)v;
          stepper.reverse(!direction);
          Serial.println(String("G8: direction=") + (direction ? "1" : "0"));
        } else {
          Serial.println("Err: G8 needs S0 or S1");
          setError(ERR_BAD_PARAMS);
        }
      } break;
      case 9: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && checkParameter(9, v)) {
          pause_between_movements = (uint32_t)v;
          Serial.println("G9: pause_ms=" + String(pause_between_movements));
        } else if (isnan(v)) {
          Serial.println("Err: G9 needs S<ms>");
          setError(ERR_BAD_PARAMS);
        }
      } break;
      case 10: { // G10 S<°> [P<i>] — серво; без P = все серво
        float angleF = extractParameter(params, 'S');
        float indexF = extractParameter(params, 'P');
        if (isnan(angleF) || !checkParameter(10, angleF)) {
          Serial.println("Err: G10 needs S<angle 0..180>");
          if (!isnan(angleF)) setError(ERR_ANGLE_RANGE);
          else setError(ERR_BAD_PARAMS);
          break;
        }
        int targetAngle = constrain((int)angleF, 43, 133);
        int sStart, sEnd;
        if (isnan(indexF)) {
          // P не указан — все серво
          sStart = 0;
          sEnd = NUM_SERVOS;
        } else {
          int si = (int)indexF;
          if (si < 0 || si >= NUM_SERVOS) {
            Serial.println("Err: P 0-" + String(NUM_SERVOS - 1));
            setError(ERR_BAD_SERVO_INDEX);
            break;
          }
          sStart = si;
          sEnd = si + 1;
        }
        detachAllServos();
        for (int si = sStart; si < sEnd; si++) {
          servos[si].write(targetAngle);
          if (!servoAttached[si]) {
            servos[si].attach(servoPins[si]);
            servoAttached[si] = true;
          }
          servos[si].write(targetAngle);
          servoPosition[si] = targetAngle;
          servoDetachAfterDone[si] = true;
          servoDetachTime[si] = millis() + servoDetachDelayMs;
          Serial.println("G10: servo " + String(si) + " -> " + String(targetAngle));
        }
      } break;
      case 11: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && checkParameter(11, v)) {
          Serial.println("G11: stub, S=" + String((long)v));
        } else if (isnan(v)) {
          Serial.println("G11: stub (no params)");
        }
      } break;
      case 12: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && (v == 0 || v == 1)) {
          autoPauseMode = (bool)v;
          Serial.println(String("G12: autoPause=") + (autoPauseMode ? "1" : "0"));
        } else {
          Serial.println("Err: G12 needs S0 or S1");
          setError(ERR_BAD_PARAMS);
        }
      } break;
      case 13: {
        float v = extractParameter(params, 'S');
        if (!isnan(v) && checkParameter(13, v)) {
          servoDetachDelayMs = (uint32_t)v;
          Serial.println("G13: servoDetachDelayMs=" + String(servoDetachDelayMs));
        } else if (isnan(v)) {
          Serial.println("Err: G13 needs S<ms>");
          setError(ERR_BAD_PARAMS);
        }
      } break;

      // =============== ОСИ NEMA 17 (G20..G33) — без P = все оси ===============
      case 20: { // G20 S<steps> [P<axis>] — RELATIVE
        float stepsF = extractParameter(params, 'S');
        float axisF  = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(stepsF)) { Serial.println("Err: G20 needs S<steps>"); setError(ERR_BAD_PARAMS); break; }
        long steps = (long)stepsF;
        for (int i = s; i < e; i++) {
          long absT = nema[i].getCurrent() + steps;
          absT = clampToLimits(i, absT);
          nema[i].setTarget(absT);
          Serial.print("G20: axis "); Serial.print(i); Serial.print(" move to "); Serial.println(absT);
        }
      } break;
      case 21: { // G21 S<speed> [P<axis>]
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v) || !isInteger(v)) { Serial.println("Err: G21 needs S<integer speed>"); setError(isnan(v)?ERR_BAD_PARAMS:ERR_INTEGER_NEEDED); break; }
        for (int i = s; i < e; i++) {
          nemaSpeed[i] = v; nema[i].setMaxSpeed(v);
          Serial.print("G21: axis "); Serial.print(i); Serial.print(" speed="); Serial.println((long)v);
        }
      } break;
      case 22: { // G22 S<accel> [P<axis>]
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v) || !isInteger(v)) { Serial.println("Err: G22 needs S<integer accel>"); setError(isnan(v)?ERR_BAD_PARAMS:ERR_INTEGER_NEEDED); break; }
        for (int i = s; i < e; i++) {
          nemaAccel[i] = v; nema[i].setAcceleration(v);
          Serial.print("G22: axis "); Serial.print(i); Serial.print(" accel="); Serial.println((long)v);
        }
      } break;
      case 23: { // G23 S0/1 [P<axis>]
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v) || (v != 0 && v != 1)) { Serial.println("Err: G23 needs S0 or S1"); setError(ERR_BAD_PARAMS); break; }
        for (int i = s; i < e; i++) {
          nemaDir[i] = (bool)v; nema[i].reverse(!nemaDir[i]);
          Serial.print("G23: axis "); Serial.print(i); Serial.print(" dir="); Serial.println(nemaDir[i]?"1":"0");
        }
      } break;
      case 24: { // G24 [P<axis>] — мягкая остановка
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        for (int i = s; i < e; i++) {
          homingAbort(i); nema[i].stop(); nemaStopPending[i] = true;
          Serial.print("G24: axis "); Serial.print(i); Serial.println(" smooth stop");
        }
      } break;
      case 25: { // G25 [P<axis>] — аварийная остановка
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        for (int i = s; i < e; i++) {
          homingAbort(i); nema[i].brake(); nema[i].reset(); nemaStopPending[i] = false;
          Serial.print("G25: axis "); Serial.print(i); Serial.println(" emergency stop");
        }
      } break;
      case 26: { // G26 S0/1 [P<axis>] — драйвер вкл/выкл
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v) || (v != 0 && v != 1)) { Serial.println("Err: G26 needs S0 or S1"); setError(ERR_BAD_PARAMS); break; }
        for (int i = s; i < e; i++) {
          nemaEnabled[i] = (bool)v;
          digitalWrite(nemaEnPin[i], nemaEnabled[i] ? LOW : HIGH);
          Serial.print("G26: axis "); Serial.print(i); Serial.print(" driver="); Serial.println(nemaEnabled[i]?"ON":"OFF");
        }
      } break;
      case 27: { // G27 S<steps> [P<axis>] — ABSOLUTE
        float stepsF = extractParameter(params, 'S');
        float axisF  = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(stepsF)) { Serial.println("Err: G27 needs S<steps>"); setError(ERR_BAD_PARAMS); break; }
        long absT = (long)stepsF;
        for (int i = s; i < e; i++) {
          long t = clampToLimits(i, absT);
          nema[i].setTarget(t);
          Serial.print("G27: axis "); Serial.print(i); Serial.print(" move ABS "); Serial.println(t);
        }
      } break;
      case 28: { // G28 [P<axis>] — хоминг
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        for (int i = s; i < e; i++) {
          if (nemaHomingPhase[i] != HOME_IDLE) {
            Serial.print("Err: axis "); Serial.print(i); Serial.println(" already homing");
            setError(ERR_HOMING_BUSY);
            continue;
          }
          nemaHomed[i] = false;
          nemaLimitsEnabled[i] = false;
          if (readEndstop(i)) {
            Serial.print("G28: axis "); Serial.print(i); Serial.println(" already on endstop, backing off first...");
            nema[i].reset();
            homingStartBackoff(i);
          } else {
            homingStartSeek(i);
          }
        }
      } break;
      case 29: { // G29 S<speed> [P<axis>]
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v) || !isInteger(v)) { Serial.println("Err: G29 needs S<integer speed>"); setError(isnan(v)?ERR_BAD_PARAMS:ERR_INTEGER_NEEDED); break; }
        for (int i = s; i < e; i++) {
          nemaHomeSpeed[i] = v;
          Serial.print("G29: axis "); Serial.print(i); Serial.print(" homeSpeed="); Serial.println((long)v);
        }
      } break;
      case 30: { // G30 S<steps> [P<axis>]
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v) || !isInteger(v)) { Serial.println("Err: G30 needs S<integer steps>"); setError(isnan(v)?ERR_BAD_PARAMS:ERR_INTEGER_NEEDED); break; }
        for (int i = s; i < e; i++) {
          nemaBackoff[i] = (long)v;
          Serial.print("G30: axis "); Serial.print(i); Serial.print(" backoff="); Serial.println(nemaBackoff[i]);
        }
      } break;
      case 31: { // G31 S<min> [P<axis>]
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v)) { Serial.println("Err: G31 needs S<steps>"); setError(ERR_BAD_PARAMS); break; }
        for (int i = s; i < e; i++) {
          nemaLimitMin[i] = (long)v;
          Serial.print("G31: axis "); Serial.print(i); Serial.print(" limitMin="); Serial.println(nemaLimitMin[i]);
        }
      } break;
      case 32: { // G32 S<max> [P<axis>]
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v)) { Serial.println("Err: G32 needs S<steps>"); setError(ERR_BAD_PARAMS); break; }
        for (int i = s; i < e; i++) {
          nemaLimitMax[i] = (long)v;
          Serial.print("G32: axis "); Serial.print(i); Serial.print(" limitMax="); Serial.println(nemaLimitMax[i]);
        }
      } break;
      case 33: { // G33 S0/1 [P<axis>]
        float v     = extractParameter(params, 'S');
        float axisF = extractParameter(params, 'P');
        int s, e;
        if (!getNemaRange(axisF, s, e)) break;
        if (isnan(v) || (v != 0 && v != 1)) { Serial.println("Err: G33 needs S0 or S1"); setError(ERR_BAD_PARAMS); break; }
        for (int i = s; i < e; i++) {
          nemaLimitsEnabled[i] = (bool)v;
          Serial.print("G33: axis "); Serial.print(i); Serial.print(" limits="); Serial.println(nemaLimitsEnabled[i]?"ON":"OFF");
        }
      } break;

      default:
        Serial.println("Unknown G code " + String(cmdNumber));
        setError(ERR_UNKNOWN_CMD);
        break;
    }
  }

  // ================= I-КОДЫ ============================
  else if (prefix == 'I') {
    switch (cmdNumber) {
      case 0:
        Serial.print("Motion: ");
        Serial.println(isMoving ? 1 : 0);
        break;
      case 1:
        Serial.println(isMoving ? 1 : 0);
        break;
      case 2: {
        Serial.print("MOV=");  Serial.print(isMoving ? 1 : 0);
        Serial.print(" PAUSED="); Serial.print(isPaused ? 1 : 0);
        Serial.print(" AUTO=");   Serial.print(autoPauseMode ? 1 : 0);
        Serial.print(" WAIT=");   Serial.print(interMoveWaitActive ? 1 : 0);
        Serial.print(" POS=");    Serial.print(stepper.getCurrent());
        Serial.print(" TGT=");    Serial.print(stepper.getTarget());
        Serial.print(" lastReadyMs="); Serial.print(lastArrivedAtMs);
        Serial.print(" lastErr=");     Serial.println((uint8_t)lastError);
        lastArrivedPulse = false;
      } break;
      case 3:
        Serial.print("speed="); Serial.println((long)speed);
        Serial.print("accel="); Serial.println((long)acceleration);
        Serial.print("steps_per_division="); Serial.println(steps_per_division);
        Serial.print("divisions_per_movement="); Serial.println(divisions_per_movement);
        Serial.print("direction="); Serial.println(direction ? 1 : 0);
        Serial.print("pause_between_movements_ms="); Serial.println(pause_between_movements);
        Serial.print("servoDetachDelayMs="); Serial.println(servoDetachDelayMs);
        Serial.print("autoPauseMode="); Serial.println(autoPauseMode ? 1 : 0);
        break;
      case 4: {
        for (uint8_t i = 0; i < NUM_SERVOS; i++) {
          Serial.print("S"); Serial.print(i);
          Serial.print(" angle="); Serial.print(servoPosition[i]);
          Serial.print(" attached="); Serial.print(servoAttached[i] ? 1 : 0);
          Serial.print(" detachInMs=");
          if (servoDetachAfterDone[i]) {
            long left = (long)(servoDetachTime[i] - millis());
            if (left < 0) left = 0;
            Serial.println(left);
          } else {
            Serial.println(-1);
          }
        }
      } break;
      case 5:
        Serial.println(millis() / 1000UL);
        break;
      case 6:
        Serial.print(FW_NAME);
        Serial.print(" v");
        Serial.print(FW_VERSION);
        Serial.print(" (");
        Serial.print(FW_DATE);
        Serial.println(")");
        break;
      case 7: {
        Serial.print("ERR=");
        Serial.print((uint8_t)lastError);
        Serial.print(" atMs=");
        Serial.println(lastErrorAtMs);
      } break;
      case 8:
        Serial.println("I0  Motion: 0/1 (conveyor)");
        Serial.println("I1  0/1 (conveyor moving)");
        Serial.println("I2  conveyor status line");
        Serial.println("I3  conveyor config");
        Serial.println("I4  servos");
        Serial.println("I5  uptime_s");
        Serial.println("I6  fw_version");
        Serial.println("I7  last_error");
        Serial.println("I10 NEMA axes status");
        Serial.println("I11 NEMA axes config");
        Serial.println("I12 endstop status");
        break;
      case 10: { // I10 — статус осей
        for (uint8_t i = 0; i < NUM_NEMA; i++) {
          Serial.print("AXIS"); Serial.print(i);
          Serial.print(" POS=");    Serial.print(nema[i].getCurrent());
          Serial.print(" TGT=");    Serial.print(nema[i].getTarget());
          Serial.print(" MOV=");    Serial.print(nema[i].tick() ? 1 : 0);
          Serial.print(" EN=");     Serial.print(nemaEnabled[i] ? 1 : 0);
          Serial.print(" STOP_P="); Serial.print(nemaStopPending[i] ? 1 : 0);
          Serial.print(" HOME=");   Serial.print((uint8_t)nemaHomingPhase[i]);
          Serial.print(" HOMED=");  Serial.print(nemaHomed[i] ? 1 : 0);
          Serial.print(" LIM=");    Serial.print(nemaLimitsEnabled[i] ? 1 : 0);
          Serial.print(" ES=");     Serial.println(readEndstop(i) ? 1 : 0);
        }
      } break;
      case 11: { // I11 — конфигурация осей
        for (uint8_t i = 0; i < NUM_NEMA; i++) {
          Serial.print("AXIS"); Serial.print(i);
          Serial.print(" speed=");   Serial.print((long)nemaSpeed[i]);
          Serial.print(" accel=");   Serial.print((long)nemaAccel[i]);
          Serial.print(" dir=");     Serial.print(nemaDir[i] ? 1 : 0);
          Serial.print(" en=");      Serial.print(nemaEnabled[i] ? 1 : 0);
          Serial.print(" homeSpd="); Serial.print((long)nemaHomeSpeed[i]);
          Serial.print(" backoff="); Serial.print(nemaBackoff[i]);
          Serial.print(" limMin=");  Serial.print(nemaLimitMin[i]);
          Serial.print(" limMax=");  Serial.println(nemaLimitMax[i]);
        }
      } break;
      case 12: {
        for (uint8_t i = 0; i < NUM_NEMA; i++) {
          Serial.print("ES"); Serial.print(i);
          Serial.print(" pin="); Serial.print(nemaEndstopPin[i]);
          Serial.print(" state="); Serial.println(readEndstop(i) ? "TRIGGERED" : "open");
        }
      } break;
      default:
        Serial.println("Unknown I code " + String(cmdNumber));
        setError(ERR_UNKNOWN_CMD);
        break;
    }
  }
  else {
    Serial.println("Unknown command (" + cmd + ")");
    setError(ERR_UNKNOWN_CMD);
  }
}

// ========================================================
//                    СЕРВО: авто-detach по таймеру
// ========================================================
void updateServoStates() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < NUM_SERVOS; i++) {
    if (servoDetachAfterDone[i] && now >= servoDetachTime[i]) {
      if (servoAttached[i]) {
        servos[i].detach();
        servoAttached[i] = false;
        digitalWrite(servoPins[i], LOW);
        Serial.print("Servo ");
        Serial.print(i);
        Serial.println(" detached");
      }
      servoDetachAfterDone[i] = false;
    }
  }
}

void detachAllServos() {
  for (uint8_t i = 0; i < NUM_SERVOS; i++) {
    if (servoAttached[i]) {
      servos[i].detach();
      servoAttached[i] = false;
      digitalWrite(servoPins[i], LOW);
      Serial.print("Servo ");
      Serial.print(i);
      Serial.println(" detached (forced)");
    }
    servoDetachAfterDone[i] = false;
  }
}

// ========================================================
//                    ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ========================================================
float extractParameter(String cmd, char param) {
  int idx = cmd.indexOf(param);
  if (idx == -1) return NAN;
  int start = idx + 1;
  int end = start;
  int len = (int)cmd.length();
  // Поддержка отрицательных чисел: первый символ может быть '-'
  if (end < len && cmd[end] == '-') end++;
  while (end < len && !isWhitespace(cmd[end]) && cmd[end] != 'G' && cmd[end] != 'I') end++;
  if (end == start) return NAN;  // нет значения после буквы параметра
  return cmd.substring(start, end).toFloat();
}

bool checkParameter(int caseNumber, float value) {
  switch (caseNumber) {
    case 4: case 5: case 6: case 7: case 9: case 11: case 13:
      if (!isInteger(value)) {
        Serial.println("Error: integer needed");
        setError(ERR_INTEGER_NEEDED);
        return false;
      }
      break;
    case 10: 
      if (value < 0 || value > 180) {
        Serial.println("Error: angle 0-180");
        setError(ERR_ANGLE_RANGE);
        return false;
      }
      break;
  }
  return true;
}

bool isWhitespace(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }
bool isDigit(char c) { return c >= '0' && c <= '9'; }
bool isInteger(float v) { return fabs(v - round(v)) < 0.00001; }
