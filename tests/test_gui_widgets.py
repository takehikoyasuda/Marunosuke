#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUIウィジェットテスト — MarunosukeGUI の自動化可能なGUI検証
======================================================

記述式のみモード専用の MarunosukeGUI インスタンスを生成して以下を自動テスト:

1. 初期ウィジェット生成: ボタン・ラベル・入力欄が存在するか
2. 初期状態: テキスト・state 属性が期待通りか
3. 入力バリデーション: 各アクションの事前チェックが正しく動作するか
4. ボタン操作: invoke() で呼び出したときの状態遷移
5. log_message, select_folder 等の基本動作

Tkinter が利用できない環境では全テストを自動スキップする。
"""

import sys
import os
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

# Tk が使えない環境では全体スキップ
try:
    import tkinter as tk
    _root_test = tk.Tk()
    _root_test.withdraw()
    _root_test.destroy()
    _root_test = None
    HAS_TK = True
except Exception:
    HAS_TK = False

pytestmark = pytest.mark.skipif(not HAS_TK, reason="Tkinter not available")


# ================================================================
# テスト用ヘルパー
# ================================================================

def _make_gui():
    """MarunosukeGUI を Toplevel 上に生成して (top, app) を返す

    共有 Tk ルート上に Toplevel を作成し、テスト終了時に
    Toplevel のみ destroy する（Tcl インタプリタは残る）。
    """
    from conftest import get_shared_tk_root
    from main_gui import MarunosukeGUI
    root = get_shared_tk_root()
    top = tk.Toplevel(root)
    app = MarunosukeGUI(top)
    top.update_idletasks()
    return top, app


def _destroy_gui(top):
    """Toplevel を安全に破棄"""
    try:
        top.destroy()
    except Exception:
        pass


class TestColoredButton:
    """macOS向け独自ボタンのホバー表示を検証する。"""

    def setup_method(self):
        from conftest import get_shared_tk_root
        from main_gui import ColoredButton
        self.root = get_shared_tk_root()
        self.button = ColoredButton(
            self.root, text="テスト", bg="#90CAF9",
            activebackground="#42A5F5",
        )

    def teardown_method(self):
        self.button.destroy()

    def test_hover_restores_normal_background(self):
        self.button._on_enter()
        assert self.button.cget("bg") == "#42A5F5"
        assert self.button._normal_bg == "#90CAF9"

        self.button._on_leave()
        assert self.button.cget("bg") == "#90CAF9"
        assert self.button._label.cget("bg") == "#90CAF9"

    def test_pointer_events_are_bound_only_to_label(self):
        assert not self.button.bind("<Enter>")
        assert not self.button.bind("<Leave>")
        assert self.button._label.bind("<Enter>")
        assert self.button._label.bind("<Leave>")

    def test_same_hover_color_does_not_redraw(self):
        from main_gui import ColoredButton
        button = ColoredButton(
            self.root, text="採点結果を確認", bg="#90CAF9",
        )
        try:
            with patch.object(button._label, "config") as label_config, \
                    patch.object(tk.Frame, "config") as frame_config:
                button._on_enter()
                button._on_leave()

            label_config.assert_not_called()
            frame_config.assert_not_called()
            assert button._hovered is False
        finally:
            button.destroy()


# ================================================================
# 1. 初期状態テスト — ウィジェットの存在と属性
# ================================================================

class TestInitialState:
    """MarunosukeGUI の初期生成直後の状態を検証"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    def test_window_title(self):
        """ウィンドウタイトルが設定されている"""
        title = self.root.title()
        assert "マル之助" in title
        assert "v0.1.0" in title

    def test_window_geometry(self):
        """初期サイズが設定されている

        main_gui.MarunosukeGUI.__init__ は create_widgets() の後に
        fit_window_to_content(self.root, min_width=760, min_height=500) を
        呼び、コンテンツ量に応じてウィンドウを実サイズへ合わせる（最小値は
        そのfit_window_to_content呼び出しの引数と一致させること）。
        """
        # geometry は "WxH+X+Y" 形式
        geom = self.root.geometry()
        w, rest = geom.split("x", 1)
        h = rest.split("+")[0]
        assert int(w) >= 760, f"幅が小さすぎます: {w}"
        assert int(h) >= 500, f"高さが小さすぎます: {h}"

    def test_brand_icon_is_shown_in_header(self):
        """赤いマル之助アイコンをトップ画面のブランド要素として表示する。"""
        assert self.app._header_icon is not None
        assert self.app._header_icon.width() == 48
        assert self.app._header_icon.height() == 48

    def test_main_action_buttons_exist(self):
        """主要アクションボタンが存在する"""
        assert hasattr(self.app, '_btn_run_box')
        assert hasattr(self.app, '_btn_step2_more')
        assert hasattr(self.app, '_btn_run_scoring')
        assert hasattr(self.app, '_btn_run_summary')
        assert hasattr(self.app, 'desc_setup_btn')
        assert hasattr(self.app, 'desc_scoring_btn')

    def test_button_labels(self):
        """ボタンのテキストが期待通り"""
        assert "採点準備" in self.app._btn_run_box["text"]
        assert "採点準備をやり直す" in self.app.desc_setup_btn["text"]
        assert "採点実行" in self.app.desc_scoring_btn["text"]
        assert "採点済み答案" in self.app._btn_run_scoring["text"]
        assert "集計" in self.app._btn_run_summary["text"]

    def test_main_colored_buttons_do_not_repaint_on_hover(self):
        """macOSでちらつかないよう主要ボタンは背景色をホバー変更しない。"""
        buttons = (
            self.app._btn_run_box,
            self.app.desc_scoring_btn,
            self.app._btn_run_summary,
        )
        for button in buttons:
            assert button._active_bg == button._normal_bg

    def test_buttons_initially_normal(self):
        """Step 1 ボタンはフォルダ未設定時 disabled、Step 2/3 も disabled（Step 進行ガード）"""
        assert str(self.app._btn_run_box["state"]) == "disabled", "Step1 画像準備ボタンが disabled でない"

        step2_buttons = [
            self.app.desc_scoring_btn,
            self.app._btn_desc_review,
            self.app._btn_step2_more,
            self.app._btn_run_scoring,
        ]
        for btn in step2_buttons:
            assert str(btn["state"]) == "disabled", f"{btn['text']} should be disabled before Step 1"

        assert str(self.app._btn_run_summary["state"]) == "disabled", "集計ボタンが disabled でない"

    def test_folder_buttons_initially_disabled(self):
        """📁 ボタン（枠結果・採点結果・集計結果）は初期 disabled"""
        assert str(self.app.open_boxed_btn["state"]) == "disabled"
        assert str(self.app.open_scored_btn["state"]) == "disabled"
        assert str(self.app.open_results_btn["state"]) == "disabled"

    def test_input_variables_empty(self):
        """入力変数が初期状態で空"""
        assert self.app.image_folder_path.get() == ""

    def test_default_option_values(self):
        """オプションのデフォルト値が正しい"""
        assert self.app.skip_questions.get() == "4"
        # 記述式のみモードでは記述採点が常に有効
        assert self.app.descriptive_enabled.get() is True

    def test_descriptive_buttons_visible_by_default(self):
        """記述式のみモードでは記述ボタンが常に表示される。

        採点状況の詳細（_desc_status_frame）は、必要時の確認画面に
        移したためトップ画面には常設しない。
        """
        assert self.app.desc_setup_btn.winfo_manager() == "pack"
        assert self.app.desc_scoring_btn.winfo_manager() == "pack"
        assert self.app._desc_status_frame.winfo_manager() == ""

    def test_log_text_exists(self):
        """ログテキストウィジェットが存在する"""
        assert hasattr(self.app, 'log_text')
        # 初期状態で disabled (読み取り専用)
        assert str(self.app.log_text["state"]) == "disabled"

    def test_processing_flag_false(self):
        """初期状態で処理中フラグが False"""
        assert self.app._processing is False

