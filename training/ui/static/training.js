(() => {
    'use strict';

    const $ = (id) => document.getElementById(id);
    const els = {
        connection: $('connection-state'), setup: $('setup-panel'), work: $('work-panel'),
        result: $('result-panel'), datasetName: $('dataset-name'), classes: $('defect-classes'),
        roles: $('camera-roles'), create: $('create-session'), setupMessage: $('setup-message'),
        sessionTitle: $('session-title'), sessionStatus: $('session-status'), partsCount: $('parts-count'),
        framesCount: $('frames-count'), partNumber: $('part-number'), partProgress: $('part-progress'),
        newPart: $('new-part'), finishPart: $('finish-part'), export: $('export-dataset'),
        finishSession: $('finish-session'), workflowMessage: $('workflow-message'), cameraTitle: $('camera-title'),
        frameId: $('frame-id'), wrap: $('canvas-wrap'), emptyState: $('empty-state'), image: $('frame-image'),
        canvas: $('annotation-canvas'), frameRole: $('frame-role'), frameSize: $('frame-size'),
        annotationHelp: $('annotation-help'), palette: $('element-palette'),
        newElement: $('new-element'), addElement: $('add-element'),
        classSelect: $('defect-class'), noDefect: $('no-defect'),
        clearBox: $('clear-box'), save: $('save-annotation'), nextCamera: $('next-camera'),
        annotationMessage: $('annotation-message'), resultText: $('result-text'), resultYaml: $('result-yaml'),
    };

    let config = null;
    let state = null;
    let currentFrame = null;
    let annotations = [];
    let noDefectSelected = false;
    let drawing = false;
    let drawStart = null;
    let lastError = '';

    function setMessage(element, text, kind = '') {
        if (!element) return;
        element.textContent = text || '';
        element.className = element.className.replace(/\b(error|ok)\b/g, '').trim();
        if (kind) element.classList.add(kind);
    }

    async function api(path, options = {}) {
        const response = await fetch(path, {
            ...options,
            headers: {'Content-Type': 'application/json', ...(options.headers || {})},
        });
        let payload = null;
        try { payload = await response.json(); } catch (_) { payload = {}; }
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        return payload;
    }

    function selectedValues(container) {
        return [...container.querySelectorAll('input[type="checkbox"]:checked')].map((item) => item.value);
    }

    function fillSetup(data) {
        config = data;
        els.classes.value = data.defect_classes.join(', ');
        els.roles.replaceChildren();
        data.camera_roles.forEach((role) => {
            const label = document.createElement('label');
            label.className = 'check-item';
            label.innerHTML = `<input type="checkbox" value="${escapeHtml(role)}" checked><span>${escapeHtml(role)}</span>`;
            els.roles.appendChild(label);
        });
    }

    function fillClasses(names) {
        const selected = els.classSelect.value;
        els.classSelect.replaceChildren();
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Выберите элемент…';
        els.classSelect.appendChild(placeholder);
        (names || []).forEach((name) => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            els.classSelect.appendChild(option);
        });
        if ([...(names || [])].includes(selected)) els.classSelect.value = selected;
        renderPalette(names || []);
    }

    function renderPalette(names) {
        if (!els.palette) return;
        els.palette.replaceChildren();
        (names || []).forEach((name) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'palette-item';
            button.dataset.element = name;
            button.textContent = name;
            button.disabled = !currentFrame;
            button.addEventListener('click', () => selectElement(name));
            els.palette.appendChild(button);
        });
        updatePaletteSelection();
    }

    function selectElement(name) {
        els.classSelect.value = name || '';
        noDefectSelected = false;
        els.noDefect.classList.remove('selected');
        updatePaletteSelection();
        if (annotations.length) redrawBox();
    }

    function updatePaletteSelection() {
        if (!els.palette) return;
        [...els.palette.querySelectorAll('.palette-item')].forEach((button) => {
            button.classList.toggle(
                'active',
                button.dataset.element === els.classSelect.value,
            );
            button.disabled = !currentFrame;
        });
    }

    function escapeHtml(value) {
        return String(value).replace(/[&<>'"]/g, (char) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        }[char]));
    }

    function renderState(next) {
        state = next || state;
        if (!state) return;
        const session = state.session || {};
        const part = state.part;
        const expected = (state.camera_roles || []).length;
        const frameIds = part && Array.isArray(part.frame_ids) ? part.frame_ids : [];
        els.sessionTitle.textContent = session.session_id || '—';
        els.partsCount.textContent = session.part_count ?? 0;
        els.framesCount.textContent = session.frame_count ?? 0;
        els.sessionStatus.textContent = state.active ? (part ? 'СБОРКА' : 'ГОТОВА') : 'ЗАВЕРШЕНА';
        els.partNumber.textContent = part ? `#${part.part_id}` : '—';
        if (part) {
            els.partProgress.textContent = `${frameIds.length} из ${expected} камер снято · ${state.next_role ? `следующая: ${state.next_role}` : 'все камеры готовы'}`;
        } else {
            els.partProgress.textContent = state.active ? 'Начните новую деталь' : 'Сессия завершена';
        }
        const busy = Boolean(currentFrame) || Boolean(state.current_frame);
        els.newPart.disabled = !state.active || Boolean(part) || busy;
        els.finishPart.disabled = !state.active || !part || busy || frameIds.length !== expected;
        els.finishSession.disabled = !state.active || Boolean(part) || busy || Number(session.frame_count || 0) === 0;
        els.export.disabled = !state.active || Number(session.frame_count || 0) === 0;
        els.nextCamera.disabled = true;
        if (state.next_role && !currentFrame && part) {
            els.cameraTitle.textContent = `Готова камера ${state.next_role}`;
        }
        if (!currentFrame) {
            els.save.disabled = true;
            els.noDefect.disabled = true;
            els.clearBox.disabled = true;
            els.classSelect.disabled = true;
            els.newElement.disabled = !state.active;
            els.addElement.disabled = !state.active;
        }
        updatePaletteSelection();
    }

    function resetFrame() {
        currentFrame = null;
        annotations = [];
        noDefectSelected = false;
        drawing = false;
        drawStart = null;
        els.wrap.classList.add('empty');
        els.wrap.style.aspectRatio = '16 / 9';
        els.image.removeAttribute('src');
        const ctx = els.canvas.getContext('2d');
        ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);
        els.emptyState.classList.remove('hidden');
        els.frameId.textContent = 'FRAME —';
        els.frameRole.textContent = 'КАМЕРА —';
        els.frameSize.textContent = '— × —';
        els.cameraTitle.textContent = 'Ожидание детали';
        els.annotationHelp.textContent = 'Потяните мышью по дефекту, чтобы обвести область';
        els.classSelect.value = '';
        els.classSelect.disabled = true;
        els.noDefect.disabled = true;
        els.clearBox.disabled = true;
        els.save.disabled = true;
        els.nextCamera.disabled = true;
        els.newElement.disabled = !(state && state.active);
        els.addElement.disabled = !(state && state.active);
        els.canvas.style.pointerEvents = 'none';
        updatePaletteSelection();
    }

    function showFrame(frame, annotated = false) {
        currentFrame = frame;
        annotations = [];
        noDefectSelected = false;
        els.wrap.classList.remove('empty');
        els.emptyState.classList.add('hidden');
        els.image.onload = () => {
            const width = els.image.naturalWidth || frame.width;
            const height = els.image.naturalHeight || frame.height;
            els.canvas.width = width;
            els.canvas.height = height;
            els.wrap.style.aspectRatio = `${width} / ${height}`;
            redrawBox();
        };
        const url = (annotated && frame.annotated_url) ? frame.annotated_url : frame.original_url;
        els.image.src = `${url}${url.includes('?') ? '&' : '?'}v=${Date.now()}`;
        els.frameId.textContent = `FRAME #${frame.image_id}`;
        els.frameRole.textContent = frame.camera_role || frame.role || 'КАМЕРА —';
        els.frameSize.textContent = `${frame.width} × ${frame.height}`;
        els.cameraTitle.textContent = `${frame.camera_role || frame.role} · разметка`;
        els.annotationHelp.textContent = annotated ? 'Разметка сохранена. Можно переходить к следующей камере.' : 'Потяните мышью по дефекту, чтобы обвести область';
        els.canvas.style.pointerEvents = annotated ? 'none' : 'auto';
        els.classSelect.disabled = annotated;
        els.noDefect.disabled = annotated;
        els.clearBox.disabled = annotated;
        els.save.disabled = annotated;
        els.nextCamera.disabled = !annotated;
        els.newElement.disabled = annotated || !(state && state.active);
        els.addElement.disabled = annotated || !(state && state.active);
        els.canvas.getContext('2d').clearRect(0, 0, els.canvas.width, els.canvas.height);
        updatePaletteSelection();
    }

    function canvasPoint(event) {
        const rect = els.canvas.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(els.canvas.width, (event.clientX - rect.left) * els.canvas.width / rect.width)),
            y: Math.max(0, Math.min(els.canvas.height, (event.clientY - rect.top) * els.canvas.height / rect.height)),
        };
    }

    function redrawBox(preview = null) {
        const ctx = els.canvas.getContext('2d');
        ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);
        const boxes = annotations.slice();
        if (preview) boxes.push({
            ...preview,
            class_name: els.classSelect.value || 'элемент',
        });
        boxes.forEach((box, index) => {
            const x = Math.min(box.x, box.x + box.width);
            const y = Math.min(box.y, box.y + box.height);
            const width = Math.abs(box.width);
            const height = Math.abs(box.height);
            if (width < 1 || height < 1) return;
            const hue = (index * 67) % 360;
            ctx.fillStyle = `hsla(${hue}, 80%, 55%, .14)`;
            ctx.fillRect(x, y, width, height);
            ctx.strokeStyle = `hsl(${hue}, 80%, 62%)`;
            ctx.lineWidth = Math.max(2, els.canvas.width / 600);
            ctx.strokeRect(x, y, width, height);
            ctx.fillStyle = `hsl(${hue}, 80%, 70%)`;
            ctx.font = `${Math.max(14, els.canvas.width / 75)}px Segoe UI, Arial`;
            ctx.fillText(
                box.class_name || 'элемент',
                x + 5,
                Math.max(18, y - 7),
            );
        });
    }

    els.canvas.addEventListener('pointerdown', (event) => {
        if (!currentFrame || els.save.disabled || noDefectSelected) return;
        if (!els.classSelect.value) {
            setMessage(els.annotationMessage, 'Сначала выберите элемент в палитре.', 'error');
            return;
        }
        event.preventDefault();
        els.canvas.setPointerCapture(event.pointerId);
        drawing = true;
        drawStart = canvasPoint(event);
        redrawBox({x: drawStart.x, y: drawStart.y, width: 0, height: 0});
    });
    els.canvas.addEventListener('pointermove', (event) => {
        if (!drawing) return;
        event.preventDefault();
        const point = canvasPoint(event);
        redrawBox({x: drawStart.x, y: drawStart.y, width: point.x - drawStart.x, height: point.y - drawStart.y});
    });
    els.canvas.addEventListener('pointerup', (event) => {
        if (!drawing) return;
        drawing = false;
        const point = canvasPoint(event);
        const candidate = {x: drawStart.x, y: drawStart.y, width: point.x - drawStart.x, height: point.y - drawStart.y};
        if (Math.abs(candidate.width) >= 3 && Math.abs(candidate.height) >= 3) {
            annotations.push({
                ...candidate,
                class_name: els.classSelect.value,
            });
            noDefectSelected = false;
            els.noDefect.classList.remove('selected');
            redrawBox();
        } else {
            redrawBox();
        }
    });

    els.classSelect.addEventListener('change', () => {
        noDefectSelected = false;
        els.noDefect.classList.remove('selected');
        updatePaletteSelection();
        redrawBox();
    });
    els.noDefect.addEventListener('click', () => {
        noDefectSelected = true;
        annotations = [];
        els.classSelect.value = '';
        els.noDefect.classList.add('selected');
        updatePaletteSelection();
        redrawBox();
    });
    els.clearBox.addEventListener('click', () => {
        annotations = [];
        noDefectSelected = false;
        els.classSelect.value = '';
        els.noDefect.classList.remove('selected');
        updatePaletteSelection();
        redrawBox();
    });

    els.addElement.addEventListener('click', async () => {
        const name = els.newElement.value.trim();
        if (!name) {
            setMessage(els.annotationMessage, 'Введите название элемента палитры.', 'error');
            return;
        }
        els.addElement.disabled = true;
        try {
            const result = await api('/api/training/classes', {
                method: 'POST',
                body: JSON.stringify({class_name: name}),
            });
            fillClasses(result.defect_classes || []);
            selectElement(name);
            els.newElement.value = '';
            setMessage(els.annotationMessage, `Элемент «${name}» добавлен в палитру.`, 'ok');
        } catch (error) {
            setMessage(els.annotationMessage, error.message, 'error');
        } finally {
            els.addElement.disabled = !(state && state.active);
        }
    });

    els.newElement.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') els.addElement.click();
    });

    async function loadCapture() {
        clearMessages();
        try {
            const result = await api('/api/training/capture', {method: 'POST', body: '{}'});
            renderState(result.state);
            showFrame(result.frame, false);
            setMessage(els.annotationMessage, `Кадр #${result.frame.image_id} сохранён. Теперь выберите класс и обведите область.`, 'ok');
        } catch (error) {
            setMessage(els.annotationMessage, error.message, 'error');
        }
    }

    els.create.addEventListener('click', async () => {
        const roles = selectedValues(els.roles);
        const classes = els.classes.value.split(',').map((item) => item.trim()).filter(Boolean);
        if (!roles.length) { setMessage(els.setupMessage, 'Выберите хотя бы одну камеру.', 'error'); return; }
        if (!classes.length) { setMessage(els.setupMessage, 'Укажите хотя бы один класс дефекта.', 'error'); return; }
        els.create.disabled = true;
        try {
            const result = await api('/api/training/session', {
                method: 'POST', body: JSON.stringify({dataset_name: els.datasetName.value.trim() || 'defects', camera_roles: roles, defect_classes: classes}),
            });
            fillClasses(result.defect_classes || classes);
            renderState(result);
            els.setup.classList.add('hidden');
            els.work.classList.remove('hidden');
            setMessage(els.workflowMessage, 'Набор создан. Нажмите «Новая деталь», затем мастер покажет первую камеру.', 'ok');
        } catch (error) {
            setMessage(els.setupMessage, error.message, 'error');
            els.create.disabled = false;
        }
    });

    els.newPart.addEventListener('click', async () => {
        els.newPart.disabled = true;
        try {
            const result = await api('/api/training/parts', {method: 'POST', body: '{}'});
            renderState(result);
            setMessage(els.workflowMessage, `Деталь #${result.part.part_id} начата. Снимаем ${result.next_role}.`);
            await loadCapture();
        } catch (error) {
            setMessage(els.workflowMessage, error.message, 'error');
            renderState(state);
        }
    });

    els.save.addEventListener('click', async () => {
        if (!currentFrame) return;
        if (!noDefectSelected && !annotations.length) {
            setMessage(els.annotationMessage, 'Выберите элемент и обведите хотя бы одну область. Если дефекта нет — нажмите «Дефекта нет».', 'error');
            return;
        }
        els.save.disabled = true;
        const wasNoDefect = noDefectSelected;
        try {
            const payload = {
                image_id: currentFrame.image_id,
                boxes: wasNoDefect ? [] : annotations,
            };
            const result = await api('/api/training/annotations', {method: 'POST', body: JSON.stringify(payload)});
            renderState(result.state);
            showFrame(result.frame, true);
            setMessage(els.annotationMessage, wasNoDefect ? 'Кадр сохранён как отрицательный пример.' : 'Разметка сохранена: оригинал и изображение с областями записаны.', 'ok');
            setMessage(els.workflowMessage, result.state.next_role ? `Готово. Следующая камера: ${result.state.next_role}.` : 'Все камеры детали готовы. Завершите деталь.', 'ok');
        } catch (error) {
            els.save.disabled = false;
            setMessage(els.annotationMessage, error.message, 'error');
        }
    });

    els.nextCamera.addEventListener('click', async () => {
        resetFrame();
        if (state && state.next_role) await loadCapture();
        else renderState(state);
    });

    els.finishPart.addEventListener('click', async () => {
        try {
            const result = await api('/api/training/parts/finish', {method: 'POST', body: '{}'});
            resetFrame();
            renderState(result);
            setMessage(els.workflowMessage, `Деталь #${result.finished_part.part_id} сохранена. Можно начать следующую.`, 'ok');
        } catch (error) { setMessage(els.workflowMessage, error.message, 'error'); }
    });

    els.export.addEventListener('click', async () => {
        try {
            const result = await api('/api/training/export', {method: 'POST', body: '{}'});
            setMessage(els.workflowMessage, `YOLO-экспорт обновлён: train ${result.yolo.train_count}, val ${result.yolo.validation_count}.`, 'ok');
        } catch (error) { setMessage(els.workflowMessage, error.message, 'error'); }
    });

    els.finishSession.addEventListener('click', async () => {
        if (!confirm('Завершить набор и подготовить структуру YOLO?')) return;
        try {
            const result = await api('/api/training/session/finish', {method: 'POST', body: '{}'});
            els.work.classList.add('hidden');
            els.result.classList.remove('hidden');
            const yolo = result.yolo || {};
            els.resultText.textContent = `Изображения распределены по группам train (${yolo.train_count || 0}) и val (${yolo.validation_count || 0}). Пустые label-файлы сохранены для кадров без дефекта.`;
            els.resultYaml.textContent = yolo.yaml_path || 'dataset.yaml создан в папке партии';
        } catch (error) { setMessage(els.workflowMessage, error.message, 'error'); }
    });

    function clearMessages() {
        setMessage(els.annotationMessage, '');
    }

    async function init() {
        try {
            const data = await api('/api/training/config');
            fillSetup(data);
            const existing = await api('/api/training/state');
            els.connection.textContent = 'СЕРВЕР ГОТОВ';
            els.connection.classList.add('ok');
            resetFrame();
            // После обновления страницы не теряем текущий кадр: backend
            // держит состояние сессии в памяти до завершения мастера.
            if (existing && existing.active && existing.session) {
                fillClasses(existing.defect_classes || data.defect_classes);
                renderState(existing);
                els.setup.classList.add('hidden');
                els.work.classList.remove('hidden');
                if (existing.current_frame) {
                    showFrame(existing.current_frame, false);
                    setMessage(els.annotationMessage, 'Сессия восстановлена. Продолжите разметку текущего кадра.', 'ok');
                } else {
                    setMessage(els.workflowMessage, 'Сессия восстановлена. Можно продолжить текущую деталь или начать новую.', 'ok');
                }
            }
        } catch (error) {
            els.connection.textContent = 'ОШИБКА СОЕДИНЕНИЯ';
            els.connection.classList.add('error');
            lastError = error.message;
            setMessage(els.setupMessage, error.message, 'error');
        }
    }

    init();
})();
