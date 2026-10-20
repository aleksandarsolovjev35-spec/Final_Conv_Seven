/**
 * @file dock.js
 * @description Боковая панель (Photoshop dock), вкладки правил и моделей, фильтрация/поиск, выбор локальных папок.
 */

'use strict';

/** Плавный скролл списков каталога колесом мыши */
function wireScrollSnap() {
    [$('asset-models'), $('asset-rules')].forEach(list => {
        if (!list) return;
        list.addEventListener('wheel', e => {
            if (list.scrollHeight <= list.clientHeight) return;
            e.preventDefault();
            const h = (list.firstElementChild?.offsetHeight || 0) > 0 ? list.firstElementChild.offsetHeight + 6 : 40;
            const d = (e.deltaY > 0 ? 1 : -1) * h;
            if (list.scrollTo) {
                list.scrollTo({ top: list.scrollTop + d, behavior: 'smooth' });
            } else {
                list.scrollTop += d;
            }
        }, { passive: false });
    });
}

/** Закрытие всплывающего поповера порогов по клику вовне или Escape */
function wireThrClose() {
    const close = () => {
        if (openThrCam !== null) {
            openThrCam = null;
            render();
        }
    };
    document.addEventListener('click', close);
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') close();
    });
}

/** Фильтрация элементов каталога правил и моделей через строку поиска */
function wireSearch() {
    [
        ['rule-search', v => { ruleQuery = v; }],
        ['model-search', v => { modelQuery = v; }]
    ].forEach(([id, fn]) => {
        $(id)?.addEventListener('input', e => {
            fn(e.target.value.trim().toLowerCase());
            render();
        });
    });
}

/**
 * Правая боковая стенка в стиле Photoshop (вкладки правил и моделей, сворачивание)
 */
function wireSideDock() {
    const dock = $('side-dock');
    if (!dock) return;

    const KEY_COL = 'belt_side_dock_collapsed';
    const KEY_TAB = 'belt_side_dock_tab';
    let currentTab = 'rules';

    /** Переключение активной вкладки */
    function setTab(tab, save) {
        currentTab = tab === 'models' ? 'models' : 'rules';
        dock.classList.toggle('show-rules', currentTab === 'rules');
        dock.classList.toggle('show-models', currentTab === 'models');

        ['rules', 'models'].forEach(t => {
            const active = currentTab === t;
            const btn = $(`tab-btn-${t}`);
            btn?.classList.toggle('active', active);
            btn?.setAttribute('aria-selected', active ? 'true' : 'false');
            dock.querySelector(`.side-dock-tab[data-panel="${t}"]`)?.classList.toggle('active', active);
        });

        if (save) {
            try { localStorage.setItem(KEY_TAB, currentTab); } catch (e) {}
        }
        renderWires();
    }

    /** Сворачивание / разворачивание боковой панели */
    function setCollapsed(col, save) {
        dock.classList.toggle('collapsed', col);
        if (save) {
            try { localStorage.setItem(KEY_COL, col ? '1' : '0'); } catch (e) {}
        }
        window.dispatchEvent(new Event('resize'));
        renderWires();
        (window.requestAnimationFrame || (f => f()))(() => {
            renderWires();
            setTimeout(renderWires, 40);
        });
    }

    try {
        if (localStorage.getItem(KEY_COL) === '1') setCollapsed(true, false);
    } catch (e) {}

    try {
        setTab(localStorage.getItem(KEY_TAB) === 'models' ? 'models' : 'rules', false);
    } catch (e) {
        setTab('rules', false);
    }

    $('tab-btn-rules')?.addEventListener('click', e => {
        e.stopPropagation();
        setTab('rules', true);
        $('rule-search')?.focus();
    });

    $('tab-btn-models')?.addEventListener('click', e => {
        e.stopPropagation();
        setTab('models', true);
        $('model-search')?.focus();
    });

    ['transitionend', 'transitioncancel'].forEach(evt =>
        dock.addEventListener(evt, () => {
            renderWires();
            window.dispatchEvent(new Event('resize'));
        })
    );

    $('btn-side-collapse')?.addEventListener('click', e => {
        e.stopPropagation();
        setCollapsed(true, true);
    });

    $('btn-side-expand')?.addEventListener('click', e => {
        e.stopPropagation();
        setCollapsed(false, true);
    });

    $('side-dock-collapsed-bar')?.addEventListener('click', ev => {
        const panel = ev.target?.closest?.('.side-dock-tab')?.dataset.panel;
        if (panel === 'models' || panel === 'rules') {
            setTab(panel, true);
            setCollapsed(false, true);
            setTimeout(() => $(`${panel === 'models' ? 'model' : 'rule'}-search`)?.focus(), 100);
        } else {
            setCollapsed(false, true);
        }
    });

    window.SideDock = { setTab, setCollapsed, currentTab: () => currentTab };
}