# ================================================================
# 2. validate_inputs — 入力バリデーション
# ================================================================

class TestValidateInputs:
    """validate_inputs の全分岐を検証"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    @patch("main_gui.messagebox")
    def test_no_image_folder(self, mock_mb):
        """画像フォルダ未設定 → False"""
        result = self.app.validate_inputs()
        assert result is False
        mock_mb.showerror.assert_called_once()
        assert "画像フォルダ" in mock_mb.showerror.call_args[0][1]

    @patch("main_gui.messagebox")
    def test_image_folder_not_exist(self, mock_mb):
        """画像フォルダが存在しない → False"""
        self.app.image_folder_path.set("/nonexistent/folder")
        result = self.app.validate_inputs()
        assert result is False
        mock_mb.showerror.assert_called_once()
        assert "存在しません" in mock_mb.showerror.call_args[0][1]

    @patch("main_gui.messagebox")
    def test_invalid_skip_questions(self, mock_mb):
        """skip_questions が不正 → False"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app.skip_questions.set("abc")
            result = self.app.validate_inputs()
            assert result is False
            mock_mb.showerror.assert_called_once()
            assert "整数" in mock_mb.showerror.call_args[0][1]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("main_gui.messagebox")
    def test_negative_skip_questions(self, mock_mb):
        """skip_questions が負 → False"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app.skip_questions.set("-1")
            result = self.app.validate_inputs()
            assert result is False
            mock_mb.showerror.assert_called_once()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("main_gui.messagebox")
    def test_valid_inputs(self, mock_mb):
        """全項目が有効 → True"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app.skip_questions.set("4")
            result = self.app.validate_inputs()
            assert result is True
            mock_mb.showerror.assert_not_called()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================================
