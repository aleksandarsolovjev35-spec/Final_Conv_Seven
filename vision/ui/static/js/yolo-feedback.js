// yolo-feedback.js — Обводка пропущенных дефектов на камере и выгрузка ZIP для YOLO
'use strict';

const yoloState = {
    pendingCount: 0,
    totalCount: 0,

    markOpen: false,
    exportOpen: false,
    busy: false,

    snapshot: null,       // ответ POST /api/yolo-tasks/snapshot
    showDetections: true, // показывать детекции текущей YOLO поверх снимка
    detectionsCount: 0,   // число детекций модели на текущем снимке
    tool: 'polygon',      // 'polygon' (обводка) | 'bbox' (рамка)
    activeClass: null,    // выбранный объект класса из snapshot.classes
    marks: [],            // [{shape, yolo_class, label, color, points: [[x,y], ...]}]

    drawing: false,
    pointerId: null,
    draftPoints: [],      // текущая рисуемая фигура в нормализованных [0..1]
};

// Слишком много детекций модели — оверлей мешает читать кадр: он
// скрывается автоматически, а оператор включает его обратно кнопкой
// «МОДЕЛЬ: СКРЫТА (N)» только когда это действительно нужно.
const YOLO_OVERLAY_AUTOHIDE_LIMIT = 12;

let _yoloResizeObserver = null;

async function yoloRequestJson(path, options = {}) {
    try {
        const res = await fetch(path, options);
        const ct = res.headers.get('content-type') || '';
        const payload = ct.includes('json') ? await res.json() : null;
        if (!res.ok) {
            const msg = (payload && (payload.error || payload.detail))
                || `Ошибка запроса (${res.status})`;
            return {ok: false, error: String(msg), status: res.status};
        }
        return payload || {ok: true};
    } catch (err) {
        return {
            ok: false,
            error: (err && err.message) || 'Нет связи с сервером',
        };
    }
}

function isYoloModalOpen() {
    return yoloState.markOpen || yoloState.exportOpen;
}

function yoloJogEligible() {
    return (
        !state.splashActive
        && !state.offline
        && !!state.jogActive
        && JOG_ALLOWED_STATES.includes(state.lineState)
    );
}

function yoloMarkAvailable() {
    if (!yoloJogEligible() || state.jogBusy || state.jogStepPending || !state.currentCamera) {
        return false;
    }
    const roleVer = Number(state.frameVersions[state.currentCamera] || 0);
    return roleVer > 0;
}

function updateYoloFeedbackButtons() {
    const eligible = yoloJogEligible();
    if (!eligible) {
        if (yoloState.markOpen && typeof closeYoloMarkModal === 'function') {
            closeYoloMarkModal();
        }
        if (yoloState.exportOpen && typeof closeYoloExportModal === 'function') {
            closeYoloExportModal();
        }
    }

    const markBtn = $('mark-yolo-defect');
    if (markBtn) {
        markBtn.classList.toggle('is-hidden', !eligible);
        markBtn.disabled = !yoloMarkAvailable() || yoloState.busy;
    }

    const exportBtn = $('yolo-export-open');
    const exportGroup = $('yolo-export-group');
    if (exportGroup) {
        exportGroup.classList.toggle('is-hidden', !eligible);
    }
    if (exportBtn) {
        exportBtn.disabled = !eligible || state.jogBusy || state.jogStepPending;
        exportBtn.textContent = `YOLO · ${yoloState.pendingCount}`;
        exportBtn.classList.toggle('has-pending', yoloState.pendingCount > 0);
        exportBtn.title = yoloState.pendingCount > 0
            ? `Новых кадров к выгрузке в ZIP: ${yoloState.pendingCount} (всего: ${yoloState.totalCount})`
            : `Очередь кадров для разметчика YOLO (всего сохранено: ${yoloState.totalCount})`;
    }
}

function updateYoloFeedbackStatus(payload) {
    if (payload && payload.available === true) {
        yoloState.pendingCount = Math.max(0, Number(payload.pending) || 0);
        yoloState.totalCount = Math.max(0, Number(payload.total) || 0);
    }
    updateYoloFeedbackButtons();
}

// ─── Открытие снимка камеры для обводки ─────────────────────────

function setYoloMarkStatus(text, kind = '') {
    const el = $('yolo-mark-status');
    if (!el) return;
    setIfChanged(el, text || '', false);
    el.classList.toggle('is-error', kind === 'error');
    el.classList.toggle('is-ok', kind === 'ok');
}

function formatSnapshotSource(snap) {
    if (!snap) return '—';
    const stepSuffix = Number.isInteger(snap.step) ? ` · ШАГ ${snap.step}` : '';
    const partSuffix = Number.isInteger(snap.part_id) ? ` · КОРПУС \u2116\u00a0${snap.part_id}` : '';
    if (snap.source_kind === 'analysis') {
        return `JOG · АНАЛИЗ КАДРА${partSuffix}${stepSuffix}`;
    }
    return `JOG · КАДР КАМЕРЫ${partSuffix}${stepSuffix}`;
}

