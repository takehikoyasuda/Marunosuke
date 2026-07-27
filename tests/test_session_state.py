#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 1+2 テスト: セッション状態保存/復元 + 記述ステータス
============================================================

テスト対象:
- SESSION_STATE_FILE 定数
- _save_session_state / _load_session_state のラウンドトリップ
- _check_descriptive_completeness 各状態
- _update_descriptive_status ラベル内容
- _get_session_state_path パス構成
- _apply_session_state
- _try_auto_restore
"""

import sys
import os
import json
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import tkinter as tk

# プロジェクトパス追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "main_src"))

from saitensamurai import (
    SESSION_STATE_FILE,
    RESULTS_FOLDER,
    RESULTS_DATA_FOLDER,
    BOXED_FOLDER,
    ANSWER_KEY_FILE,
    Mark2GUI,
)


# =================================================================
# テスト全体で共有する Tk ルートウィンドウ（conftest.py 経由）
# =================================================================

from conftest import get_shared_tk_root


def _get_root():
    return get_shared_tk_root()


def tearDownModule():
    """モジュール終了時: 共有ルートは conftest が管理するため何もしない"""
    pass


# =================================================================
# ヘルパー: Mark2GUI の軽量スタブ
# =================================================================

def _make_stub_app(img_folder=""):
    """Mark2GUI の軽量スタブ（__init__ をスキップ）"""
    root = _get_root()
    app = object.__new__(Mark2GUI)

    # tkinter 変数
    app.root = root
    app.image_folder_path = tk.StringVar(root, value=img_folder)
    app.skip_questions = tk.StringVar(root, value="4")
    app.descriptive_enabled = tk.BooleanVar(root, value=True)

    # 描画詳細設定
    from constants import get_rendering_settings
    app.rendering_settings = get_rendering_settings()

    # ログメッセージ用スタブ
    app._log_messages = []

    def log_message(msg):
        app._log_messages.append(msg)

    app.log_message = log_message

    # 記述ステータスラベル
    app._desc_status_label = tk.Label(root)
    app._desc_status_frame = tk.Frame(root)

    return app


# =================================================================
# テストクラス
# =================================================================

class TestSessionStateConstant(unittest.TestCase):
    """SESSION_STATE_FILE 定数の存在確認"""

    def test_constant_exists(self):
        self.assertEqual(SESSION_STATE_FILE, "session_state.json")


class TestSessionStateSaveLoad(unittest.TestCase):
    """_save_session_state / _load_session_state のラウンドトリップ"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.img_folder = Path(self.tmpdir) / "images"
        self.img_folder.mkdir()
        self.results_data = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        self.results_data.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_creates_json(self):
        """_save_session_state でファイルが作成される"""
        app = _make_stub_app(str(self.img_folder))
        app._save_session_state()

        session_path = self.results_data / SESSION_STATE_FILE
        self.assertTrue(session_path.exists())

        with open(session_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data["version"], 1)
        self.assertIn("saved_at", data)

    def test_roundtrip(self):
        """保存→読込でデータが保持される"""
        app = _make_stub_app(str(self.img_folder))

        app.skip_questions.set("3")
        app._save_session_state()

        # 別のスタブで読み込み
        session_path = self.results_data / SESSION_STATE_FILE
        app2 = _make_stub_app(str(self.img_folder))
        data = app2._load_session_state(session_path)

        self.assertIsNotNone(data)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["skip_questions"], "3")

    def test_load_invalid_json(self):
        """不正なJSONファイルの場合 None を返す"""
        app = _make_stub_app(str(self.img_folder))
        bad_path = self.results_data / "bad.json"
        bad_path.write_text("not valid json", encoding='utf-8')

        result = app._load_session_state(bad_path)
        self.assertIsNone(result)

    def test_load_missing_version(self):
        """version キーがないJSONは None を返す"""
        app = _make_stub_app(str(self.img_folder))
        bad_path = self.results_data / "no_version.json"
        bad_path.write_text('{"key": "val"}', encoding='utf-8')

        result = app._load_session_state(bad_path)
        self.assertIsNone(result)

    def test_load_nonexistent(self):
        """存在しないファイルの場合 None を返す"""
        app = _make_stub_app(str(self.img_folder))
        result = app._load_session_state(Path("/nonexistent/path.json"))
        self.assertIsNone(result)

    def test_save_no_folder(self):
        """画像フォルダが未設定の場合は何もしない（エラーなし）"""
        app = _make_stub_app("")
        app._save_session_state()
        # エラーが出ないこと
        self.assertTrue(True)

