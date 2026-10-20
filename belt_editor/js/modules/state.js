/**
 * @file state.js
 * @description Центральное состояние редактора ленты, константы и базовые структуры данных.
 */

'use strict';

const MAX_POSITIONS = 64;
const CAM_NAME_MAX = 24;
const THR_DEFAULT = 0.5;
const CANVAS_W = 5000;
const CANVAS_H = 3000;

let ruleQuery = '';
let modelQuery = '';
let nextModelId = 12;
let nextRuleId = 4;
let uidSeq = 0;

let dragKind = null;
let dragFrom = -1;
let dragCamId = null;
let dragAsset = null;
let openThrCam = null;
let movingG = null;

/** Список доступных моделей машинного зрения */
const MODELS = [
    'uneven-heights', 'window-sinks', 'omission-long', 'contacts-long',
    'bracket-90', 'flange-low', 'gear-set', 'hinge-side',
    'plate-thin', 'roller-mid', 'shaft-long', 'yoke-drop'
].map((name, i) => ({ id: 'm' + i, name }));

/** Список детекционных правил и инспекций */
const RULES = [
    { id: 'r0', name: 'геометрия', color: '#d9a441', thr: ['площадь', 'перекос', 'высота'], models: [] },
    { id: 'r1', name: 'наличие', color: '#58b79a', thr: ['контраст'], models: [] },
    { id: 'r2', name: 'пропуск', color: '#cf7aa6', thr: ['окно'], models: [] },
    { id: 'r3', name: 'контакты', color: '#a58ad9', thr: ['нажим', 'смещение'], models: [] }
];

/** Цветовая палитра правил */
const RULE_COLORS = [
    '#4fa3d1', '#d9a441', '#58b79a', '#cf7aa6', '#a58ad9', '#e06c75', '#98c379',
    '#d19a66', '#61afef', '#c678dd', '#56b6c2', '#e5c07b', '#e27d60', '#85dcba', '#e8a87c'
];

/** Список обнаруженных камер захвата */
const inventory = Array.from({ length: 8 }, (_, i) => ({
    id: 'cam' + i,
    name: 'CAM_' + (i + 1),
    dev: 'video' + i,
    rules: []
}));

/** Состояние позиций и свободных нод на холсте */
const belt = {
    positions: [],
    places: Object.create(null)
};

/** Быстрый доступ к DOM-элементу по ID */
const $ = id => document.getElementById(id);

/** Поиск камеры в инвентаре по ID */
const invCam = id => inventory.find(c => c.id === id) || null;

/** Получение имени камеры по ID */
const camName = id => (invCam(id) || {}).name || id;

/** Получение акцентного цвета правила по ID */
const ruleColor = id => RULES.find(x => x.id === id)?.color || 'var(--text-dim)';

/**
 * Всплывающее уведомление пользователю
 * @param {string} text Текст сообщения
 * @param {string} [kind] Тип ('err' для ошибок)
 */
function toast(text, kind) {
    const box = $('toasts');
    if (!box) return;
    const t = el('div', 'toast' + (kind ? ' toast-' + kind : ''), text);
    box.appendChild(t);
    setTimeout(() => {
        t.classList.add('toast-out');
        setTimeout(() => t.remove(), 300);
    }, 2800);
}

/**
 * Проверка и соблюдение инвариантов цепи позиций ленты
 */
function applyInvariants() {
    let resetKept = false;
    belt.positions.forEach((pos, i) => {
        if (pos.uid == null) pos.uid = ++uidSeq;
        if (pos.reset && pos.nextUid) pos.nextUid = null;
        if (pos.reset) {
            if (resetKept) pos.reset = false;
            resetKept = true;
        }
        if (i === 0) {
            if (!pos.inspection) pos.inspection = { cameras: [], primary: true };
            else pos.inspection.primary = true;
        } else if (pos.inspection) {
            pos.inspection.primary = false;
        }
        if (pos.reset && pos.inspection) {
            pos.reset = false;
        }
    });
}
