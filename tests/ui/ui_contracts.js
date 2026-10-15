// ui_contracts.js — проверки заявленного поведения HMI: что видно, что
// запрещено и чего в интерфейсе больше нет. Запуск: node ui_contracts.js.
//
// Проверки читают и разметку, и код JS, и CSS: удалённые окна не должны
// возвращаться ни в одном из слоёв.
'use strict';

const fs = require('fs');
const path = require('path');
const { buildDom, makeChecker, REPO } = require('./harness');

const ROOT = '/tmp/archive';
const DATE = '2026-10-12';

function batchPayload({
    active = null,
    open = [],
    recent = [],
    suggestion = '12.10.2026-4',
    editable = true,
    canFinish = true,
} = {}) {
    return {
        available: true,
        active: !!active,
        batch: active,
        open,
        recent,
        suggestion,
        root_path: ROOT,
        date: DATE,
        default_folder: `${ROOT}/${DATE}/${suggestion}`,
        editable,
        can_finish: canFinish,
    };
}

function row(label, counts = 0, extra = {}) {
    return {
        batch_id: `batch_${label}`,
        label,
        operator: 'Иванов Иван Иванович',
        folder: `${ROOT}/${DATE}/${label}`,
        available: true,
        counts: { total: counts, good: counts, bad: 0, cleanup: 0 },
        ...extra,
    };
}

function lineStatus(state = 'IDLE', overrides = {}) {
    return {
        state,
        exit_requested: false,
        in_line: 0,
        step: 0,
        line_parts: [],
        total: 0,
        good: 0,
        rejected: 0,
        cleanup: 0,
        empty: 0,
        process: {phase: 'IDLE', label: 'Система готова к пуску', step: 0},
        controls: {start: true, stop: false, pause: false, resume: false, exit: true},
        live: {running: false, streaming: false, fps: 0},
        jog: {active: false, can_enter: false, busy: false},
        ...overrides,
    };
}

