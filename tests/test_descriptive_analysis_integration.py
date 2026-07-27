#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
記述採点の分析チェックボックスのテスト

記述式のみモードでは記述採点は常に有効(チェックボックスは常に表示・ON固定)
であるため、GUI上のチェックボックス周りのみを検証する。
CTT/R Exportの記述問題統合そのものは test_v4_modes.py の
TestCTTDescriptiveOnly / TestRExportDescriptiveOnly で検証済み。
"""

import sys
from pathlib import Path

import pytest

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "main_src"))


class TestGUIDescriptiveCheckbox:
    """GUI の記述採点分析チェックボックスのテスト"""

    def test_include_descriptive_in_analysis_var_exists(self):
        """include_descriptive_in_analysis 変数が存在する"""
        import tkinter as tk
        from conftest import get_shared_tk_root
        root = get_shared_tk_root()

        from main_gui import Mark2GUI
        app = Mark2GUI(root)

        assert hasattr(app, 'include_descriptive_in_analysis')
        assert isinstance(app.include_descriptive_in_analysis, tk.BooleanVar)

    def test_include_descriptive_default_on(self):
        """デフォルトでON"""
        from conftest import get_shared_tk_root
        root = get_shared_tk_root()

        from main_gui import Mark2GUI
        app = Mark2GUI(root)

        assert app.include_descriptive_in_analysis.get() is True

    def test_checkbox_widget_exists(self):
        """チェックボックスウィジェットが存在する"""
        from conftest import get_shared_tk_root
        root = get_shared_tk_root()

        from main_gui import Mark2GUI
        app = Mark2GUI(root)

        assert hasattr(app, '_chk_include_desc_analysis')

    def test_checkbox_always_shown(self):
        """記述式のみモードではチェックボックスが常に表示される"""
        from conftest import get_shared_tk_root
        root = get_shared_tk_root()

        from main_gui import Mark2GUI
        app = Mark2GUI(root)

        info = app._chk_include_desc_analysis.pack_info()
        assert info is not None
