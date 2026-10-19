(() => {
    'use strict';

    const $ = (id) => document.getElementById(id);
    const els = {
        connection: $('connection-state'), beltState: $('belt-state'),
        setup: $('setup-panel'), work: $('work-panel'),
        result: $('result-panel'), datasetName: $('dataset-name'), classes: $('defect-classes'),
        roles: $('camera-roles'), create: $('create-session'), setupMessage: $('setup-message'),
        sessionTitle: $('session-title'), sessionStatus: $('session-status'), partsCount: $('parts-count'),
        framesCount: $('frames-count'), partNumber: $('part-number'), partProgress: $('part-progress'),
        newPart: $('new-part'), nextPart: $('next-part'), finishPart: $('finish-part'),
        beltStep: $('belt-step'), export: $('export-dataset'),
        finishSession: $('finish-session'), newDataset: $('new-dataset'),
        workflowMessage: $('workflow-message'), cameraTitle: $('camera-title'),
        frameId: $('frame-id'), wrap: $('canvas-wrap'), emptyState: $('empty-state'), image: $('frame-image'),
        canvas: $('annotation-canvas'), frameRole: $('frame-role'), frameSize: $('frame-size'),
        annotationHelp: $('annotation-help'), palette: $('element-palette'),
        newElement: $('new-element'), addElement: $('add-element'),
        classSelect: $('defect-class'), finishPolygon: $('finish-polygon'),
        noDefect: $('no-defect'), clearBox: $('clear-box'),
        deleteRegion: $('delete-region'), reclassRegion: $('reclass-region'),
        save: $('save-annotation'),
        nextCamera: $('next-camera'), annotationMessage: $('annotation-message'),
        resultText: $('result-text'), resultYaml: $('result-yaml'),
        motionOverlay: $('motion-overlay'), motionTitle: $('motion-title'), motionText: $('motion-text'),
    };

    let config = null;
    let state = null;
    let currentFrame = null;
    let currentScreen = 'setup';
    let annotations = [];
    let draftPoints = [];
    let draftClass = '';
    let hoverPoint = null;
    let noDefectSelected = false;
    let selectedRegion = -1;
    let dragVertex = null;
    let lastError = '';

    // ------------------------------------------------------------------
    // Экраны мастера: настройка → разметка → готово.
    // ------------------------------------------------------------------

    const SCREENS = ['setup', 'work', 'result'];
    const SCREEN_PANELS = {setup: () => els.setup, work: () => els.work, result: () => els.result};

    function showScreen(name) {
        if (!SCREENS.includes(name)) return;
        currentScreen = name;
        SCREENS.forEach((key) => {
            const panel = SCREEN_PANELS[key]();
            if (!panel) return;
            panel.classList.toggle('hidden', key !== name);
            if (key === name) {
                panel.classList.remove('screen-enter');
                // Перезапуск анимации перехода между экранами.
                void panel.offsetWidth;
                panel.classList.add('screen-enter');
            }
        });
        document.querySelectorAll('.step-chip').forEach((chip) => {
            const index = SCREENS.indexOf(chip.dataset.screen);
            chip.classList.toggle('active', chip.dataset.screen === name);
            chip.classList.toggle('done', index >= 0 && index < SCREENS.indexOf(name));
        });
    }

    document.querySelectorAll('.step-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            const target = chip.dataset.screen;
            if (target === 'work' && !(state && state.active)) {
                setMessage(els.setupMessage, 'Сначала создайте набор на экране настройки.', 'error');
                return;
            }
            if (target === 'result' && !(state && !state.active && state.session)) {
                setMessage(els.workflowMessage, 'Экран «ГОТОВО» откроется после завершения набора.', 'error');
                return;
            }
            showScreen(target);
        });
    });

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
        return [...container.querySelectorAll('input[type="checkbox"]:checked')]
            .map((item) => item.value);
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
            button.disabled = !annotationEditable();
            button.addEventListener('click', () => selectElement(name));
            els.palette.appendChild(button);
        });
        updatePaletteSelection();
    }

    function annotationEditable() {
        return Boolean(currentFrame) && !els.save.disabled;
    }

    function selectElement(name) {
        if (draftPoints.length && name !== draftClass) {
            setMessage(els.annotationMessage, 'Сначала завершите текущую область.', 'error');
            return;
        }
        // Работа с выделенной областью: сменить её элемент без удаления.
        if (selectedRegion >= 0 && annotations[selectedRegion]) {
            annotations[selectedRegion].class_name = name;
            els.classSelect.value = name || '';
            updatePaletteSelection();
            redrawAnnotations();
            setMessage(els.annotationMessage, `Элемент выделенной области изменён на «${name}».`, 'ok');
            return;
        }
        els.classSelect.value = name || '';
        noDefectSelected = false;
        els.noDefect.classList.remove('selected');
        updatePaletteSelection();
        redrawAnnotations();
    }

    function updatePaletteSelection() {
        if (!els.palette) return;
        [...els.palette.querySelectorAll('.palette-item')].forEach((button) => {
            button.classList.toggle(
                'active',
                button.dataset.element === els.classSelect.value,
            );
            button.disabled = !annotationEditable();
        });
    }

    function updateSelectionButtons() {
        const hasSelection = selectedRegion >= 0 && annotationEditable();
        if (els.deleteRegion) els.deleteRegion.disabled = !hasSelection;
        if (els.reclassRegion) els.reclassRegion.disabled = !hasSelection;
    }

    function escapeHtml(value) {
        return String(value).replace(/[&<>'"]/g, (char) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        }[char]));
    }

    function renderBelt(belt) {
        if (!els.beltState) return;
        const info = belt || (state && state.belt) || null;
        if (!info) {
            els.beltState.textContent = 'ЛЕНТА: —';
            els.beltState.className = 'belt-state';
            return;
        }
        if (info.available) {
            els.beltState.textContent = `ЛЕНТА: ГОТОВА · ШАГ ${info.steps ?? 0}`;
            els.beltState.className = 'belt-state ok';
        } else {
            els.beltState.textContent = 'ЛЕНТА: НЕ ПОДКЛЮЧЕНА';
            els.beltState.className = 'belt-state off';
        }
    }

    function showMotion(visible, title, text) {
        if (!els.motionOverlay) return;
        els.motionOverlay.classList.toggle('hidden', !visible);
        if (title && els.motionTitle) els.motionTitle.textContent = title;
        if (text && els.motionText) els.motionText.textContent = text;
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
        const allCaptured = Boolean(part) && frameIds.length === expected;
        els.newPart.disabled = !state.active || Boolean(part) || busy;
        // «ДАЛЕЕ»: завершить деталь, сдвинуть ленту, открыть следующую.
        els.nextPart.disabled = !state.active || busy || (Boolean(part) && !allCaptured);
        els.finishPart.disabled = !state.active || !part || busy || frameIds.length !== expected;
        els.finishSession.disabled = !state.active || Boolean(part) || busy || Number(session.frame_count || 0) === 0;
        els.export.disabled = !state.active || Number(session.frame_count || 0) === 0;
        // Ручной шаг ленты — только когда деталь не открыта (иначе собьётся кадр).
        els.beltStep.disabled = busy || Boolean(part);
        // «Следующая камера»/«Снять кадр»: продолжение после ГОТОВО или
        // повторная съёмка, если получить кадр сразу не удалось.
        const viewingAnnotated = Boolean(currentFrame) && els.save.disabled;
        els.nextCamera.disabled = viewingAnnotated
            ? false
            : !(state.active && Boolean(part) && Boolean(state.next_role) && !busy);
        els.nextCamera.textContent = currentFrame ? 'СЛЕДУЮЩАЯ КАМЕРА' : 'СНЯТЬ КАДР';
        renderBelt(state.belt);
        if (state.next_role && !currentFrame && part) {
            els.cameraTitle.textContent = `Готова камера ${state.next_role}`;
        }
        if (!currentFrame) {
            els.save.disabled = true;
            els.finishPolygon.disabled = true;
            els.noDefect.disabled = true;
            els.clearBox.disabled = true;
            els.classSelect.disabled = true;
            els.newElement.disabled = !state.active;
            els.addElement.disabled = !state.active;
            selectedRegion = -1;
            dragVertex = null;
            updateSelectionButtons();
        }
        updatePaletteSelection();
    }

    function resetFrame() {
        currentFrame = null;
        annotations = [];
        draftPoints = [];
        draftClass = '';
        hoverPoint = null;
        noDefectSelected = false;
        selectedRegion = -1;
        dragVertex = null;
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
        els.annotationHelp.textContent = 'Кликайте точки контура, затем нажмите «Завершить область»';
        els.classSelect.value = '';
        els.classSelect.disabled = true;
        els.finishPolygon.disabled = true;
        els.noDefect.disabled = true;
        els.clearBox.disabled = true;
        els.save.disabled = true;
        els.nextCamera.disabled = true;
        els.newElement.disabled = !(state && state.active);
        els.addElement.disabled = !(state && state.active);
        els.canvas.style.pointerEvents = 'none';
        updateSelectionButtons();
        updatePaletteSelection();
    }

    function showFrame(frame, annotated = false) {
        currentFrame = frame;
        annotations = [];
        draftPoints = [];
        draftClass = '';
        hoverPoint = null;
        noDefectSelected = false;
        selectedRegion = -1;
        dragVertex = null;
        els.wrap.classList.remove('empty');
        els.emptyState.classList.add('hidden');
        els.image.onload = () => {
            const width = els.image.naturalWidth || frame.width;
            const height = els.image.naturalHeight || frame.height;
            els.canvas.width = width;
            els.canvas.height = height;
            els.wrap.style.aspectRatio = `${width} / ${height}`;
            redrawAnnotations();
        };
        const url = (annotated && frame.annotated_url) ? frame.annotated_url : frame.original_url;
        els.image.src = `${url}${url.includes('?') ? '&' : '?'}v=${Date.now()}`;
        els.frameId.textContent = `FRAME #${frame.image_id}`;
        els.frameRole.textContent = frame.camera_role || frame.role || 'КАМЕРА —';
        els.frameSize.textContent = `${frame.width} × ${frame.height}`;
        els.cameraTitle.textContent = `${frame.camera_role || frame.role} · разметка`;
        els.annotationHelp.textContent = annotated
            ? 'Разметка сохранена. Можно переходить к следующей камере.'
            : 'Кликайте точки контура, затем нажмите «Завершить область»';
        els.canvas.style.pointerEvents = annotated ? 'none' : 'auto';
        els.classSelect.disabled = annotated;
        els.finishPolygon.disabled = annotated;
        els.noDefect.disabled = annotated;
        els.clearBox.disabled = annotated;
        els.save.disabled = annotated;
        els.nextCamera.disabled = !annotated;
        els.newElement.disabled = annotated || !(state && state.active);
        els.addElement.disabled = annotated || !(state && state.active);
        els.canvas.getContext('2d').clearRect(0, 0, els.canvas.width, els.canvas.height);
        els.nextCamera.textContent = 'СЛЕДУЮЩАЯ КАМЕРА';
        updateSelectionButtons();
        updatePaletteSelection();
    }

    function canvasPoint(event) {
        const rect = els.canvas.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(els.canvas.width, (event.clientX - rect.left) * els.canvas.width / rect.width)),
            y: Math.max(0, Math.min(els.canvas.height, (event.clientY - rect.top) * els.canvas.height / rect.height)),
        };
    }

    function distance(left, right) {
        return Math.hypot(left.x - right.x, left.y - right.y);
    }

    function distanceToSegment(point, start, end) {
        const dx = end.x - start.x;
        const dy = end.y - start.y;
        const lengthSquared = dx * dx + dy * dy;
        if (!lengthSquared) return distance(point, start);
        let t = ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared;
        t = Math.max(0, Math.min(1, t));
        return distance(point, {x: start.x + t * dx, y: start.y + t * dy});
    }

    function pointInPolygon(point, points) {
        let inside = false;
        for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
            const a = points[i];
            const b = points[j];
            const intersects = ((a.y > point.y) !== (b.y > point.y))
                && (point.x < (b.x - a.x) * (point.y - a.y) / ((b.y - a.y) || 1e-9) + a.x);
            if (intersects) inside = !inside;
        }
        return inside;
    }

    function hitTestVertex(point, points) {
        const radius = Math.max(10, els.canvas.width / 90);
        for (let index = points.length - 1; index >= 0; index -= 1) {
            if (distance(point, points[index]) <= radius) return index;
        }
        return -1;
    }

    function hitTestRegion(point) {
        const edgeTolerance = Math.max(6, els.canvas.width / 160);
        for (let index = annotations.length - 1; index >= 0; index -= 1) {
            const points = annotations[index].points;
            if (pointInPolygon(point, points)) return index;
            for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
                if (distanceToSegment(point, points[j], points[i]) <= edgeTolerance) return index;
            }
        }
        return -1;
    }

    function selectRegion(index) {
        selectedRegion = (index >= 0 && index < annotations.length) ? index : -1;
        if (selectedRegion >= 0) {
            const annotation = annotations[selectedRegion];
            if (annotation.class_name) els.classSelect.value = annotation.class_name;
            noDefectSelected = false;
            els.noDefect.classList.remove('selected');
            setMessage(
                els.annotationMessage,
                `Область «${annotation.class_name}» выделена: вершины можно тащить, элемент — менять, удалить — только её.`,
                'ok',
            );
        }
        updateSelectionButtons();
        updatePaletteSelection();
        redrawAnnotations();
    }

    function drawPolygon(ctx, points, className, index, draft = false, selected = false) {
        if (!points.length) return;
        const hue = (index * 67) % 360;
        ctx.strokeStyle = selected ? '#ffffff' : `hsl(${hue}, 80%, 62%)`;
        ctx.fillStyle = `hsla(${hue}, 80%, 55%, ${draft ? '.08' : selected ? '.22' : '.14'})`;
        ctx.lineWidth = Math.max(selected ? 4 : 2, els.canvas.width / (selected ? 380 : 600));
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        points.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
        if (!draft && points.length >= 3) {
            ctx.closePath();
            ctx.fill();
        }
        ctx.stroke();
        const vertexRadius = Math.max(selected ? 6 : 4, els.canvas.width / (selected ? 130 : 180));
        points.forEach((point) => {
            ctx.beginPath();
            ctx.fillStyle = selected ? '#ffffff' : `hsl(${hue}, 80%, 70%)`;
            ctx.arc(point.x, point.y, vertexRadius, 0, Math.PI * 2);
            ctx.fill();
            if (selected) {
                ctx.beginPath();
                ctx.strokeStyle = `hsl(${hue}, 80%, 62%)`;
                ctx.lineWidth = Math.max(2, els.canvas.width / 600);
                ctx.arc(point.x, point.y, vertexRadius, 0, Math.PI * 2);
                ctx.stroke();
            }
        });
        if (className) {
            ctx.fillStyle = selected ? '#ffffff' : `hsl(${hue}, 80%, 70%)`;
            ctx.font = `${Math.max(14, els.canvas.width / 75)}px Segoe UI, Arial`;
            const label = selected ? `${className} · выделена` : className;
            ctx.fillText(label, points[0].x + 6, Math.max(18, points[0].y - 8));
        }
    }

    function redrawAnnotations() {
        const ctx = els.canvas.getContext('2d');
        ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);
        annotations.forEach((annotation, index) => {
            drawPolygon(
                ctx,
                annotation.points,
                annotation.class_name,
                index,
                false,
                index === selectedRegion,
            );
        });
        if (draftPoints.length) {
            const preview = draftPoints.slice();
            if (hoverPoint) preview.push(hoverPoint);
            drawPolygon(ctx, preview, draftClass || els.classSelect.value, annotations.length, true);
        }
        els.finishPolygon.disabled = !annotationEditable() || draftPoints.length < 3;
    }

    function finishCurrentPolygon() {
        if (!draftPoints.length) {
            setMessage(els.annotationMessage, 'Сначала поставьте точки контура.', 'error');
            return false;
        }
        if (draftPoints.length < 3) {
            setMessage(els.annotationMessage, 'Для области нужно минимум три точки.', 'error');
            return false;
        }
        annotations.push({
            class_name: draftClass || els.classSelect.value,
            points: draftPoints.map((point) => ({x: point.x, y: point.y})),
        });
        draftPoints = [];
        draftClass = '';
        hoverPoint = null;
        selectedRegion = -1;
        updateSelectionButtons();
        redrawAnnotations();
        setMessage(els.annotationMessage, 'Область добавлена. Можно выбрать другой элемент.', 'ok');
        return true;
    }

    els.canvas.addEventListener('pointerdown', (event) => {
        if (!annotationEditable() || noDefectSelected) return;
        event.preventDefault();
        const point = canvasPoint(event);

        // 1) Тянуть вершину уже выделенной области (правка без перерисовки).
        if (!draftPoints.length && selectedRegion >= 0 && annotations[selectedRegion]) {
            const vertexIndex = hitTestVertex(point, annotations[selectedRegion].points);
            if (vertexIndex >= 0) {
                dragVertex = {regionIndex: selectedRegion, pointIndex: vertexIndex};
                try { els.canvas.setPointerCapture(event.pointerId); } catch (_) { /* noop */ }
                return;
            }
        }

        // 2) Продолжение текущего черновика контура.
        if (draftPoints.length) {
            const closeDistance = Math.max(8, els.canvas.width / 100);
            if (draftPoints.length >= 3 && distance(point, draftPoints[0]) <= closeDistance) {
                finishCurrentPolygon();
                return;
            }
            draftPoints.push(point);
            hoverPoint = null;
            redrawAnnotations();
            return;
        }

        // 3) Клик по существующей области — выделить только её.
        const regionIndex = hitTestRegion(point);
        if (regionIndex >= 0) {
            selectRegion(regionIndex);
            return;
        }

        // 4) Пустое место: снять выделение, не затирая области.
        if (selectedRegion >= 0) {
            selectRegion(-1);
            return;
        }

        // 5) Новый контур.
        if (!els.classSelect.value) {
            setMessage(els.annotationMessage, 'Сначала выберите элемент в палитре.', 'error');
            return;
        }
        if (!draftPoints.length) draftClass = els.classSelect.value;
        draftPoints.push(point);
        hoverPoint = null;
        redrawAnnotations();
    });

    els.canvas.addEventListener('pointermove', (event) => {
        if (dragVertex) {
            const point = canvasPoint(event);
            const target = annotations[dragVertex.regionIndex];
            if (target) {
                target.points[dragVertex.pointIndex] = point;
                redrawAnnotations();
            }
            return;
        }
        if (!draftPoints.length || !annotationEditable()) return;
        hoverPoint = canvasPoint(event);
        redrawAnnotations();
    });

    els.canvas.addEventListener('pointerup', (event) => {
        if (!dragVertex) return;
        dragVertex = null;
        try { els.canvas.releasePointerCapture(event.pointerId); } catch (_) { /* noop */ }
        redrawAnnotations();
        setMessage(els.annotationMessage, 'Вершина области обновлена. Остальные области не тронуты.', 'ok');
    });

    els.canvas.addEventListener('pointerleave', () => {
        if (!hoverPoint) return;
        hoverPoint = null;
        redrawAnnotations();
    });

    els.canvas.addEventListener('dblclick', (event) => {
        event.preventDefault();
        if (!draftPoints.length) return;
        finishCurrentPolygon();
    });

    els.finishPolygon.addEventListener('click', finishCurrentPolygon);

    els.classSelect.addEventListener('change', () => {
        if (draftPoints.length && els.classSelect.value !== draftClass) {
            els.classSelect.value = draftClass;
            setMessage(els.annotationMessage, 'Сначала завершите текущую область.', 'error');
            return;
        }
        // Смена элемента выделенной области без её удаления.
        if (selectedRegion >= 0 && annotations[selectedRegion] && els.classSelect.value) {
            annotations[selectedRegion].class_name = els.classSelect.value;
            redrawAnnotations();
            setMessage(els.annotationMessage, `Элемент выделенной области изменён на «${els.classSelect.value}».`, 'ok');
            return;
        }
        noDefectSelected = false;
        els.noDefect.classList.remove('selected');
        updatePaletteSelection();
        redrawAnnotations();
    });

    els.reclassRegion.addEventListener('click', () => {
        if (selectedRegion < 0 || !annotations[selectedRegion]) return;
        const name = els.classSelect.value;
        if (!name) {
            setMessage(els.annotationMessage, 'Сначала выберите элемент в палитре.', 'error');
            return;
        }
        annotations[selectedRegion].class_name = name;
        redrawAnnotations();
        setMessage(els.annotationMessage, `Элемент области изменён на «${name}». Область сохранена.`, 'ok');
    });

    els.deleteRegion.addEventListener('click', () => {
        if (selectedRegion < 0 || !annotations[selectedRegion]) return;
        const removed = annotations.splice(selectedRegion, 1)[0];
        selectedRegion = -1;
        updateSelectionButtons();
        redrawAnnotations();
        setMessage(els.annotationMessage, `Область «${removed.class_name}» удалена. Остальные области сохранены.`, 'ok');
    });

    els.noDefect.addEventListener('click', () => {
        draftPoints = [];
        draftClass = '';
        hoverPoint = null;
        annotations = [];
        selectedRegion = -1;
        dragVertex = null;
        noDefectSelected = true;
        els.classSelect.value = '';
        els.noDefect.classList.add('selected');
        updateSelectionButtons();
        updatePaletteSelection();
        redrawAnnotations();
    });

    els.clearBox.addEventListener('click', () => {
        // Сначала убираем только незавершённый контур — сохранённые области целы.
        if (draftPoints.length) {
            draftPoints = [];
            draftClass = '';
            hoverPoint = null;
            redrawAnnotations();
            setMessage(els.annotationMessage, 'Незавершённый контур очищен. Сохранённые области не тронуты.', 'ok');
            return;
        }
        if (annotations.length && !confirm('Удалить все области этого кадра? Выделенную область можно удалить отдельно кнопкой «УДАЛИТЬ ВЫБРАННУЮ».')) {
            return;
        }
        annotations = [];
        selectedRegion = -1;
        dragVertex = null;
        noDefectSelected = false;
        els.classSelect.value = '';
        els.noDefect.classList.remove('selected');
        updateSelectionButtons();
        updatePaletteSelection();
        redrawAnnotations();
        setMessage(els.annotationMessage, 'Все области кадра удалены.', 'ok');
    });

    document.addEventListener('keydown', (event) => {
        if (currentScreen !== 'work' || !annotationEditable()) return;
        const tag = (event.target && event.target.tagName) || '';
        if (['INPUT', 'SELECT', 'TEXTAREA'].includes(tag)) return;
        if (event.key === 'Escape') {
            if (draftPoints.length) {
                draftPoints = [];
                draftClass = '';
                hoverPoint = null;
                redrawAnnotations();
                setMessage(els.annotationMessage, 'Незавершённый контур отменён.', 'ok');
            } else if (selectedRegion >= 0) {
                selectRegion(-1);
            }
            return;
        }
        if (event.key === 'Delete' && selectedRegion >= 0 && annotations[selectedRegion]) {
            els.deleteRegion.click();
        }
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
                method: 'POST', body: JSON.stringify({class_name: name}),
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
            setMessage(els.annotationMessage, `Кадр #${result.frame.image_id} сохранён. Выберите элемент и поставьте точки контура.`, 'ok');
        } catch (error) {
            setMessage(els.annotationMessage, error.message, 'error');
        }
    }

    els.create.addEventListener('click', async () => {
        const roles = selectedValues(els.roles);
        const classes = els.classes.value.split(',').map((item) => item.trim()).filter(Boolean);
        if (!roles.length) { setMessage(els.setupMessage, 'Выберите хотя бы одну камеру.', 'error'); return; }
        if (!classes.length) { setMessage(els.setupMessage, 'Укажите хотя бы один элемент палитры.', 'error'); return; }
        els.create.disabled = true;
        try {
            const result = await api('/api/training/session', {
                method: 'POST',
                body: JSON.stringify({
                    dataset_name: els.datasetName.value.trim() || 'defects',
                    camera_roles: roles,
                    defect_classes: classes,
                }),
            });
            fillClasses(result.defect_classes || classes);
            renderState(result);
            showScreen('work');
            setMessage(els.workflowMessage, 'Набор создан. Нажмите «НОВАЯ ДЕТАЛЬ» — мастер покажет первую камеру.', 'ok');
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

    // «ДАЛЕЕ»: камеры детали кончились → шаг ленты → новая деталь → новые кадры.
    els.nextPart.addEventListener('click', async () => {
        if (draftPoints.length) {
            setMessage(els.annotationMessage, 'Сначала нажмите «Завершить область».', 'error');
            return;
        }
        if (currentFrame && !els.save.disabled) {
            setMessage(els.annotationMessage, 'Сначала сохраните разметку кнопкой «ГОТОВО».', 'error');
            return;
        }
        els.nextPart.disabled = true;
        showMotion(true, 'ЛЕНТА ДВИЖЕТСЯ…', 'Шаг конвейера, ожидание новой детали');
        try {
            const result = await api('/api/training/parts/next', {method: 'POST', body: '{}'});
            showMotion(false);
            const belt = result.belt || {};
            const finished = result.finished_part;
            resetFrame();
            renderState(result);
            if (result.frame) {
                showFrame(result.frame, false);
            }
            const stepNote = belt.moved
                ? `лента сдвинута на шаг #${belt.steps}`
                : (belt.message || 'шаг ленты пропущен');
            setMessage(
                els.workflowMessage,
                finished
                    ? `Деталь #${finished.part_id} сохранена, ${stepNote}. Новая деталь #${result.part ? result.part.part_id : '?'} — размечайте ${result.next_role || ''}.`
                    : `${stepNote}. Деталь #${result.part ? result.part.part_id : '?'} — размечайте ${result.next_role || ''}.`,
                'ok',
            );
            setMessage(els.annotationMessage, `Кадр #${result.frame ? result.frame.image_id : '—'} снят. Обведите дефекты.`, 'ok');
        } catch (error) {
            showMotion(false);
            setMessage(els.workflowMessage, error.message, 'error');
            await refreshState();
        }
    });

    // Ручной шаг ленты: подготовить позицию перед первой деталью.
    els.beltStep.addEventListener('click', async () => {
        els.beltStep.disabled = true;
        showMotion(true, 'ЛЕНТА ДВИЖЕТСЯ…', 'Один шаг конвейера вручную');
        try {
            const result = await api('/api/training/belt/step', {method: 'POST', body: '{}'});
            renderState(result.state);
            setMessage(els.workflowMessage, result.belt.message || 'Лента сдвинута на шаг.', result.belt.moved ? 'ok' : 'error');
        } catch (error) {
            setMessage(els.workflowMessage, error.message, 'error');
        } finally {
            showMotion(false);
            await refreshState();
        }
    });

    els.save.addEventListener('click', async () => {
        if (!currentFrame) return;
        if (draftPoints.length) {
            setMessage(els.annotationMessage, 'Сначала нажмите «Завершить область».', 'error');
            return;
        }
        if (!noDefectSelected && !annotations.length) {
            setMessage(els.annotationMessage, 'Выберите элемент и обведите область. Если дефекта нет — нажмите «Дефекта нет».', 'error');
            return;
        }
        els.save.disabled = true;
        const wasNoDefect = noDefectSelected;
        try {
            const result = await api('/api/training/annotations', {
                method: 'POST',
                body: JSON.stringify({
                    image_id: currentFrame.image_id,
                    annotations: wasNoDefect ? [] : annotations,
                }),
            });
            renderState(result.state);
            showFrame(result.frame, true);
            setMessage(els.annotationMessage, wasNoDefect
                ? 'Кадр сохранён как отрицательный пример.'
                : 'Готово: оригинал и изображение с polygon-областями записаны.', 'ok');
            setMessage(els.workflowMessage, result.state.next_role
                ? `Готово. Следующая камера: ${result.state.next_role}.`
                : 'Все камеры детали готовы. Нажмите «ДАЛЕЕ» — лента сдвинется на шаг.', 'ok');
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
            setMessage(els.workflowMessage, `Деталь #${result.finished_part.part_id} сохранена. Нажмите «ДАЛЕЕ» — лента сдвинется на шаг и откроется следующая деталь.`, 'ok');
        } catch (error) { setMessage(els.workflowMessage, error.message, 'error'); }
    });

    els.export.addEventListener('click', async () => {
        try {
            const result = await api('/api/training/export', {method: 'POST', body: '{}'});
            setMessage(els.workflowMessage, `YOLO-${result.yolo.task || 'segment'}-экспорт обновлён: train ${result.yolo.train_count}, val ${result.yolo.validation_count}.`, 'ok');
        } catch (error) { setMessage(els.workflowMessage, error.message, 'error'); }
    });

    els.finishSession.addEventListener('click', async () => {
        if (!confirm('Завершить набор и подготовить структуру YOLO segmentation?')) return;
        try {
            const result = await api('/api/training/session/finish', {method: 'POST', body: '{}'});
            showScreen('result');
            const yolo = result.yolo || {};
            els.resultText.textContent = `Полигоны экспортированы: train (${yolo.train_count || 0}), val (${yolo.validation_count || 0}). Пустые label-файлы сохранены для кадров без дефекта.`;
            els.resultYaml.textContent = yolo.yaml_path || 'dataset.yaml создан в папке партии';
        } catch (error) { setMessage(els.workflowMessage, error.message, 'error'); }
    });

    els.newDataset.addEventListener('click', () => {
        els.create.disabled = false;
        setMessage(els.setupMessage, '');
        setMessage(els.workflowMessage, '');
        showScreen('setup');
    });

    function clearMessages() {
        setMessage(els.annotationMessage, '');
    }

    async function refreshState() {
        try {
            const fresh = await api('/api/training/state');
            renderState(fresh);
        } catch (_) { /* состояние обновится при следующем действии */ }
    }

    async function init() {
        try {
            const data = await api('/api/training/config');
            fillSetup(data);
            const existing = await api('/api/training/state');
            els.connection.textContent = 'СЕРВЕР ГОТОВ';
            els.connection.classList.add('ok');
            resetFrame();
            if (existing && existing.active && existing.session) {
                fillClasses(existing.defect_classes || data.defect_classes);
                renderState(existing);
                showScreen('work');
                if (existing.current_frame) {
                    showFrame(existing.current_frame, false);
                    setMessage(els.annotationMessage, 'Сессия восстановлена. Продолжите обводку точками.', 'ok');
                } else {
                    setMessage(els.workflowMessage, 'Сессия восстановлена. Можно продолжить текущую деталь или начать новую.', 'ok');
                }
            } else {
                renderState(existing);
                showScreen('setup');
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
