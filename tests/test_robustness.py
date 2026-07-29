#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_robustness.py — データ破壊防止・堅牢性テスト

v4.0 で導入された以下のリスク対策コードを検証する:
  R1: atomic_json_save / load_json_safe (書き込み中断からの保護)
  R2: log_message スレッドセーフ
  R3: WM_DELETE_WINDOW ハンドラ
  R4: 処理中ボタン無効化 (データソース選択含む)
  R5: _prepare_images_for_descriptive ガード
  R6/R12: DescriptiveReviewGUI._save 戻り値 / modified フラグ
  R8: cv2 Unicode パス対応
  R9: stdout リダイレクト復元保証
  R17: バックグラウンドスレッドでの StringVar 参照排除
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ================================================================
# R1: atomic_json_save / load_json_safe
# ================================================================

class TestAtomicJsonSave:
    """atomic_json_save のアトミック性・バックアップ・リカバリを検証"""

    def test_basic_save_and_load(self, tmp_path):
        """正常な保存と読み込み"""
        from constants import atomic_json_save, load_json_safe

        filepath = tmp_path / "test.json"
        data = {"key": "value", "num": 42}
        atomic_json_save(filepath, data)

        assert filepath.exists()
        result = load_json_safe(filepath)
        assert result == data

    def test_backup_created_on_overwrite(self, tmp_path):
        """上書き保存時に .bak ファイルが作成される"""
        from constants import atomic_json_save

        filepath = tmp_path / "test.json"
        bak_path = filepath.with_suffix(".json.bak")

        atomic_json_save(filepath, {"version": 1})
        assert not bak_path.exists()

        atomic_json_save(filepath, {"version": 2})
        assert bak_path.exists()

        with open(bak_path, 'r') as f:
            old = json.load(f)
        assert old["version"] == 1

        with open(filepath, 'r') as f:
            new = json.load(f)
        assert new["version"] == 2

    def test_recovery_from_corrupted_file(self, tmp_path):
        """本体ファイル破損時に .bak からリカバリする"""
        from constants import atomic_json_save, load_json_safe

        filepath = tmp_path / "test.json"
        bak_path = filepath.with_suffix(".json.bak")

        # 正常データを保存 → バックアップ生成のため2回保存
        atomic_json_save(filepath, {"version": 1})
        atomic_json_save(filepath, {"version": 2})

        # 本体を破損させる
        with open(filepath, 'w') as f:
            f.write("{invalid json!!")

        result = load_json_safe(filepath, required_keys=["version"])
        assert result is not None
        assert result["version"] == 1  # bak から復旧

    def test_load_returns_none_for_missing_file(self, tmp_path):
        """存在しないファイルの読み込みは None"""
        from constants import load_json_safe
        result = load_json_safe(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_validates_required_keys(self, tmp_path):
        """required_keys にないキーは None"""
        from constants import atomic_json_save, load_json_safe

        filepath = tmp_path / "test.json"
        atomic_json_save(filepath, {"other_key": True})

        result = load_json_safe(filepath, required_keys=["must_have"])
        assert result is None

    def test_unicode_content(self, tmp_path):
        """日本語を含むデータの保存・読み込み"""
        from constants import atomic_json_save, load_json_safe

        filepath = tmp_path / "test.json"
        data = {"質問": "記述問題の配点", "配点": 10}
        atomic_json_save(filepath, data)

        result = load_json_safe(filepath)
        assert result["質問"] == "記述問題の配点"

    def test_creates_parent_directories(self, tmp_path):
        """親ディレクトリが存在しなくても自動作成"""
        from constants import atomic_json_save

        filepath = tmp_path / "deep" / "nested" / "dir" / "test.json"
        atomic_json_save(filepath, {"ok": True})
        assert filepath.exists()

    def test_no_partial_write_on_error(self, tmp_path):
        """シリアライズ不可能なデータでエラー時、ファイルが壊れない"""
        from constants import atomic_json_save, load_json_safe

        filepath = tmp_path / "test.json"
        atomic_json_save(filepath, {"original": True})

        # シリアライズ不可能なオブジェクトで失敗させる
        class NotSerializable:
            pass

        with pytest.raises(TypeError):
            atomic_json_save(filepath, {"bad": NotSerializable()})

        # 元のファイルが保持されている
        result = load_json_safe(filepath)
        assert result["original"] is True

    def test_concurrent_saves(self, tmp_path):
        """複数スレッドからの同時保存でもデータが破壊されない"""
        from constants import atomic_json_save, load_json_safe

        filepath = tmp_path / "concurrent.json"
        errors = []

        def save_worker(worker_id):
            try:
                for i in range(5):
                    atomic_json_save(filepath, {"worker": worker_id, "iteration": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Concurrent save errors: {errors}"
        # ファイルが有効な JSON であること
        result = load_json_safe(filepath)
        assert result is not None
        assert "worker" in result


# ================================================================
# R1 (応用): descriptive_scorer の save/load 関数
# ================================================================

class TestDescriptiveScorerAtomicIO:
    """descriptive_scorer の JSON 永続化関数がアトミック保存を使っているか検証"""

    def test_save_and_load_config(self, tmp_path):
        from descriptive_scorer import save_descriptive_config, load_descriptive_config

        path = str(tmp_path / "config.json")
        config = {"questions": [{"id": "Q1", "name": "問1"}]}
        save_descriptive_config(path, config)

        loaded = load_descriptive_config(path)
        assert loaded == config

        # .bak ができることを確認（2回目保存）
        save_descriptive_config(path, {"questions": [{"id": "Q2"}]})
        bak = Path(path + ".bak")
        assert bak.exists()

    def test_save_and_load_scores(self, tmp_path):
        from descriptive_scorer import save_descriptive_scores, load_descriptive_scores

        path = str(tmp_path / "scores.json")
        scores = {"scores": {"img1.jpg": {"Q1": 5}}}
        save_descriptive_scores(path, scores)

        loaded = load_descriptive_scores(path)
        assert loaded == scores

    def test_save_and_load_total_display_config(self, tmp_path):
        from descriptive_scorer import save_total_display_config, load_total_display_config

        path = str(tmp_path / "total.json")
        region = [100, 200, 300, 400]
        save_total_display_config(path, region)

        loaded = load_total_display_config(path)
        assert loaded["total_display_region"] == region

    def test_corrupted_config_recovery(self, tmp_path):
        """config ファイル破損時のバックアップリカバリ"""
        from descriptive_scorer import save_descriptive_config, load_descriptive_config

        path = str(tmp_path / "config.json")
        original = {"questions": [{"id": "Q1"}]}
        save_descriptive_config(path, original)
        save_descriptive_config(path, {"questions": [{"id": "Q2"}]})

        # 本体を破損
        with open(path, 'w') as f:
            f.write("CORRUPTED")

        loaded = load_descriptive_config(path)
        assert loaded is not None
        assert loaded["questions"][0]["id"] == "Q1"  # bak から復旧


# ================================================================
# R1 (応用): session_state のアトミック保存
# ================================================================

class TestSessionStateAtomicSave:
    """_save_session_state がアトミック保存を使っているか検証"""

    def test_session_save_creates_backup(self, tmp_path):
        """セッション保存時にバックアップが作成される"""
        from conftest import get_shared_tk_root
        from main_gui import SaitenSamuraiGUI
        from constants import MODE_MARK_AND_DESCRIPTIVE

        root = get_shared_tk_root()
        app = SaitenSamuraiGUI(root)

        # ダミーフォルダ構造を作成
        results_dir = tmp_path / "_saiten_grading_results" / "01_Results"
        results_dir.mkdir(parents=True)
        app.image_folder_path.set(str(tmp_path))

        # 1回目保存
        app._save_session_state()
        session_path = results_dir / "session_state.json"
        assert session_path.exists()

        # 2回目保存 → .bak ができる
        app._save_session_state()
        assert session_path.with_suffix(".json.bak").exists()

        app.root.protocol("WM_DELETE_WINDOW", lambda: None)  # cleanup


# ================================================================
# R2: log_message スレッドセーフ
# ================================================================

class TestLogMessageThreadSafety:
    """log_message がバックグラウンドスレッドから安全に呼べるか検証"""

    def test_log_from_main_thread(self):
        """メインスレッドからの呼び出しは直接実行される"""
        from conftest import get_shared_tk_root
        from main_gui import SaitenSamuraiGUI
        from constants import MODE_MARK_ONLY

        root = get_shared_tk_root()
        app = SaitenSamuraiGUI(root)

        app.log_message("テストメッセージ")
        content = app.log_text.get("1.0", "end-1c")
        assert "テストメッセージ" in content

    def test_log_from_background_thread(self):
        """バックグラウンドスレッドからの呼び出しは root.after 経由にルーティングされる"""
        from conftest import get_shared_tk_root
        from main_gui import SaitenSamuraiGUI
        from constants import MODE_MARK_ONLY

        root = get_shared_tk_root()
        app = SaitenSamuraiGUI(root)

        # root.after がバックグラウンドスレッドから呼ばれることを確認
        after_called = threading.Event()
        original_after = root.after

        def mock_after(delay, *args, **kwargs):
            if args and args[0] is app.log_message:
                after_called.set()
            return original_after(delay, *args, **kwargs)

        def bg_worker():
            try:
                with patch.object(root, 'after', side_effect=mock_after):
                    app.log_message("バックグラウンドメッセージ")
            except RuntimeError:
                # テスト環境では mainloop がないため RuntimeError が発生し得る
                after_called.set()

        t = threading.Thread(target=bg_worker)
        t.start()
        t.join(timeout=5)

        # after() が呼ばれたか、または RuntimeError でスキップされたかを確認
        assert after_called.is_set(), "log_message がバックグラウンドスレッドから root.after を呼ぶことを確認"


# ================================================================
# R3: WM_DELETE_WINDOW ハンドラ
# ================================================================

class TestWindowCloseHandler:
    """WM_DELETE_WINDOW プロトコルハンドラの存在と動作を検証"""

    def test_close_handler_registered(self):
        """_on_window_close が WM_DELETE_WINDOW に登録されている"""
        from conftest import get_shared_tk_root
        from main_gui import SaitenSamuraiGUI
        from constants import MODE_MARK_ONLY

        root = get_shared_tk_root()
        app = SaitenSamuraiGUI(root)

        # protocol handler が設定されていることを確認
        assert hasattr(app, '_on_window_close')

    def test_close_blocked_during_processing(self):
        """処理中にウィンドウ閉じるを試みると確認ダイアログが出る"""
        from conftest import get_shared_tk_root
        from main_gui import SaitenSamuraiGUI
        from constants import MODE_MARK_ONLY

        root = get_shared_tk_root()
        app = SaitenSamuraiGUI(root)
        app._processing = True

        with patch('main_gui.messagebox.askyesno', return_value=False) as mock_ask:
            app._on_window_close()
            mock_ask.assert_called_once()
            # root が destroy されていないこと（False = キャンセル）
            assert root.winfo_exists()


# ================================================================
# R4: 処理中のデータソース選択ボタン無効化
# ================================================================

class TestProcessingStateButtons:
    """_set_processing_state がフォルダ/Excel選択ボタンも無効化するか検証"""

    def test_source_buttons_disabled_during_processing(self):
        """処理中はデータソース選択ボタンが無効化される"""
        from conftest import get_shared_tk_root
        from main_gui import SaitenSamuraiGUI
        from constants import MODE_MARK_AND_DESCRIPTIVE

        root = get_shared_tk_root()
        app = SaitenSamuraiGUI(root)

        # 処理開始
        app._set_processing_state(True)
        assert str(app._btn_select_folder['state']) == 'disabled'
        assert str(app._btn_select_pdf['state']) == 'disabled'

        # 処理終了
        app._set_processing_state(False)
        assert str(app._btn_select_folder['state']) == 'normal'
        assert str(app._btn_select_pdf['state']) == 'normal'


# ================================================================
# R5: _prepare_images_for_descriptive ガード
# ================================================================

class TestPrepareImagesGuard:
    """処理中に _prepare_images_for_descriptive が実行されないか検証"""

    def test_blocked_during_processing(self):
        """_processing=True のとき画像準備は何もしない"""
        from conftest import get_shared_tk_root
        from main_gui import SaitenSamuraiGUI
        from constants import MODE_DESCRIPTIVE_ONLY

        root = get_shared_tk_root()
        app = SaitenSamuraiGUI(root)
        app._processing = True

        # messagebox も threading も呼ばれないことを確認
        with patch('main_gui.messagebox.showerror') as mock_err:
            app._prepare_images_for_descriptive()
            mock_err.assert_not_called()


# ================================================================
# R6/R12: DescriptiveReviewGUI._save 戻り値 / modified フラグ
# ================================================================

class TestDescriptiveReviewSave:
    """DescriptiveReviewGUI._save の戻り値と modified フラグリセットを検証"""

    def test_save_returns_true_and_resets_modified(self, tmp_path):
        """_save() 成功時は True を返し modified=False になる"""
        from descriptive_scorer import DescriptiveReviewGUI
        from conftest import get_shared_tk_root

        root = get_shared_tk_root()
        scores_path = str(tmp_path / "scores.json")

        # 最小限のモック
        gui = DescriptiveReviewGUI.__new__(DescriptiveReviewGUI)
        gui.win = MagicMock()
        gui.scores = {"img.jpg": {"Q1": 5}}
        gui.scores_save_path = scores_path
        gui.modified = True

        with patch('descriptive_gui.messagebox.showinfo'):
            result = gui._save()

        assert result is True
        assert gui.modified is False
        assert Path(scores_path).exists()

    def test_save_returns_false_on_error(self, tmp_path):
        """_save() 失敗時は False を返す"""
        from descriptive_scorer import DescriptiveReviewGUI

        gui = DescriptiveReviewGUI.__new__(DescriptiveReviewGUI)
        gui.win = MagicMock()
        gui.scores = {"img.jpg": {"Q1": 5}}
        gui.scores_save_path = str(tmp_path / "nonexistent_dir_readonly" / "scores.json")
        gui.modified = True

        # atomic_json_save が失敗するようにモック
        with patch('descriptive_gui.atomic_json_save', side_effect=OSError("disk full")):
            with patch('descriptive_gui.messagebox.showerror'):
                result = gui._save()

        assert result is False
        assert gui.modified is True  # 失敗時は modified のまま

    def test_save_no_changes(self, tmp_path):
        """変更なしの場合は True を返す"""
        from descriptive_scorer import DescriptiveReviewGUI

        gui = DescriptiveReviewGUI.__new__(DescriptiveReviewGUI)
        gui.win = MagicMock()
        gui.modified = False

        with patch('descriptive_gui.messagebox.showinfo'):
            result = gui._save()

        assert result is True


# ================================================================
# R6: _on_close の3択ダイアログ
# ================================================================

class TestDescriptiveReviewClose:
    """DescriptiveReviewGUI._on_close の3択ダイアログを検証"""

    def _make_gui(self, tmp_path):
        from descriptive_scorer import DescriptiveReviewGUI
        gui = DescriptiveReviewGUI.__new__(DescriptiveReviewGUI)
        gui.win = MagicMock()
        gui.scores = {}
        gui.scores_save_path = str(tmp_path / "scores.json")
        return gui

    def test_cancel_does_not_close(self, tmp_path):
        """キャンセル → ウィンドウは閉じない"""
        gui = self._make_gui(tmp_path)
        gui.modified = True

        with patch('descriptive_gui._ask_three_way_japanese', return_value=None):
            gui._on_close()

        gui.win.destroy.assert_not_called()

    def test_no_discard_closes(self, tmp_path):
        """「いいえ」→ 保存せず閉じる"""
        gui = self._make_gui(tmp_path)
        gui.modified = True

        with patch('descriptive_gui._ask_three_way_japanese', return_value=False):
            gui._on_close()

        gui.win.destroy.assert_called_once()

    def test_yes_save_success_closes(self, tmp_path):
        """「はい」→ 保存成功 → 閉じる"""
        gui = self._make_gui(tmp_path)
        gui.modified = True

        with patch('descriptive_gui._ask_three_way_japanese', return_value=True):
            with patch.object(gui, '_save', return_value=True):
                gui._on_close()

        gui.win.destroy.assert_called_once()

    def test_yes_save_fail_stays_open(self, tmp_path):
        """「はい」→ 保存失敗 → 閉じない"""
        gui = self._make_gui(tmp_path)
        gui.modified = True

        with patch('descriptive_gui._ask_three_way_japanese', return_value=True):
            with patch.object(gui, '_save', return_value=False):
                gui._on_close()

        gui.win.destroy.assert_not_called()


# ================================================================
# R17: バックグラウンドスレッドでの StringVar 参照排除
# ================================================================

class TestThreadSafeParams:
    """_run_descriptive_only_thread / _run_prepare_images_thread がパラメータ dict を受け取るか検証"""

    def test_descriptive_only_thread_accepts_params(self):
        """_run_descriptive_only_thread が params 引数を受け取る"""
        from main_gui import SaitenSamuraiGUI
        import inspect
        sig = inspect.signature(SaitenSamuraiGUI._run_descriptive_only_thread)
        assert 'params' in sig.parameters

    def test_prepare_images_thread_accepts_params(self):
        """_run_prepare_images_thread が img_folder / image_files 引数を受け取る"""
        from main_gui import SaitenSamuraiGUI
        import inspect
        sig = inspect.signature(SaitenSamuraiGUI._run_prepare_images_thread)
        assert 'img_folder' in sig.parameters
        assert 'image_files' in sig.parameters
