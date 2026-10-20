/**
 * @file init.js
 * @description Точка входа: сборка обработчиков и первичная отрисовка рабочей области редактора ленты.
 */

'use strict';

/**
 * Инициализация всех подсистем редактора
 */
function initBeltEditor() {
    wirePalette();
    wireBelt();
    wireSearch();
    wireThrClose();
    wireLinkEngine();
    dragGNodes();
    wireScrollSnap();
    wireSideDock();
    wireFolderPickers();
    render();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBeltEditor);
} else {
    initBeltEditor();
}