async function openYoloMarkModal(options = {}) {
    if (!yoloMarkAvailable() || yoloState.busy) return;
    const role = options.role || state.currentCamera;
    if (!role) return;

    const modal = $('yolo-mark-modal');
    const loading = $('yolo-stage-loading');
    const img = $('yolo-mark-image');
    if (!modal) return;

    yoloState.busy = true;
    yoloState.markOpen = true;
    yoloState.drawing = false;
    yoloState.pointerId = null;
    yoloState.draftPoints = [];
    yoloState.snapshot = null;
    yoloState.marks = [];
    if (img) img.classList.add('is-loading');
    redrawYoloCanvas();
    renderMarksChips();
    updateYoloFeedbackButtons();
    updateMarkActionStates();

    modal.classList.remove('is-hidden');
    fitCanvasStage();
    if (loading) {
        loading.textContent = 'ЗАХВАТ КАДРА JOG...';
        loading.classList.remove('is-hidden');
    }
    const commentInput = $('yolo-mark-comment');
    if (commentInput) commentInput.value = '';
    setYoloMarkStatus('');

    const res = await yoloRequestJson('/api/yolo-tasks/snapshot', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({role}),
    });
    yoloState.busy = false;
    updateYoloFeedbackButtons();

    if (!res || !res.ok || !res.snapshot) {
        if (loading) loading.classList.add('is-hidden');
        updateMarkActionStates();
        setYoloMarkStatus(
            (res && res.error) || 'Не удалось получить кадр камеры для разметки',
            'error',
        );
        return;
    }

    yoloState.marks = [];
    applySnapshotToModal(res.snapshot);
}

function applySnapshotToModal(snap) {
    yoloState.snapshot = snap;
    yoloState.detectionsCount = Number(snap.detections_count || 0);
    const tooManyDetections =
        yoloState.detectionsCount > YOLO_OVERLAY_AUTOHIDE_LIMIT;
    yoloState.showDetections = !!snap.has_detections && !tooManyDetections;
    const classes = Array.isArray(snap.classes) ? snap.classes : [];
    yoloState.activeClass = classes[0] || {
        yolo_class: 'other',
        label: 'Другое',
        color: '#ffa537',
    };

    const titleEl = $('yolo-mark-title');
    if (titleEl) {
        titleEl.textContent = `ОБВОДКА ДЕФЕКТА · ${snap.role_label || snap.role}`;
    }
    const badgeEl = $('yolo-mark-source-badge');
    if (badgeEl) {
        badgeEl.textContent = formatSnapshotSource(snap);
    }

    updateDetectionsToggleUI();
    if (tooManyDetections) {
        setYoloMarkStatus(
            `Детекций модели: ${yoloState.detectionsCount} — оверлей скрыт ` +
            'для читаемости кадра; включите кнопкой «МОДЕЛЬ», если нужен',
        );
    }
    renderClassButtons(classes);
    renderMarksChips();
    updateMarkActionStates();
    loadSnapshotImage();
}

function updateDetectionsToggleUI() {
    const btn = $('yolo-toggle-detections');
    const snap = yoloState.snapshot;
    if (!btn) return;
    if (!snap || !snap.has_detections) {
        btn.disabled = true;
        btn.textContent = 'МОДЕЛЬ: НЕТ ДЕТЕКЦИЙ';
        btn.classList.remove('yolo-tool-btn', 'is-active');
        return;
    }
    btn.disabled = false;
    btn.classList.add('yolo-tool-btn');
    btn.classList.toggle('is-active', yoloState.showDetections);
    if (yoloState.showDetections) {
        btn.textContent = 'МОДЕЛЬ: ПОКАЗАНА';
    } else if (yoloState.detectionsCount > YOLO_OVERLAY_AUTOHIDE_LIMIT) {
        btn.textContent = `МОДЕЛЬ: СКРЫТА (${yoloState.detectionsCount})`;
    } else {
        btn.textContent = 'МОДЕЛЬ: СКРЫТА';
    }
}

function loadSnapshotImage() {
    const snap = yoloState.snapshot;
    const img = $('yolo-mark-image');
    const loading = $('yolo-stage-loading');
    if (!snap || !img) return;

    const mySnapId = snap.snapshot_id;
    if (loading) {
        loading.textContent = 'ЗАГРУЗКА КАДРА...';
        loading.classList.remove('is-hidden');
    }

    const targetUrl = (yoloState.showDetections && snap.has_detections)
        ? snap.overlay_url
        : snap.clean_url;

    img.onload = () => {
        if (!yoloState.snapshot || yoloState.snapshot.snapshot_id !== mySnapId) {
            return;
        }
        img.classList.remove('is-loading');
        if (loading) loading.classList.add('is-hidden');
        fitCanvasStage();
        redrawYoloCanvas();
    };
    img.onerror = () => {
        if (!yoloState.snapshot || yoloState.snapshot.snapshot_id !== mySnapId) {
            return;
        }
        img.classList.add('is-loading');
        if (loading) {
            loading.textContent = 'ОШИБКА ЗАГРУЗКИ КАДРА';
        }
    };
    img.src = `${targetUrl}&t=${Date.now()}`;
}

function closeYoloMarkModal() {
    const modal = $('yolo-mark-modal');
    if (modal) modal.classList.add('is-hidden');
    yoloState.markOpen = false;
    yoloState.drawing = false;
    yoloState.pointerId = null;
    yoloState.draftPoints = [];
    yoloState.snapshot = null;
    setYoloMarkStatus('');
}

