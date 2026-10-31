/* belt_editor/js/tool-lab.js — Лаборатория инструментов (стенд симуляции и замера фигур) */
'use strict';

(function () {
    const labState = {
        open: false,
        fig: 'window',
        topH: 30,
        botH: 28,
        w: 72,
        cutsV: 3,
        cutsH: 1,
        topMin: 15,
        topMax: 45,
        bottomMin: 15,
        bottomMax: 45,
        wMin: 50,
        wMax: 100
    };

    function $id(id) { return document.getElementById(id); }

    function drawGrid(ctx, w, h) {
        ctx.fillStyle = '#0f1418';
        ctx.fillRect(0, 0, w, h);
        ctx.strokeStyle = 'rgba(120, 153, 165, 0.08)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let x = 0; x <= w; x += 16) { ctx.moveTo(x, 0); ctx.lineTo(x, h); }
        for (let y = 0; y <= h; y += 16) { ctx.moveTo(0, y); ctx.lineTo(w, y); }
        ctx.stroke();
    }

    function drawSimulatedFigure(ctx, bx, by, bw, bh, midY) {
        ctx.fillStyle = '#222b32';
        ctx.fillRect(bx - 20, by - 16, bw + 40, bh + 32);
        ctx.fillStyle = '#0c1216';
        ctx.fillRect(bx, by, bw, bh);
        ctx.fillStyle = '#394853';
        ctx.fillRect(bx, midY - 4, bw, 8);
        ctx.strokeStyle = '#4fa3d1';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(bx, by, bw, bh);
    }

    function drawMeasurementArrow(ctx, vx, y1, y2, ok, label) {
        ctx.strokeStyle = ctx.fillStyle = ok ? '#7ac48c' : '#ef4444';
        ctx.lineWidth = 2.0;
        ctx.beginPath(); ctx.moveTo(vx, y1); ctx.lineTo(vx, y2); ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(vx - 3, y1 + 5); ctx.lineTo(vx, y1); ctx.lineTo(vx + 3, y1 + 5);
        ctx.moveTo(vx - 3, y2 - 5); ctx.lineTo(vx, y2); ctx.lineTo(vx + 3, y2 - 5);
        ctx.stroke();

        ctx.font = 'bold 12px monospace';
        const tw = ctx.measureText(label).width, ym = Math.round((y1 + y2) / 2);
        ctx.fillStyle = 'rgba(8, 12, 16, 0.9)';
        ctx.fillRect(vx + 4, ym - 8, tw + 8, 16);
        ctx.fillStyle = ok ? '#7ac48c' : '#ef4444';
        ctx.fillText(label, vx + 8, ym + 4);
    }

    function drawHorizMeasurementArrow(ctx, y, x1, x2, ok, label) {
        ctx.strokeStyle = ctx.fillStyle = ok ? '#7ac48c' : '#ef4444';
        ctx.lineWidth = 2.0;
        ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x1 + 5, y - 3); ctx.lineTo(x1, y); ctx.lineTo(x1 + 5, y + 3);
        ctx.moveTo(x2 - 5, y - 3); ctx.lineTo(x2, y); ctx.lineTo(x2 - 5, y + 3);
        ctx.stroke();

        ctx.font = 'bold 12px monospace';
        const tw = ctx.measureText(label).width, xm = Math.round((x1 + x2) / 2);
        ctx.fillStyle = 'rgba(8, 12, 16, 0.9)';
        ctx.fillRect(xm - Math.round(tw / 2) - 4, y - 8, tw + 8, 16);
        ctx.fillStyle = ok ? '#7ac48c' : '#ef4444';
        ctx.fillText(label, xm - Math.round(tw / 2), y + 4);
    }

    function drawLabCutsAndMeasurements(ctx, bx, by, bw, bh, midY) {
        ctx.lineWidth = 2.0; ctx.strokeStyle = '#d9a441';
        ctx.strokeRect(bx, by, bw, bh);

        const hMeasurements = [], hStep = bh / (labState.cutsH + 1);
        for (let h = 1; h <= labState.cutsH; h++) {
            const hy = Math.round(by + h * hStep);
            ctx.setLineDash([4, 3]); ctx.strokeStyle = 'rgba(217, 164, 65, 0.8)';
            ctx.beginPath(); ctx.moveTo(bx - 14, hy); ctx.lineTo(bx + bw + 14, hy); ctx.stroke();
            ctx.setLineDash([]);

            const wVal = labState.w;
            const wOk = wVal >= labState.wMin && wVal <= labState.wMax;
            hMeasurements.push({ h, hy, wVal, wOk });
            drawHorizMeasurementArrow(ctx, hy, bx, bx + bw, wOk, `W${h}: ${wVal}px`);
        }

        const vMeasurements = [], vStep = bw / (labState.cutsV + 1);
        for (let v = 1; v <= labState.cutsV; v++) {
            const vx = Math.round(bx + v * vStep);
            ctx.setLineDash([3, 2]); ctx.strokeStyle = 'rgba(243, 202, 108, 0.5)';
            ctx.beginPath(); ctx.moveTo(vx, by - 8); ctx.lineTo(vx, by + bh + 8); ctx.stroke();
            ctx.setLineDash([]);

            const tVal = labState.topH, bVal = labState.botH;
            const tOk = tVal >= labState.topMin && tVal <= labState.topMax;
            const bOk = bVal >= labState.bottomMin && bVal <= labState.bottomMax;
            vMeasurements.push({ v, vx, tVal, bVal, tOk, bOk });

            drawMeasurementArrow(ctx, vx, by, midY, tOk, `T${v}: ${tVal}px`);
            drawMeasurementArrow(ctx, vx, midY, by + bh, bOk, `B${v}: ${bVal}px`);
        }

        ctx.font = 'bold 12px monospace'; ctx.fillStyle = '#f3ca6c';
        const sumText = `BBox: ${labState.w}×${labState.topH + labState.botH} px (масштаб 2.4×) | Срезов: ${labState.cutsV}V × ${labState.cutsH}H`;
        ctx.fillText(sumText, bx, by + bh + 24);
        return { vMeasurements, hMeasurements };
    }

    function renderLabReport(report) {
        const verdEl = $id('lab-verdict'), detEl = $id('lab-details');
        if (!verdEl || !detEl) return;
        const vList = report.vMeasurements || [], hList = report.hMeasurements || [];
        const allOk = vList.every(m => m.tOk && m.bOk) && hList.every(m => m.wOk);

        verdEl.className = 'lab-verdict ' + (allOk ? 'pass' : 'fail');
        verdEl.textContent = allOk ? '✓ ГОДНАЯ (ОК): ВСЕ ЗАМЕРЫ В ДОПУСКЕ' : '✗ БРАК: ОБНАРУЖЕН ВЫЛЕТ РАЗМЕРА';

        detEl.innerHTML = '';
        vList.forEach(m => {
            const row = document.createElement('div');
            row.className = 'lab-report-row ' + (m.tOk && m.bOk ? 'ok' : 'fail');
            row.innerHTML = `<span>Верт. срез V${m.v}:</span> ` +
                `<b style="color:${m.tOk ? '#7ac48c' : '#ef4444'}">T = ${m.tVal} px ${m.tOk ? '✓' : '✗'}</b> ` +
                `<b style="color:${m.bOk ? '#7ac48c' : '#ef4444'}">B = ${m.bVal} px ${m.bOk ? '✓' : '✗'}</b>`;
            detEl.appendChild(row);
        });

        hList.forEach(m => {
            const row = document.createElement('div');
            row.className = 'lab-report-row ' + (m.wOk ? 'ok' : 'fail');
            row.innerHTML = `<span>Гор. срез H${m.h}:</span> ` +
                `<b style="color:${m.wOk ? '#7ac48c' : '#ef4444'}">Ширина W = ${m.wVal} px (норма ${labState.wMin}–${labState.wMax}) ${m.wOk ? '✓' : '✗'}</b>`;
            detEl.appendChild(row);
        });
    }

    function computeFallbackMeasurements() {
        const vList = [], tVal = labState.topH, bVal = labState.botH;
        for (let v = 1; v <= labState.cutsV; v++) {
            const tOk = tVal >= labState.topMin && tVal <= labState.topMax;
            const bOk = bVal >= labState.bottomMin && bVal <= labState.bottomMax;
            vList.push({ v, tVal, bVal, tOk, bOk });
        }
        const hList = [], wVal = labState.w;
        for (let h = 1; h <= labState.cutsH; h++) {
            const wOk = wVal >= labState.wMin && wVal <= labState.wMax;
            hList.push({ h, wVal, wOk });
        }
        return { vMeasurements: vList, hMeasurements: hList };
    }

    function paintLabCanvas() {
        const cv = $id('lab-canvas');
        if (!cv || !cv.getContext) { renderLabReport(computeFallbackMeasurements()); return; }
        const ctx = cv.getContext('2d');
        if (!ctx) { renderLabReport(computeFallbackMeasurements()); return; }
        const w = cv.width, h = cv.height;

        drawGrid(ctx, w, h);

        const ZOOM = 2.4;
        const bw = Math.round(labState.w * ZOOM);
        const topH = Math.round(labState.topH * ZOOM);
        const botH = Math.round(labState.botH * ZOOM);
        const bh = topH + botH;
        const bx = Math.round((w - bw) / 2), by = Math.round((h - bh) / 2);
        const midY = by + topH;

        drawSimulatedFigure(ctx, bx, by, bw, bh, midY);
        const measurements = drawLabCutsAndMeasurements(ctx, bx, by, bw, bh, midY);
        renderLabReport(measurements);
    }

    function updateUiValues() {
        $id('fig-val-top') && ($id('fig-val-top').textContent = labState.topH + ' px');
        $id('fig-val-bot') && ($id('fig-val-bot').textContent = labState.botH + ' px');
        $id('fig-val-w') && ($id('fig-val-w').textContent = labState.w + ' px');
        $id('lab-val-v') && ($id('lab-val-v').textContent = String(labState.cutsV));
        $id('lab-val-h') && ($id('lab-val-h').textContent = String(labState.cutsH));
        $id('lab-val-t') && ($id('lab-val-t').textContent = `${labState.topMin}–${labState.topMax} px`);
        $id('lab-val-b') && ($id('lab-val-b').textContent = `${labState.bottomMin}–${labState.bottomMax} px`);
        $id('lab-val-w') && ($id('lab-val-w').textContent = `${labState.wMin}–${labState.wMax} px`);
        paintLabCanvas();
    }

    function setFigurePreset(preset) {
        labState.fig = preset;
        document.querySelectorAll('.btn-lab-fig').forEach(b => b.classList.toggle('active', b.dataset.fig === preset));
        if (preset === 'window') { labState.topH = 30; labState.botH = 28; labState.w = 72; }
        else if (preset === 'window_defect_top') { labState.topH = 52; labState.botH = 28; labState.w = 72; }
        else if (preset === 'window_defect_bot') { labState.topH = 30; labState.botH = 50; labState.w = 72; }
        else if (preset === 'rect') { labState.topH = 24; labState.botH = 24; labState.w = 88; }
        const sT = $id('fig-slider-top'), sB = $id('fig-slider-bot'), sW = $id('fig-slider-w');
        if (sT) sT.value = labState.topH;
        if (sB) sB.value = labState.botH;
        if (sW) sW.value = labState.w;
        updateUiValues();
    }

    function openLab() {
        labState.open = true;
        const ov = $id('tool-lab-overlay');
        if (ov) ov.style.display = 'flex';
        updateUiValues();
    }

    function closeLab() {
        labState.open = false;
        const ov = $id('tool-lab-overlay');
        if (ov) ov.style.display = 'none';
    }

    function wireLabEvents() {
        $id('btn-open-lab')?.addEventListener('click', openLab);
        $id('btn-open-lab-palette')?.addEventListener('click', openLab);
        $id('btn-close-lab')?.addEventListener('click', closeLab);
        $id('tool-lab-overlay')?.addEventListener('click', e => {
            if (e.target === $id('tool-lab-overlay')) closeLab();
        });

        document.querySelectorAll('.btn-lab-fig').forEach(btn => {
            btn.addEventListener('click', () => setFigurePreset(btn.dataset.fig));
        });

        $id('fig-slider-top')?.addEventListener('input', e => { labState.topH = parseInt(e.target.value, 10); updateUiValues(); });
        $id('fig-slider-bot')?.addEventListener('input', e => { labState.botH = parseInt(e.target.value, 10); updateUiValues(); });
        $id('fig-slider-w')?.addEventListener('input', e => { labState.w = parseInt(e.target.value, 10); updateUiValues(); });

        $id('lab-v-dec')?.addEventListener('click', () => { labState.cutsV = Math.max(1, labState.cutsV - 1); updateUiValues(); });
        $id('lab-v-inc')?.addEventListener('click', () => { labState.cutsV = Math.min(6, labState.cutsV + 1); updateUiValues(); });
        $id('lab-h-dec')?.addEventListener('click', () => { labState.cutsH = Math.max(1, labState.cutsH - 1); updateUiValues(); });
        $id('lab-h-inc')?.addEventListener('click', () => { labState.cutsH = Math.min(3, labState.cutsH + 1); updateUiValues(); });

        $id('lab-t-dec')?.addEventListener('click', () => { labState.topMin = Math.max(5, labState.topMin - 2); labState.topMax = Math.max(labState.topMin + 5, labState.topMax - 2); updateUiValues(); });
        $id('lab-t-inc')?.addEventListener('click', () => { labState.topMin = Math.min(30, labState.topMin + 2); labState.topMax = Math.min(60, labState.topMax + 2); updateUiValues(); });
        $id('lab-b-dec')?.addEventListener('click', () => { labState.bottomMin = Math.max(5, labState.bottomMin - 2); labState.bottomMax = Math.max(labState.bottomMin + 5, labState.bottomMax - 2); updateUiValues(); });
        $id('lab-b-inc')?.addEventListener('click', () => { labState.bottomMin = Math.min(30, labState.bottomMin + 2); labState.bottomMax = Math.min(60, labState.bottomMax + 2); updateUiValues(); });

        $id('lab-w-dec')?.addEventListener('click', () => { labState.wMin = Math.max(20, labState.wMin - 5); labState.wMax = Math.max(labState.wMin + 10, labState.wMax - 5); updateUiValues(); });
        $id('lab-w-inc')?.addEventListener('click', () => { labState.wMin = Math.min(80, labState.wMin + 5); labState.wMax = Math.min(140, labState.wMax + 5); updateUiValues(); });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wireLabEvents);
    } else {
        wireLabEvents();
    }

    window.ToolLab = { open: openLab, close: closeLab, state: () => labState, setPreset: setFigurePreset };
})();
