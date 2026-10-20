#!/usr/bin/env node
/**
 * scripts/build.js
 * Сборщик модулей belt_editor/js/modules/ в единый бандл belt_editor/js/builder.js
 */

const fs = require('fs');
const path = require('path');

const rootDir = path.resolve(__dirname, '..');
const modulesDir = path.join(rootDir, 'belt_editor', 'js', 'modules');
const targetFile = path.join(rootDir, 'belt_editor', 'js', 'builder.js');

const moduleFiles = [
    'state.js',
    'geometry.js',
    'actions.js',
    'render.js',
    'wires.js',
    'dnd.js',
    'dock.js',
    'init.js'
];

const parts = [
    '/**\n * BELT BUILDER — Модульная сборка редактора ленты конвейера\n * Скомпоновано из модулей belt_editor/js/modules/\n */\n(() => {\n\'use strict\';\n'
];

for (const file of moduleFiles) {
    const fullPath = path.join(modulesDir, file);
    if (!fs.existsSync(fullPath)) {
        console.error(`Модуль не найден: ${fullPath}`);
        process.exit(1);
    }
    const raw = fs.readFileSync(fullPath, 'utf8');
    const cleaned = raw.split('\n')
        .filter(line => line.trim() !== "'use strict';")
        .join('\n')
        .trim();
    parts.push(`\n/* ─── МОДУЛЬ: ${file} ─── */\n${cleaned}\n`);
}

parts.push('\n})();\n');

const bundled = parts.join('\n');
fs.writeFileSync(targetFile, bundled, 'utf8');
console.log(`[build] Успешно собрано ${bundled.split('\n').length} строк в ${targetFile}`);