# 3. _prepare_images_for_descriptive — ガード条件
# ================================================================

class TestPrepareImagesGuard:
    """_prepare_images_for_descriptive (Step1 画像準備) の入力チェックと処理中ガード"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    @patch("main_gui.messagebox")
    def test_blocked_during_processing(self, mock_mb):
        """処理中は即 return"""
        self.app._processing = True
        self.app._prepare_images_for_descriptive()
        mock_mb.showerror.assert_not_called()

    @patch("main_gui.messagebox")
    def test_no_image_folder(self, mock_mb):
        """画像フォルダ未設定 → エラー"""
        self.app._prepare_images_for_descriptive()
        mock_mb.showerror.assert_called_once()
        assert "画像フォルダ" in mock_mb.showerror.call_args[0][1]

    @patch("main_gui.messagebox")
    def test_image_folder_not_exist(self, mock_mb):
        """画像フォルダが存在しない → エラー"""
        self.app.image_folder_path.set("/nonexistent/folder")
        self.app._prepare_images_for_descriptive()
        mock_mb.showerror.assert_called_once()
        assert "存在しません" in mock_mb.showerror.call_args[0][1]

    @patch("main_gui.messagebox")
    def test_no_images_in_folder(self, mock_mb):
        """画像ファイルがない → エラー"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app._prepare_images_for_descriptive()
            mock_mb.showerror.assert_called_once()
            assert "画像ファイル" in mock_mb.showerror.call_args[0][1]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================================
# 4. run_scoring — 入力チェック
# ================================================================

class TestRunScoringGuard:
    """run_scoring の入力バリデーション"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    @patch("main_gui.messagebox")
    def test_no_image_folder(self, mock_mb):
        self.app.run_scoring()
        mock_mb.showerror.assert_called_once()
        assert "画像フォルダ" in mock_mb.showerror.call_args[0][1]

    @patch("main_gui.messagebox")
    def test_no_descriptive_config(self, mock_mb):
        """記述設定ファイルなし → エラー"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app.run_scoring()
            mock_mb.showerror.assert_called_once()
            assert "記述" in mock_mb.showerror.call_args[0][1]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================================
# 5. run_summary_generation — 入力チェック
# ================================================================

class TestRunSummaryGuard:
    """run_summary_generation の入力バリデーション"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    @patch("main_gui.messagebox")
    def test_blocked_during_processing(self, mock_mb):
        self.app._processing = True
        self.app.run_summary_generation()
        mock_mb.showerror.assert_not_called()

    @patch("main_gui.messagebox")
    def test_no_image_folder(self, mock_mb):
        self.app.run_summary_generation()
        mock_mb.showerror.assert_called_once()
        assert "画像フォルダ" in mock_mb.showerror.call_args[0][1]

    @patch("main_gui.messagebox")
    def test_no_descriptive_config(self, mock_mb):
        """記述設定・記述採点結果がない → エラー"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app.run_summary_generation()
            mock_mb.showerror.assert_called_once()
            assert "採点領域" in mock_mb.showerror.call_args[0][1]
            assert "採点結果" in mock_mb.showerror.call_args[0][1]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================================
# 6. setup_total_position — 入力チェック
# ================================================================