class TestGetSessionStatePath(unittest.TestCase):
    """_get_session_state_path のテスト"""

    def test_returns_path_when_folder_set(self):
        app = _make_stub_app("C:/test/images")
        p = app._get_session_state_path()
        self.assertIsNotNone(p)
        self.assertEqual(p.name, SESSION_STATE_FILE)
        self.assertIn(RESULTS_FOLDER, str(p))
        self.assertIn(RESULTS_DATA_FOLDER, str(p))

    def test_returns_none_when_folder_empty(self):
        app = _make_stub_app("")
        p = app._get_session_state_path()
        self.assertIsNone(p)


class TestApplySessionState(unittest.TestCase):
    """_apply_session_state のテスト"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.img_folder = Path(self.tmpdir) / "images"
        self.img_folder.mkdir()
        self.results_data = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        self.results_data.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_apply_with_valid_paths(self):
        """画像フォルダが有効な場合、正常に復元される"""
        state = {
            "version": 1,
            "image_folder": str(self.img_folder),
            "skip_questions": "5",
        }

        app = _make_stub_app(str(self.img_folder))
        result = app._apply_session_state(state)

        self.assertTrue(result)
        self.assertEqual(app.skip_questions.get(), "5")

    @patch("main_gui.messagebox")
    def test_apply_with_missing_image_folder(self, mock_msgbox):
        """画像フォルダが存在しない場合 False を返す"""
        state = {
            "version": 1,
            "image_folder": "/nonexistent/folder",
        }

        app = _make_stub_app()
        result = app._apply_session_state(state)

        self.assertFalse(result)
        mock_msgbox.showerror.assert_called_once()


class TestDescriptiveCompletenessCheck(unittest.TestCase):
    """_check_descriptive_completeness のテスト"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.img_folder = Path(self.tmpdir) / "images"
        self.img_folder.mkdir()
        self.results_data = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        self.results_data.mkdir(parents=True)
        self.boxed_folder = self.img_folder / RESULTS_FOLDER / BOXED_FOLDER
        self.boxed_folder.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_config(self, questions):
        config = {"questions": questions}
        config_path = self.results_data / "descriptive_config.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)

    def _make_scores(self, scores_dict):
        data = {"scores": scores_dict}
        scores_path = self.results_data / "descriptive_scores.json"
        with open(scores_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)

    def _make_images(self, names):
        for name in names:
            (self.boxed_folder / name).touch()

    def test_all_scored(self):
        """全画像・全問題が採点済み → is_complete=True"""
        questions = [
            {"id": "Q1", "name": "問1", "max_score": 5},
            {"id": "Q2", "name": "問2", "max_score": 3},
        ]
        self._make_config(questions)
        self._make_images(["img001.jpg", "img002.jpg"])
        self._make_scores({
            "img001.jpg": {"Q1": 3, "Q2": 2},
            "img002.jpg": {"Q1": 5, "Q2": 1},
        })

        app = _make_stub_app(str(self.img_folder))
        is_complete, unscored, total, detail = app._check_descriptive_completeness()

        self.assertTrue(is_complete)
        self.assertEqual(unscored, 0)
        self.assertEqual(total, 2)
        self.assertEqual(len(detail), 0)

    def test_partial_scored(self):
        """一部画像が未採点 → is_complete=False"""
        questions = [{"id": "Q1", "name": "問1", "max_score": 5}]
        self._make_config(questions)
        self._make_images(["img001.jpg", "img002.jpg", "img003.jpg"])
        self._make_scores({"img001.jpg": {"Q1": 3}})

        app = _make_stub_app(str(self.img_folder))
        is_complete, unscored, total, detail = app._check_descriptive_completeness()

        self.assertFalse(is_complete)
        self.assertEqual(unscored, 2)
        self.assertEqual(total, 3)
        self.assertTrue(len(detail) > 0)

    def test_no_images(self):
        """画像が0枚 → is_complete=False"""
        questions = [{"id": "Q1", "name": "問1", "max_score": 5}]
        self._make_config(questions)

        app = _make_stub_app(str(self.img_folder))
        is_complete, unscored, total, detail = app._check_descriptive_completeness()

        self.assertFalse(is_complete)
        self.assertEqual(total, 0)

    def test_no_config(self):
        """設定が空 → is_complete=False"""
        self._make_config([])
        self._make_images(["img001.jpg"])

        app = _make_stub_app(str(self.img_folder))
        is_complete, unscored, total, detail = app._check_descriptive_completeness()

        self.assertFalse(is_complete)
        self.assertIn("設定されていません", detail[0])

    def test_no_scores_file(self):
        """採点ファイルが存在しない → 全画像が未採点"""
        questions = [{"id": "Q1", "name": "問1", "max_score": 5}]
        self._make_config(questions)
        self._make_images(["img001.jpg", "img002.jpg"])

        app = _make_stub_app(str(self.img_folder))
        is_complete, unscored, total, detail = app._check_descriptive_completeness()

        self.assertFalse(is_complete)
        self.assertEqual(unscored, 2)