/**
 * Регистрация модели нейросети из файла весов
 * @param {string} fileName
 * @param {string} path
 */
function addModelFromFile(fileName, path) {
    const name = fileName.replace(/\.[^/.]+$/, '').trim();
    if (!name) return null;
    const exist = MODELS.find(m => m.name.toLowerCase() === name.toLowerCase());
    if (exist) return exist;
    const mod = { id: 'm' + (nextModelId++), name, path: path || name };
    MODELS.push(mod);
    render();
    return mod;
}

/**
 * Регистрация правила дефектоскопии из файла скрипта/конфига
 * @param {string} fileName
 * @param {string} path
 */
function addRuleFromFile(fileName, path) {
    const name = fileName.replace(/\.[^/.]+$/, '').replace(/^rule_/, '').replace(/_/g, ' ').trim();
    if (!name) return null;
    const exist = RULES.find(r => r.name.toLowerCase() === name.toLowerCase());
    if (exist) return exist;
    const rule = {
        id: 'r' + (nextRuleId++),
        name,
        color: RULE_COLORS[RULES.length % RULE_COLORS.length],
        thr: ['порог'],
        models: [],
        path: path || name
    };
    RULES.push(rule);
    render();
    return rule;
}

/**
 * Настройка полей выбора локальных директорий правил и моделей
 */
function wireFolderPickers() {
    const setup = (pathId, btnId, fileId, key, title, defFolder, unit, filter, add) => {
        const pathInp = $(pathId);
        const fileInp = $(fileId);

        try {
            const s = localStorage.getItem(key);
            if (s && pathInp) pathInp.value = s;
        } catch (e) {}

        $(btnId)?.addEventListener('click', e => {
            e.stopPropagation();
            fileInp?.click();
        });

        fileInp?.addEventListener('change', function () {
            if (!this.files?.length) return;
            let folder = '';
            let count = 0;

            Array.from(this.files).forEach(f => {
                const rel = f.webkitRelativePath || f.name;
                if (!folder && rel.includes('/')) folder = rel.split('/')[0];
                if (filter(f.name.toLowerCase(), rel) && add(f.name, rel)) count++;
            });

            folder = folder || defFolder;
            if (pathInp) {
                pathInp.value = folder + '/';
                try { localStorage.setItem(key, folder + '/'); } catch (e) {}
            }

            toast(`${title}: ${folder}${count ? ` (+ ${count} ${unit})` : ''}`);
            render();
            this.value = '';
        });

        pathInp?.addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                const val = pathInp.value.trim();
                if (val) {
                    try { localStorage.setItem(key, val); } catch (e) {}
                    toast(`${title}: ${val}`);
                }
            }
        });
    };

    // Каталог скриптов правил
    setup(
        'rule-folder-path',
        'btn-rule-folder',
        'rule-folder-input',
        'belt_rule_folder',
        'Папка правил',
        'папка правил',
        'правил',
        n => (n.endsWith('.py') || n.endsWith('.json') || n.endsWith('.rule')) && n !== '__init__.py' && n !== 'base.py',
        addRuleFromFile
    );

    // Каталог весов моделей
    setup(
        'model-folder-path',
        'btn-model-folder',
        'model-folder-input',
        'belt_model_folder',
        'Папка весов',
        'папка весов',
        'моделей',
        n => ['.pt', '.onnx', '.engine', '.tflite', '.weights', '.bin'].some(ext => n.endsWith(ext)),
        addModelFromFile
    );
}
