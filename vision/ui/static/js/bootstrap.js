// bootstrap.js — Line Monitor UI module
'use strict';

// ─── Hotkeys ─────────────────────────────────────────────────

function setupHotkeys() {
    window.addEventListener('keydown', (e) => {
        const tag = (e.target && e.target.tagName) || '';
        const inInput = tag === 'INPUT' || tag === 'TEXTAREA';

        if (typeof isOperatorModalOpen === 'function' && isOperatorModalOpen()) {
            if (e.key === 'Escape') {
                e.preventDefault();
                if (typeof isOperatorModalMandatory === 'function' && !isOperatorModalMandatory()) {
                    closeOperatorModal(false);
                }
            }
            return;
        }

        if (e.key === 'Escape') {
            const fullscreen = document.querySelector('.gallery-fullscreen');
            if (fullscreen) {
                fullscreen.remove();
                e.preventDefault();
                return;
            }

            const yoloMarkModal = document.getElementById('yolo-mark-modal');
            if (yoloMarkModal && !yoloMarkModal.classList.contains('is-hidden')) {
                if (typeof closeYoloMarkModal === 'function') closeYoloMarkModal();
                e.preventDefault();
                return;
            }

            const yoloExportModal = document.getElementById('yolo-export-modal');
            if (yoloExportModal && !yoloExportModal.classList.contains('is-hidden')) {
                if (typeof closeYoloExportModal === 'function') closeYoloExportModal();
                e.preventDefault();
                return;
            }

            if (els.archiveSettingsModal && !els.archiveSettingsModal.classList.contains('is-hidden')) {
                closeArchiveSettings();
                e.preventDefault();
                return;
            }

            if (
                els.galleryModal
                && !els.galleryModal.classList.contains('is-hidden')
            ) {
                closeGallery();
                e.preventDefault();
                return;
            }

            if (inInput) return;

            els.btnExit.click();
            return;
        }

        if (typeof isYoloModalOpen === 'function' && isYoloModalOpen()) {
            if (!inInput && (e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z' || e.key === 'я' || e.key === 'Я')) {
                e.preventDefault();
                if (typeof undoLastYoloMark === 'function') undoLastYoloMark();
                return;
            }
            if (!inInput && e.key >= '1' && e.key <= '9') {
                e.preventDefault();
                if (typeof selectYoloClassByIndex === 'function') {
                    selectYoloClassByIndex(parseInt(e.key, 10) - 1);
                }
                return;
            }
            return;
        }

        if (inInput) return;

        if (e.key === 'm' || e.key === 'M' || e.key === 'ь' || e.key === 'Ь') {
            const markBtn = document.getElementById('mark-yolo-defect');
            if (markBtn && !markBtn.disabled) {
                e.preventDefault();
                markBtn.click();
            }
            return;
        }

        if (e.key === 'F5') {
            e.preventDefault();
            els.btnStart.click();
            return;
        }

        if (e.key === 'F6') {
            e.preventDefault();
            els.btnStop.click();
            return;
        }

        if (e.key === 'F7' || e.key === 'p' || e.key === 'P') {
            e.preventDefault();
            if (els.btnPause && !els.btnPause.classList.contains('is-hidden') && !els.btnPause.disabled) {
                els.btnPause.click();
            } else if (els.btnResume && !els.btnResume.classList.contains('is-hidden') && !els.btnResume.disabled) {
                els.btnResume.click();
            }
            return;
        }

        if (e.key === 'F11') {
            e.preventDefault();
            if (
                !document.fullscreenElement
                && typeof document.documentElement.requestFullscreen === 'function'
            ) {
                document.documentElement.requestFullscreen().catch(() => {});
            } else if (
                document.fullscreenElement
                && typeof document.exitFullscreen === 'function'
            ) {
                document.exitFullscreen().catch(() => {});
            }
            return;
        }

        if (state.jogActive) {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                e.preventDefault();
                if (!e.repeat && !state.jogHoldDirection && !state.jogStepPending) {
                    const direction = e.key === 'ArrowLeft' ? '-' : '+';
                    const button = els.jogPanel.querySelector(
                        `.jog-hold-btn[data-direction="${direction}"]`
                    );
                    if (button) triggerJogPress(direction, button);
                }
                return;
            }
            if (e.key === 'ArrowUp' || e.key === 'ArrowDown') return;
        }

        if (e.key === 'Tab') {
            e.preventDefault();
            if (viewModeAllowed()) toggleMode();
            return;
        }

        if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') {
            navigateCamera(-1);
            return;
        }

        if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') {
            navigateCamera(1);
            return;
        }

        if (e.key >= '1' && e.key <= '9') {
            const idx = parseInt(e.key, 10) - 1;
            if (idx < state.cameras.length) {
                selectCamera(state.cameras[idx]);
            }
        }
    });
}

window.addEventListener('keyup', e => {
    if (
        state.jogHoldDirection
        && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')
    ) {
        e.preventDefault();
        releaseJogHold(`key released: ${e.key}`);
    }
});

// ─── Init ────────────────────────────────────────────────────

function init() {
    els.cameraContainer = document.querySelector('.camera-container');

    setupButtons();
    setupHotkeys();
    setupGallery();
    if (typeof setupOperatorControls === 'function') setupOperatorControls();
    if (typeof setupArchiveSettings === 'function') setupArchiveSettings();
    if (typeof setupYoloFeedback === 'function') setupYoloFeedback();
    setupCameraHover();
    setupGridToggle();
    setupViewModeControls();
    setupJogControls();
    setupSelectedFrameAnalysis();
    setupThresholdsControls();

    fetchBoot();
    state.bootInterval = setInterval(fetchBoot, BOOT_INTERVAL);

    startUiReadyWatcher();

    setInterval(fetchCameras, 2000);
    setInterval(refreshPreviewStrip, PREVIEW_INTERVAL);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
