"""Контракты HMI карточки «ПАРТИЯ» и параллельной инспекции.

Проверки читают исходники разметки, статики и ядра: они держат то, что
нельзя поймать python-тестами на живом сервере, — что поля карточки
заполняет только синхронизация с целью ПУСКА, что удалённые окна не
вернулись и что вход и контроль считаются параллельно.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = ROOT / "vision" / "ui" / "static" / "js"
STATIC_CSS = ROOT / "vision" / "ui" / "static" / "css"
TEMPLATE = ROOT / "vision" / "ui" / "templates" / "index.html"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    """Тело функции по имени: JS-функции HMI и методы ядра.

    Границы тела определяются по отступам: у JS-функции это закрывающая
    скобка в первой колонке, у метода Python — следующий `def` того же
    уровня.
    """
    match = re.search(
        rf"^(?:function {re.escape(name)}\(|    def {re.escape(name)}\()",
        source, re.M,
    )
    if not match:
        raise AssertionError(f"функция {name} не найдена")
    tail = source[match.start():]
    if tail.startswith("    def "):
        end = re.search(r"\n    def |\nclass |\nif __name__", tail)
        return tail[:end.start()] if end else tail
    end = tail.find("\n}\n")
    if end < 0:
        raise AssertionError(f"не найдена закрывающая скобка функции {name}")
    return tail[:end]


class StaticAssetsTest(unittest.TestCase):
    """Разметка ссылается только на существующие файлы и с версией кэша."""

    def test_template_assets_exist_and_versioned(self):
        html = read(TEMPLATE)
        references = re.findall(
            r'(?:src|href)="(/static/[^"]+)"', html,
        )
        self.assertTrue(references, "в разметке нет ссылок на статику")
        for reference in references:
            path, _, query = reference.partition("?")
            target = ROOT / "vision" / "ui" / path.lstrip("/")
            self.assertTrue(
                target.is_file(), f"нет файла для ссылки {reference}",
            )
            self.assertTrue(
                query.startswith("v="),
                f"ссылка без версии кэша: {reference}",
            )


class BatchCardContractTest(unittest.TestCase):
    """Поля карточки описывают цель ПУСКА, а не первое автозаполнение."""

    def setUp(self):
        self.source = read(STATIC_JS / "batch.js")

    def test_fields_are_written_only_by_sync(self):
        """Поля карточки пишет только syncBatchFields.

        Раньше свежий номер подставлялся в renderBatchPanel один раз, и
        после первого автозаполнения шаблон замирал. Теперь любая запись в
        поле номера или пути обязана жить внутри синхронизации с целью
        ПУСКА — иначе шаблон снова начнёт «застревать» в поле.
        """
        sync = function_body(self.source, "syncBatchFields")
        writes = re.findall(
            r"els\.batch(?:Label|Path)Input\.value\s*=", self.source,
        )
        self.assertTrue(writes, "поля карточки вообще не заполняются")
        inside = re.findall(
            r"els\.batch(?:Label|Path)Input\.value\s*=", sync,
        )
        self.assertEqual(
            len(writes), len(inside),
            "поле карточки заполняется вне syncBatchFields",
        )

    def test_render_panel_does_not_touch_inputs(self):
        render = function_body(self.source, "renderBatchPanel")
        self.assertNotIn("batchLabelInput.value", render)
        self.assertNotIn("batchPathInput.value", render)

    def test_target_contract(self):
        """Цели ПУСКА: выбранная партия, ввод оператора, шаблон."""
        self.assertIn("function batchStartTarget()", self.source)
        self.assertIn("window.batchStartTarget = batchStartTarget;",
                      self.source)
        target = function_body(self.source, "batchStartTarget")
        self.assertIn("selectedBatchRow()", target)
        self.assertIn("batchLabelTouched", target)
        self.assertIn("batchTemplateLabel()", target)
        template = function_body(self.source, "batchTemplateLabel")
        self.assertIn("suggestion", template)

    def test_payload_carries_selected_batch(self):
        payload = function_body(self.source, "batchStartPayload")
        self.assertIn("batchStartTarget()", payload)
        self.assertIn("if (target.batch_id) payload.batch_id = target.batch_id",
                      payload)

    def test_selection_toggles_off(self):
        select = function_body(self.source, "selectBatch")
        self.assertIn("if (selectedBatchId === item.batch_id)", select)
        self.assertIn("clearBatchSelection()", select)

    def test_hint_names_current_accounting(self):
        """Подсказка называет и открытую партию: поля — это цель ПУСКА."""
        hint = function_body(self.source, "updateBatchOpenHint")
        self.assertIn("Учёт идёт в партию", hint)
        self.assertIn("Продолжить её — выбрать в списке", hint)


class RemovedHmiTest(unittest.TestCase):
    """Удалённые окна, кнопки и блоки не возвращаются в интерфейс."""

    def test_html_has_no_removed_blocks(self):
        html = read(TEMPLATE)
        for fragment in (
            "batch-exit-modal",
            "archive.js",
            "archive.css",
            "btn-archive",
            "НАЧАТЬ ПАРТИЮ",
            "СТАТИСТИКА РАБОЧЕГО ЦИКЛА",
            "Замеры объектов",
            "ЗАМЕРЫ ОБЪЕКТОВ",
        ):
            self.assertNotIn(fragment, html, f"в разметке вернулся {fragment}")
        self.assertNotRegex(html, r"DIST[12]")

    def test_scripts_have_no_exit_dialog(self):
        for name in ("batch.js", "controls.js", "core.js", "bootstrap.js"):
            source = read(STATIC_JS / name)
            self.assertNotIn("batch-exit", source, name)
            self.assertNotIn("BatchExit", source, name)

    def test_css_has_no_exit_dialog(self):
        stylesheet = read(STATIC_CSS / "batch.css")
        self.assertNotIn(".batch-exit", stylesheet)


class ParallelInspectionContractTest(unittest.TestCase):
    """Вход и контроль считаются параллельно, записи — по порядку стадий."""

    def setUp(self):
        self.source = read(ROOT / "core" / "cycle" / "step.py")

    def test_both_positions_use_two_threads(self):
        self.assertIn("from concurrent.futures import ThreadPoolExecutor",
                      self.source)
        parallel = function_body(self.source, "_analyze_stages_parallel")
        self.assertIn("max_workers=2", parallel)
        self.assertIn("inspect_input", parallel)
        self.assertIn("inspect_spider", parallel)

    def test_results_are_applied_in_stage_order(self):
        stages = function_body(self.source, "_inspect_stages_parallel")
        self.assertLess(
            stages.index("_apply_input_result"),
            stages.index("_apply_spider_result"),
            "решения стадий обязаны применяться в порядке вход → контроль",
        )
        for helper in ("_apply_input_result", "_apply_spider_result"):
            self.assertIn(f"def {helper}(", self.source)

    def test_single_stage_stays_sequential(self):
        inspect = function_body(self.source, "_inspect_occupied_stages")
        self.assertIn("_inspect_stages_sequential", inspect)
        self.assertIn("_inspect_stages_parallel", inspect)

    def test_capture_reads_stages_one_after_another(self):
        """Кадры обеих позиций снимаются в одном блоке заморозки."""
        parallel = function_body(self.source, "_inspect_stages_parallel")
        self.assertIn("enter_capture(roles)", parallel)
        self.assertIn("_capture_stage_frames", parallel)

    def test_hmi_labels_parallel_phase(self):
        status = read(STATIC_JS / "status.js")
        self.assertIn("PARALLEL_ANALYSIS", status)
        simulation = read(ROOT / "ui_simulation.py")
        self.assertIn("PARALLEL_ANALYSIS", simulation)


if __name__ == "__main__":
    unittest.main()