// ─── Кнопки выбора класса YOLO ──────────────────────────────────

function renderClassButtons(classes) {
    const container = $('yolo-class-buttons');
    if (!container) return;
    container.textContent = '';

    classes.forEach((cls, idx) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'yolo-class-btn';
        if (
            yoloState.activeClass
            && yoloState.activeClass.yolo_class === cls.yolo_class
        ) {
            btn.classList.add('is-active');
        }
        btn.style.setProperty('--cls-color', cls.color || '#ffa537');
        btn.dataset.yoloClass = cls.yolo_class;
        const modelHint = cls.model_path
            ? `${cls.model_path} (класс: ${cls.yolo_class})`
            : 'Без привязки к конкретной модели';
        btn.title = modelHint;

        const dot = document.createElement('span');
        dot.className = 'yolo-class-dot';
        btn.appendChild(dot);

        const label = document.createElement('span');
        label.textContent = cls.label || cls.yolo_class;
        btn.appendChild(label);

        if (idx < 9) {
            const keyHint = document.createElement('span');
            keyHint.className = 'yolo-class-key';
            keyHint.textContent = `[${idx + 1}]`;
            btn.appendChild(keyHint);
        }

        btn.addEventListener('click', () => selectYoloClass(cls));
        container.appendChild(btn);
    });
}

function selectYoloClass(cls) {
    if (!cls) return;
    yoloState.activeClass = cls;
    const container = $('yolo-class-buttons');
    if (!container) return;
    container.querySelectorAll('.yolo-class-btn').forEach(btn => {
        btn.classList.toggle('is-active', btn.dataset.yoloClass === cls.yolo_class);
    });
}

function selectYoloClassByIndex(zeroBasedIdx) {
    const snap = yoloState.snapshot;
    if (!snap || !Array.isArray(snap.classes)) return;
    const target = snap.classes[zeroBasedIdx];
    if (target) selectYoloClass(target);
}

// ─── Геометрия холста и рисование обводок ───────────────────────

function fitCanvasStage() {
    const stage = $('yolo-mark-stage');
    const wrap = $('yolo-canvas-wrap');
    const canvas = $('yolo-mark-canvas');
    if (!stage || !wrap || !canvas || !yoloState.markOpen) return;

    const snap = yoloState.snapshot;
    const imgW = (snap && snap.width) ? Number(snap.width) : 1280;
    const imgH = (snap && snap.height) ? Number(snap.height) : 720;

    const availW = Math.max(120, stage.clientWidth - 24);
    const availH = Math.max(90, stage.clientHeight - 16);
    const scale = Math.min(availW / imgW, availH / imgH);

    const cssW = Math.max(64, Math.round(imgW * scale));
    const cssH = Math.max(36, Math.round(imgH * scale));

    wrap.style.width = `${cssW}px`;
    wrap.style.height = `${cssH}px`;

    const innerW = Math.max(1, canvas.clientWidth || (cssW - 2));
    const innerH = Math.max(1, canvas.clientHeight || (cssH - 2));
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const targetPxW = Math.round(innerW * dpr);
    const targetPxH = Math.round(innerH * dpr);
    if (canvas.width !== targetPxW || canvas.height !== targetPxH) {
        canvas.width = targetPxW;
        canvas.height = targetPxH;
    }
    redrawYoloCanvas();
}

function clamp01(val) {
    return Math.max(0, Math.min(1, Number(val) || 0));
}

function pointerNormCoords(event, canvas) {
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, rect.width);
    const h = Math.max(1, rect.height);
    const x = clamp01((event.clientX - rect.left) / w);
    const y = clamp01((event.clientY - rect.top) / h);
    return [x, y];
}