class TestSetupTotalPositionGuard:
    """setup_total_position の事前チェック"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    @patch("main_gui.messagebox")
    def test_no_image_folder(self, mock_mb):
        self.app.setup_total_position()
        mock_mb.showerror.assert_called_once()
        assert "画像フォルダ" in mock_mb.showerror.call_args[0][1]

    @patch("main_gui.messagebox")
    def test_no_boxed_folder(self, mock_mb):
        """boxed_folder (00_Processing) が存在しない"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app.setup_total_position()
            mock_mb.showerror.assert_called_once()
            assert "補正済み画像" in mock_mb.showerror.call_args[0][1]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("main_gui.messagebox")
    def test_no_images_in_boxed_folder(self, mock_mb):
        """boxed_folder は存在するがJPG/PNGなし"""
        tmpdir = tempfile.mkdtemp()
        try:
            boxed = Path(tmpdir) / "_saiten_grading_results" / "00_Processing"
            boxed.mkdir(parents=True)
            self.app.image_folder_path.set(tmpdir)
            self.app.setup_total_position()
            mock_mb.showerror.assert_called_once()
            assert "見つかりません" in mock_mb.showerror.call_args[0][1]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================================
# 7. run_descriptive_scoring — 入力チェック
# ================================================================

class TestRunDescriptiveScoringGuard:
    """run_descriptive_scoring の事前チェック"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    @patch("main_gui.messagebox")
    def test_no_image_folder(self, mock_mb):
        self.app.run_descriptive_scoring()
        mock_mb.showerror.assert_called_once()
        assert "画像フォルダ" in mock_mb.showerror.call_args[0][1]

    @patch("main_gui.messagebox")
    def test_no_descriptive_config(self, mock_mb):
        """記述問題設定なし → エラー"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app.run_descriptive_scoring()
            mock_mb.showerror.assert_called_once()
            assert "記述" in mock_mb.showerror.call_args[0][1]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================================
# 8. log_message — ログ表示
# ================================================================

class TestLogMessage:
    """log_message の基本動作"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    def test_log_appends_text(self):
        """メッセージがログに追加される"""
        self.app.log_message("テスト行1")
        self.app.log_message("テスト行2")
        content = self.app.log_text.get("1.0", tk.END)
        assert "テスト行1" in content
        assert "テスト行2" in content

    def test_log_replace_last(self):
        """replace_last=True で最終行が上書きされる"""
        self.app.log_message("行1")
        self.app.log_message("行2 (消される)")
        self.app.log_message("行2 (置換)", replace_last=True)
        content = self.app.log_text.get("1.0", tk.END)
        assert "行1" in content
        assert "行2 (置換)" in content
        # 上書きされた行は残っていないはず
        assert "行2 (消される)" not in content

    def test_log_text_stays_disabled(self):
        """ログ書き込み後も状態は disabled"""
        self.app.log_message("test")
        assert str(self.app.log_text["state"]) == "disabled"


# ================================================================
# 9. _set_processing_state — 状態遷移
# ================================================================

class TestProcessingState:
    """処理中/待機中の状態切り替え"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    def test_busy_disables_all(self):
        """busy=True → 全アクションボタン disabled"""
        self.app._set_processing_state(True)
        self.root.update_idletasks()

        assert self.app._processing is True
        for btn in [self.app._btn_run_box, self.app._btn_step2_more,
                     self.app._btn_run_scoring, self.app._btn_run_summary,
                     self.app.desc_setup_btn, self.app.desc_scoring_btn]:
            assert str(btn["state"]) == "disabled"

    def test_idle_enables_all(self):
        """busy=False → _processing解除 & Stepガードに従いボタン状態復元"""
        self.app._set_processing_state(True)
        self.app._set_processing_state(False)
        self.root.update_idletasks()

        assert self.app._processing is False
        # ガード対象外の desc_setup_btn は常に normal に戻る
        assert str(self.app.desc_setup_btn["state"]) == "normal"

    def test_progress_bar_visibility(self):
        """busy=True でプログレスバー表示、False で非表示"""
        self.app._set_processing_state(True)
        self.root.update_idletasks()
        assert self.app._progress_bar.winfo_manager() == "pack"

        self.app._set_processing_state(False)
        self.root.update_idletasks()
        assert self.app._progress_bar.winfo_manager() == ""

    def test_processing_area_height_does_not_change(self):
        """処理開始・終了で処理状況エリアの確保済み高さを変えない。

        処理状況エリア（log_frame）自体は詳細ログを別ウィンドウへ
        移したためトップ画面には常設しない。それでも、内部の
        _processing_frame は表示時にレイアウトが上下しないよう、
        高さ42を要求し続けることを確認する。
        """
        self.root.update_idletasks()
        idle_height = self.app._processing_frame.winfo_reqheight()

        self.app._set_processing_state(True)
        self.root.update_idletasks()
        busy_height = self.app._processing_frame.winfo_reqheight()

        self.app._set_processing_state(False)
        self.root.update_idletasks()

        assert idle_height == busy_height == 42


