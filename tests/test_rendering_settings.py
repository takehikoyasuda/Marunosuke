#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_rendering_settings.py — ④ 採点結果描画 詳細設定のテスト

対象:
  - constants.py: get_rendering_settings / DEFAULT_RENDERING_SETTINGS
  - descriptive_scorer.py: draw_descriptive_on_image の設定パラメータ対応
  - gui_components.py: RenderingSettingsGUI
  - main_gui.py: セッション保存・復元での rendering_settings 引き継ぎ
"""

import json
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np

# プロジェクトルートを PATH に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_SRC = PROJECT_ROOT / "main_src"
sys.path.insert(0, str(MAIN_SRC))

from constants import (
    DEFAULT_RENDERING_SETTINGS,
    get_rendering_settings,
)


# ========================================
# 1. 設定モデル（constants.py）
# ========================================

class TestDefaultRenderingSettings(unittest.TestCase):
    """DEFAULT_RENDERING_SETTINGS に必要なキーが存在し、デフォルト値が正しい"""

    EXPECTED_KEYS = [
        'mark_result_offset',
        'show_correct_answer',
        'show_ox_mark',
        'show_score',
        'show_aspect',
        'descriptive_opacity',
        'descriptive_show_mark',
        'descriptive_show_score',
        'descriptive_show_aspect',
    ]

    def test_all_keys_present(self):
        for key in self.EXPECTED_KEYS:
            self.assertIn(key, DEFAULT_RENDERING_SETTINGS, f"キー '{key}' が DEFAULT_RENDERING_SETTINGS に存在しません")

    def test_default_offset_is_zero(self):
        self.assertEqual(DEFAULT_RENDERING_SETTINGS['mark_result_offset'], 0.0)
        self.assertIsInstance(DEFAULT_RENDERING_SETTINGS['mark_result_offset'], float)

    def test_default_booleans_are_true(self):
        for key in self.EXPECTED_KEYS:
            if key.startswith('show_') or key.startswith('descriptive_show_'):
                self.assertTrue(DEFAULT_RENDERING_SETTINGS[key], f"{key} のデフォルトは True であるべき")

    def test_default_opacity(self):
        self.assertAlmostEqual(DEFAULT_RENDERING_SETTINGS['descriptive_opacity'], 0.50)


class TestGetRenderingSettings(unittest.TestCase):
    """get_rendering_settings() のマージロジック"""

    def test_no_overrides_returns_defaults(self):
        result = get_rendering_settings()
        self.assertEqual(result, DEFAULT_RENDERING_SETTINGS)

    def test_none_overrides_returns_defaults(self):
        result = get_rendering_settings(None)
        self.assertEqual(result, DEFAULT_RENDERING_SETTINGS)

    def test_partial_override(self):
        result = get_rendering_settings({'show_ox_mark': False})
        self.assertFalse(result['show_ox_mark'])
        # 他のキーはデフォルトのまま
        self.assertTrue(result['show_score'])
        self.assertTrue(result['show_aspect'])

    def test_offset_override(self):
        result = get_rendering_settings({'mark_result_offset': -3})
        self.assertEqual(result['mark_result_offset'], -3)

    def test_float_offset_override(self):
        """小数オフセットを正しく保持する"""
        result = get_rendering_settings({'mark_result_offset': 0.5})
        self.assertAlmostEqual(result['mark_result_offset'], 0.5)
        result = get_rendering_settings({'mark_result_offset': -1.3})
        self.assertAlmostEqual(result['mark_result_offset'], -1.3)

    def test_opacity_override(self):
        result = get_rendering_settings({'descriptive_opacity': 0.75})
        self.assertAlmostEqual(result['descriptive_opacity'], 0.75)

    def test_unknown_keys_ignored(self):
        result = get_rendering_settings({'unknown_key': 42})
        self.assertNotIn('unknown_key', result)
        self.assertEqual(len(result), len(DEFAULT_RENDERING_SETTINGS))

    def test_returns_copy_not_reference(self):
        r1 = get_rendering_settings()
        r2 = get_rendering_settings()
        r1['show_ox_mark'] = False
        self.assertTrue(r2['show_ox_mark'], "get_rendering_settings() は独立したコピーを返すべき")

    def test_json_serializable(self):
        """設定辞書はJSON化可能であること（セッション保存のため）"""
        result = get_rendering_settings()
        json_str = json.dumps(result)
        restored = json.loads(json_str)
        self.assertEqual(result, restored)


class TestDescriptiveScorerSettings(unittest.TestCase):
    """draw_descriptive_on_image が設定を受け入れる"""

    def test_draw_descriptive_signature(self):
        import inspect
        from descriptive_scorer import draw_descriptive_on_image
        sig = inspect.signature(draw_descriptive_on_image)
        self.assertIn('rendering_settings', sig.parameters)


# ========================================
# 5. RenderingSettingsGUI
# ========================================

class TestRenderingSettingsGUI(unittest.TestCase):
    """RenderingSettingsGUI の基本テスト"""

    @classmethod
    def setUpClass(cls):
        """テスト用の非表示 root ウィンドウを用意"""
        try:
            from conftest import get_shared_tk_root
            cls._root = get_shared_tk_root()
        except Exception:
            import tkinter as tk
            cls._root = tk.Tk()
            cls._root.withdraw()

    @classmethod
    def tearDownClass(cls):
        # conftest管理のrootは破棄しない
        pass

    def test_create_and_destroy(self):
        """ウィンドウを正常に作成・破棄できる"""
        from gui_components import RenderingSettingsGUI
        applied = {}

        def on_apply(s):
            applied.update(s)

        gui = RenderingSettingsGUI(
            parent_window=self._root,
            current_settings=get_rendering_settings(),
            on_apply=on_apply,
        )
        # ウィンドウが作成されている
        self.assertTrue(gui.window.winfo_exists())
        gui._on_cancel()

    def test_apply_returns_settings(self):
        """適用ボタンで設定がコールバックに渡される"""
        from gui_components import RenderingSettingsGUI
        result = {}

        def on_apply(s):
            result.update(s)

        gui = RenderingSettingsGUI(
            parent_window=self._root,
            current_settings=get_rendering_settings(),
            on_apply=on_apply,
        )
        # GUI上で値を変更
        gui.var_show_ox.set(False)
        gui.var_offset.set(2.0)
        gui.var_desc_opacity.set(0.8)

        gui._on_apply()

        self.assertFalse(result['show_ox_mark'])
        self.assertAlmostEqual(result['mark_result_offset'], 2.0)
        self.assertAlmostEqual(result['descriptive_opacity'], 0.8)

    def test_reset_to_defaults(self):
        """デフォルトに戻すボタンで値がリセットされる"""
        from gui_components import RenderingSettingsGUI
        gui = RenderingSettingsGUI(
            parent_window=self._root,
            current_settings={'show_ox_mark': False, 'mark_result_offset': 5},
            on_apply=lambda s: None,
        )
        # カスタム値で初期化されている
        self.assertFalse(gui.var_show_ox.get())
        self.assertEqual(gui.var_offset.get(), 5.0)

        gui._reset_to_defaults()

        self.assertTrue(gui.var_show_ox.get())
        self.assertEqual(gui.var_offset.get(), 0.0)
        gui._on_cancel()

    def test_collect_settings_all_keys(self):
        """_collect_settings がすべての設定キーを返す"""
        from gui_components import RenderingSettingsGUI
        gui = RenderingSettingsGUI(
            parent_window=self._root,
            current_settings=get_rendering_settings(),
            on_apply=lambda s: None,
        )
        settings = gui._collect_settings()
        for key in DEFAULT_RENDERING_SETTINGS:
            self.assertIn(key, settings, f"_collect_settings() に '{key}' がありません")
        gui._on_cancel()


# ========================================
# 6. セッション保存・復元の rendering_settings
# ========================================

class TestSessionRenderingSettings(unittest.TestCase):
    """rendering_settings がセッション JSON に含まれ正しく復元される"""

    @classmethod
    def setUpClass(cls):
        try:
            from conftest import get_shared_tk_root
            cls._root = get_shared_tk_root()
        except Exception:
            import tkinter as tk
            cls._root = tk.Tk()
            cls._root.withdraw()

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.img_folder = Path(self.tmpdir) / "images"
        self.img_folder.mkdir()
        from constants import RESULTS_FOLDER, RESULTS_DATA_FOLDER
        results_data = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        results_data.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_stub_app(self, img_folder=""):
        """Mark2GUI の軽量スタブ"""
        import tkinter as tk
        from main_gui import Mark2GUI
        from constants import MODE_MARK_AND_DESCRIPTIVE

        app = object.__new__(Mark2GUI)
        app.root = self._root
        app.app_mode = MODE_MARK_AND_DESCRIPTIVE
        app.image_folder_path = tk.StringVar(self._root, value=img_folder)
        app.coord_excel_path = tk.StringVar(self._root, value="")
        app.template_path = tk.StringVar(self._root, value="")
        app.mark2_result_path = tk.StringVar(self._root, value="")
        app.skip_questions = tk.StringVar(self._root, value="4")
        app.color_threshold = tk.DoubleVar(self._root, value=0.1)
        app.area_threshold = tk.DoubleVar(self._root, value=0.4)
        app.descriptive_enabled = tk.BooleanVar(self._root, value=False)
        app.rendering_settings = get_rendering_settings()
        app._log_messages = []
        app.log_message = lambda msg: app._log_messages.append(msg)
        app._desc_status_label = tk.Label(self._root)
        app._desc_status_frame = tk.Frame(self._root)
        app._on_descriptive_toggle = lambda: None
        return app

    def test_save_includes_rendering_settings(self):
        """保存したJSONに rendering_settings が含まれる"""
        app = self._make_stub_app(str(self.img_folder))
        app.rendering_settings['show_ox_mark'] = False
        app.rendering_settings['mark_result_offset'] = 3
        app._save_session_state()

        from constants import SESSION_STATE_FILE, RESULTS_FOLDER, RESULTS_DATA_FOLDER
        session_path = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER / SESSION_STATE_FILE
        self.assertTrue(session_path.exists())

        with open(session_path, encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('rendering_settings', data)
        self.assertFalse(data['rendering_settings']['show_ox_mark'])
        self.assertEqual(data['rendering_settings']['mark_result_offset'], 3)

    def test_restore_rendering_settings(self):
        """_apply_session_state で rendering_settings が正しく復元される"""
        app = self._make_stub_app(str(self.img_folder))

        state = {
            "version": 1,
            "image_folder": str(self.img_folder),
            "rendering_settings": {
                "show_ox_mark": False,
                "descriptive_opacity": 0.25,
                "mark_result_offset": -2,
            }
        }
        app._apply_session_state(state)

        self.assertFalse(app.rendering_settings['show_ox_mark'])
        self.assertAlmostEqual(app.rendering_settings['descriptive_opacity'], 0.25)
        self.assertEqual(app.rendering_settings['mark_result_offset'], -2)
        # 指定されていないキーはデフォルト
        self.assertTrue(app.rendering_settings['show_score'])

    def test_restore_without_rendering_settings(self):
        """rendering_settings がないセッションでもデフォルトが残る"""
        app = self._make_stub_app(str(self.img_folder))
        state = {
            "version": 1,
            "image_folder": str(self.img_folder),
        }
        app._apply_session_state(state)
        self.assertEqual(app.rendering_settings, DEFAULT_RENDERING_SETTINGS)

    def test_roundtrip_save_restore(self):
        """保存→復元のラウンドトリップで設定が一致する"""
        app1 = self._make_stub_app(str(self.img_folder))
        custom = {
            'show_correct_answer': False,
            'show_ox_mark': False,
            'show_score': True,
            'show_aspect': False,
            'mark_result_offset': 2,
            'descriptive_opacity': 0.30,
            'descriptive_show_mark': True,
            'descriptive_show_score': False,
            'descriptive_show_aspect': True,
        }
        app1.rendering_settings = get_rendering_settings(custom)
        app1._save_session_state()

        # 復元
        from constants import SESSION_STATE_FILE, RESULTS_FOLDER, RESULTS_DATA_FOLDER
        session_path = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER / SESSION_STATE_FILE
        with open(session_path, encoding='utf-8') as f:
            state = json.load(f)

        app2 = self._make_stub_app(str(self.img_folder))
        app2._apply_session_state(state)

        self.assertEqual(app2.rendering_settings, app1.rendering_settings)


if __name__ == "__main__":
    unittest.main()