function hexToRgba(hex, alpha) {
    const clean = String(hex || '#ffa537').replace('#', '');
    if (clean.length !== 6) return `rgba(255, 165, 55, ${alpha})`;
    const r = parseInt(clean.slice(0, 2), 16) || 255;
    const g = parseInt(clean.slice(2, 4), 16) || 165;
    const b = parseInt(clean.slice(4, 6), 16) || 55;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function polygonAreaPx(points, w, h) {
    if (points.length < 3) return 0;
    let area2 = 0;
    for (let i = 0; i < points.length; i += 1) {
        const x1 = points[i][0] * w;
        const y1 = points[i][1] * h;
        const next = points[(i + 1) % points.length];
        const x2 = next[0] * w;
        const y2 = next[1] * h;
        area2 += x1 * y2 - x2 * y1;
    }
    return Math.abs(area2) * 0.5;
}

function polylineLengthPx(points, w, h) {
    let total = 0;
    for (let i = 1; i < points.length; i += 1) {
        const dx = (points[i][0] - points[i - 1][0]) * w;
        const dy = (points[i][1] - points[i - 1][1]) * h;
        total += Math.hypot(dx, dy);
    }
    return total;
}

function expandStrokeToRibbon(points, w, h, halfWidthPx = 4) {
    const ptsPx = [];
    points.forEach(([nx, ny]) => {
        const px = nx * w;
        const py = ny * h;
        if (
            !ptsPx.length
            || Math.hypot(px - ptsPx[ptsPx.length - 1][0], py - ptsPx[ptsPx.length - 1][1]) >= 1.5
        ) {
            ptsPx.push([px, py]);
        }
    });
    if (ptsPx.length < 2) {
        const cx = points[0][0] * w;
        const cy = points[0][1] * h;
        return [
            [clamp01((cx - halfWidthPx) / w), clamp01((cy - halfWidthPx) / h)],
            [clamp01((cx + halfWidthPx) / w), clamp01((cy - halfWidthPx) / h)],
            [clamp01((cx + halfWidthPx) / w), clamp01((cy + halfWidthPx) / h)],
            [clamp01((cx - halfWidthPx) / w), clamp01((cy + halfWidthPx) / h)],
        ];
    }

    const normals = [];
    for (let i = 0; i < ptsPx.length - 1; i += 1) {
        const dx = ptsPx[i + 1][0] - ptsPx[i][0];
        const dy = ptsPx[i + 1][1] - ptsPx[i][1];
        const len = Math.hypot(dx, dy) || 1;
        normals.push([-dy / len, dx / len]);
    }

    const leftRail = [];
    const rightRail = [];
    for (let i = 0; i < ptsPx.length; i += 1) {
        let nx;
        let ny;
        if (i === 0) {
            [nx, ny] = normals[0];
        } else if (i === ptsPx.length - 1) {
            [nx, ny] = normals[normals.length - 1];
        } else {
            const sx = normals[i - 1][0] + normals[i][0];
            const sy = normals[i - 1][1] + normals[i][1];
            const mlen = Math.hypot(sx, sy);
            [nx, ny] = mlen > 1e-3 ? [sx / mlen, sy / mlen] : normals[i];
        }
        const [px, py] = ptsPx[i];
        leftRail.push([
            clamp01((px + nx * halfWidthPx) / w),
            clamp01((py + ny * halfWidthPx) / h),
        ]);
        rightRail.push([
            clamp01((px - nx * halfWidthPx) / w),
            clamp01((py - ny * halfWidthPx) / h),
        ]);
    }
    rightRail.reverse();
    return leftRail.concat(rightRail);
}

function drawPolygonPath(ctx, points, w, h, closePath) {
    if (!points.length) return;
    ctx.beginPath();
    ctx.moveTo(points[0][0] * w, points[0][1] * h);
    for (let i = 1; i < points.length; i += 1) {
        ctx.lineTo(points[i][0] * w, points[i][1] * h);
    }
    if (closePath) ctx.closePath();
}

function redrawYoloCanvas() {
    const canvas = $('yolo-mark-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;

    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    yoloState.marks.forEach((mark, idx) => {
        const pts = mark.points;
        if (!pts || pts.length < 3) return;
        const color = mark.color || '#ffa537';

        drawPolygonPath(ctx, pts, w, h, true);
        ctx.fillStyle = hexToRgba(color, 0.20);
        ctx.fill();

        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.lineWidth = 4;
        ctx.strokeStyle = 'rgba(8, 12, 16, 0.90)';
        ctx.stroke();

        ctx.lineWidth = 2;
        ctx.strokeStyle = color;
        ctx.stroke();

        let minX = 1;
        let minY = 1;
        pts.forEach(p => {
            if (p[0] < minX) minX = p[0];
            if (p[1] < minY) minY = p[1];
        });

        const tag = `#${idx + 1} ${mark.label || mark.yolo_class}`;
        ctx.font = '700 11px "Segoe UI", Arial, sans-serif';
        const tw = ctx.measureText(tag).width;
        const px = Math.max(4, Math.min(w - tw - 14, minX * w));
        const py = minY * h >= 24 ? minY * h - 22 : Math.min(h - 22, minY * h + 6);

        ctx.fillStyle = 'rgba(12, 16, 20, 0.92)';
        ctx.fillRect(px, py, tw + 10, 18);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.strokeRect(px, py, tw + 10, 18);

        ctx.fillStyle = color;
        ctx.textBaseline = 'middle';
        ctx.fillText(tag, px + 5, py + 9.5);
    });

    if (yoloState.drawing && yoloState.draftPoints.length >= 2) {
        const activeColor = (yoloState.activeClass && yoloState.activeClass.color) || '#ffa537';
        const draft = yoloState.draftPoints;
        let drawPts = draft;
        if (yoloState.tool === 'bbox') {
            const [x1, y1] = draft[0];
            const [x2, y2] = draft[draft.length - 1];
            drawPts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
        }
        drawPolygonPath(ctx, drawPts, w, h, yoloState.tool === 'bbox');
        ctx.fillStyle = hexToRgba(activeColor, 0.14);
        ctx.fill();

        ctx.lineWidth = 3.5;
        ctx.strokeStyle = 'rgba(8, 12, 16, 0.85)';
        ctx.stroke();

        ctx.lineWidth = 2;
        ctx.strokeStyle = activeColor;
        ctx.stroke();

        if (yoloState.tool === 'polygon' && drawPts.length >= 3) {
            ctx.save();
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(drawPts[drawPts.length - 1][0] * w, drawPts[drawPts.length - 1][1] * h);
            ctx.lineTo(drawPts[0][0] * w, drawPts[0][1] * h);
            ctx.strokeStyle = activeColor;
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.restore();
        }
    }

    ctx.restore();
}

function finalizeDraftMark() {
    const draft = yoloState.draftPoints;
    const canvas = $('yolo-mark-canvas');
    if (!draft || draft.length < 2 || !canvas) return;

    const rect = canvas.getBoundingClientRect();
    const cw = Math.max(1, rect.width);
    const ch = Math.max(1, rect.height);

    const xs = draft.map(p => p[0]);
    const ys = draft.map(p => p[1]);
    let minX = Math.min(...xs);
    let maxX = Math.max(...xs);
    let minY = Math.min(...ys);
    let maxY = Math.max(...ys);

    // Защита от случайного одиночного клика без протяжки
    const dragSpanScreenPx = Math.hypot((maxX - minX) * cw, (maxY - minY) * ch);
    if (dragSpanScreenPx < 5) {
        return;
    }

    const snap = yoloState.snapshot;
    const imgW = (snap && snap.width) ? Number(snap.width) : 1280;
    const imgH = (snap && snap.height) ? Number(snap.height) : 720;

    const cls = yoloState.activeClass || {
        yolo_class: 'other',
        label: 'Другое',
        color: '#ffa537',
    };

    let finalPoints;
    const shape = yoloState.tool === 'bbox' ? 'bbox' : 'polygon';
    if (shape === 'bbox') {
        if ((maxX - minX) * imgW < 4) {
            const mx = (minX + maxX) * 0.5;
            minX = clamp01(mx - 2 / imgW);
            maxX = clamp01(mx + 2 / imgW);
        }
        if ((maxY - minY) * imgH < 4) {
            const my = (minY + maxY) * 0.5;
            minY = clamp01(my - 2 / imgH);
            maxY = clamp01(my + 2 / imgH);
        }
        finalPoints = [
            [minX, minY],
            [maxX, minY],
            [maxX, maxY],
            [minX, maxY],
        ];
    } else {
        const areaPx = polygonAreaPx(draft, imgW, imgH);
        const pathPx = polylineLengthPx(draft, imgW, imgH);
        if (draft.length < 3 || areaPx < Math.max(16, pathPx * 1.5)) {
            finalPoints = expandStrokeToRibbon(draft, imgW, imgH, 4);
        } else {
            finalPoints = draft.slice();
        }
    }

    yoloState.marks.push({
        shape,
        yolo_class: cls.yolo_class,
        label: cls.label || cls.yolo_class,
        color: cls.color || '#ffa537',
        points: finalPoints,
    });
    setYoloMarkStatus('');
    renderMarksChips();
    updateMarkActionStates();
}

function renderMarksChips() {
    const strip = $('yolo-marks-strip');
    if (!strip) return;
    strip.textContent = '';

    if (!yoloState.marks.length) {
        const hint = document.createElement('span');
        hint.className = 'yolo-marks-hint';
        hint.textContent = 'Выберите класс выше и обведите на кадре не обнаруженные дефекты мышью или касанием';
        strip.appendChild(hint);
        return;
    }

    // Счётчик первым — при большом числе обводок всегда видно, сколько их.
    const counter = document.createElement('span');
    counter.className = 'yolo-mark-chip yolo-mark-chip-count';
    counter.textContent = `ОБВОДОК: ${yoloState.marks.length}`;
    strip.appendChild(counter);

    yoloState.marks.forEach((mark, idx) => {
        const chip = document.createElement('span');
        chip.className = 'yolo-mark-chip';
        chip.style.setProperty('--chip-color', mark.color || '#ffa537');

        const txt = document.createElement('span');
        txt.textContent = `#${idx + 1} ${mark.label}`;
        chip.appendChild(txt);

        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'yolo-mark-chip-remove';
        del.textContent = '\u00d7';
        del.title = 'Удалить эту обводку';
        del.addEventListener('click', () => {
            yoloState.marks.splice(idx, 1);
            renderMarksChips();
            updateMarkActionStates();
            redrawYoloCanvas();
        });
        chip.appendChild(del);

        strip.appendChild(chip);
    });

    // Новейшая обводка всегда видна: полоса прокручивается до конца.
    strip.scrollTop = strip.scrollHeight;
}

function setYoloTool(tool) {
    yoloState.tool = tool === 'bbox' ? 'bbox' : 'polygon';
    const polyBtn = $('yolo-tool-polygon');
    const bboxBtn = $('yolo-tool-bbox');
    if (polyBtn) polyBtn.classList.toggle('is-active', yoloState.tool === 'polygon');
    if (bboxBtn) bboxBtn.classList.toggle('is-active', yoloState.tool === 'bbox');
}

function undoLastYoloMark() {
    if (!yoloState.marks.length) return;
    yoloState.marks.pop();
    renderMarksChips();
    updateMarkActionStates();
    redrawYoloCanvas();
}

function clearAllYoloMarks() {
    if (!yoloState.marks.length) return;
    yoloState.marks = [];
    renderMarksChips();
    updateMarkActionStates();
    redrawYoloCanvas();
}

function updateMarkActionStates() {
    const hasMarks = yoloState.marks.length > 0;
    const undoBtn = $('yolo-mark-undo');
    const clearBtn = $('yolo-mark-clear');
    const saveBtn = $('yolo-mark-save');

    if (undoBtn) undoBtn.disabled = !hasMarks || yoloState.busy;
    if (clearBtn) clearBtn.disabled = !hasMarks || yoloState.busy;
    if (saveBtn) {
        saveBtn.disabled = !hasMarks || yoloState.busy || !yoloState.snapshot;
        saveBtn.textContent = hasMarks
            ? `СОХРАНИТЬ (${yoloState.marks.length})`
            : 'СОХРАНИТЬ';
    }
}

// ─── Сохранение кадра и обводок ─────────────────────────────────

async function saveCurrentYoloTask() {
    if (yoloState.busy || !yoloState.snapshot || !yoloState.marks.length) return;

    yoloState.busy = true;
    updateMarkActionStates();
    setYoloMarkStatus('Сохранение кадра и разметки...');

    const commentEl = $('yolo-mark-comment');
    const payload = {
        snapshot_id: yoloState.snapshot.snapshot_id,
        comment: commentEl ? commentEl.value.trim() : '',
        marks: yoloState.marks.map(m => ({
            shape: m.shape,
            yolo_class: m.yolo_class,
            points: m.points,
        })),
    };

    const result = await yoloRequestJson('/api/yolo-tasks/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
    });
    yoloState.busy = false;
    updateMarkActionStates();

    if (!result || !result.ok) {
        setYoloMarkStatus(
            (result && result.error) || 'Не удалось сохранить кадр для YOLO',
            'error',
        );
        return;
    }

    if (result.summary) {
        yoloState.pendingCount = Number(result.summary.pending_count) || 0;
        yoloState.totalCount = Number(result.summary.total_count) || 0;
    } else {
        yoloState.pendingCount += 1;
        yoloState.totalCount += 1;
    }
    updateYoloFeedbackButtons();
    closeYoloMarkModal();
    requestImmediateStatus();
}

// ─── Модальное окно очереди и выгрузки ZIP ──────────────────────

function setYoloExportStatus(text, kind = '') {
    const el = $('yolo-export-status');
    if (!el) return;
    setIfChanged(el, text || '', false);
    el.classList.toggle('is-error', kind === 'error');
    el.classList.toggle('is-ok', kind === 'ok');
}

async function openYoloExportModal() {
    if (state.splashActive || state.offline) return;
    const modal = $('yolo-export-modal');
    if (!modal) return;
    yoloState.exportOpen = true;
    modal.classList.remove('is-hidden');
    setYoloExportStatus('Загрузка списка кадров...');
    await refreshYoloExportSummary();
}

function closeYoloExportModal() {
    const modal = $('yolo-export-modal');
    if (modal) modal.classList.add('is-hidden');
    yoloState.exportOpen = false;
    setYoloExportStatus('');
}

async function refreshYoloExportSummary() {
    const data = await yoloRequestJson('/api/yolo-tasks/summary');
    if (!data || data.ok === false) {
        setYoloExportStatus(
            (data && data.error) || 'Не удалось загрузить очередь YOLO',
            'error',
        );
        return;
    }
    renderYoloExportSummary(data);
    setYoloExportStatus('');
}

function renderYoloExportSummary(summary) {
    const pending = Math.max(0, Number(summary.pending_count) || 0);
    const total = Math.max(0, Number(summary.total_count) || 0);
    yoloState.pendingCount = pending;
    yoloState.totalCount = total;
    updateYoloFeedbackButtons();

    setIfChanged($('yolo-stat-pending'), String(pending), false);
    setIfChanged($('yolo-stat-total'), String(total), false);

    const btnPending = $('yolo-download-pending');
    const btnAll = $('yolo-download-all');
    if (btnPending) {
        btnPending.disabled = pending <= 0 || yoloState.busy;
        btnPending.textContent = pending > 0
            ? `ВЫГРУЗИТЬ ZIP · НОВЫЕ (${pending})`
            : 'ВЫГРУЗИТЬ ZIP · НОВЫЕ';
    }
    if (btnAll) {
        btnAll.disabled = total <= 0 || yoloState.busy;
        btnAll.textContent = total > 0
            ? `СКАЧАТЬ ВСЕ (${total})`
            : 'СКАЧАТЬ ВСЕ';
    }

    const breakdownEl = $('yolo-models-breakdown');
    if (breakdownEl) {
        breakdownEl.textContent = '';
        const byModel = Array.isArray(summary.by_model) ? summary.by_model : [];
        byModel.forEach(item => {
            const pill = document.createElement('span');
            pill.className = 'yolo-model-pill';
            const roleName = cameraRoleLabel(item.camera_role);
            pill.appendChild(document.createTextNode(`${roleName} · ${item.label_ru}:`));
            const countEl = document.createElement('b');
            countEl.textContent = `${item.pending_marks}/${item.total_marks}`;
            pill.appendChild(countEl);
            breakdownEl.appendChild(pill);
        });
    }

    const listEl = $('yolo-items-list');
    if (!listEl) return;
    listEl.textContent = '';

    const items = Array.isArray(summary.items) ? summary.items : [];
    if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'yolo-empty-note';
        empty.textContent = 'Отмеченных кадров пока нет. Перейдите на камеру и нажмите «ОТМЕТИТЬ ДЕФЕКТ» (или клавишу M).';
        listEl.appendChild(empty);
        return;
    }

    items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'yolo-item-row';

        const thumb = document.createElement('img');
        thumb.className = 'yolo-item-thumb';
        thumb.alt = item.task_id;
        thumb.src = `/api/yolo-tasks/item/${encodeURIComponent(item.task_id)}/image?kind=hint`;
        thumb.title = 'Нажмите для полноэкранного просмотра шпаргалки разметчика';
        thumb.addEventListener('click', () => {
            if (typeof window._galleryFullscreen === 'function') {
                window._galleryFullscreen(thumb.src);
            }
        });
        row.appendChild(thumb);

        const info = document.createElement('div');
        info.className = 'yolo-item-info';

        const head = document.createElement('div');
        head.className = 'yolo-item-head';

        const roleSpan = document.createElement('span');
        roleSpan.className = 'yolo-item-role';
        roleSpan.textContent = item.camera_label || cameraRoleLabel(item.camera_role);
        head.appendChild(roleSpan);

        const statusBadge = document.createElement('span');
        statusBadge.className = `yolo-item-badge ${item.exported ? 'exported' : 'pending'}`;
        statusBadge.textContent = item.exported ? 'ВЫГРУЖЕНО' : 'НОВОЕ';
        head.appendChild(statusBadge);

        info.appendChild(head);

        const classesLine = document.createElement('div');
        classesLine.className = 'yolo-item-classes';
        const labels = Array.isArray(item.labels_ru) && item.labels_ru.length
            ? item.labels_ru.join(', ')
            : (item.yolo_classes || []).join(', ');
        classesLine.textContent = `Классы: ${labels} · Обводок: ${item.marks_count}`;
        info.appendChild(classesLine);

        const metaLine = document.createElement('div');
        metaLine.className = 'yolo-item-meta';
        const parts = [`${item.date || ''} ${item.time || ''}`.trim()];
        if (Number.isInteger(item.part_id)) parts.push(`Корпус \u2116\u00a0${item.part_id}`);
        if (item.comment) parts.push(`«${item.comment}»`);
        metaLine.textContent = parts.filter(Boolean).join(' · ');
        info.appendChild(metaLine);

        row.appendChild(info);

        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn btn-icon yolo-close-btn';
        delBtn.textContent = '\u00d7';
        delBtn.title = 'Удалить кадр из очереди';
        delBtn.addEventListener('click', async () => {
            delBtn.disabled = true;
            const res = await yoloRequestJson(
                `/api/yolo-tasks/item/${encodeURIComponent(item.task_id)}/delete`,
                {method: 'POST'},
            );
            if (res && res.ok && res.summary) {
                renderYoloExportSummary(res.summary);
            } else {
                await refreshYoloExportSummary();
            }
        });
        row.appendChild(delBtn);

        listEl.appendChild(row);
    });
}