# ================================================================
# 10. select_folder — フォルダ選択チェーン
# ================================================================

class TestSelectFolderChain:
    """select_folder がコールバックチェーンを正しく起動するか"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    @patch("main_gui.filedialog")
    def test_cancel_does_nothing(self, mock_fd):
        """キャンセル時はフォルダ変更なし"""
        mock_fd.askdirectory.return_value = ""
        self.app.select_folder()
        assert self.app.image_folder_path.get() == ""

    @patch("main_gui.filedialog")
    def test_folder_selected_only_sets_path(self, mock_fd):
        """フォルダ選択は作業スペースの反映と _try_auto_restore のみ行い、
        画像準備・複数ページ管理は開始しない（Step3で明示的に進める）。
        """
        tmpdir = tempfile.mkdtemp()
        try:
            Path(tmpdir, "answer.png").touch()
            mock_fd.askdirectory.return_value = tmpdir
            with patch.object(self.app, '_try_auto_restore') as mock_restore, \
                 patch.object(self.app, '_prepare_images_for_descriptive') as mock_prepare, \
                 patch.object(self.app, 'run_multi_page_merge') as mock_multi_page:
                self.app.select_folder()
                assert self.app.image_folder_path.get() == tmpdir
                mock_restore.assert_called_once()
                mock_prepare.assert_not_called()
                mock_multi_page.assert_not_called()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================================
# 11. _start_answer_prep — Step3「答案ファイル追加＆採点準備」の分岐
# ================================================================

class TestStartAnswerPrep:
    """_start_answer_prep が画像案件・PDF案件を正しく振り分けるか"""

    def setup_method(self):
        self.root, self.app = _make_gui()

    def teardown_method(self):
        _destroy_gui(self.root)

    @patch("main_gui.messagebox")
    def test_requires_folder(self, mock_mb):
        """作業スペース未選択 → エラー"""
        self.app._start_answer_prep()
        mock_mb.showerror.assert_called_once()

    @patch("main_gui.messagebox")
    def test_requires_pages_confirmed(self, mock_mb):
        """ページ数未確定 → エラー"""
        tmpdir = tempfile.mkdtemp()
        try:
            self.app.image_folder_path.set(tmpdir)
            self.app._start_answer_prep()
            mock_mb.showerror.assert_called_once()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_image_folder_prepares_directly(self):
        """画像案件は追加画面を開かず、そのまま採点準備を実行する"""
        tmpdir = tempfile.mkdtemp()
        try:
            Path(tmpdir, "answer.png").touch()
            self.app.image_folder_path.set(tmpdir)
            self.app._pages_confirmed = True
            with patch.object(self.app, '_prepare_images_for_descriptive') as mock_prepare, \
                 patch.object(self.app, 'run_multi_page_merge') as mock_multi_page:
                self.app._start_answer_prep()
                mock_prepare.assert_called_once_with(auto_start_setup=True)
                mock_multi_page.assert_not_called()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_pdf_folder_without_import_opens_add_dialog(self):
        """PDF案件で何も取り込まれていなければ、追加専用画面を開く"""
        tmpdir = tempfile.mkdtemp()
        try:
            Path(tmpdir, "page1.pdf").touch()
            self.app.image_folder_path.set(tmpdir)
            self.app._pages_confirmed = True
            with patch.object(self.app, '_prepare_images_for_descriptive') as mock_prepare, \
                 patch.object(self.app, 'run_multi_page_merge') as mock_multi_page:
                self.app._start_answer_prep()
                mock_prepare.assert_not_called()
                mock_multi_page.assert_called_once()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_pdf_folder_with_import_skips_dialog(self):
        """PDF案件で既に答案が取り込まれていれば、追加画面を開かず直接
        採点準備（アクティブページのワークスペース準備）へ進む。
        """
        tmpdir = tempfile.mkdtemp()
        try:
            Path(tmpdir, "page1.pdf").touch()
            self.app.image_folder_path.set(tmpdir)
            self.app._pages_confirmed = True
            with patch.object(self.app, '_try_continue_multi_page_prep', return_value=True) as mock_continue, \
                 patch.object(self.app, 'run_multi_page_merge') as mock_multi_page:
                self.app._start_answer_prep()
                mock_continue.assert_called_once()
                mock_multi_page.assert_not_called()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