class TestUpdateDescriptiveStatus(unittest.TestCase):
    """_update_descriptive_status のラベルテキスト検証"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.img_folder = Path(self.tmpdir) / "images"
        self.img_folder.mkdir()
        self.results_data = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        self.results_data.mkdir(parents=True)
        self.boxed_folder = self.img_folder / RESULTS_FOLDER / BOXED_FOLDER
        self.boxed_folder.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_folder(self):
        """フォルダ未設定 → 'フォルダ未選択' 表示"""
        app = _make_stub_app("")
        app.descriptive_enabled.set(True)
        app._update_descriptive_status()
        text = app._desc_status_label.cget("text")
        self.assertIn("フォルダ未選択", text)

    def test_no_config(self):
        """config が存在しない → '未設定' 表示"""
        app = _make_stub_app(str(self.img_folder))
        app.descriptive_enabled.set(True)
        app._update_descriptive_status()
        text = app._desc_status_label.cget("text")
        self.assertIn("未設定", text)

    def test_with_config_and_images(self):
        """config + 画像あり → 問題ごとのステータス表示"""
        config = {
            "questions": [
                {"id": "Q1", "name": "問題1", "max_score": 5},
            ]
        }
        config_path = self.results_data / "descriptive_config.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)

        (self.boxed_folder / "img001.jpg").touch()
        (self.boxed_folder / "img002.jpg").touch()

        app = _make_stub_app(str(self.img_folder))
        app.descriptive_enabled.set(True)
        app._update_descriptive_status()
        text = app._desc_status_label.cget("text")
        self.assertIn("Q1", text)
        self.assertIn("1問", text)

    def test_disabled_does_nothing(self):
        """descriptive_enabled=False → 何も更新しない"""
        app = _make_stub_app(str(self.img_folder))
        app.descriptive_enabled.set(False)
        app._desc_status_label.config(text="初期テキスト")
        app._update_descriptive_status()
        text = app._desc_status_label.cget("text")
        self.assertEqual(text, "初期テキスト")

    def test_all_scored_shows_complete(self):
        """全採点完了 → ✅ 表示"""
        config = {
            "questions": [
                {"id": "Q1", "name": "問題1", "max_score": 5},
            ]
        }
        config_path = self.results_data / "descriptive_config.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)

        scores = {
            "scores": {
                "img001.jpg": {"Q1": 3},
                "img002.jpg": {"Q1": 5},
            }
        }
        scores_path = self.results_data / "descriptive_scores.json"
        with open(scores_path, 'w', encoding='utf-8') as f:
            json.dump(scores, f, ensure_ascii=False)

        (self.boxed_folder / "img001.jpg").touch()
        (self.boxed_folder / "img002.jpg").touch()

        app = _make_stub_app(str(self.img_folder))
        app.descriptive_enabled.set(True)
        app._update_descriptive_status()
        text = app._desc_status_label.cget("text")
        self.assertIn("✅", text)
        self.assertIn("完了", text)


class TestTryAutoRestore(unittest.TestCase):
    """_try_auto_restore の自動復元提案"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.img_folder = Path(self.tmpdir) / "images"
        self.img_folder.mkdir()
        self.results_data = self.img_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        self.results_data.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("main_gui.messagebox")
    def test_no_session_file(self, mock_msgbox):
        """session_state.json が存在しない → 何もしない"""
        app = _make_stub_app(str(self.img_folder))
        app._try_auto_restore()
        mock_msgbox.askyesno.assert_not_called()

    @patch("main_gui.messagebox")
    def test_with_session_file_user_declines(self, mock_msgbox):
        """session_state.json あり、ユーザーが拒否 → 復元しない"""
        mock_msgbox.askyesno.return_value = False

        state = {
            "version": 1,
            "image_folder": str(self.img_folder),
            "skip_questions": "4",
            "saved_at": "2026-01-01T00:00:00",
        }
        session_path = self.results_data / SESSION_STATE_FILE
        with open(session_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)

        app = _make_stub_app(str(self.img_folder))
        app._try_auto_restore()

        mock_msgbox.askyesno.assert_called_once()

    @patch("main_gui.messagebox")
    def test_with_session_file_user_accepts(self, mock_msgbox):
        """session_state.json あり、ユーザーが承認 → 復元される"""
        mock_msgbox.askyesno.return_value = True

        state = {
            "version": 1,
            "image_folder": str(self.img_folder),
            "skip_questions": "7",
            "saved_at": "2026-01-01T00:00:00",
        }
        session_path = self.results_data / SESSION_STATE_FILE
        with open(session_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)

        app = _make_stub_app(str(self.img_folder))
        app._try_auto_restore()

        self.assertEqual(app.skip_questions.get(), "7")


