/* roi.js — веб-разметка ROI поверх roi_capture.RoiSessionController.
 *
 * Страница ничего не решает сама: рисует состояние из /api/state и
 * отправляет действия. Координаты зоны всегда передаются в пикселях
 * кадра, поэтому масштаб окна на них не влияет.
 */

(function () {
    'use strict';

    const API = {
        state: '/api/state',
        start: '/api/start',
        capture: '/api/capture',
        save: '/api/save',
        step: '/api/step',
        skip: '/api/skip',
        finish: '/api/finish',
        camera: (index) => `/api/camera/${index}`,
        frame: (index) => `/api/frame/${index}?t=${Date.now()}`,
        preview: (index) => `/api/preview/${index}?t=${Date.now()}`,
    };

    const POLL_MS = 900;
    const HANDLE_RADIUS = 5;
    const SNAP_PX = 12;

    const els = {};
    let state = null;
    let pending = false;
    let work = null;          // зона, которую правит оператор
    let draftKey = '';        // круг:камера, для которой сделан черновик
    let lastToken = '';
    let toastTimer = null;
    let pollTimer = null;

    // ─── Утилиты ─────────────────────────────────────────────────────

    function $(id) { return document.getElementById(id); }

    function cache() {
        [
            'preview-strip', 'camera-label', 'mode-badge', 'stage', 'main-camera',
            'roi-canvas', 'stage-hint', 'stage-empty', 'stage-busy',
            'stage-empty-text', 'stage-busy-text', 'btn-mode', 'btn-undo', 'btn-reset', 'btn-capture',
            'btn-save', 'round-note', 'line-cells', 'session-state', 'stat-session',
            'stat-round', 'stat-camera', 'stat-index', 'stat-mode', 'stat-step',
            'zone-x', 'zone-y', 'zone-w', 'zone-h', 'zone-area', 'zone-points',
            'zone-empty', 'stat-saved', 'stat-rounds', 'stat-steps',
            'progress-fill', 'session-folder', 'fault-card', 'fault-text',
            'btn-start', 'btn-step', 'btn-skip', 'btn-finish', 'status-dot',
            'status-text', 'toast', 'tag-source', 'tag-step-mode', 'tag-session',
        ].forEach((id) => { els[id] = $(id); });
        els.canvas = els['roi-canvas'];
        els.image = els['main-camera'];
        els.ctx = els.canvas.getContext('2d');
    }

    function toast(message, kind) {
        if (!message) return;
        els.toast.textContent = message;
        els.toast.className = `toast ${kind || ''}`.trim();
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => els.toast.classList.add('is-hidden'), 2600);
    }

    async function request(url, options) {
        const response = await fetch(url, options || { method: 'GET' });
        let payload = null;
        try { payload = await response.json(); } catch (error) { payload = null; }
        if (payload && payload.state) {
            applyState(payload.state);
        }
        if (!response.ok || (payload && payload.ok === false)) {
            const message = (payload && payload.message) || `HTTP ${response.status}`;
            toast(message, 'bad');
            return { ok: false, message };
        }
        return { ok: true, payload };
    }

    function post(url, body) {
        const options = { method: 'POST', headers: {} };
        if (body !== undefined) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
        }
        return request(url, options);
    }

    async function guarded(fn) {
        if (pending) return;
        pending = true;
        setBusy(true);
        try {
            await fn();
        } catch (error) {
            toast(String(error && error.message ? error.message : error), 'bad');
        } finally {
            pending = false;
            setBusy(false);
            await refresh();
        }
    }

    function setBusy(on) {
        document.body.classList.toggle('is-busy', on);
        if (on) {
            els['stage-busy'].classList.remove('is-hidden');
        } else {
            els['stage-busy'].classList.add('is-hidden');
        }
    }

    // ─── Состояние ───────────────────────────────────────────────────

    async function refresh() {
        try {
            const response = await fetch(API.state, { cache: 'no-store' });
            if (!response.ok) return;
            applyState(await response.json());
        } catch (error) {
            if (typeof window !== 'undefined' && window.ROI_DEBUG) {
                console.log('refresh error', error && error.stack);
            }
            els['status-text'].textContent = 'НЕТ СВЯЗИ С СЕРВЕРОМ';
            els['status-dot'].className = 'status-dot bad';
        }
    }

    function applyState(next) {
        const previous = state;
        state = next;
        render(previous);
    }

    function currentCamera() {
        if (!state || !state.cameras.length) return null;
        return state.cameras[state.cursor] || null;
    }

    function isMarkup() { return state && state.phase === 'MARKUP'; }

    function render(previous) {
        if (!state) return;
        renderTags();
        renderPreviews(previous);
        renderMainFrame(previous);
        renderBadges();
        renderStats();
        renderControls();
        renderHint();
    }

    function renderTags() {
        els['tag-source'].textContent = state.source;
        const modes = { serial: 'COM-шаг', sim: 'имитация шага', none: 'без шага' };
        els['tag-step-mode'].textContent = modes[state.step.mode] || state.step.mode;
        els['tag-session'].textContent = `сессия ${state.session.id}`;
        els['session-folder'].textContent = state.session.folder;
    }

    function renderPreviews(previous) {
        const strip = els['preview-strip'];
        const needRebuild = strip.children.length !== state.cameras.length;
        if (needRebuild) {
            strip.textContent = '';
            state.cameras.forEach((camera, index) => {
                const cell = document.createElement('div');
                cell.className = 'preview-cam';
                cell.dataset.index = String(index);

                const img = new Image();
                img.alt = camera.label;
                cell.appendChild(img);

                const indexBadge = document.createElement('span');
                indexBadge.className = 'preview-cam-index';
                indexBadge.textContent = String(index + 1);
                cell.appendChild(indexBadge);

                const stateLabel = document.createElement('span');
                stateLabel.className = 'preview-cam-state';
                stateLabel.textContent = camera.role;
                cell.appendChild(stateLabel);

                const label = document.createElement('span');
                label.className = 'preview-cam-label';
                label.textContent = camera.role;
                cell.appendChild(label);

                cell.addEventListener('click', () => selectCamera(index));
                strip.appendChild(cell);
            });
        }

        state.cameras.forEach((camera, index) => {
            const cell = strip.children[index];
            if (!cell) return;
            const changed = !previous
                || previous.cameras[index]?.token !== camera.token;
            const img = cell.querySelector('img');
            if (camera.captured && (changed || !img.src)) {
                img.src = API.preview(index);
            }
            cell.classList.toggle('active', index === state.cursor);
            cell.classList.toggle('saved', camera.saved);
            cell.classList.toggle('preview-ready', camera.captured);
            cell.classList.toggle('preview-cam-error', Boolean(camera.error));
            const stateLabel = cell.querySelector('.preview-cam-state');
            if (stateLabel) {
                stateLabel.textContent = camera.error ? 'НЕТ СВЯЗИ' : camera.role;
            }
        });
    }

    function renderMainFrame(previous) {
        const camera = currentCamera();
        if (!camera) return;
        const token = `${state.cursor}:${camera.token}`;
        const empty = !camera.captured;

        els['stage-empty'].classList.toggle('is-hidden', !empty);
        if (els['stage-empty-text']) {
            els['stage-empty-text'].textContent = camera.error
                ? camera.error
                : 'Нажмите «НАЧАТЬ», чтобы открыть камеры';
        }

        els['camera-label'].textContent = camera.camera_id === null
            ? camera.role
            : `${camera.role} · ${camera.label} · камера ${camera.camera_id}`;

        if (!empty && token !== lastToken) {
            lastToken = token;
            els.image.src = API.frame(state.cursor);
        }
        if (empty) {
            lastToken = '';
            els.image.removeAttribute('src');
        }
        resizeCanvas();
        draw();
    }

    function renderBadges() {
        const polygon = state.mode === 'poly';
        els['mode-badge'].textContent = polygon ? 'ПОЛИГОН' : 'ПРЯМОУГОЛЬНИК';
        els['btn-mode'].textContent = polygon ? 'ПРЯМОУГОЛЬНИК' : 'ПОЛИГОН';
        els['btn-mode'].classList.toggle('is-on', polygon);
        els['round-note'].textContent = state.round ? `круг ${state.round}` : 'круг —';

        const labels = {
            READY: 'ОЖИДАНИЕ',
            MARKUP: 'РАЗМЕТКА',
            ROUND_DONE: 'КРУГ ЗАВЕРШЁН',
            STEPPING: 'ШАГ ЛЕНТЫ',
            FINISHED: 'СЕАНС ЗАВЕРШЁН',
        };
        els['session-state'].textContent = labels[state.phase] || state.phase;
    }

    function renderStats() {
        const camera = currentCamera() || {};
        const saved = state.cameras.filter((item) => item.saved).length;

        els['stat-session'].textContent = state.session.id;
        els['stat-round'].textContent = state.round || '—';
        els['stat-camera'].textContent = camera.role || '—';
        els['stat-index'].textContent = state.cursor >= 0
            ? `${state.cursor + 1} / ${state.cameras.length}`
            : '—';
        els['stat-mode'].textContent = state.mode === 'poly' ? 'ПОЛИГОН' : 'ПРЯМ';
        els['stat-step'].textContent = state.step.number === null
            ? '—' : `STEP=${state.step.number}`;

        els['stat-saved'].textContent = String(state.session.shots);
        els['stat-rounds'].textContent = String(state.session.rounds);
        els['stat-steps'].textContent = String(state.session.steps);
        els['progress-fill'].style.width = `${Math.round(state.progress * 100)}%`;

        renderLineCells(saved);
        renderZone();
        renderStatus();
    }

    function renderLineCells(saved) {
        const container = els['line-cells'];
        if (container.children.length !== state.cameras.length) {
            container.textContent = '';
            state.cameras.forEach((camera) => {
                const cell = document.createElement('div');
                cell.className = 'line-cell';
                const title = document.createElement('div');
                title.className = 'line-cell-title';
                title.textContent = camera.role;
                const value = document.createElement('div');
                value.className = 'line-cell-value';
                value.textContent = '—';
                cell.appendChild(title);
                cell.appendChild(value);
                cell.addEventListener('click', () => selectCamera(camera.index));
                container.appendChild(cell);
            });
        }
        state.cameras.forEach((camera, index) => {
            const cell = container.children[index];
            if (!cell) return;
            cell.classList.toggle('current', index === state.cursor);
            cell.classList.toggle('saved', camera.saved);
            cell.classList.toggle('error', Boolean(camera.error));
            const value = cell.querySelector('.line-cell-value');
            if (value) {
                value.textContent = camera.error
                    ? 'НЕТ СВЯЗИ'
                    : (camera.saved ? 'СОХРАНЕНО' : (camera.captured ? 'КАДР' : '—'));
            }
        });
        if (saved !== undefined) {
            els['round-note'].textContent = state.round
                ? `круг ${state.round} · ${saved}/${state.cameras.length}`
                : 'круг —';
        }
    }

    function draftKeyNow() {
        return state ? `${state.round}:${state.cursor}` : '';
    }

    function serverRoi() {
        const camera = currentCamera();
        return camera && camera.roi ? camera.roi : null;
    }

    function activeRoi() {
        if (work && draftKey === draftKeyNow()) return work;
        const roi = serverRoi();
        if (!roi) return null;
        return {
            mode: roi.mode,
            closed: roi.closed !== false,
            points: roi.points.map((p) => ({ x: px(p), y: py(p) })),
        };
    }

    function dropDraft() {
        work = null;
        draftKey = '';
    }

    function keepDraft(roi) {
        work = roi;
        draftKey = draftKeyNow();
    }

    function renderZone() {
        const roi = activeRoi();
        // прямоугольник валиден уже по двум противоположным углам,
        // полигон — только после третьей вершины
        const minPoints = roi && roi.mode === 'rect' ? 2 : 3;
        const empty = !roi || roi.points.length < minPoints;
        els['zone-empty'].classList.toggle('is-hidden', !empty);
        if (empty) {
            els['zone-x'].textContent = '—';
            els['zone-y'].textContent = '—';
            els['zone-w'].textContent = '—';
            els['zone-h'].textContent = '—';
            els['zone-area'].textContent = '—';
            els['zone-points'].textContent = '—';
            return;
        }
        const box = bbox(roi.points);
        const area = roi.mode === 'rect'
            ? box.w * box.h
            : Math.abs(polygonArea(roi.points));
        const frameArea = state.frame_size.width * state.frame_size.height;
        els['zone-x'].textContent = String(box.x);
        els['zone-y'].textContent = String(box.y);
        els['zone-w'].textContent = String(box.w);
        els['zone-h'].textContent = String(box.h);
        els['zone-area'].textContent = `${((area / frameArea) * 100).toFixed(2)} %`;
        els['zone-points'].textContent = String(roi.points.length);
    }

    function renderStatus() {
        let text = 'ГОТОВА К РАБОТЕ';
        let kind = '';
        if (state.phase === 'MARKUP') {
            text = 'РАЗМЕТКА · ОБВЕДИТЕ ЗОНУ';
            kind = 'ok';
        } else if (state.phase === 'ROUND_DONE') {
            text = state.step.fault
                ? 'ШАГ НЕ ПОДТВЕРЖДЁН'
                : 'КРУГ ЗАВЕРШЁН · СДЕЛАЙТЕ ШАГ';
            kind = state.step.fault ? 'bad' : 'warn';
        } else if (state.phase === 'STEPPING') {
            text = state.step.status ? `ШАГ: ${state.step.status}` : 'ШАГ ЛЕНТЫ…';
            kind = 'busy';
        } else if (state.phase === 'FINISHED') {
            text = 'СЕАНС ЗАВЕРШЁН';
            kind = 'warn';
        }
        if (state.notice && state.phase === 'MARKUP') {
            text = state.notice.toUpperCase();
        }
        els['status-text'].textContent = text;
        els['status-dot'].className = `status-dot ${kind}`.trim();

        const fault = state.step.fault;
        els['fault-card'].classList.toggle('is-hidden', !fault);
        els['fault-text'].textContent = fault || '';
    }

    function renderControls() {
        const markup = isMarkup();
        const done = state.phase === 'ROUND_DONE';
        const finished = state.phase === 'FINISHED';
        const ready = state.phase === 'READY';
        const busy = state.phase === 'STEPPING';

        els['btn-start'].disabled = !ready;
        els['btn-step'].disabled = !(state.can_step && state.step.mode !== 'none');
        els['btn-skip'].disabled = !done;
        els['btn-save'].disabled = !markup;
        els['btn-capture'].disabled = !markup;
        els['btn-reset'].disabled = !markup;
        els['btn-mode'].disabled = !markup;
        els['btn-finish'].disabled = finished;
        els['btn-undo'].disabled = !(markup && state.mode === 'poly');
        els['btn-step'].classList.toggle('pending', busy);
        if (busy) {
            els['btn-step'].textContent = 'ШАГ…';
        } else {
            els['btn-step'].textContent = 'ШАГ КОНВЕЙЕРА';
        }
    }

    function renderHint() {
        let hint = '';
        if (isMarkup()) {
            hint = state.mode === 'poly'
                ? 'Точки ЛКМ · двойной клик замыкает контур · ПКМ убирает точку'
                : 'Тяните ЛКМ от угла до угла';
            if (currentCamera() && !currentCamera().captured) {
                hint = 'Нет кадра — нажмите «ПЕРЕСНЯТЬ КАДР»';
            }
        } else if (state.phase === 'ROUND_DONE') {
            hint = 'Сделайте шаг конвейера или начните новый круг без шага';
        }
        els['stage-hint'].textContent = hint;
        els['stage-hint'].classList.toggle('is-hidden', !hint);
    }

    // ─── Канва: рисование зоны ───────────────────────────────────────

    function stageSize() {
        const rect = els.stage.getBoundingClientRect();
        return { width: Math.max(1, Math.floor(rect.width)),
                 height: Math.max(1, Math.floor(rect.height)) };
    }

    function frameToViewScale() {
        const frame = state ? state.frame_size : { width: 1280, height: 720 };
        const stage = stageSize();
        return Math.min(stage.width / frame.width, stage.height / frame.height);
    }

    function resizeCanvas() {
        const frame = state ? state.frame_size : { width: 1280, height: 720 };
        const scale = frameToViewScale();
        const width = Math.max(1, Math.round(frame.width * scale));
        const height = Math.max(1, Math.round(frame.height * scale));
        if (els.canvas.width !== width * devicePixelRatio
            || els.canvas.height !== height * devicePixelRatio
        ) {
            els.canvas.width = Math.round(width * devicePixelRatio);
            els.canvas.height = Math.round(height * devicePixelRatio);
        }
        els.canvas.style.width = `${width}px`;
        els.canvas.style.height = `${height}px`;
    }

    function viewPoint(event) {
        const rect = els.canvas.getBoundingClientRect();
        const scale = frameToViewScale();
        const x = (event.clientX - rect.left) / scale;
        const y = (event.clientY - rect.top) / scale;
        const frame = state.frame_size;
        return {
            x: Math.max(0, Math.min(frame.width - 1, Math.round(x))),
            y: Math.max(0, Math.min(frame.height - 1, Math.round(y))),
        };
    }

    function draw() {
        if (!els.ctx) return;
        const ctx = els.ctx;
        const dpr = devicePixelRatio || 1;
        const scale = frameToViewScale() * dpr;

        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);
        if (!state) return;

        const roi = activeRoi();
        const viewW = els.canvas.width;
        const viewH = els.canvas.height;

        if (roi && roi.points.length >= 2) {
            const points = roi.points.map((p) => [px(p) * scale, py(p) * scale]);

            // затемнение всего вне зоны
            ctx.save();
            ctx.beginPath();
            ctx.rect(0, 0, viewW, viewH);
            if (roi.mode === 'rect' || roi.points.length >= 3) {
                ctx.moveTo(points[0][0], points[0][1]);
                points.slice(1).forEach((p) => ctx.lineTo(p[0], p[1]));
                ctx.closePath();
            }
            ctx.fillStyle = 'rgba(9, 12, 15, 0.56)';
            ctx.fill('evenodd');
            ctx.restore();

            // контур
            ctx.beginPath();
            ctx.moveTo(points[0][0], points[0][1]);
            points.slice(1).forEach((p) => ctx.lineTo(p[0], p[1]));
            const closed = roi.mode === 'rect' || roi.closed || roi.points.length > 2;
            if (closed) ctx.closePath();
            ctx.strokeStyle = '#7899a5';
            ctx.lineWidth = 2 * dpr;
            ctx.stroke();

            // вершины
            points.forEach((p, index) => {
                const first = index === 0;
                ctx.beginPath();
                ctx.arc(p[0], p[1], (first ? 6 : HANDLE_RADIUS) * dpr, 0, Math.PI * 2);
                ctx.fillStyle = first ? '#7899a5' : '#0f1317';
                ctx.fill();
                ctx.strokeStyle = '#7899a5';
                ctx.lineWidth = 2 * dpr;
                ctx.stroke();
            });

            // незамкнутый полигон: резиновая линия до курсора
            if (roi.mode === 'poly' && !roi.closed && cursorPoint) {
                ctx.beginPath();
                const last = points[points.length - 1];
                ctx.moveTo(last[0], last[1]);
                ctx.lineTo(cursorPoint.x * scale, cursorPoint.y * scale);
                ctx.setLineDash([8 * dpr, 6 * dpr]);
                ctx.strokeStyle = '#7899a5';
                ctx.lineWidth = 1.5 * dpr;
                ctx.stroke();
                ctx.setLineDash([]);
            }

            // подпись зоны
            const camera = currentCamera();
            const label = `${String(state.round).padStart(2, '0')} · `
                + (camera ? camera.role : '');
            drawLabel(ctx, label, points[0], dpr);
        }
    }

    function drawLabel(ctx, text, point, dpr) {
        const size = 12 * dpr;
        ctx.font = `700 ${size}px 'Segoe UI', Arial, sans-serif`;
        const padding = 5 * dpr;
        const width = ctx.measureText(text).width + padding * 2;
        const height = size + padding * 2;
        let x = point[0];
        let y = point[1] - height - 4 * dpr;
        if (y < 0) y = point[1] + 4 * dpr;
        x = Math.max(0, Math.min(els.canvas.width - width, x));
        ctx.fillStyle = 'rgba(15, 19, 23, 0.94)';
        ctx.fillRect(x, y, width, height);
        ctx.strokeStyle = '#7899a5';
        ctx.lineWidth = 1 * dpr;
        ctx.strokeRect(x, y, width, height);
        ctx.fillStyle = '#e0e5e9';
        ctx.textBaseline = 'top';
        ctx.fillText(text, x + padding, y + padding);
    }

    // ─── Мышь ────────────────────────────────────────────────────────

    let cursorPoint = null;

    function onPointerDown(event) {
        if (!isMarkup() || pending) return;
        const camera = currentCamera();
        if (!camera || !camera.captured) {
            toast('Нет кадра: нажмите «ПЕРЕСНЯТЬ КАДР»', 'warn');
            return;
        }
        const point = viewPoint(event);

        if (event.button === 2) {
            undoPoint();
            return;
        }
        const mode = state.mode;
        const existing = activeRoi();

        if (mode === 'rect') {
            keepDraft({ mode: 'rect', points: [point, point], closed: true,
                        dragging: true, origin: point });
        } else {
            let roi = existing && existing.mode === 'poly' ? existing : null;
            if (!roi || roi.closed) {
                roi = { mode: 'poly', points: [], closed: false };
            }
            const pts = roi.points.slice();
            if (pts.length >= 3 && distance(pts[0], point) <= SNAP_PX) {
                roi.closed = true;
            } else {
                pts.push(point);
                roi.points = pts;
            }
            keepDraft({ mode: 'poly', points: roi.points, closed: roi.closed,
                        dragging: false, origin: null });
        }
        canvasChanged();
    }

    function onPointerMove(event) {
        if (!isMarkup()) return;
        cursorPoint = viewPoint(event);
        if (work && work.dragging && work.origin) {
            const point = viewPoint(event);
            work.points = [work.origin, point];
            canvasChanged();
        } else if (work && work.mode === 'poly') {
            draw();
        }
    }

    function onPointerUp() {
        if (!work || !work.dragging) return;
        work.dragging = false;
        const [first, second] = work.points;
        if (Math.abs(first.x - second.x) < 3 || Math.abs(first.y - second.y) < 3) {
            dropDraft();
            toast('Зона слишком мала', 'warn');
        }
        canvasChanged();
    }

    function onDoubleClick() {
        if (!isMarkup() || state.mode !== 'poly') return;
        if (work && work.mode === 'poly' && work.points.length >= 3) {
            work.closed = true;
            canvasChanged();
        }
    }

    function canvasChanged() {
        renderZone();
        draw();
    }

    function undoPoint() {
        if (!isMarkup() || state.mode !== 'poly') return;
        if (work && work.points.length) {
            work.points = work.points.slice(0, -1);
            work.closed = false;
            if (!work.points.length) dropDraft();
            canvasChanged();
        }
    }

    function resetRoi() {
        dropDraft();
        renderZone();
        draw();
        toast('Зона сброшена', 'warn');
    }

    // ─── Действия ────────────────────────────────────────────────────

    function roiPayload() {
        const roi = activeRoi();
        if (!roi) return null;
        return {
            mode: roi.mode,
            points: roi.points.map((p) => [px(p), py(p)]),
            closed: roi.closed !== false,
        };
    }

    function selectCamera(index) {
        guarded(async () => {
            dropDraft();
            await post(API.camera(index));
        });
    }

    function startSession() {
        guarded(async () => {
            dropDraft();
            const result = await post(API.start);
            if (result.ok) toast('Сеанс запущен', 'ok');
        });
    }

    function saveShot() {
        const roi = roiPayload();
        if (!roi || roi.points.length < 2) {
            toast('Обведите зону перед сохранением', 'warn');
            return;
        }
        guarded(async () => {
            const result = await post(API.save, { roi });
            if (result.ok) {
                // после сохранения сервер сам переключает камеру;
                // следующий ответ /api/state придёт с новой зоной
                dropDraft();
                lastToken = '';
            }
        });
    }

    function recapture() {
        guarded(async () => {
            dropDraft();
            await post(API.capture);
        });
    }

    function makeStep() {
        guarded(async () => {
            const result = await post(API.step);
            if (result.ok) toast('Шаг конвейера выполнен', 'ok');
        });
    }

    function skipStep() {
        guarded(async () => {
            dropDraft();
            await post(API.skip);
        });
    }

    function finishSession() {
        if (!window.confirm('Завершить сеанс разметки?')) return;
        guarded(async () => {
            await post(API.finish);
        });
    }

    // ─── Геометрия ───────────────────────────────────────────────────

    function bbox(points) {
        const xs = points.map((p) => (Array.isArray(p) ? p[0] : p.x));
        const ys = points.map((p) => (Array.isArray(p) ? p[1] : p.y));
        const x = Math.min.apply(null, xs);
        const y = Math.min.apply(null, ys);
        return { x, y, w: Math.max.apply(null, xs) - x, h: Math.max.apply(null, ys) - y };
    }

    function polygonArea(points) {
        let sum = 0;
        for (let i = 0; i < points.length; i += 1) {
            const a = points[i];
            const b = points[(i + 1) % points.length];
            const ax = Array.isArray(a) ? a[0] : a.x;
            const ay = Array.isArray(a) ? a[1] : a.y;
            const bx = Array.isArray(b) ? b[0] : b.x;
            const by = Array.isArray(b) ? b[1] : b.y;
            sum += ax * by - bx * ay;
        }
        return sum / 2;
    }

    function distance(a, b) {
        const ax = Array.isArray(a) ? a[0] : a.x;
        const ay = Array.isArray(a) ? a[1] : a.y;
        const bx = Array.isArray(b) ? b[0] : b.x;
        const by = Array.isArray(b) ? b[1] : b.y;
        return Math.hypot(ax - bx, ay - by);
    }

    /* Точки приходят из двух источников: локальный черновик ({x, y}) и
       /api/state ([[x, y], ...]). Приводим к [x, y] в одном месте. */
    function px(point) { return Array.isArray(point) ? point[0] : point.x; }
    function py(point) { return Array.isArray(point) ? point[1] : point.y; }

    // ─── Клавиатура ──────────────────────────────────────────────────

    function onKeyDown(event) {
        if (event.target && /input|textarea/i.test(event.target.tagName)) return;
        const key = event.key.toLowerCase();
        if (key === 'enter') {
            event.preventDefault();
            if (state && state.phase === 'ROUND_DONE') makeStep();
            else if (isMarkup()) saveShot();
            return;
        }
        if (key === '1') { postMode('rect'); return; }
        if (key === '2') { postMode('poly'); return; }
        if (key === 'r') { resetRoi(); return; }
        if (key === 'c') { recapture(); return; }
        if (key === 'a') { selectCamera((state.cursor - 1 + 7) % 7); return; }
        if (key === 'd') { selectCamera((state.cursor + 1) % 7); return; }
        if (key === 'n' && state.phase === 'ROUND_DONE') { skipStep(); return; }
        if (key === 'backspace') { undoPoint(); }
    }

    function postMode(mode) {
        if (!state || !isMarkup()) return;
        if (state.mode === mode) return;
        state.mode = mode;
        const roi = activeRoi();
        if (roi) {
            // переключение режима сохраняет геометрию: прямоугольник -> полигон
            if (mode === 'rect' && roi.mode === 'poly') {
                const box = bbox(roi.points);
                keepDraft({
                    mode: 'rect', closed: true, dragging: false, origin: null,
                    points: [
                        { x: box.x, y: box.y },
                        { x: box.x + box.w, y: box.y },
                        { x: box.x + box.w, y: box.y + box.h },
                        { x: box.x, y: box.y + box.h },
                    ],
                });
            } else if (mode === 'poly' && roi.mode === 'rect') {
                keepDraft({
                    mode: 'poly', closed: true, dragging: false, origin: null,
                    points: roi.points.map((p) => ({ x: px(p), y: py(p) })),
                });
            } else {
                keepDraft({ mode, closed: roi.closed !== false, dragging: false,
                            origin: null,
                            points: roi.points.map((p) => ({ x: px(p), y: py(p) })) });
            }
        }
        canvasChanged();
        renderBadges();
        renderControls();
    }

    // ─── Инициализация ───────────────────────────────────────────────

    function bind() {
        els['btn-start'].addEventListener('click', startSession);
        els['btn-save'].addEventListener('click', saveShot);
        els['btn-step'].addEventListener('click', makeStep);
        els['btn-skip'].addEventListener('click', skipStep);
        els['btn-finish'].addEventListener('click', finishSession);
        els['btn-capture'].addEventListener('click', recapture);
        els['btn-reset'].addEventListener('click', resetRoi);
        els['btn-undo'].addEventListener('click', undoPoint);
        els['btn-mode'].addEventListener('click', () => {
            postMode(state && state.mode === 'poly' ? 'rect' : 'poly');
        });

        els.canvas.addEventListener('pointerdown', onPointerDown);
        els.canvas.addEventListener('pointermove', onPointerMove);
        window.addEventListener('pointerup', onPointerUp);
        els.canvas.addEventListener('dblclick', onDoubleClick);
        els.canvas.addEventListener('contextmenu', (event) => event.preventDefault());
        els.canvas.addEventListener('pointerleave', () => { cursorPoint = null; draw(); });

        els.image.addEventListener('load', () => { resizeCanvas(); draw(); });
        window.addEventListener('resize', () => { resizeCanvas(); draw(); });
        document.addEventListener('keydown', onKeyDown);
    }

    function boot() {
        cache();
        bind();
        refresh();
        pollTimer = setInterval(refresh, POLL_MS);
        window.addEventListener('beforeunload', () => clearInterval(pollTimer));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
}());
