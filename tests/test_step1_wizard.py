#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_step1_wizard.py — Step1「採点準備」統合セットアップウィザードのテスト。

各サブステップ(名簿・ページ設定・氏名欄・学籍番号欄)のGUI呼び出しはモックし、
実行順序・保存済み設定の自動スキップ・キャンセル時の継続・2回目実行時の
全スキップを検証する。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tkinter as tk
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from saitensamurai import Mark2GUI, RESULTS_FOLDER, RESULTS_DATA_FOLDER, BOXED_FOLDER

from conftest import get_shared_tk_root


def _make_stub_app(img_folder=""):
    """Mark2GUI の軽量スタブ（__init__ をスキップ）。ウィザードのテストに必要な
    属性だけを用意する。"""
    root = get_shared_tk_root()
    app = object.__new__(Mark2GUI)
    app.root = root
    app.image_folder_path = tk.StringVar(root, value=img_folder)
    app.skip_questions = tk.StringVar(root, value="4")
    app.student_id_ocr_enabled = tk.BooleanVar(root, value=False)
    app._log_messages = []

    def log_message(msg):
        app._log_messages.append(msg)

    app.log_message = log_message
    return app


class TestStep1SetupWizard(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_step1_wizard_")
        self.img_folder = Path(self.tmpdir) / "images"
        self.img_folder.mkdir()
        self.boxed_folder = self.img_folder / RESULTS_FOLDER / BOXED_FOLDER
        self.boxed_folder.mkdir(parents=True)
        Image.new("RGB", (100, 150), "white").save(str(self.boxed_folder / "001.jpg"))
        self.results_data = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ------------------------------------------------------------
    # 前提チェック
    # ------------------------------------------------------------

    def test_no_image_folder_shows_error(self):
        app = _make_stub_app("")
        with patch('tkinter.messagebox.showerror') as mock_err:
            app._run_step1_setup_wizard()
        mock_err.assert_called_once()

    def test_no_boxed_folder_shows_error(self):
        img_folder = Path(self.tmpdir) / "no_boxed"
        img_folder.mkdir()
        app = _make_stub_app(str(img_folder))
        with patch('tkinter.messagebox.showerror') as mock_err:
            app._run_step1_setup_wizard()
        mock_err.assert_called_once()

    # ------------------------------------------------------------
    # 実行順序
    # ------------------------------------------------------------

    def test_runs_all_substeps_in_order_then_setup_descriptive(self):
        app = _make_stub_app(str(self.img_folder))
        calls = []
        app._wizard_step_roster = MagicMock(side_effect=lambda *a: calls.append('roster'))
        app._wizard_step_page_check = MagicMock(side_effect=lambda *a: calls.append('page'))
        app._wizard_step_name_area = MagicMock(side_effect=lambda *a: calls.append('name'))
        app._wizard_step_id_area = MagicMock(side_effect=lambda *a: calls.append('id'))
        app.setup_descriptive = MagicMock(side_effect=lambda: calls.append('desc'))

        app._run_step1_setup_wizard()

        self.assertEqual(calls, ['roster', 'page', 'name', 'id', 'desc'])

    # ------------------------------------------------------------
    # 名簿ステップ
    # ------------------------------------------------------------

    def test_roster_step_skips_if_already_configured(self):
        from roster_config import save_roster_config, ROSTER_CONFIG_FILE
        self.results_data.mkdir(parents=True, exist_ok=True)
        save_roster_config(str(self.results_data / ROSTER_CONFIG_FILE), {"1": "a"})

        app = _make_stub_app(str(self.img_folder))
        with patch('roster_loader.select_roster_gui') as mock_gui:
            app._wizard_step_roster(self.results_data)
        mock_gui.assert_not_called()
        self.assertTrue(any("スキップ" in m for m in app._log_messages))

    def test_roster_step_saves_when_selected(self):
        app = _make_stub_app(str(self.img_folder))
        with patch('roster_loader.select_roster_gui', return_value={"1": "a"}):
            app._wizard_step_roster(self.results_data)
        from roster_config import load_roster_config, ROSTER_CONFIG_FILE
        loaded = load_roster_config(str(self.results_data / ROSTER_CONFIG_FILE))
        self.assertEqual(loaded, {"1": "a"})

    def test_roster_step_cancel_does_not_save(self):
        app = _make_stub_app(str(self.img_folder))
        with patch('roster_loader.select_roster_gui', return_value=None):
            app._wizard_step_roster(self.results_data)
        from roster_config import load_roster_config, ROSTER_CONFIG_FILE
        self.assertIsNone(load_roster_config(str(self.results_data / ROSTER_CONFIG_FILE)))

    # ------------------------------------------------------------
    # ページ設定ステップ
    # ------------------------------------------------------------

    def test_page_check_step_skips_when_answered_no(self):
        app = _make_stub_app(str(self.img_folder))
        app.run_page_number_check = MagicMock()
        with patch('tkinter.messagebox.askyesno', return_value=False):
            app._wizard_step_page_check()
        app.run_page_number_check.assert_not_called()

    def test_page_check_step_runs_when_answered_yes(self):
        app = _make_stub_app(str(self.img_folder))
        app.run_page_number_check = MagicMock()
        with patch('tkinter.messagebox.askyesno', return_value=True):
            app._wizard_step_page_check()
        app.run_page_number_check.assert_called_once()

    # ------------------------------------------------------------
    # 氏名欄ステップ
    # ------------------------------------------------------------

    def test_name_area_step_skips_if_already_configured(self):
        from name_area_config import save_name_area_config, NAME_AREA_CONFIG_FILE
        self.results_data.mkdir(parents=True, exist_ok=True)
        save_name_area_config(str(self.results_data / NAME_AREA_CONFIG_FILE), (0.1, 0.1, 0.5, 0.2))

        app = _make_stub_app(str(self.img_folder))
        with patch('name_trimmer.NameTrimmer') as mock_trimmer_cls:
            app._wizard_step_name_area(self.boxed_folder, self.results_data)
        mock_trimmer_cls.assert_not_called()

    def test_name_area_step_saves_selected_rect_as_fraction(self):
        app = _make_stub_app(str(self.img_folder))
        mock_trimmer = MagicMock()
        mock_trimmer.run.return_value = {"001.jpg": "/tmp/dummy.jpg"}
        mock_trimmer.last_trim_rect = (10, 15, 60, 45)  # 画像は100x150
        with patch('name_trimmer.NameTrimmer', return_value=mock_trimmer):
            app._wizard_step_name_area(self.boxed_folder, self.results_data)

        from name_area_config import load_name_area_config, NAME_AREA_CONFIG_FILE
        rect_frac = load_name_area_config(str(self.results_data / NAME_AREA_CONFIG_FILE))
        self.assertAlmostEqual(rect_frac[0], 10 / 100)
        self.assertAlmostEqual(rect_frac[1], 15 / 150)
        self.assertAlmostEqual(rect_frac[2], 60 / 100)
        self.assertAlmostEqual(rect_frac[3], 45 / 150)

    def test_name_area_step_cancel_does_not_save(self):
        app = _make_stub_app(str(self.img_folder))
        mock_trimmer = MagicMock()
        mock_trimmer.run.return_value = None
        with patch('name_trimmer.NameTrimmer', return_value=mock_trimmer):
            app._wizard_step_name_area(self.boxed_folder, self.results_data)
        from name_area_config import load_name_area_config, NAME_AREA_CONFIG_FILE
        self.assertIsNone(load_name_area_config(str(self.results_data / NAME_AREA_CONFIG_FILE)))

    # ------------------------------------------------------------
    # 学籍番号欄ステップ
    # ------------------------------------------------------------

    def test_id_area_step_skips_if_already_configured(self):
        from id_area_config import save_id_area_config, ID_AREA_CONFIG_FILE
        self.results_data.mkdir(parents=True, exist_ok=True)
        save_id_area_config(str(self.results_data / ID_AREA_CONFIG_FILE), {"digit_count": 8})

        app = _make_stub_app(str(self.img_folder))
        with patch('student_id_ocr.ensure_id_area_config') as mock_ensure:
            app._wizard_step_id_area(self.boxed_folder, self.results_data)
        mock_ensure.assert_not_called()

    def test_id_area_step_skips_when_answered_no(self):
        app = _make_stub_app(str(self.img_folder))
        with patch('tkinter.messagebox.askyesno', return_value=False), \
             patch('student_id_ocr.ensure_id_area_config') as mock_ensure:
            app._wizard_step_id_area(self.boxed_folder, self.results_data)
        mock_ensure.assert_not_called()
        self.assertFalse(app.student_id_ocr_enabled.get())

    def test_id_area_step_enables_checkbox_on_success(self):
        app = _make_stub_app(str(self.img_folder))
        with patch('tkinter.messagebox.askyesno', return_value=True), \
             patch('student_id_ocr.ensure_id_area_config', return_value={"digit_count": 8}):
            app._wizard_step_id_area(self.boxed_folder, self.results_data)
        self.assertTrue(app.student_id_ocr_enabled.get())

    def test_id_area_step_cancel_leaves_checkbox_off(self):
        app = _make_stub_app(str(self.img_folder))
        with patch('tkinter.messagebox.askyesno', return_value=True), \
             patch('student_id_ocr.ensure_id_area_config', return_value=None):
            app._wizard_step_id_area(self.boxed_folder, self.results_data)
        self.assertFalse(app.student_id_ocr_enabled.get())

    # ------------------------------------------------------------
    # 2回目実行(全て設定済み)
    # ------------------------------------------------------------

    def test_second_run_skips_everything_except_setup_descriptive(self):
        """1回目実行後、保存済みファイルがあれば2回目はサブGUIを一切呼ばない"""
        from roster_config import save_roster_config, ROSTER_CONFIG_FILE
        from name_area_config import save_name_area_config, NAME_AREA_CONFIG_FILE
        from id_area_config import save_id_area_config, ID_AREA_CONFIG_FILE
        self.results_data.mkdir(parents=True, exist_ok=True)
        save_roster_config(str(self.results_data / ROSTER_CONFIG_FILE), {"1": "a"})
        save_name_area_config(str(self.results_data / NAME_AREA_CONFIG_FILE), (0.1, 0.1, 0.5, 0.2))
        save_id_area_config(str(self.results_data / ID_AREA_CONFIG_FILE), {"digit_count": 8})

        app = _make_stub_app(str(self.img_folder))
        app.setup_descriptive = MagicMock()
        app.run_page_number_check = MagicMock()
        with patch('roster_loader.select_roster_gui') as mock_roster_gui, \
             patch('tkinter.messagebox.askyesno', return_value=False), \
             patch('name_trimmer.NameTrimmer') as mock_trimmer_cls, \
             patch('student_id_ocr.ensure_id_area_config') as mock_ensure:
            app._run_step1_setup_wizard()

        mock_roster_gui.assert_not_called()
        mock_trimmer_cls.assert_not_called()
        mock_ensure.assert_not_called()
        app.run_page_number_check.assert_not_called()
        app.setup_descriptive.assert_called_once()


if __name__ == '__main__':
    unittest.main()
