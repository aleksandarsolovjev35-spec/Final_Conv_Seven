// harness.js — общая обвязка UI-проверок: настоящая разметка
// `vision/ui/templates/index.html` и настоящие модули HMI в jsdom, с
// заглушкой сети вместо backend.
//
// Проверки живут рядом, в `tests/ui/*.js`: каждый файл получает готовый
// `dom` и сам решает, что проверять. Это страховка от регрессий в HMI,
// которую python-тесты поймать не могут (они не исполняют JS).
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const REPO = process.env.REPO_DIR
    || path.resolve(__dirname, '..', '..');

// Порядок модулей повторяет index.html; bootstrap.js не подключается — он
// запускает опросы статуса и кадров, а в проверках ими управляют сами
// наборы.
const SCRIPTS = [
    'vision/ui/static/js/core.js',
    'vision/ui/static/js/boot.js',
    'vision/ui/static/js/status.js',
    'vision/ui/static/js/controls.js',
    'vision/ui/static/js/thresholds.js',
    'vision/ui/static/js/cameras.js',
    'vision/ui/static/js/jog.js',
    'vision/ui/static/js/history.js',
    'vision/ui/static/js/operator.js',
    'vision/ui/static/js/batch.js',
    'vision/ui/static/js/panel-deck.js',
];

function buildDom(options = {}) {
    const html = fs.readFileSync(
        path.join(REPO, 'vision/ui/templates/index.html'), 'utf8',
    ).replace(/<script[^>]*><\/script>/g, '');
    const dom = new JSDOM(html, {
        runScripts: 'dangerously',
        pretendToBeVisual: true,
        url: 'http://localhost:8000/',
    });
    const { window } = dom;

    // Сеть: запросы перехватываются, ответы берутся из таблицы routes
    // («GET /api/batch» → объект). Всё, что не описано, отвечает пустым
    // объектом — модулям этого достаточно, чтобы не падать.
    const routes = new Map();
    const posts = [];
    window.fetch = async (url, options = {}) => {
        const target = String(url);
        const method = String(options.method || 'GET').toUpperCase();
        if (method !== 'GET') {
            posts.push({ url: target, body: options.body });
        }
        const key = `${method} ${target.split('?')[0]}`;
        let payload = routes.has(key) ? routes.get(key) : {};
        if (typeof payload === 'function') payload = payload(options);
        return {
            ok: true,
            status: 200,
            async json() {
                return JSON.parse(JSON.stringify(payload));
            },
            async text() {
                return JSON.stringify(payload);
            },
        };
    };
    window.alert = () => {};

    for (const script of SCRIPTS.concat(options.extraScripts || [])) {
        const code = fs.readFileSync(path.join(REPO, script), 'utf8');
        const tag = window.document.createElement('script');
        tag.textContent = code;
        window.document.head.appendChild(tag);
    }
    return { dom, window, routes, posts };
}

function makeChecker(log) {
    let fails = 0;
    let total = 0;
    const check = (name, ok, extra) => {
        total += 1;
        if (ok) {
            log(`OK   ${name}${extra ? ' :: ' + extra : ''}`);
        } else {
            fails += 1;
            log(`FAIL ${name}${extra ? ' :: ' + extra : ''}`);
        }
    };
    return { check, result: () => ({ total, fails }) };
}

module.exports = { buildDom, makeChecker, REPO, SCRIPTS };
