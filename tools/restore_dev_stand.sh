#!/usr/bin/env bash
# restore_dev_stand.sh — поднять стенд симуляции HMI в Linux-окружении
# (песочница, CI-хост) после его пересборки. На Windows стенд поднимают
# setup.bat + run.bat: этот скрипт для Linux.
#
# Что делает по шагам:
#   1. подтягивает рабочую ветку из origin (локальный клон после
#      пересборки окружения откатывается к main);
#   2. собирает .venv, если его нет, и ставит зависимости;
#   3. ставит jsdom для проверок HMI (tests/ui), если есть npm;
#   4. запускает ui_simulation.py на 0.0.0.0.
#
# Почему зависимость от OpenCV подменяется: в требованиях стоит
# opencv-python, которому нужен libGL. На хосте без графики его нет, и
# импорт падает с «ImportError: libGL.so.1». Сборка opencv-python-headless
# даёт тот же API (включая imshow и VideoCapture) без графических библиотек.
# Ultralytics на стенд не нужен: ui_simulation.py нейросети не запускает
# (он импортирует только cv2, numpy, domain, inspection и vision.ui.server),
# но приложение целиком — нужен, поэтому он ставится по флагу --with-vision.
#
# Использование:
#   tools/restore_dev_stand.sh                  # ветка + окружение + запуск
#   tools/restore_dev_stand.sh --port 8080      # другой порт
#   tools/restore_dev_stand.sh --skip-branch    # не трогать git
#   tools/restore_dev_stand.sh --only-deps      # только собрать окружение
#   tools/restore_dev_stand.sh --with-vision    # добавить ultralytics

set -euo pipefail

BRANCH="${BRANCH:-arena/2cb00061-final-conv-seven}"
PORT=8000
HOST=0.0.0.0
SKIP_BRANCH=0
ONLY_DEPS=0
WITH_VISION=0

while [ $# -gt 0 ]; do
    case "$1" in
        --port)        PORT="$2"; shift 2 ;;
        --host)        HOST="$2"; shift 2 ;;
        --branch)      BRANCH="$2"; shift 2 ;;
        --skip-branch) SKIP_BRANCH=1; shift ;;
        --only-deps)   ONLY_DEPS=1; shift ;;
        --with-vision) WITH_VISION=1; shift ;;
        -h|--help)     sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
done

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

PYTHON="${PYTHON:-python3}"

step() { printf '\n=== %s ===\n' "$1"; }

# ─── 1. Ветка ────────────────────────────────────────────────────────
if [ "$SKIP_BRANCH" -eq 0 ] && git rev-parse --git-dir >/dev/null 2>&1; then
    step "Ветка $BRANCH"
    if git fetch -q origin "$BRANCH" 2>/dev/null; then
        local_head="$(git rev-parse HEAD)"
        remote_head="$(git rev-parse FETCH_HEAD)"
        if [ "$local_head" = "$remote_head" ]; then
            echo "уже на $remote_head — git не трогаем"
        else
            # Незакоммиченные правки в песочнице не нужны: их источник —
            # сама ветка. Если что-то и было, оно лежит в stash.
            git stash --include-untracked -q -m "restore_dev_stand: автосохранение" || true
            git reset --hard FETCH_HEAD -q
            echo "переключено на $(git log --oneline -1)"
        fi
    else
        echo "не удалось получить $BRANCH — остаёмся на $(git log --oneline -1)"
    fi
fi

# ─── 2. Окружение ────────────────────────────────────────────────────
if [ ! -x .venv/bin/python ]; then
    step "Сборка .venv"
    "$PYTHON" -m venv .venv
    .venv/bin/pip install -q --upgrade pip
else
    step "Окружение .venv уже есть"
fi

step "Зависимости"
# Требования — из requirements*.txt, но OpenCV берём headless-сборкой.
.venv/bin/pip install -q \
    "numpy>=1.26,<2.1" \
    "opencv-python-headless>=4.10,<4.12" \
    "pyserial>=3.5,<4" \
    "fastapi>=0.115,<1" \
    "uvicorn>=0.34,<1" \
    -r requirements-dev.txt

if [ "$WITH_VISION" -eq 1 ]; then
    .venv/bin/pip install -q "ultralytics>=8.3,<9"
    # ultralytics тянет opencv-python обратно — возвращаем headless-сборку.
    .venv/bin/pip uninstall -q -y opencv-python 2>/dev/null || true
    .venv/bin/pip install -q "opencv-python-headless>=4.10,<4.12"
fi

.venv/bin/python - <<'PY'
import cv2
assert hasattr(cv2, "VideoCapture") and hasattr(cv2, "imwrite"), "cv2 без нужных функций"
print(f"cv2 {cv2.__version__}: VideoCapture, imread, imwrite, imshow — на месте")
PY

# ─── 3. Проверки HMI ─────────────────────────────────────────────────
if command -v npm >/dev/null 2>&1; then
    step "jsdom для tests/ui"
    (cd tests/ui && npm install --silent --no-fund --no-audit >/dev/null 2>&1) \
        && echo "npm install выполнен" \
        || echo "npm install не удался — проверки HMI запустятся после установки вручную"
else
    echo "npm не найден — проверки HMI (tests/ui) пропускаем"
fi

if [ "$ONLY_DEPS" -eq 1 ]; then
    step "Готово"
    echo "окружение собрано; запуск: .venv/bin/python -u ui_simulation.py --host $HOST --port $PORT"
    exit 0
fi

# ─── 4. Стенд ────────────────────────────────────────────────────────
step "Стенд"
if curl -s -m 3 -o /dev/null "http://localhost:$PORT/"; then
    echo "на порту $PORT уже отвечает сервер — новый не запускаем"
    echo "адрес: http://localhost:$PORT/"
    exit 0
fi
echo "запуск: http://$HOST:$PORT/"
exec .venv/bin/python -u ui_simulation.py --host "$HOST" --port "$PORT"
