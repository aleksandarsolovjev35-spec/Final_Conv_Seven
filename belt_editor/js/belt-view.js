/* belt-view.js — вьюпорт ленты: зум колесом и панорамирование мышью.
 *
 * Ряд ленты — max-content-полотно, отцентровано flex'ом зоны;
 * transform = translate(экранные px) + scale(центр). Композионный
 * слой (will-change) не поднимается сознательно: браузер перерастеризует
 * текст под текущий масштаб — на увеличении остаётся чётким.
 *
 * Автоматический режим: если цепь длиннее окна — ряд отдаляется до
 * вмещающего размера, смещений нет. Колесо или ЛКМ-драг по фону переводят
 * в ручное полотно: свободный зум к курсору и пан с границей
 * «не менее MIN_VIS цепи в окне». Двойной клик по фону — снова авто.
 *
 * Дроп не затронут: builder считает индексы по getBoundingClientRect,
 * который учитывает трансформацию.
 */
(function () {
'use strict';

var Z_MIN = 0.1;
var Z_MAX = 2.2;
var PAD = 16;                      /* padding зоны */
var MIN_VIS = 40;                  /* цепи видно минимум столько */

var zone = null;
var row = null;
var z = 1;
var panX = 0;
var panY = 0;
var userZoomed = false;

function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
function round(v) { return Math.round(v * 100) / 100; }

function availW() { return zone.clientWidth - PAD * 2; }
function availH() { return zone.clientHeight - PAD * 2; }
/* layout-размеры ряда: не зависят от transform */
function chainW() { return row.offsetWidth || 0; }
function chainH() { return row.offsetHeight || 104; }

function write() {
    row.style.transform = 'translate(' + round(panX) + 'px, '
        + round(panY) + 'px) scale(' + round(z) + ')';
}

function apply() {
    if (!row) { return; }
    var aw = availW();
    var ah = availH();
    if (aw <= 0 || ah <= 0) { write(); return; }   /* нет макета (jsdom) */
    if (!userZoomed) {
        panX = 0;                                  /* flex центрирует сам */
        panY = 0;
    } else {
        var limX = Math.max(0, (aw + chainW() * z) / 2 - MIN_VIS);
        var limY = Math.max(0, (ah + chainH() * z) / 2 - MIN_VIS);
        panX = clamp(panX, -limX, limX);
        panY = clamp(panY, -limY, limY);
    }
    write();
}

function zoomAt(clientX, clientY, factor) {
    var nz = clamp(z * factor, Z_MIN, Z_MAX);
    if (nz === z) { return; }
    var r = row.getBoundingClientRect();
    panX += (z - nz) * (clientX - (r.left + r.width / 2)) / z;
    panY += (z - nz) * (clientY - (r.top + r.height / 2)) / z;
    z = nz;
    apply();
}

function autoFit() {
    var aw = availW();
    var ah = availH();
    var w = chainW();
    var h = chainH();
    if (aw <= 0 || w <= 0) { return; }
    var k = (aw - 8) / w;
    if (ah > 0 && h > 0) { k = Math.min(k, (ah - 8) / h); }
    z = clamp(Math.min(1, k), Z_MIN, 1);
    apply();
}

/* ── зум: колесо ─────────────────────────────────────────────────────── */

function wireWheel() {
    zone.addEventListener('wheel', function (ev) {
        ev.preventDefault();
        var unit = ev.deltaMode === 1 ? 16 : (ev.deltaMode === 2 ? 360 : 1);
        if (Math.abs(ev.deltaX || 0) > Math.abs(ev.deltaY || 0)) {
            /* трекпад/наклонённое колесо: свободный сдвиг, не зум */
            userZoomed = true;
            panX -= (ev.deltaX || 0) * unit;
            apply();
            return;
        }
        userZoomed = true;
        zoomAt(ev.clientX, ev.clientY,
            Math.exp(-ev.deltaY * unit * 0.0015));
    }, { passive: false });
}

/* ── пан: ЛКМ по фону + движение ─────────────────────────────────────── */

function isBackground(target) {
    return target === zone || target === row || target === document.body;
}

function wirePan() {
    zone.addEventListener('mousedown', function (ev) {
        /* ЛКМ по фону или СКМ откуда угодно (Blender-style): пан
         * свободного холста — по карточкам тоже, drag'у не мешает */
        var mid = ev.button === 1;
        if (!mid && (ev.button !== 0 || !isBackground(ev.target))) { return; }
        /* пан = пользователь взял полотно: автоподгонка до dblclick спит */
        userZoomed = true;
        var startX = ev.clientX - panX;
        var startY = ev.clientY - panY;
        zone.classList.add('panning');
        ev.preventDefault();

        function up() {
            zone.classList.remove('panning');
            window.removeEventListener('mousemove', move);
            window.removeEventListener('mouseup', up);
        }
        function move(mv) {
            if (!(mv.buttons & (mid ? 4 : 1))) { up(); return; } /* потёрян */
            panX = mv.clientX - startX;
            panY = mv.clientY - startY;
            apply();
        }
        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', up);
    });
}

/* двойной клик по фону — вернуть автоподгонку (зум-вместилище, центр) */
function wireReset() {
    zone.addEventListener('dblclick', function (ev) {
        if (!isBackground(ev.target)) { return; }
        userZoomed = false;
        autoFit();
    });
}

function wireRender() {
    zone.addEventListener('belt:render', function () {
        if (!userZoomed) { autoFit(); } else { apply(); }
    });
}

function boot() {
    zone = document.getElementById('belt-zone');
    row = document.getElementById('belt-row');
    if (!zone || !row) { return; }
    wireWheel();
    wirePan();
    wireReset();
    wireRender();
    window.addEventListener('resize', function () {
        if (!userZoomed) { autoFit(); } else { apply(); }
    });
    autoFit();
}

window.BeltView = {
    state: function () { return { z: z, panX: panX, panY: panY }; },
    setZoomLock: function (v) { userZoomed = !!v; },
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
} else {
    boot();
}

})();
