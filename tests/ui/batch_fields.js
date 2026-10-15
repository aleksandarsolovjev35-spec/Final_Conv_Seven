// batch_fields.js — проверки карточки «ПАРТИЯ»: что описывают поля и что
// сделает ПУСК. Запуск: node batch_fields.js (из папки tests/ui).
'use strict';

const { buildDom, makeChecker } = require('./harness');

const ROOT = '/tmp/archive';
const DATE = '2026-10-12';

function payload({
    active = null,
    open = [],
    suggestion = '12.10.2026-4',
    editable = true,
    canFinish = true,
} = {}) {
    return {
        available: true,
        active: !!active,
        batch: active,
        open,
        suggestion,
        root_path: ROOT,
        date: DATE,
        default_folder: `${ROOT}/${DATE}/${suggestion}`,
        editable,
        can_finish: canFinish,
        operators: [],
    };
}

function batch(label, batchId, folder, counts = 0, extra = {}) {
    return {
        batch_id: batchId || `batch_${label}`,
        label,
        operator: 'Иванов Иван Иванович',
        folder: folder || `${ROOT}/${DATE}/${label}`,
        available: true,
        counts: { total: counts, good: counts, bad: 0, cleanup: 0 },
        ...extra,
    };
}

function row(label, batchId, counts = 0, extra = {}) {
    return {
        batch_id: batchId || `batch_${label}`,
        label,
        operator: 'Иванов Иван Иванович',
        folder: `${ROOT}/${DATE}/${label}`,
        available: true,
        counts: { total: counts, good: counts, bad: 0, cleanup: 0 },
        ...extra,
    };
}