async function exportYoloZip(scope = 'pending') {
    if (yoloState.busy) return;
    yoloState.busy = true;
    setYoloExportStatus('Формирование ZIP-архива...');

    try {
        if (
            window.pywebview
            && window.pywebview.api
            && typeof window.pywebview.api.export_yolo_tasks_zip === 'function'
        ) {
            const res = await window.pywebview.api.export_yolo_tasks_zip(scope);
            if (res && res.cancelled) {
                setYoloExportStatus('');
                return;
            }
            if (!res || !res.ok) {
                setYoloExportStatus(
                    (res && res.error) || 'Ошибка сохранения ZIP',
                    'error',
                );
                return;
            }
            if (res.summary) renderYoloExportSummary(res.summary);
            setYoloExportStatus(`Сохранено: ${res.path}`, 'ok');
            requestImmediateStatus();
            return;
        }

        const url = `/api/yolo-tasks/export?scope=${encodeURIComponent(scope)}&mark_exported=1`;
        const response = await fetch(url);
        if (!response.ok) {
            let errMsg = 'Не удалось сформировать ZIP';
            try {
                const errJson = await response.json();
                if (errJson && errJson.error) errMsg = errJson.error;
            } catch (_) { /* ignore */ }
            setYoloExportStatus(errMsg, 'error');
            return;
        }
        const blob = await response.blob();
        const cd = response.headers.get('content-disposition') || '';
        const match = cd.match(/filename="([^"]+)"/);
        const filename = match ? match[1] : `yolo_tasks_${Date.now()}.zip`;

        const blobUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);

        await refreshYoloExportSummary();
        setYoloExportStatus(`ZIP выгружен: ${filename}`, 'ok');
        requestImmediateStatus();
    } catch (err) {
        setYoloExportStatus(err.message || 'Ошибка выгрузки ZIP', 'error');
    } finally {
        yoloState.busy = false;
        const btnPending = $('yolo-download-pending');
        const btnAll = $('yolo-download-all');
        if (btnPending) btnPending.disabled = yoloState.pendingCount <= 0;
        if (btnAll) btnAll.disabled = yoloState.totalCount <= 0;
    }
}

