/* belt_editor/js/model.js — доменная модель «пути корпуса».
 *
 * Единый формат конфигурации `belt.path.v1`, его же принимает сервер
 * (belt_model.py) — права и левая части не могут разъехаться: кодировки
 * нарушений (code) совпадают в JS и Python.
 *
 * Элементы:
 *   Позиция            — слот ленты, пронумерован по индексу; корпус
 *                        сдвигается на одну позицию за шаг.
 *   Место инспекции    — добавляется на позицию и делает её инспекционной;
 *                        содержит список камер (ролей).
 *   Основное место     — определяет наличие детали (part_presence).
 *                        Если место инспекции одно, оно становится
 *                        основным автоматически; иначе его выбирает
 *                        оператор (по умолчанию — самое раннее).
 *   Точка сброса       — позиция, на которой корпус покидает ленту.
 *                        Ровно одна. Для линейного пути позиции после неё
 *                        недостижимы — это ошибка конфигурации.
 */
'use strict';

(function (global) {

const SCHEMA = 'belt.path.v1';
const MIN_POSITIONS = 2;
const MAX_POSITIONS = 64;
const CAM_NAME_RE = /^[A-Z][A-Z0-9_]{1,23}$/;

function clone(value) { return JSON.parse(JSON.stringify(value)); }

/* ─── Нормализация ──────────────────────────────────────────────────── */

function normalizePosition(raw) {
    const src = (raw && typeof raw === 'object') ? raw : {};
    const pos = {
        label: String(src.label || '').trim().slice(0, 40),
        inspection: null,
        reset: src.reset === true,
    };
    const insp = src.inspection;
    if (insp && typeof insp === 'object') {
        const cameras = Array.isArray(insp.cameras)
            ? insp.cameras.map(function (name) {
                return String(name || '').trim().toUpperCase();
              })
            : [];
        pos.inspection = {
            cameras: cameras,
            primary: insp.primary === true,
        };
    }
    return pos;
}

function normalizeBelt(raw) {
    const src = (raw && typeof raw === 'object') ? raw : {};
    if (!Array.isArray(src.positions)) {
        throw new Error('belt.path: ожидается массив positions');
    }
    if (src.positions.length > MAX_POSITIONS) {
        throw new Error('belt.path: позиций не больше ' + MAX_POSITIONS);
    }
    const belt = {
        schema: SCHEMA,
        name: String(src.name || '').trim().slice(0, 64),
        path_type: src.path_type === 'loop' ? 'loop' : 'linear',
        positions: src.positions.map(normalizePosition),
    };
    applyInvariants(belt);
    return belt;
}

/* Инварианты, которые редактор восстанавливает после каждой правки:
 *   - ровно одна точка сброса максимум (лишние true сбрасываются);
 *   - при одном месте инспекции оно обязательно основное;
 *   - при нескольких — ровно одно основное, иначе первым становится
 *     самое раннее по позиции;
 *   - пустая подпись позиции получает автоимя «П{индекс}».
 */
function applyInvariants(belt) {
    const points = [];
    let resetKept = false;
    belt.positions.forEach(function (pos, i) {
        if (!pos.label) { pos.label = 'П' + i; }
        if (pos.reset) {
            if (resetKept) { pos.reset = false; }
            resetKept = true;
        }
        if (pos.inspection) { points.push(pos); }
    });
    if (points.length === 1) {
        points[0].inspection.primary = true;
    } else if (points.length > 1) {
        let primaryUsed = false;
        points.forEach(function (pos) {
            if (pos.inspection.primary && !primaryUsed) {
                primaryUsed = true;
            } else {
                pos.inspection.primary = false;
            }
        });
        if (!primaryUsed) { points[0].inspection.primary = true; }
    }
}

/* ─── Вычисление пути корпуса ───────────────────────────────────────── */

function findResetIndex(belt) {
    for (let i = 0; i < belt.positions.length; i += 1) {
        if (belt.positions[i].reset) { return i; }
    }
    return -1;
}

function primaryIndex(belt) {
    for (let i = 0; i < belt.positions.length; i += 1) {
        const pos = belt.positions[i];
        if (pos.inspection && pos.inspection.primary) { return i; }
    }
    return -1;
}

/* Шаг пути: {index, label, cameras|null, primary, reset}.
 * null — путь неопределим (нет позиции или нет точки сброса).
 * Вход: линейный путь — позиция 0; циклический — следующая после сброса
 * (корпус садится на ретур сразу после разгрузки).
 */
function computeCasePath(belt) {
    const n = belt.positions.length;
    const resetIdx = findResetIndex(belt);
    if (n === 0 || resetIdx < 0) { return null; }
    const loop = belt.path_type === 'loop';
    const steps = [];
    let i = loop ? (resetIdx + 1) % n : 0;
    for (let visited = 0; visited < n; visited += 1) {
        const pos = belt.positions[i];
        steps.push({
            index: i,
            label: pos.label,
            cameras: pos.inspection ? pos.inspection.cameras.slice() : null,
            primary: !!(pos.inspection && pos.inspection.primary),
            reset: pos.reset,
        });
        if (pos.reset) { break; }
        i = (i + 1) % n;
    }
    return steps;
}

/* ─── Валидация ─────────────────────────────────────────────────────── */
/* Issue: {level: 'error'|'warn', code, text, position|null} — коды
 * совпадают с belt_model.py. */

function validateBelt(belt) {
    const issues = [];
    const n = belt.positions.length;
    const push = function (level, code, text, position) {
        issues.push({
            level: level, code: code, text: text,
            position: (typeof position === 'number' ? position : null),
        });
    };

    if (n === 0) {
        push('error', 'EMPTY_BELT', 'Лента пуста — добавьте позиции.', null);
        return issues;
    }
    if (n < MIN_POSITIONS) {
        push('error', 'MIN_POSITIONS',
            'Минимум ' + MIN_POSITIONS + ' позиции на ленте.', 0);
    }
    if (n > MAX_POSITIONS) {
        push('error', 'MAX_POSITIONS',
            'Позиций не больше ' + MAX_POSITIONS + '.', null);
    }

    const inspectionIdx = [];
    belt.positions.forEach(function (pos, i) {
        if (pos.inspection) { inspectionIdx.push(i); }
    });
    if (inspectionIdx.length === 0) {
        push('error', 'NO_INSPECTIONS',
            'Нет мест инспекции — добавьте место инспекции на позицию.', null);
    }

    const resetIdx = findResetIndex(belt);
    if (resetIdx < 0) {
        push('error', 'RESET_MISSING',
            'Точка сброса не задана — укажите, где корпус покидает ленту.', null);
    } else if (belt.path_type === 'linear' && resetIdx < n - 1) {
        push('error', 'UNREACHABLE_AFTER_RESET',
            'Линейный путь: позиции ' + (resetIdx + 1) + '…' + (n - 1) +
            ' стоят после сброса и никогда не увидят корпус. ' +
            'Удалите их или включите циклический путь.',
            resetIdx + 1);
    } else if (belt.path_type === 'linear' && resetIdx === 0 &&
               inspectionIdx.length > 0) {
        push('warn', 'LINEAR_RESET_AT_ENTRY',
            'Точка сброса совпадает со входом: корпус сойдёт с ленты ' +
            'до любой инспекции.', 0);
    }

    const seenCameras = Object.create(null);
    belt.positions.forEach(function (pos, i) {
        const insp = pos.inspection;
        if (!insp) { return; }
        if (insp.cameras.length === 0) {
            push('warn', 'CAMS_MISSING',
                'Место инспекции «' + pos.label + '» без камер.', i);
        }
        insp.cameras.forEach(function (name) {
            if (!CAM_NAME_RE.test(name)) {
                push('error', 'CAM_BAD_NAME',
                    'Камера «' + name + '»: роль — 2–24 символа ' +
                    'A-Z, 0-9, _ с буквы.', i);
            }
            if (Object.prototype.hasOwnProperty.call(seenCameras, name)) {
                push('error', 'CAM_DUP',
                    'Камера ' + name + ' назначена дважды (' +
                    seenCameras[name] + ' и ' + i +
                    ') — одна камера одна роль на линии.', i);
            } else {
                seenCameras[name] = 'позиция ' + i;
            }
        });
    });
    return issues;
}

/* ─── Заготовки (пресеты) ───────────────────────────────────────────── */

function position(label, cameras, primary, reset) {
    return {
        label: label,
        inspection: cameras ? { cameras: cameras, primary: !!primary } : null,
        reset: !!reset,
    };
}

const PRESETS = {
    current7: {
        caption: 'Текущая линия · 7 камер (9 позиций)',
        build: function () {
            const positions = [
                position('ВХОД · НАЛИЧИЕ', ['INPUT_LEFT', 'INPUT_RIGHT'], true, false),
                position('ТРАНСПОРТ'),
                position('ТРАНСПОРТ'),
                position('ТРАНСПОРТ'),
                position('СПАЙДЕР / TOP', ['SPIDER_LEFT', 'SPIDER_RIGHT',
                    'SPIDER_IN', 'SPIDER_OUT', 'TOP'], false, false),
                position('ТРАНСПОРТ'),
                position('ТРАНСПОРТ'),
                position('РАСПРЕДЕЛИТЕЛЬ'),
                position('ВЫХОД · СБРОС', null, false, true),
            ];
            return {
                name: '7-камерная линия (текущая)',
                path_type: 'linear',
                positions: positions,
            };
        },
    },
    carousel7: {
        caption: '7-камерный ретур (циклическая лента)',
        build: function () {
            const positions = [];
            for (let i = 0; i < 7; i += 1) {
                positions.push(position('КАМЕРА ' + (i + 1)));
            }
            positions[1].inspection = {
                cameras: ['RING_TOP_1', 'RING_SIDE_1'], primary: true,
            };
            positions[4].inspection = {
                cameras: ['RING_TOP_2'], primary: false,
            };
            positions[6].reset = true;
            return {
                name: '7-камерный ретур',
                path_type: 'loop',
                positions: positions,
            };
        },
    },
    blank: {
        caption: 'Пустая лента (4 позиции)',
        build: function () {
            return {
                name: 'Новая лента',
                path_type: 'linear',
                positions: [position('ВХОД'), position('П1'),
                    position('П2'), position('СБРОС')],
            };
        },
    },
};

/* ─── Модель с подпиской ────────────────────────────────────────────── */

class BeltModel {
    constructor(belt) {
        this._belt = normalizeBelt(belt || PRESETS.current7.build());
        this._listeners = [];
        this.version = 0;
    }

    get belt() { return this._belt; }

    subscribe(fn) { this._listeners.push(fn); }

    commit() {
        applyInvariants(this._belt);
        this.version += 1;
        this._listeners.forEach(function (fn) { fn(); });
    }

    /* Геттеры-помощники. */
    positionCount() { return this._belt.positions.length; }
    position(i) { return this._belt.positions[i] || null; }
    resetIndex() { return findResetIndex(this._belt); }
    primaryIndex() { return primaryIndex(this._belt); }
    inspectionCount() {
        return this._belt.positions.filter(function (p) {
            return !!p.inspection;
        }).length;
    }
    validate() { return validateBelt(this._belt); }
    casePath() { return computeCasePath(this._belt); }
    exportBelt() { return clone(this._belt); }

    /* Мутации — каждая держит инварианты через commit(). */
    setName(name) { this._belt.name = String(name || '').trim().slice(0, 64); this.commit(); }
    setPathType(type) {
        this._belt.path_type = (type === 'loop' ? 'loop' : 'linear');
        this.commit();
    }
    setPositionLabel(i, label) {
        const pos = this._belt.positions[i];
        if (!pos) { return; }
        pos.label = String(label || '').trim().slice(0, 40);
        this.commit();
    }
    addPosition() { return this.insertPosition(this._belt.positions.length - 1); }
    insertPosition(afterIndex) {
        if (this._belt.positions.length >= MAX_POSITIONS) { return -1; }
        const at = Math.min(Math.max(afterIndex + 1, 0), this._belt.positions.length);
        this._belt.positions.splice(at, 0, { label: '', inspection: null, reset: false });
        this.commit();
        return at;
    }
    removePosition(i) {
        if (i < 0 || i >= this._belt.positions.length) { return; }
        this._belt.positions.splice(i, 1);
        this.commit();
    }
    movePosition(i, dir) {
        const j = i + dir;
        if (i < 0 || j < 0 || i >= this._belt.positions.length ||
            j >= this._belt.positions.length) { return; }
        const arr = this._belt.positions;
        const tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
        this.commit();
    }

    /* Место инспекции. */
    addInspection(i) {
        const pos = this._belt.positions[i];
        if (!pos || pos.inspection) { return; }
        pos.inspection = { cameras: [], primary: false };
        this.commit();
    }
    removeInspection(i) {
        const pos = this._belt.positions[i];
        if (!pos) { return; }
        pos.inspection = null;
        this.commit();
    }
    setPrimary(i) {
        this._belt.positions.forEach(function (pos, k) {
            if (pos.inspection) {
                pos.inspection.primary = (k === i);
            }
        });
        this.commit();
    }

    /* Камеры места инспекции. */
    addCamera(i) {
        const pos = this._belt.positions[i];
        if (!pos || !pos.inspection) { return null; }
        const used = Object.create(null);
        this._belt.positions.forEach(function (other) {
            if (other.inspection) {
                other.inspection.cameras.forEach(function (c) { used[c] = true; });
            }
        });
        let k = 1;
        while (used['CAM_' + k]) { k += 1; }
        const name = 'CAM_' + k;
        pos.inspection.cameras.push(name);
        this.commit();
        return name;
    }
    renameCamera(i, j, name) {
        const pos = this._belt.positions[i];
        if (!pos || !pos.inspection || !pos.inspection.cameras[j]) { return; }
        pos.inspection.cameras[j] = String(name || '')
            .trim().toUpperCase().slice(0, 24);
        this.commit();
    }
    removeCamera(i, j) {
        const pos = this._belt.positions[i];
        if (!pos || !pos.inspection) { return; }
        pos.inspection.cameras.splice(j, 1);
        this.commit();
    }

    /* Точка сброса — ровно одна: установка переносит её. */
    setReset(i, value) {
        let note = null;
        this._belt.positions.forEach(function (pos, k) {
            if (pos.reset && k !== i) {
                note = 'Точка сброса перенесена с позиции ' + k + '.';
            }
            pos.reset = (k === i) ? !!value : false;
        });
        this.commit();
        return note;
    }

    loadBelt(raw) { this._belt = normalizeBelt(raw); this.commit(); }
    applyPreset(key) {
        const preset = PRESETS[key];
        if (!preset) { return false; }
        this._belt = normalizeBelt(preset.build());
        this.commit();
        return true;
    }
}

BeltModel.SCHEMA = SCHEMA;
BeltModel.MAX_POSITIONS = MAX_POSITIONS;
BeltModel.PRESETS = PRESETS;
BeltModel.normalize = normalizeBelt;
BeltModel.validate = validateBelt;
BeltModel.casePath = computeCasePath;

global.BeltModel = BeltModel;

})(window);
