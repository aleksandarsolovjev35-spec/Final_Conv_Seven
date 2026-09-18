/* belt-view.js — вьюпорт ленты: зум колесом и панорамирование мышью.
 *
 * Колесо мыши над блоком сборки = увеличение/уменьшение (курсор — точка
 * масштабирования). Зажатая ЛКМ на пустом фоне и движение = перемещение
 * по блоку. Если цепь не влезает — ряд автоматически отдаляется до
 * размера, вмещающего всю цепь (пока пользователь не крутанул колесо;
 * двойной клик по фону — вернуть автоподгонку).
 * Координаты дропа не трогаем: builder читает getBoundingClientRect,
 * который уже учитывает трансформацию.
 */
(function () {
'use strict';

var Z_MIN = 0.1;
var Z_MAX = 2.2;
var PAD = 16;                      /* padding зоны, учтён в доступе */
var MIN_VIS = 120;                 /* цепь нельзя утащить целиком за край */

var zone = null;
var row = null;
var z = 1;
var panX = 0;
var panY = 0;
var userZoomed = false;            /* колесо отключает автоподгонку */

function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

function availW() { return zone.clientWidth - PAD * 2; }
function availH() { return zone.clientHeight - PAD * 2; }

function apply() {
    if (!row) { return; }
    var aw = availW();
    var ah = availH();
    var cw = row.scrollWidth * z;
    var ch = (row.scrollHeight || 96) * z;
    if (aw <= 0 || ah <= 0) {              /* нет макета (jsdom) — только запись */
        write();
        return;
    }
    if (!userZoomed) {
        /* автоподгонка: цепь отдалена до вмещающей и по центру */
        panX = (aw - cw) / 2;
        panY = (ah - ch) / 2;
    } else {
        /* ручное полотно: двигаем свободно, но ≥ MIN_VIS цепи в окне */
        panX = clamp(panX, MIN_VIS - cw, aw - MIN_VIS);
        panY = clamp(panY, MIN_VIS - ch, ah - MIN_VIS);
    }
    write();
}

function write() {
    row.style.transform = 'translate(' + round(panX) + 'px, '
        + round(panY) + 'px) scale(' + round(z) + ')';
}

function round(v) { return Math.round(v * 100) / 100; }

function zoomAt(clientX, clientY, factor) {
    var nz = clamp(z * factor, Z_MIN, Z_MAX);
    if (nz === z) { return; }
    var r = row.getBoundingClientRect();
    panX += (z - nz) * ((clientX - r.left) / z);
    panY += (z - nz) * ((clientY - r.top) / z);
    z = nz;
    apply();
}

function autoFit() {
    var aw = availW();
    var cw = row.scrollWidth;
    if (aw <= 0 || cw <= 0) { return; }
    z = clamp(Math.min(1, (aw - 8) / cw), Z_MIN, 1);
    apply();
}

/* ── зум: колесо ─────────────────────────────────────────────────────── */

function wireWheel() {
    zone.addEventListener('wheel', function (ev) {
        ev.preventDefault();
        var unit = ev.deltaMode === 1 ? 16 : (ev.deltaMode === 2 ? 360 : 1);
        var factor = Math.exp(-ev.deltaY * unit * 0.0015);
        userZoomed = true;
        zoomAt(ev.clientX, ev.clientY, factor);
    }, { passive: false });
}

/* ── пан: ЛКМ по фону + движение ─────────────────────────────────────── */

function isBackground(target) {
    return target === zone || target === row || target === document.body;
}

function wirePan() {
    zone.addEventListener('mousedown', function (ev) {
        if (ev.button !== 0 || !isBackground(ev.target)) { return; }
        /* пан = пользователь взял полотно в руки: автоподгонка
         * до двойного клика не перехватывает позицию */
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
            if (mv.buttons === 0) { up(); return; } /* кнопка потеряна */
            panX = mv.clientX - startX;
            panY = mv.clientY - startY;
            apply();
        }
        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', up);
    });
}

/* двойной клик по фону — вернуть автоподгонку к размеру цепи */
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
