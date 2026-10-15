#!/usr/bin/env bash
# Прогон всего UI-набора: контракты карточки партии, интерфейса и живые
# проверки против запущенного стенда (HMI_URL, по умолчанию localhost:8000).
#
# Перед первым запуском: npm install (нужен jsdom).
set -u

cd "$(dirname "$0")" || exit 2
status=0

for suite in batch_fields.js ui_contracts.js live_contracts.js; do
    echo "=== $suite ==="
    if ! node "$suite"; then
        status=1
    fi
    echo
done

if [ "$status" -eq 0 ]; then
    echo "ВСЕ UI-НАБОРЫ ПРОЙДЕНЫ"
else
    echo "ЕСТЬ ПРОВАЛЫ"
fi
exit "$status"