async function main() {
    const { window } = buildDom();
    const { check, result } = makeChecker(console.log);
    const doc = window.document;
    const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));

    window.eval('state.splashActive = false; state.offline = false;'
        + ' state.lineState = "IDLE";');
    window.updateOperatorStatus({
        available: true,
        assigned: true,
        operator: 'Иванов Иван Иванович',
        users: ['Иванов Иван Иванович'],
    });
    window.setupOperatorControls();
    window.setupBatchControls();
    await sleep(20);

    const labelInput = doc.getElementById('batch-label-input');
    const pathInput = doc.getElementById('batch-path-input');
    const status = doc.getElementById('batch-status');
    const activeHint = doc.getElementById('batch-active-hint');
    const startButton = doc.getElementById('btn-start');
    const fields = () => `${labelInput.value} | ${pathInput.value}`;
    const setInput = (el, value) => {
        el.value = value;
        el.dispatchEvent(new window.Event('input', {bubbles: true}));
    };
    const rows = () => Array.from(doc.querySelectorAll('.batch-open-row'));
    // Кнопки HMI пересобираются из статуса линии: в проверке карточки
    // достаточно «линия стоит, пуск разрешён, партии нет».
    const applyControls = (controls = {start: true}) => {
        window.eval(`applyButtonsForState('IDLE', false, ${
            JSON.stringify(controls)})`);
    };

    // ─── 1. Партии нет: поля идут по шаблону ───────────────────
    window.updateBatchStatus(payload({open: [row('12.10.2026-3', null, 2)]}));
    await sleep(10);
    check('шаблон в полях: номер и путь по нему',
        labelInput.value === '12.10.2026-4'
        && pathInput.value === `${ROOT}/${DATE}/12.10.2026-4`,
        fields());
    check('шаблон показан и подсказкой-плейсхолдером',
        labelInput.placeholder === '12.10.2026-4', labelInput.placeholder);
    check('ПУСК опишет партию по шаблону',
        status.textContent.includes('ПУСК начнёт партию 12.10.2026-4'),
        status.textContent);
    check('запрос ПУСКА идёт без batch_id, по номеру и пути',
        JSON.stringify(window.batchStartPayload())
            === JSON.stringify({
                label: '12.10.2026-4',
                path: `${ROOT}/${DATE}/12.10.2026-4`,
            }),
        JSON.stringify(window.batchStartPayload()));
    applyControls();
    check('ПУСК не заблокирован: номер не спрашивается',
        startButton.disabled === false, startButton.title);

    // ─── 2. Партия открыта, ничего не выбрано: снова шаблон ────
    window.updateBatchStatus(payload({
        active: batch('12.10.2026-3', null, `${ROOT}/${DATE}/12.10.2026-3`, 2),
        open: [row('12.10.2026-3', null, 2)],
        suggestion: '12.10.2026-4',
    }));
    await sleep(10);
    check('при открытой партии поля всё равно по шаблону',
        labelInput.value === '12.10.2026-4'
        && pathInput.value === `${ROOT}/${DATE}/12.10.2026-4`,
        fields());
    check('в шаблоне следующий номер за день, а не номер открытой партии',
        labelInput.value === '12.10.2026-4', labelInput.value);
    check('подсказка объясняет: ПУСК начнёт новую, прежняя останется открытой',
        status.textContent.includes('Учёт идёт в партию 12.10.2026-3')
        && status.textContent.includes('ПУСК начнёт партию 12.10.2026-4')
        && status.textContent.includes('останется открытой'),
        status.textContent);
    check('подсказка говорит, как продолжить открытую партию',
        status.textContent.includes('Продолжить её — выбрать в списке'),
        status.textContent);
    check('подсказка под открытой партией ведёт в список',
        activeHint.textContent.includes('выбрать её в списке'),
        activeHint.textContent);
    check('ПУСК уйдёт как новая партия, без batch_id',
        window.batchSwitchIntent() !== null
        && window.batchSwitchIntent().kind === 'new'
        && window.batchStartPayload().batch_id === undefined,
        JSON.stringify(window.batchSwitchIntent())
            + ' | ' + JSON.stringify(window.batchStartPayload()));
    check('строка открытой партии помечена «ОТКРЫТА»',
        rows()[0].querySelector('.batch-open-mark').textContent === 'ОТКРЫТА',
        rows()[0].querySelector('.batch-open-mark').textContent);

    // ─── 3. Выбрана открытая партия: ПУСК продолжит её ─────────
    rows()[0].dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(10);
    check('выбор открытой партии вернул её номер и путь в поля',
        labelInput.value === '12.10.2026-3'
        && pathInput.value === `${ROOT}/${DATE}/12.10.2026-3`,
        fields());
    check('выбранная партия уходит в ПУСК своим batch_id',
        window.batchStartPayload().batch_id === 'batch_12.10.2026-3',
        JSON.stringify(window.batchStartPayload()));
    check('подсказка: выбранная партия уже открыта — ПУСК продолжит её',
        status.textContent.includes('уже открыта')
        && status.textContent.includes('продолжит учёт в ней'),
        status.textContent);
    check('строка выбрана, метка «ОТКРЫТА» на месте',
        rows()[0].classList.contains('is-selected')
        && rows()[0].querySelector('.batch-open-mark').textContent === 'ОТКРЫТА',
        rows()[0].className);

    // ─── 4. Повторное нажатие снимает выбор — назад к шаблону ──
    rows()[0].dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(10);
    check('повторное нажатие снимает выбор и возвращает шаблон',
        !rows()[0].classList.contains('is-selected')
        && labelInput.value === '12.10.2026-4'
        && pathInput.value === `${ROOT}/${DATE}/12.10.2026-4`,
        fields());
    check('после снятия выбора ПУСК снова про новую партию',
        window.batchStartPayload().batch_id === undefined,
        JSON.stringify(window.batchStartPayload()));

    // ─── 5. Выбор другой незавершённой партии ─────────────────
    window.updateBatchStatus(payload({
        active: batch('12.10.2026-3', null, `${ROOT}/${DATE}/12.10.2026-3`, 2),
        open: [row('12.10.2026-3', null, 2), row('12.10.2026-5', null, 7)],
    }));
    await sleep(10);
    rows()[1].dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(10);
    check('выбор другой партии подставляет её номер и путь',
        labelInput.value === '12.10.2026-5'
        && pathInput.value === `${ROOT}/${DATE}/12.10.2026-5`,
        fields());
    check('подсказка предупреждает о переключении',
        status.textContent.includes('ПУСК переключит учёт на неё')
        && status.textContent.includes('останется открытой'),
        status.textContent);
    check('в запрос ПУСКА уходит выбранная партия',
        window.batchStartPayload().batch_id === 'batch_12.10.2026-5',
        JSON.stringify(window.batchStartPayload()));

    // ─── 6. Свой номер: путь считается по шаблону ─────────────
    setInput(labelInput, 'заказ-7');
    await sleep(10);
    check('свой номер: путь пересчитан под него',
        pathInput.value === `${ROOT}/${DATE}/заказ-7`, fields());
    check('свой номер: выбор снят, запрос без batch_id',
        window.batchStartPayload().batch_id === undefined
        && window.batchStartPayload().label === 'заказ-7',
        JSON.stringify(window.batchStartPayload()));
    check('свой номер: подсказка называет открытую партию и цель ПУСКА',
        status.textContent.includes('Учёт идёт в партию 12.10.2026-3')
        && status.textContent.includes('партию заказ-7')
        && status.textContent.includes('останется открытой'),
        status.textContent);

    // ─── 7. Свой путь: смена номера ведёт путь по шаблону, а опрос
    //        статуса правленый путь не перетирает ──────────────────
    setInput(labelInput, 'заказ-8');
    await sleep(10);
    check('сменив номер, оператор получает путь по шаблону нового номера',
        pathInput.value === `${ROOT}/${DATE}/заказ-8`, pathInput.value);
    setInput(pathInput, '/tmp/orders/заказ-8');
    await sleep(10);
    window.updateBatchStatus(payload({
        active: batch('12.10.2026-3', null, `${ROOT}/${DATE}/12.10.2026-3`, 2),
        open: [row('12.10.2026-3', null, 2)],
        suggestion: '12.10.2026-9',
    }));
    await sleep(10);
    check('опрос статуса не перетирает введённый оператором путь',
        pathInput.value === '/tmp/orders/заказ-8' && labelInput.value === 'заказ-8',
        fields());

    // ─── 8. ПУСК прошёл: поля снова ведёт карточка ────────────
    window.updateBatchStatus(payload({
        active: batch('заказ-8', null, '/tmp/orders/заказ-7', 0),
        open: [
            row('12.10.2026-3', null, 2),
            row('заказ-8', null, 0, {folder: '/tmp/orders/заказ-7'}),
        ],
        suggestion: '12.10.2026-6',
    }));
    await sleep(10);
    check('после ПУСКА поля вернулись к шаблону (следующий номер)',
        labelInput.value === '12.10.2026-6'
        && pathInput.value === `${ROOT}/${DATE}/12.10.2026-6`,
        fields());
    check('открытая партия видна блоком и помечена в списке',
        doc.getElementById('batch-active-face').classList.contains('is-hidden') === false
        && rows().some(item => item.querySelector('.batch-open-mark').textContent === 'ОТКРЫТА'),
        doc.getElementById('batch-active-face').className);

    // ─── 9. Шаблона нет: поля показывают открытую партию ──────
    window.updateBatchStatus(payload({
        active: batch('12.10.2026-3', null, `${ROOT}/${DATE}/12.10.2026-3`, 2),
        open: [row('12.10.2026-3', null, 2)],
        suggestion: '',
    }));
    await sleep(10);
    check('без шаблона поля показывают открытую партию, а не пустоту',
        labelInput.value === '12.10.2026-3'
        && pathInput.value === `${ROOT}/${DATE}/12.10.2026-3`,
        fields());

    // ─── 10. Партия исчезла из списка: выбор не держится ──────
    window.updateBatchStatus(payload({
        open: [row('12.10.2026-3', null, 2), row('12.10.2026-5', null, 7)],
    }));
    await sleep(10);
    rows()[1].dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(10);
    window.updateBatchStatus(payload({open: [row('12.10.2026-3', null, 2)]}));
    await sleep(10);
    check('закрытая партия больше не держит выбор: поля снова шаблон',
        labelInput.value === '12.10.2026-4'
        && !doc.querySelector('.batch-open-row.is-selected'),
        fields());

    // ─── 11. Подпись фазы параллельного анализа ───────────────
    check('фаза параллельного анализа подписана в HMI',
        typeof window.isInspectionDisplayPhase === 'function'
        && window.isInspectionDisplayPhase('PARALLEL_ANALYSIS') === true,
        String(window.isInspectionDisplayPhase
            && window.isInspectionDisplayPhase('PARALLEL_ANALYSIS')));

    const summary = result();
    console.log(`\nпроверок: ${summary.total}, провалов: ${summary.fails}`);
    process.exit(summary.fails ? 1 : 0);
}

main().catch(error => {
    console.error('харнесс упал:', error);
    process.exit(2);
});