// ─── Инициализация событий ──────────────────────────────────────

function setupYoloCanvasEvents() {
    const canvas = $('yolo-mark-canvas');
    if (!canvas) return;

    canvas.addEventListener('contextmenu', e => e.preventDefault());

    canvas.addEventListener('pointerdown', e => {
        if (e.button !== undefined && e.button !== 0) return;
        if (!yoloState.markOpen || !yoloState.snapshot || yoloState.busy) return;
        e.preventDefault();
        if (canvas.setPointerCapture) {
            try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
        }
        yoloState.drawing = true;
        yoloState.pointerId = e.pointerId;
        const pt = pointerNormCoords(e, canvas);
        yoloState.draftPoints = [pt];
        redrawYoloCanvas();
    });

    canvas.addEventListener('pointermove', e => {
        if (!yoloState.drawing || e.pointerId !== yoloState.pointerId) return;
        e.preventDefault();
        const pt = pointerNormCoords(e, canvas);
        if (yoloState.tool === 'bbox') {
            yoloState.draftPoints = [yoloState.draftPoints[0], pt];
        } else {
            const last = yoloState.draftPoints[yoloState.draftPoints.length - 1];
            const rect = canvas.getBoundingClientRect();
            const dx = (pt[0] - last[0]) * rect.width;
            const dy = (pt[1] - last[1]) * rect.height;
            if ((dx * dx + dy * dy) >= 9 && yoloState.draftPoints.length < 350) {
                yoloState.draftPoints.push(pt);
            }
        }
        redrawYoloCanvas();
    });

    const finishPointer = (e) => {
        if (!yoloState.drawing) return;
        if (yoloState.pointerId !== null && e.pointerId !== yoloState.pointerId) return;
        const pt = pointerNormCoords(e, canvas);
        if (yoloState.draftPoints.length === 1) {
            yoloState.draftPoints.push(pt);
        } else if (yoloState.tool === 'bbox') {
            yoloState.draftPoints = [yoloState.draftPoints[0], pt];
        }
        yoloState.drawing = false;
        yoloState.pointerId = null;
        finalizeDraftMark();
        yoloState.draftPoints = [];
        redrawYoloCanvas();
    };

    canvas.addEventListener('pointerup', finishPointer);
    window.addEventListener('pointerup', finishPointer);
    canvas.addEventListener('pointercancel', () => {
        yoloState.drawing = false;
        yoloState.pointerId = null;
        yoloState.draftPoints = [];
        redrawYoloCanvas();
    });
}