# ============================================================
# テストクラス 10: 記述設定初期化
# ============================================================

class TestResetDescriptiveData(unittest.TestCase):
    """_reset_descriptive_data のテスト"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.img_folder = Path(self.tmpdir) / "images"
        self.img_folder.mkdir()
        self.results_data = self.img_folder / "_saiten_grading_results" / "01_Results"
        self.results_data.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reset_deletes_config_and_scores(self):
        """初期化で config/scores/total_display_config が削除される"""
        config_path = self.results_data / "descriptive_config.json"
        scores_path = self.results_data / "descriptive_scores.json"
        total_path = self.results_data / "total_display_config.json"
        config_path.write_text('{"questions":[]}', encoding='utf-8')
        scores_path.write_text('{"scores":{}}', encoding='utf-8')
        total_path.write_text('{}', encoding='utf-8')

        app = _make_stub_app(str(self.img_folder))
        with patch('tkinter.messagebox.askokcancel', return_value=True):
            app._reset_descriptive_data()

        self.assertFalse(config_path.exists())
        self.assertFalse(scores_path.exists())
        self.assertFalse(total_path.exists())

    def test_reset_cancel_preserves_files(self):
        """キャンセルでファイルが残る"""
        config_path = self.results_data / "descriptive_config.json"
        config_path.write_text('{"questions":[]}', encoding='utf-8')

        app = _make_stub_app(str(self.img_folder))
        with patch('tkinter.messagebox.askokcancel', return_value=False):
            app._reset_descriptive_data()

        self.assertTrue(config_path.exists())

    def test_reset_no_files_shows_info(self):
        """削除対象がない場合は showinfo"""
        app = _make_stub_app(str(self.img_folder))
        with patch('tkinter.messagebox.showinfo') as mock_info:
            app._reset_descriptive_data()
            mock_info.assert_called_once()

    def test_reset_no_folder_shows_error(self):
        """画像フォルダ未選択の場合はエラー"""
        app = _make_stub_app("")
        with patch('tkinter.messagebox.showerror') as mock_err:
            app._reset_descriptive_data()
            mock_err.assert_called_once()

    def test_reset_partial_files(self):
        """一部ファイルのみ存在する場合もOK"""
        scores_path = self.results_data / "descriptive_scores.json"
        scores_path.write_text('{"scores":{}}', encoding='utf-8')

        app = _make_stub_app(str(self.img_folder))
        with patch('tkinter.messagebox.askokcancel', return_value=True):
            app._reset_descriptive_data()

        self.assertFalse(scores_path.exists())


if __name__ == '__main__':
    unittest.main()