async function main() {
    const { window, routes, posts } = buildDom();
    const { check, result } = makeChecker(console.log);
    const doc = window.document;
    const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));
    const html = doc.documentElement.outerHTML;
    const read = file => fs.readFileSync(path.join(REPO, file), 'utf8');

    routes.set('GET /api/status', {
        splash_active: false,
        line_status: lineStatus(),
    });
    routes.set('POST /api/exit', {ok: true});
    routes.set('POST /api/start', {ok: true});
    routes.set('POST /api/batch/finish', {ok: true, batch: batchPayload()});
    routes.set('POST /api/line/jog', {ok: true});
    window.eval('state.splashActive = false; state.offline = false;');
    window.setupButtons();
    window.setupOperatorControls();
    window.setupBatchControls();
    await sleep(30);

    const operator = {available: true, assigned: true, operator: 'Иванов Иван Иванович'};
    window.updateOperatorStatus(operator);
    await sleep(10);

    // ─── 1. Чего в интерфейсе больше нет ──────────────────────
    check('в HTML нет окна выхода с закрытием партии',
        !doc.getElementById('batch-exit-modal') && !/batch-exit/.test(html));
    check('в коде карточки нет диалога выхода партии',
        !/batch-exit/.test(read('vision/ui/static/js/batch.js'))
        && !/askBatchExit|answerBatchExit/.test(read('vision/ui/static/js/controls.js')),
        'batch.js + controls.js');
    check('в CSS нет правил окна выхода',
        !/\.batch-exit/.test(read('vision/ui/static/css/batch.css')));
    check('нет окна и кнопки «АРХИВ»',
        !doc.getElementById('btn-archive') && !/archive-modal/.test(html)
        && !/archive\.js/.test(html) && !/archive\.css/.test(html));
    check('нет кнопки «НАЧАТЬ ПАРТИЮ»',
        !/НАЧАТЬ ПАРТИЮ/.test(html));
    check('нет блока замеров объектов',
        !/ЗАМЕРЫ ОБЪЕКТОВ|Замеры объектов/.test(html));
    check('нет статистики рабочего цикла сверху',
        !/СТАТИСТИКА РАБОЧЕГО ЦИКЛА/.test(html));
    check('нет кнопок распределителя DIST1/DIST2',
        !/DIST1|DIST2/.test(html));
    check('в карточке партии нет кнопки «ПРОДОЛЖИТЬ»',
        !/ПРОДОЛЖИТЬ/.test(doc.getElementById('batch-panel').textContent));
    check('в карточке партии нет шагов-кружочков',
        !doc.querySelector('#batch-panel .batch-step-index, #batch-panel .batch-step-dot'));

    // ─── 2. Плашка оператора ──────────────────────────────────
    const line = doc.getElementById('operator-line');
    check('в плашке есть иконка оператора',
        !!line.querySelector('.operator-line-icon svg'));
    check('в плашке есть ФИО и кнопка «СМЕНИТЬ»',
        doc.getElementById('operator-name').textContent === 'Иванов Иван Иванович'
        && doc.getElementById('operator-change').textContent.trim() === 'СМЕНИТЬ');
    check('в плашке нет слова «оператор» и времени входа',
        !/оператор/i.test(line.textContent)
        && !/\d{1,2}:\d{2}/.test(line.textContent),
        line.textContent.trim().replace(/\s+/g, ' '));

    // ─── 3. Колода: «ПАРТИЯ» по умолчанию, «ПОРОГИ» по ручному режиму ──
    const tabBatch = doc.getElementById('deck-tab-batch');
    const tabThresholds = doc.getElementById('deck-tab-thresholds');
    window.updateBatchStatus(batchPayload({open: [row('12.10.2026-3', 2)]}));
    await sleep(10);
    check('зона открыта на «ПАРТИИ» по умолчанию',
        doc.getElementById('service-deck').dataset.face === 'batch'
        && tabBatch.classList.contains('is-active')
        && tabBatch.getAttribute('aria-selected') === 'true'
        && doc.getElementById('thresholds-panel').classList.contains('is-hidden'));
    check('«ПОРОГИ» выключены без ручного режима',
        tabThresholds.disabled === true, `disabled=${tabThresholds.disabled}`);

    window.eval('state.jogActive = true; state.lineState = "IDLE";'
        + ' state.currentCamera = "INPUT_LEFT";');
    window.updateBatchStatus(batchPayload({open: [row('12.10.2026-3', 2)]}));
    await sleep(10);
    check('«ПОРОГИ» включаются в ручном режиме на остановленной линии',
        tabThresholds.disabled === false);

    tabThresholds.dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(10);
    check('нажатие переключает зону на «ПОРОГИ»',
        doc.getElementById('service-deck').dataset.face === 'thresholds'
        && tabThresholds.classList.contains('is-active')
        && tabThresholds.getAttribute('aria-selected') === 'true'
        && doc.getElementById('thresholds-panel').classList.contains('is-hidden') === false);

    // Опросы статуса не должны возвращать вкладку на «ПАРТИЮ», пока ручной
    // режим продолжается: в статусе он остаётся включённым.
    const jogOn = lineStatus('IDLE', {
        jog: {active: true, can_enter: false, busy: false},
    });
    for (let i = 0; i < 3; i += 1) {
        window.updateBatchStatus(batchPayload({
            open: [row('12.10.2026-3', 2 + i)],
        }));
        await sleep(5);
    }
    window.updateLineStatus(jogOn);
    await sleep(10);
    check('опросы статуса не сбрасывают вкладку «ПОРОГИ»',
        doc.getElementById('service-deck').dataset.face === 'thresholds'
        && tabThresholds.classList.contains('is-active'),
        doc.getElementById('service-deck').dataset.face);
    // Ручной режим закончился — пороги больше недоступны, и зона сама
    // возвращает карточку партии.
    window.updateLineStatus(lineStatus());
    await sleep(10);
    check('выход из ручного режима возвращает зону на «ПАРТИЮ»',
        doc.getElementById('service-deck').dataset.face === 'batch'
        && tabBatch.classList.contains('is-active'),
        doc.getElementById('service-deck').dataset.face);

    // ─── 4. Кнопки линии ──────────────────────────────────────
    const startButton = doc.getElementById('btn-start');
    const exitButton = doc.getElementById('btn-exit');
    const finishButton = doc.getElementById('batch-finish');

    window.updateOperatorStatus({available: true, assigned: false, operator: ''});
    window.updateBatchStatus(batchPayload());
    window.updateLineStatus(lineStatus());
    await sleep(10);
    check('без оператора ПУСК заблокирован и объясняет причину',
        startButton.disabled === true
        && startButton.title === 'Сначала войдите в программу',
        `disabled=${startButton.disabled} title=${startButton.title}`);
    check('без оператора вкладка «ПАРТИЯ» выключена',
        tabBatch.disabled === true);

    window.updateOperatorStatus(operator);
    window.updateBatchStatus(batchPayload());
    window.updateLineStatus(lineStatus());
    await sleep(10);
    check('с оператором ПУСК доступен, вкладка «ПАРТИЯ» включена',
        startButton.disabled === false && tabBatch.disabled === false,
        `disabled=${startButton.disabled}`);

    posts.length = 0;
    startButton.dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(40);
    const startPost = posts.find(item => item.url.includes('/api/start'));
    check('ПУСК отправляет номер и путь партии',
        !!startPost
        && JSON.parse(startPost.body).label === '12.10.2026-4'
        && JSON.parse(startPost.body).path === `${ROOT}/${DATE}/12.10.2026-4`,
        startPost ? startPost.body : 'запроса нет');

    // ─── 5. Выход партию не закрывает и ни о чём не спрашивает ──
    window.updateLineStatus(lineStatus());
    await sleep(10);
    check('кнопка ВЫХОД доступна на остановленной линии',
        exitButton.disabled === false && exitButton.textContent === 'ВЫХОД',
        `disabled=${exitButton.disabled}`);
    posts.length = 0;
    exitButton.dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(60);
    check('ВЫХОД сразу уходит на /api/exit',
        posts.some(item => item.url.includes('/api/exit')),
        posts.map(item => item.url).join(', ') || 'запросов нет');
    check('ВЫХОД не открывает ни одного диалога',
        !doc.querySelector('.modal:not(.is-hidden), #batch-exit-modal')
        && !/завершить партию\?/i.test(html));

    // ─── 6. Закрытие партии: только кнопкой и только вторым нажатием ──
    const active = row('12.10.2026-3', 2);
    active.batch_id = 'batch_12.10.2026-3';
    window.updateBatchStatus(batchPayload({active, open: [active]}));
    window.updateLineStatus(lineStatus());
    await sleep(10);
    check('кнопка закрытия партии доступна на остановленной линии',
        finishButton.disabled === false
        && finishButton.textContent === 'ЗАВЕРШИТЬ ПАРТИЮ',
        `disabled=${finishButton.disabled}`);
    posts.length = 0;
    finishButton.dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(30);
    check('первое нажатие только просит подтверждение',
        !posts.some(item => item.url.includes('/api/batch/finish'))
        && finishButton.textContent === 'ПОДТВЕРДИТЬ ЗАВЕРШЕНИЕ'
        && doc.getElementById('batch-active-status').textContent.includes('ПОДТВЕРДИТЬ'),
        doc.getElementById('batch-active-status').textContent);
    finishButton.dispatchEvent(new window.MouseEvent('click', {bubbles: true}));
    await sleep(40);
    check('второе нажатие закрывает партию запросом',
        posts.some(item => item.url.includes('/api/batch/finish')),
        posts.map(item => item.url).join(', ') || 'запросов нет');

    // ─── 7. Список незавершённых и блок открытой партии ────────
    const reopened = row('12.10.2026-3', 2);
    reopened.batch_id = 'batch_12.10.2026-3';
    window.updateBatchStatus(batchPayload({
        active: reopened,
        open: [row('12.10.2026-5', 7), reopened],
        recent: [row('12.10.2026-1', 2, {status: 'CLOSED'})],
    }));
    window.updateLineStatus(lineStatus());
    await sleep(10);
    const openRows = Array.from(doc.querySelectorAll('.batch-open-row'));
    check('список партий виден и при открытой партии',
        doc.getElementById('batch-open-face').classList.contains('is-hidden') === false
        && openRows.length === 2,
        `строк: ${openRows.length}`);
    check('закрытые партии в списке не показываются',
        !openRows.some(item => item.textContent.includes('12.10.2026-1')),
        openRows.map(item => item.textContent.trim().split('\n')[0]).join(' | '));
    check('список стоит над блоком открытой партии',
        doc.getElementById('batch-open-face').compareDocumentPosition(
            doc.getElementById('batch-active-face'),
        ) === window.Node.DOCUMENT_POSITION_FOLLOWING);
    check('поля партии доступны и при открытой партии',
        doc.getElementById('batch-label-input').disabled === false
        && doc.getElementById('batch-path-input').disabled === false);
    check('открытая партия помечена в списке словом «ОТКРЫТА»',
        openRows.some(item => item.querySelector('.batch-open-mark').textContent === 'ОТКРЫТА'));
    check('в футере видно партию и оператора',
        doc.getElementById('footer-batch').textContent
            === 'ПАРТИЯ 12.10.2026-3 · Иванов Иван Иванович',
        doc.getElementById('footer-batch').textContent);
    check('без открытой партии футер так и говорит',
        (() => {
            window.updateBatchStatus(batchPayload({open: [row('12.10.2026-5', 7)]}));
            return doc.getElementById('footer-batch').textContent === 'ПАРТИЯ НЕ ОТКРЫТА';
        })());

    // ─── 8. Смена лица правой панели: сдвиг листа, без 3D ──────
    const deckScript = read('vision/ui/static/js/panel-deck.js');
    const deckCss = read('vision/ui/static/css/panel-deck.css');
    // Комментарии не считаем: в них как раз сказано, что переворот убран,
    // и упоминание старого приёма не должно ронять проверку.
    const withoutComments = text => text
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '');
    check('в панели нет 3D-переворота: ни rotateY, ни perspective, ни backface',
        !/rotateY|perspective\(|backface-visibility/.test(withoutComments(deckCss))
        && !/rotateY|perspective\(|backface-visibility/.test(withoutComments(deckScript)));
    check('смена лица описана сдвигом: классы deck-out / deck-in / deck-settle',
        /\.stats-panel\.deck-out\b/.test(deckCss)
        && /\.stats-panel\.deck-in\b/.test(deckCss)
        && /\.stats-panel\.deck-settle\b/.test(deckCss));
    check('направление сдвига приходит переменной, а не жёстким знаком',
        /--deck-shift-dir/.test(deckCss) && /--deck-shift-dir/.test(deckScript));
    check('в уменьшенном движении смена лица мгновенная',
        /prefers-reduced-motion: reduce[\s\S]*deck-out[\s\S]*transition-duration: 1ms/
            .test(deckCss));

    const panel = doc.getElementById('stats-panel');
    const faces = () => panel.dataset.face;
    const shiftClasses = () => Array.from(panel.classList)
        .filter(item => item.startsWith('deck-') || item === 'panel-shifting');
    // Ждём, пока панель встанет на место: сдвигов в очереди может быть
    // несколько, поэтому фиксированная пауза тут не годится.
    const waitPanelIdle = async (limit = 40) => {
        for (let i = 0; i < limit; i += 1) {
            if (shiftClasses().length === 0) return true;
            await sleep(50);
        }
        return shiftClasses().length === 0;
    };

    window.updatePanelFace(lineStatus('IDLE'));
    await sleep(10);
    check('на остановленной линии лицо «готовность» и классы чисты',
        faces() === 'ready' && shiftClasses().length === 0,
        `${faces()} / ${shiftClasses().join(',') || '—'}`);

    window.updatePanelFace(lineStatus('RUNNING', {
        controls: {start: false, stop: true, pause: true, resume: false, exit: false},
        jog: {active: false, can_enter: false, busy: false},
    }));
    check('смена лица началась уходом панели, старое лицо ещё на месте',
        shiftClasses().includes('panel-shifting')
        && shiftClasses().includes('deck-out')
        && faces() === 'ready',
        `${faces()} / ${shiftClasses().join(',') || '—'}`);
    check('направление сдвига — вперёд по порядку лиц',
        panel.style.getPropertyValue('--deck-shift-dir') === '1',
        panel.style.getPropertyValue('--deck-shift-dir'));
    check('ручное управление в работе под шторкой',
        panel.classList.contains('jog-locked'));
    await sleep(150);
    check('лицо подменяется на уходе, новое въезжает сбоку',
        faces() === 'production'
        && shiftClasses().includes('deck-settle')
        && !shiftClasses().includes('deck-out'),
        `${faces()} / ${shiftClasses().join(',') || '—'}`);
    check('долго ждать нечего: панель встаёт на место',
        await waitPanelIdle());
    check('после смены лица никаких следов анимации',
        shiftClasses().length === 0
        && panel.style.getPropertyValue('--deck-shift-dir') === ''
        && panel.style.getPropertyValue('--panel-deck-duration') === '',
        `${shiftClasses().join(',') || '—'} / «${panel.style.cssText}»`);
    check('шторка ходит за время сдвига, а не дольше',
        /panel-shifting \.jog-shutter[\s\S]*--panel-deck-duration/.test(deckCss));

    // Авария и возврат из неё: лицо меняется в обе стороны, панель не
    // застревает между лицами.
    window.updatePanelFace(lineStatus('FAULT', {fault_reason: 'Обрыв связи с камерой'}));
    await waitPanelIdle();
    check('авария сменила лицо и объясняет причину',
        faces() === 'fault'
        && doc.getElementById('fault-reason').textContent === 'Обрыв связи с камерой'
        && shiftClasses().length === 0,
        `${faces()} / «${doc.getElementById('fault-reason').textContent}»`);
    check('на лице аварии обычные блоки скрыты разметкой',
        deckCss.includes('.stats-panel[data-face="fault"] .service-deck'));
    window.updatePanelFace(lineStatus('IDLE'));
    await waitPanelIdle();
    check('возврат из аварии: лицо «готовность», панель ровно',
        faces() === 'ready' && shiftClasses().length === 0,
        `${faces()} / ${shiftClasses().join(',') || '—'}`);
    check('шторка вернулась: ручное управление доступно',
        !panel.classList.contains('jog-locked'));

    // Быстрая смена состояний: пока идёт смена лица, приходят ещё две.
    window.updatePanelFace(lineStatus('RUNNING', {
        controls: {start: false, stop: true, pause: true, resume: false, exit: false},
    }));
    window.updatePanelFace(lineStatus('FAULT', {fault_reason: 'Стоп по кнопке'}));
    window.updatePanelFace(lineStatus('IDLE'));
    check('частые смены состояний не оставляют панель между лицами',
        await waitPanelIdle(),
        faces() === 'ready' && shiftClasses().length === 0,
        `${faces()} / ${shiftClasses().join(',') || '—'}`);
    check('лицо по состоянию линии определяется без переворота',
        window.panelFaceForState('RUNNING') === 'production'
        && window.panelFaceForState('IDLE') === 'ready'
        && window.panelFaceForState('FAULT') === 'fault'
        && window.panelFaceForState('') === 'ready');

    // ─── 9. CSS: компоновка и метки ───────────────────────────
    const css = read('vision/ui/static/css/batch.css');
    check('в CSS есть стиль строки открытой партии',
        /\.batch-open-row\.is-open/.test(css));
    check('панель партии прокручивается сама, список не растягивает зону',
        /\.batch-panel\s*\{[^}]*overflow/.test(css)
        && /\.batch-open-list\s*\{[^}]*max-height/.test(css));

    const summary = result();
    console.log(`\nпроверок: ${summary.total}, провалов: ${summary.fails}`);
    process.exit(summary.fails ? 1 : 0);
}

main().catch(error => {
    console.error('харнесс упал:', error);
    process.exit(2);
});