function setupYoloFeedback() {
    $('mark-yolo-defect')?.addEventListener('click', () => {
        openYoloMarkModal({role: state.currentCamera});
    });

    $('yolo-mark-close')?.addEventListener('click', closeYoloMarkModal);
    $('yolo-mark-cancel')?.addEventListener('click', closeYoloMarkModal);
    $('yolo-mark-backdrop')?.addEventListener('click', closeYoloMarkModal);

    $('yolo-tool-polygon')?.addEventListener('click', () => setYoloTool('polygon'));
    $('yolo-tool-bbox')?.addEventListener('click', () => setYoloTool('bbox'));
    $('yolo-mark-undo')?.addEventListener('click', undoLastYoloMark);
    $('yolo-mark-clear')?.addEventListener('click', clearAllYoloMarks);
    $('yolo-mark-save')?.addEventListener('click', saveCurrentYoloTask);

    $('yolo-toggle-detections')?.addEventListener('click', () => {
        if (!yoloState.snapshot || !yoloState.snapshot.has_detections) return;
        yoloState.showDetections = !yoloState.showDetections;
        updateDetectionsToggleUI();
        loadSnapshotImage();
    });

    $('yolo-export-open')?.addEventListener('click', openYoloExportModal);
    $('yolo-export-close')?.addEventListener('click', closeYoloExportModal);
    $('yolo-export-cancel')?.addEventListener('click', closeYoloExportModal);
    $('yolo-export-backdrop')?.addEventListener('click', closeYoloExportModal);
    $('yolo-download-pending')?.addEventListener('click', () => exportYoloZip('pending'));
    $('yolo-download-all')?.addEventListener('click', () => exportYoloZip('all'));

    setupYoloCanvasEvents();

    const stage = $('yolo-mark-stage');
    if (stage && typeof ResizeObserver !== 'undefined') {
        _yoloResizeObserver = new ResizeObserver(() => {
            if (yoloState.markOpen) fitCanvasStage();
        });
        _yoloResizeObserver.observe(stage);
    }
    window.addEventListener('resize', () => {
        if (yoloState.markOpen) fitCanvasStage();
    });

    updateYoloFeedbackButtons();
}

if (typeof window !== 'undefined') {
    window.setupYoloFeedback = setupYoloFeedback;
    window.updateYoloFeedbackStatus = updateYoloFeedbackStatus;
    window.updateYoloFeedbackButtons = updateYoloFeedbackButtons;
    window.openYoloMarkModal = openYoloMarkModal;
    window.closeYoloMarkModal = closeYoloMarkModal;
    window.closeYoloExportModal = closeYoloExportModal;
    window.isYoloModalOpen = isYoloModalOpen;
    window.undoLastYoloMark = undoLastYoloMark;
    window.selectYoloClassByIndex = selectYoloClassByIndex;
}
