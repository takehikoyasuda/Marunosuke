#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descriptive_scorer.py のユニットテスト

GUIを伴わない部分（JSON永続化、描画関数、ユーティリティ等）を検証する。
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

# テスト対象モジュールのインポート
sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from descriptive_scorer import (
    load_descriptive_config,
    save_descriptive_config,
    load_descriptive_scores,
    save_descriptive_scores,
    draw_descriptive_on_image,
    draw_combined_total,
    _get_font,
    _create_overlay_image,
    _ask_add_more,
    DEFAULT_TOTAL_BOX_WIDTH,
    DEFAULT_TOTAL_BOX_HEIGHT,
)
from constants import number_to_circled


# ============================================================
# テスト用フィクスチャ
# ============================================================

@pytest.fixture
def sample_config():
    """サンプルの記述問題設定"""
    return {
        "questions": [
            {
                "id": "D1",
                "name": "記述1",
                "region": [100, 400, 300, 500],
                "max_score": 5,
                "aspect": 2,
            },
            {
                "id": "D2",
                "name": "記述2",
                "region": [100, 510, 300, 600],
                "max_score": 10,
                "aspect": 3,
            },
        ],
        "total_display_region": [350, 700, 550, 760],
    }


@pytest.fixture
def sample_config_no_total():
    """合計点表示位置なしのサンプル設定"""
    return {
        "questions": [
            {
                "id": "D1",
                "name": "記述1",
                "region": [100, 400, 300, 500],
                "max_score": 5,
                "aspect": 2,
            },
        ],
    }


@pytest.fixture
def sample_scores():
    """サンプルの採点結果"""
    return {
        "test_image_001.jpg": {"D1": 5, "D2": 7},
        "test_image_002.jpg": {"D1": 0, "D2": 3},
    }


@pytest.fixture
def blank_image_595x842():
    """595x842 の白い画像 (BGR)"""
    return np.ones((842, 595, 3), dtype=np.uint8) * 255


@pytest.fixture
def sample_mark_scoring_result():
    """saitensamurai.score_answers() 相当のダミー戻り値"""
    return {
        "total_score": 30,
        "aspect_scores": {1: 15, 2: 10, 3: 5},
        "aspect_max_scores": {1: 20, 2: 15, 3: 10},
        "results": {},
    }


@pytest.fixture
def sample_image(tmp_path):
    """テスト用のダミー画像ファイルパス"""
    img = np.ones((842, 595, 3), dtype=np.uint8) * 255
    img_path = str(tmp_path / "test_image.jpg")
    cv2.imwrite(img_path, img)
    return img_path


# ============================================================
# JSON 永続化テスト
# ============================================================


class TestJSONPersistence:
    """設定とスコアのJSON保存/読み込みテスト"""

    def test_save_and_load_config(self, sample_config, tmp_path):
        """設定を保存して再読み込みできる"""
        config_path = str(tmp_path / "test_config.json")
        save_descriptive_config(config_path, sample_config)

        loaded = load_descriptive_config(config_path)
        assert loaded is not None
        assert len(loaded["questions"]) == 2
        assert loaded["questions"][0]["id"] == "D1"
        assert loaded["questions"][1]["max_score"] == 10
        assert loaded["total_display_region"] == [350, 700, 550, 760]

    def test_save_and_load_scores(self, sample_scores, tmp_path):
        """スコアを保存して再読み込みできる"""
        scores_path = str(tmp_path / "test_scores.json")
        scores_data = {"scores": sample_scores}
        save_descriptive_scores(scores_path, scores_data)

        loaded = load_descriptive_scores(scores_path)
        assert loaded is not None
        assert "scores" in loaded
        assert loaded["scores"]["test_image_001.jpg"]["D1"] == 5
        assert loaded["scores"]["test_image_002.jpg"]["D2"] == 3

    def test_load_nonexistent_config(self, tmp_path):
        """存在しないファイルを読むとNoneが返る"""
        result = load_descriptive_config(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_nonexistent_scores(self, tmp_path):
        """存在しないファイルを読むとNoneが返る"""
        result = load_descriptive_scores(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_invalid_json(self, tmp_path):
        """不正なJSONを読むとNoneが返る"""
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("this is not json!")
        result = load_descriptive_config(str(bad_path))
        assert result is None

    def test_config_roundtrip_preserves_types(self, tmp_path):
        """保存→読み込みで型が保持される"""
        config = {
            "questions": [
                {
                    "id": "D1",
                    "name": "テスト問",
                    "region": [10.5, 20.3, 100, 200],
                    "max_score": 8,
                    "aspect": 1,
                }
            ],
            "total_display_region": [50, 700, 250, 760],
        }
        path = str(tmp_path / "roundtrip.json")
        save_descriptive_config(path, config)
        loaded = load_descriptive_config(path)

        assert isinstance(loaded["questions"][0]["max_score"], int)
        assert isinstance(loaded["questions"][0]["region"], list)
        assert loaded["questions"][0]["name"] == "テスト問"


# ============================================================
# ユーティリティテスト
# ============================================================


class TestUtilities:
    """_get_font, number_to_circled 等のユーティリティテスト"""

    def test_number_to_circled_basic(self):
        """基本的な丸数字変換"""
        assert number_to_circled(1) == "①"
        assert number_to_circled(5) == "⑤"
        assert number_to_circled(10) == "⑩"

    def test_number_to_circled_out_of_range(self):
        """範囲外の数値はそのまま文字列化"""
        result = number_to_circled(0)
        assert isinstance(result, str)
        result = number_to_circled(100)
        assert isinstance(result, str)

    def test_get_font_returns_font(self):
        """フォントオブジェクトが返される"""
        font = _get_font(14)
        assert font is not None

    def test_get_font_various_sizes(self):
        """様々なサイズでフォントが返される"""
        for size in [6, 10, 14, 20]:
            font = _get_font(size)
            assert font is not None


# ============================================================
# 描画テスト
# ============================================================


class TestDrawDescriptiveOnImage:
    """draw_descriptive_on_image のテスト"""

    def test_full_score_draws_circle(self, blank_image_595x842, sample_config):
        """満点の場合に○が描画される（画像が変化する）"""
        scores = {"D1": 5, "D2": 10}  # 両方満点
        result = draw_descriptive_on_image(blank_image_595x842, sample_config, scores)

        assert result is not None
        assert result.shape == (842, 595, 3)
        # 画像が元と異なる（描画されている）
        assert not np.array_equal(result, blank_image_595x842)

    def test_zero_score_draws_x(self, blank_image_595x842, sample_config):
        """0点の場合に×が描画される"""
        scores = {"D1": 0, "D2": 0}
        result = draw_descriptive_on_image(blank_image_595x842, sample_config, scores)

        assert result is not None
        assert result.shape == (842, 595, 3)
        assert not np.array_equal(result, blank_image_595x842)

    def test_partial_score_draws_triangle(self, blank_image_595x842, sample_config):
        """部分点の場合に△が描画される"""
        scores = {"D1": 3, "D2": 5}
        result = draw_descriptive_on_image(blank_image_595x842, sample_config, scores)

        assert result is not None
        assert not np.array_equal(result, blank_image_595x842)

    def test_missing_score_skipped(self, blank_image_595x842, sample_config):
        """スコアがない問題は描画がスキップされる"""
        scores = {"D1": 5}  # D2 のスコアなし
        result = draw_descriptive_on_image(blank_image_595x842, sample_config, scores)

        assert result is not None
        assert result.shape == (842, 595, 3)

    def test_empty_scores_returns_copy(self, blank_image_595x842, sample_config):
        """空のスコアでもエラーにならない"""
        result = draw_descriptive_on_image(blank_image_595x842, sample_config, {})
        assert result is not None
        assert result.shape == (842, 595, 3)

    def test_original_not_modified(self, blank_image_595x842, sample_config):
        """元画像が変更されない"""
        original_copy = blank_image_595x842.copy()
        scores = {"D1": 3, "D2": 7}
        draw_descriptive_on_image(blank_image_595x842, sample_config, scores)
        assert np.array_equal(blank_image_595x842, original_copy)

    # --- ① 記述得点表示改善: 中央配置・透過・太字テスト ---

    def test_drawing_is_centered_in_region(self, sample_config):
        """描画が記述エリアの中央80%領域内に収まる"""
        # 大きな画像で領域を明確に
        image = np.ones((1000, 800, 3), dtype=np.uint8) * 255
        config = {
            "questions": [{
                "id": "D1", "name": "問1",
                "region": [200, 300, 600, 500],  # 400x200 の領域
                "max_score": 5, "aspect": 1,
            }]
        }
        scores = {"D1": 5}
        result = draw_descriptive_on_image(image, config, scores)

        # 有効エリア (80%): x=240~560, y=320~480
        # 有効エリア外（左端10%、右端10%）に描画がないことを確認
        left_margin = result[300:500, 200:240, :]  # 左10%
        right_margin = result[300:500, 560:600, :] # 右10%
        top_margin = result[300:320, 200:600, :]   # 上10%
        bottom_margin = result[480:500, 200:600, :] # 下10%
        
        orig_left = image[300:500, 200:240, :]
        orig_right = image[300:500, 560:600, :]
        orig_top = image[300:320, 200:600, :]
        orig_bottom = image[480:500, 200:600, :]
        
        # マージン部分は元画像と同じ（描画なし）
        assert np.array_equal(left_margin, orig_left), "左マージンに描画がはみ出している"
        assert np.array_equal(right_margin, orig_right), "右マージンに描画がはみ出している"
        assert np.array_equal(top_margin, orig_top), "上マージンに描画がはみ出している"
        assert np.array_equal(bottom_margin, orig_bottom), "下マージンに描画がはみ出している"

        # 中央部には描画がある
        center_area = result[350:450, 300:500, :]
        orig_center = image[350:450, 300:500, :]
        assert not np.array_equal(center_area, orig_center), "中央エリアに描画がない"

    def test_transparency_produces_blended_colors(self, blank_image_595x842, sample_config):
        """透過度75%で描画すると、純赤・純黒ではなくブレンドされた色になる"""
        scores = {"D1": 5, "D2": 0}
        result = draw_descriptive_on_image(blank_image_595x842, sample_config, scores)

        # 白背景(255,255,255)に透過75%の赤(255,0,0)を合成すると
        # 約(255,63,63)付近のブレンド色になる（純赤(255,0,0)ではない）
        # 描画があった部分のピクセルを確認
        diff = np.abs(result.astype(int) - blank_image_595x842.astype(int))
        changed_pixels = np.where(diff.sum(axis=2) > 10)
        
        if len(changed_pixels[0]) > 0:
            # 変化したピクセルの色値を確認
            sample_y = changed_pixels[0][0]
            sample_x = changed_pixels[1][0]
            pixel = result[sample_y, sample_x]
            # 透過合成のため、純赤(0,0,255 BGR)や純黒(0,0,0)ではない
            # 白背景との合成で中間的な色になるはず
            assert not (pixel[0] == 0 and pixel[1] == 0 and pixel[2] == 255), \
                "透過処理されていない（純赤のまま）"

    def test_scaled_output_draws_correctly(self, sample_config):
        """output_scale > 1.0 でも正しく描画される"""
        # スケール2倍の画像
        scale = 2.0
        image = np.ones((int(842 * scale), int(595 * scale), 3), dtype=np.uint8) * 255
        scores = {"D1": 3, "D2": 10}
        result = draw_descriptive_on_image(image, sample_config, scores, output_scale=scale)
        
        assert result is not None
        assert result.shape == image.shape
        assert not np.array_equal(result, image)

    def test_large_font_for_large_region(self):
        """大きな領域では大きなフォントが使われる（目視確認用の回帰テスト）"""
        # 非常に大きな領域
        image = np.ones((1200, 1000, 3), dtype=np.uint8) * 255
        config = {
            "questions": [{
                "id": "D1", "name": "問1",
                "region": [100, 100, 900, 600],  # 800x500
                "max_score": 5, "aspect": 1,
            }]
        }
        scores = {"D1": 5}
        result = draw_descriptive_on_image(image, config, scores)
        
        # 描画された面積が一定以上あることを確認（大きなフォント使用の間接確認）
        diff = np.abs(result.astype(int) - image.astype(int))
        changed_pixel_count = np.sum(diff.sum(axis=2) > 10)
        assert changed_pixel_count > 500, f"描画面積が小さすぎる: {changed_pixel_count}px"
    """draw_combined_total のテスト"""

    def test_basic_combined_total(
        self, blank_image_595x842, sample_mark_scoring_result, sample_config
    ):
        """基本的な合計点描画が成功する"""
        desc_scores = {"D1": 5, "D2": 7}
        result = draw_combined_total(
            blank_image_595x842,
            sample_mark_scoring_result,
            sample_config,
            desc_scores,
        )
        assert result is not None
        assert result.shape == (842, 595, 3)
        assert not np.array_equal(result, blank_image_595x842)

    def test_combined_total_without_region(
        self, blank_image_595x842, sample_mark_scoring_result, sample_config_no_total
    ):
        """total_display_region なしでもフォールバック位置で描画できる"""
        desc_scores = {"D1": 3}
        result = draw_combined_total(
            blank_image_595x842,
            sample_mark_scoring_result,
            sample_config_no_total,
            desc_scores,
        )
        assert result is not None
        assert result.shape == (842, 595, 3)

    def test_combined_total_with_coordinates(
        self, blank_image_595x842, sample_mark_scoring_result, sample_config_no_total
    ):
        """座標リストでフォールバック位置を計算できる"""
        coords = [
            {"question_no": 1, "x": 50, "y": 100, "width": 20, "height": 20},
            {"question_no": 2, "x": 50, "y": 130, "width": 20, "height": 20},
        ]
        desc_scores = {"D1": 5}
        result = draw_combined_total(
            blank_image_595x842,
            sample_mark_scoring_result,
            sample_config_no_total,
            desc_scores,
            coordinates=coords,
        )
        assert result is not None

    def test_original_not_modified(
        self, blank_image_595x842, sample_mark_scoring_result, sample_config
    ):
        """元画像が変更されない"""
        original_copy = blank_image_595x842.copy()
        desc_scores = {"D1": 5, "D2": 7}
        draw_combined_total(
            blank_image_595x842,
            sample_mark_scoring_result,
            sample_config,
            desc_scores,
        )
        assert np.array_equal(blank_image_595x842, original_copy)

    def test_small_box_font_auto_adjust(
        self, blank_image_595x842, sample_mark_scoring_result
    ):
        """小さいボックスでもフォントサイズが自動調整されてエラーにならない"""
        config = {
            "questions": [
                {
                    "id": "D1", "name": "問1",
                    "region": [100, 400, 200, 450],
                    "max_score": 5, "aspect": 1,
                }
            ],
            "total_display_region": [400, 780, 480, 810],  # 80x30 の小さいボックス
        }
        desc_scores = {"D1": 3}
        result = draw_combined_total(
            blank_image_595x842,
            sample_mark_scoring_result,
            config,
            desc_scores,
        )
        assert result is not None
        assert result.shape == (842, 595, 3)

    def test_very_small_box_no_crash(
        self, blank_image_595x842, sample_mark_scoring_result
    ):
        """非常に小さいボックスでもクラッシュしない"""
        config = {
            "questions": [
                {
                    "id": "D1", "name": "問1",
                    "region": [100, 400, 200, 450],
                    "max_score": 5, "aspect": 1,
                }
            ],
            "total_display_region": [400, 780, 440, 800],  # 40x20 の極小ボックス
        }
        desc_scores = {"D1": 3}
        result = draw_combined_total(
            blank_image_595x842,
            sample_mark_scoring_result,
            config,
            desc_scores,
        )
        assert result is not None

    def test_empty_descriptive_scores(
        self, blank_image_595x842, sample_mark_scoring_result, sample_config
    ):
        """空のスコアでもエラーにならない"""
        result = draw_combined_total(
            blank_image_595x842,
            sample_mark_scoring_result,
            sample_config,
            {},
        )
        assert result is not None

    def test_large_image_font_size_scales_with_box(self):
        """大きい画像(2400x3400)でoutput_scale=1.0でもフォントが適切なサイズになること"""
        # 記述のみモードでは output_scale=1.0 だが、ボックス座標は実ピクセル基準
        # ボックスが大きいのにフォントが14ptのままでは印刷時に見えない
        large_img = np.ones((3400, 2400, 3), dtype=np.uint8) * 255
        mark_result = {
            'total_score': 0,
            'aspect_scores': {},
            'aspect_max_scores': {},
        }
        config = {
            "questions": [
                {"id": "D1", "name": "問1", "region": [100, 100, 500, 300],
                 "max_score": 10, "aspect": 1},
            ],
            # 大きな合計表示領域 (実ピクセル座標): 800x240
            "total_display_region": [100, 2800, 900, 3040],
        }
        desc_scores = {"D1": 7}
        result = draw_combined_total(
            large_img, mark_result, config, desc_scores,
            output_scale=1.0,
        )
        assert result is not None
        # 描画されたピクセル数が十分大きいことを確認
        # (14ptフォントでは描画面積が小さすぎる → box_h*0.5=120ptなら十分大きい)
        diff = np.abs(result.astype(int) - large_img.astype(int))
        changed_pixels = np.sum(diff.sum(axis=2) > 10)
        # 14ptフォントでは約200px程度、120ptフォントなら数千px以上変化するはず
        assert changed_pixels > 1000, (
            f"合計点の描画面積が小さすぎる ({changed_pixels}px)。"
            f"フォントサイズがボックスサイズに追従していない可能性がある"
        )


# ============================================================
# オーバーレイ画像生成テスト
# ============================================================


class TestCreateOverlayImage:
    """_create_overlay_image のテスト"""

    def test_creates_overlay_with_questions(self, sample_config, tmp_path):
        """問題領域のオーバーレイ画像が生成される"""
        # テスト用の白い画像を作成
        test_img = np.ones((842, 595, 3), dtype=np.uint8) * 255
        img_path = str(tmp_path / "test_base.jpg")
        cv2.imwrite(img_path, test_img)

        result_path = _create_overlay_image(img_path, sample_config["questions"])

        assert result_path is not None
        assert Path(result_path).exists()

        # 生成された画像が読めることを確認
        overlay_img = cv2.imread(result_path)
        assert overlay_img is not None
        assert overlay_img.shape == (842, 595, 3)

        # 白地ではないことを確認（何か描画されている）
        assert not np.array_equal(overlay_img, test_img)

        # 一時ファイルを削除
        Path(result_path).unlink(missing_ok=True)

    def test_empty_questions_list(self, tmp_path):
        """空の問題リストでもエラーにならない"""
        test_img = np.ones((842, 595, 3), dtype=np.uint8) * 255
        img_path = str(tmp_path / "test_base.jpg")
        cv2.imwrite(img_path, test_img)

        result_path = _create_overlay_image(img_path, [])
        assert result_path is not None
        Path(result_path).unlink(missing_ok=True)

    def test_invalid_image_returns_none(self, tmp_path):
        """存在しない画像パスではNoneが返る"""
        result = _create_overlay_image(str(tmp_path / "nonexistent.jpg"), [])
        assert result is None


# ============================================================
# 定数テスト
# ============================================================


class TestConstants:
    """定数が適切に設定されているか"""

    def test_default_box_size(self):
        """デフォルトのボックスサイズが妥当"""
        assert DEFAULT_TOTAL_BOX_WIDTH > 0
        assert DEFAULT_TOTAL_BOX_HEIGHT > 0
        assert DEFAULT_TOTAL_BOX_WIDTH >= 100  # 十分な幅
        assert DEFAULT_TOTAL_BOX_HEIGHT >= 30  # 十分な高さ


# ============================================================
# サマリー関数の記述対応テスト
# ============================================================


# ============================================================
# GUI起動テスト（非GUIモード）
# ============================================================


class TestGUIStartup:
    """GUIが正常に起動するか（2秒で自動終了）"""

    def test_mark2gui_initializes(self):
        """Mark2GUIが初期化できる（記述式のみモード固定）"""
        import tkinter as tk
        from saitensamurai import Mark2GUI
        root = tk.Tk()
        try:
            app = Mark2GUI(root)
            assert hasattr(app, "desc_setup_btn")
            assert hasattr(app, "desc_scoring_btn")
            assert hasattr(app, "descriptive_enabled")
            assert app.descriptive_enabled.get() is True
        finally:
            root.destroy()

    def test_window_geometry(self):
        """ウィンドウサイズが適切に設定されている"""
        import tkinter as tk
        from saitensamurai import Mark2GUI
        try:
            root = tk.Tk()
        except tk.TclError:
            pytest.skip("Tkinter not available in this test session")
        try:
            app = Mark2GUI(root)
            # update_idletasks()を呼ぶとジオメトリが更新される
            root.update_idletasks()
            # 最低限のサイズ確認（リクエストされたサイズ）
            assert root.winfo_reqwidth() > 0
            assert root.winfo_reqheight() > 0
        finally:
            root.destroy()


class TestProcessingStateAndButtons:
    """③ プログレスバー・ボタン無効化・ボタン順序のテスト"""

    def _make_app(self):
        import tkinter as tk
        from saitensamurai import Mark2GUI
        root = tk.Tk()
        app = Mark2GUI(root)
        return root, app

    def test_action_button_references_exist(self):
        """アクションボタンがインスタンス変数として保持されている"""
        import tkinter as tk
        try:
            root, app = self._make_app()
        except tk.TclError:
            pytest.skip("Tkinter not available")
        try:
            for attr in ("_btn_run_box", "_btn_total_pos",
                         "_btn_run_scoring", "_btn_run_summary"):
                assert hasattr(app, attr), f"Missing attribute: {attr}"
        finally:
            root.destroy()

    def test_progress_bar_exists(self):
        """プログレスバーが存在し、初期状態では非表示"""
        import tkinter as tk
        try:
            root, app = self._make_app()
        except tk.TclError:
            pytest.skip("Tkinter not available")
        try:
            assert hasattr(app, "_progress_bar")
            assert hasattr(app, "_processing")
            assert app._processing is False
            # 初期状態では pack されていない
            assert app._progress_bar.winfo_manager() == ""
        finally:
            root.destroy()

    def test_set_processing_state_busy(self):
        """_set_processing_state(True) でボタン無効化 & プログレスバー表示"""
        import tkinter as tk
        try:
            root, app = self._make_app()
        except tk.TclError:
            pytest.skip("Tkinter not available")
        try:
            app._set_processing_state(True)
            assert app._processing is True
            # プログレスバーが表示されている
            assert app._progress_bar.winfo_manager() == "pack"
            # アクションボタンが無効
            assert str(app._btn_run_box["state"]) == "disabled"
            assert str(app._btn_run_scoring["state"]) == "disabled"
            assert str(app._btn_run_summary["state"]) == "disabled"
        finally:
            root.destroy()

    def test_set_processing_state_idle(self):
        """_set_processing_state(False) でボタン有効化 & プログレスバー非表示"""
        import tkinter as tk
        try:
            root, app = self._make_app()
        except tk.TclError:
            pytest.skip("Tkinter not available")
        try:
            # busy → idle
            app._set_processing_state(True)
            app._set_processing_state(False)
            assert app._processing is False
            assert app._progress_bar.winfo_manager() == ""
            # フォルダ未設定時は Step ガードにより Step1/2/3 ボタンは disabled のまま
            assert str(app._btn_run_box["state"]) == "disabled"
            assert str(app._btn_run_scoring["state"]) == "disabled"
            assert str(app._btn_run_summary["state"]) == "disabled"
        finally:
            root.destroy()

    def test_button_order_step2(self):
        """Step 2 のボタン順序: 合計点位置設定 → 採点済み答案を生成"""
        import tkinter as tk
        try:
            root, app = self._make_app()
        except tk.TclError:
            pytest.skip("Tkinter not available")
        try:
            assert "合計点位置設定" in app._btn_total_pos["text"]
            assert "採点済み答案を出力" in app._btn_run_scoring["text"]
            # return_sheet_btn は廃止されたことを確認
            assert not hasattr(app, "return_sheet_btn")
        finally:
            root.destroy()

    def test_prepare_images_blocked_during_processing(self):
        """処理中は _prepare_images_for_descriptive が即座にリターンする"""
        import tkinter as tk
        try:
            root, app = self._make_app()
        except tk.TclError:
            pytest.skip("Tkinter not available")
        try:
            app._processing = True
            app._prepare_images_for_descriptive()  # エラーが出なければOK
        finally:
            root.destroy()


# ============================================================
# setup_descriptive_regions: 既存設定の再読み込みテスト
# ============================================================


class TestSetupDescriptiveRegionsResume:
    """setup_descriptive_regions が既存設定を読み込んで再開できることを検証"""

    def test_resume_loads_existing_config(self, tmp_path, sample_image):
        """既存の descriptive_config.json がある場合、問題数を引き継ぐ"""
        from unittest.mock import patch, MagicMock

        config_path = str(tmp_path / "descriptive_config.json")
        existing = {
            "version": 1,
            "questions": [
                {"id": "D1", "name": "記述1", "max_score": 5, "aspect": 1, "region": [10, 20, 100, 200]},
                {"id": "D2", "name": "記述2", "max_score": 3, "aspect": 2, "region": [110, 20, 200, 200]},
            ],
            "total_display_region": None,
        }
        save_descriptive_config(config_path, existing)

        # select_region_on_image を None (キャンセル) にする
        # → 既存2問のまま保存されるはず
        with patch("descriptive_gui.select_region_on_image", return_value=None), \
             patch("descriptive_gui.get_image_files", return_value=[str(sample_image)]):
            from descriptive_scorer import setup_descriptive_regions
            result = setup_descriptive_regions(str(tmp_path), config_path, parent=None)

        # 2問設定済み → キャンセルしても既存設定が保存される
        assert result is not None
        assert len(result["questions"]) == 2
        assert result["questions"][0]["id"] == "D1"
        assert result["questions"][1]["id"] == "D2"

    def test_resume_adds_question_from_correct_number(self, tmp_path, sample_image):
        """既存2問あれば「記述3」から追加が始まる"""
        from unittest.mock import patch, MagicMock, call

        config_path = str(tmp_path / "descriptive_config.json")
        existing = {
            "version": 1,
            "questions": [
                {"id": "D1", "name": "記述1", "max_score": 5, "aspect": 1, "region": [10, 20, 100, 200]},
            ],
            "total_display_region": None,
        }
        save_descriptive_config(config_path, existing)

        new_region = (210, 20, 300, 200)
        q_info = {"name": "記述2", "max_score": 4, "aspect": 1}

        with patch("descriptive_gui.select_region_on_image", return_value=new_region) as mock_select, \
             patch("descriptive_gui._ask_question_info", return_value=q_info), \
             patch("descriptive_gui._ask_add_more", return_value=False), \
             patch("descriptive_gui.get_image_files", return_value=[str(sample_image)]), \
             patch("descriptive_gui._create_overlay_image", return_value=None):
            from descriptive_scorer import setup_descriptive_regions
            result = setup_descriptive_regions(str(tmp_path), config_path, parent=None)

        # 記述2 の番号で呼ばれるべき (既存1問 + 1)
        select_call = mock_select.call_args
        assert "記述2" in select_call.kwargs.get("label_text", select_call[1].get("label_text", ""))

        assert len(result["questions"]) == 2
        assert result["questions"][1]["id"] == "D2"

    def test_fresh_start_when_no_existing_config(self, tmp_path, sample_image):
        """config ファイルが無い場合は最初から"""
        from unittest.mock import patch

        config_path = str(tmp_path / "descriptive_config.json")
        # ファイルを作成しない

        with patch("descriptive_gui.select_region_on_image", return_value=None), \
             patch("descriptive_gui.get_image_files", return_value=[str(sample_image)]):
            from descriptive_scorer import setup_descriptive_regions
            result = setup_descriptive_regions(str(tmp_path), config_path, parent=None)

        # 0問で Cancel → None
        assert result is None


# ============================================================
# _ask_add_more: カスタムダイアログのテスト (parent=None)
# ============================================================


class TestAskAddMore:
    """_ask_add_more のテスト"""

    def test_returns_false_without_parent(self):
        """parent=None の場合は常に False"""
        result = _ask_add_more(None, 1, "記述1")
        assert result is False


# ============================================================
# スレッドセーフティ: GUI更新が root.after 経由であることの確認
# ============================================================


class TestThreadSafetyGuiUpdates:
    """_run_scoring_thread / _run_box_drawer_thread のGUI更新がスレッドセーフ"""

    def test_open_scored_btn_update_via_after(self):
        """open_scored_btn.config が root.after 経由で呼ばれる"""
        import re
        code_path = Path(__file__).parent.parent / "main_src" / "saitensamurai.py"
        code = code_path.read_text(encoding="utf-8")

        # open_scored_btn.config(state=tk.NORMAL) が root.after で呼ばれているか
        # 直接呼び出しパターンをチェック
        lines = code.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "open_scored_btn.config(state=tk.NORMAL)" in stripped:
                assert "root.after" in stripped or "after(0" in stripped, \
                    f"Line {i+1}: open_scored_btn.config should be called via root.after"

    def test_open_boxed_btn_update_via_after(self):
        """open_boxed_btn.config が root.after 経由で呼ばれる"""
        code_path = Path(__file__).parent.parent / "main_src" / "saitensamurai.py"
        code = code_path.read_text(encoding="utf-8")

        lines = code.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "open_boxed_btn.config(state=tk.NORMAL)" in stripped:
                assert "root.after" in stripped or "after(0" in stripped, \
                    f"Line {i+1}: open_boxed_btn.config should be called via root.after"

    def test_open_results_btn_update_via_after(self):
        """open_results_btn.config が root.after 経由で呼ばれる"""
        code_path = Path(__file__).parent.parent / "main_src" / "saitensamurai.py"
        code = code_path.read_text(encoding="utf-8")

        lines = code.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "open_results_btn.config(state=tk.NORMAL)" in stripped:
                assert "root.after" in stripped or "after(0" in stripped, \
                    f"Line {i+1}: open_results_btn.config should be called via root.after"


# ================================================================
# Phase 1C: DescriptiveReviewGUI 得点ソート＋色分け コード構造テスト
# ================================================================

class TestDescriptiveReviewGUIStructure:
    """DescriptiveReviewGUI の v4.0 改善が正しく反映されているかをコード構造で検証"""

    def test_sort_dropdown_exists(self):
        """並び順ドロップダウンが存在する"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI
        src = inspect.getsource(DescriptiveReviewGUI)
        assert "_sort_var" in src, "ソート変数がない"
        assert "_sort_combo" in src, "ソートコンボボックスがない"
        assert "ファイル名順" in src, "ファイル名順オプションがない"
        assert "得点 昇順" in src, "得点昇順オプションがない"
        assert "得点 降順" in src, "得点降順オプションがない"

    def test_card_background_colors(self):
        """カード背景色が得点に応じて設定される"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI
        src = inspect.getsource(DescriptiveReviewGUI)
        assert "#E3F2FD" in src, "満点の背景色(薄い青)がない"
        assert "#FFEBEE" in src, "0点の背景色(薄い赤)がない"
        assert "#FFF3E0" in src, "中間点の背景色(薄い橙)がない"
        assert "#F5F5F5" in src, "未採点の背景色(灰)がない"

    def test_sort_logic_in_refresh_grid(self):
        """_refresh_grid にソートロジックが含まれる"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI
        src = inspect.getsource(DescriptiveReviewGUI._refresh_grid)
        assert "sort" in src.lower() or "ソート" in src, "ソートロジックが_refresh_gridにない"
        assert "filtered.sort" in src, "filteredリストのソートがない"

    def test_text_table_has_visible_horizontal_navigation(self):
        """テキスト一覧で隠れた左右の列へ移動できる導線がある。"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI

        build_src = inspect.getsource(DescriptiveReviewGUI._build_gui)
        mode_src = inspect.getsource(DescriptiveReviewGUI._on_display_mode_changed)
        assert "_h_scrollbar" in build_src
        assert "orient=tk.HORIZONTAL" in build_src
        assert "xscrollcommand=self._h_scrollbar.set" in build_src
        assert "左右に項目があります" in build_src
        assert "_horizontal_nav.pack" in mode_src
        assert "_horizontal_nav.pack_forget" in mode_src

    def test_text_table_keeps_full_content_width(self):
        """狭い画面でも氏名列を潰さず、超過分を横スクロールさせる。"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI

        resize_src = inspect.getsource(DescriptiveReviewGUI._on_canvas_resize)
        table_src = inspect.getsource(DescriptiveReviewGUI._render_text_table)
        assert "winfo_reqwidth" in resize_src
        assert "winfo_reqwidth" in table_src
        assert "itemconfig(self._canvas_window, width=content_width)" in table_src
        assert "xview_moveto(0)" in table_src

    def test_text_table_uses_compact_columns(self):
        """最大化時に全列を一望できるよう列幅を過度に広げない。"""
        import ast
        import inspect
        import textwrap
        from descriptive_scorer import DescriptiveReviewGUI

        table_src = inspect.getsource(DescriptiveReviewGUI._render_text_table)
        tree = ast.parse(textwrap.dedent(table_src))
        widths = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "widths" for target in node.targets):
                    widths = ast.literal_eval(node.value)
                    break
        assert widths is not None
        assert len(widths) == 9
        assert sum(widths) <= 100
        assert widths[6] <= 16  # 教員用メモ
        assert widths[7] <= 16  # 生徒コメント

    def test_text_table_uses_compact_single_line_rows(self):
        """多人数を一覧できるよう各答案行を1行の高さに抑える。"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI

        table_src = inspect.getsource(DescriptiveReviewGUI._render_text_table)
        assert "height=1" in table_src
        assert "pady=2" in table_src
        assert "wraplength=" not in table_src
        assert 'pack(side=tk.LEFT' in table_src
        assert '_annotation_preview(annotation.get("memo", ""), 18)' in table_src
        assert '_annotation_preview(annotation.get("comment", ""), 18)' in table_src

    def test_text_table_cells_have_visible_borders(self):
        """見出し・データ・操作欄の区切りを罫線で判別できる。"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI

        table_src = inspect.getsource(DescriptiveReviewGUI._render_text_table)
        assert table_src.count("relief=tk.SOLID") >= 3
        assert table_src.count("bd=1") >= 3

    def test_image_cards_use_available_width_for_annotations(self):
        """画像一覧のメモ・コメントをサムネイル幅だけで細く折り返さない。"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI

        refresh_src = inspect.getsource(DescriptiveReviewGUI._refresh_grid)
        assert "annotation_wraplength = max(320, self._thumb_size * 2)" in refresh_src
        assert refresh_src.count("wraplength=annotation_wraplength") == 2

    def test_get_thumb_no_hardcoded_595x842(self):
        """_get_thumb が 595×842 ハードコード座標変換を使っていないことを確認"""
        import inspect, re
        from descriptive_scorer import DescriptiveReviewGUI
        src = inspect.getsource(DescriptiveReviewGUI._get_thumb)
        # コメント行を除外してコード行のみチェック
        code_lines = [l for l in src.split('\n') if not l.strip().startswith('#')]
        code_only = '\n'.join(code_lines)
        # 旧バグ: scale_x = w / 595.0 のようなハードコードスケーリング
        assert "/ 595" not in code_only, "_get_thumb にスケーリング 595 が残っている"
        assert "/ 842" not in code_only, "_get_thumb にスケーリング 842 が残っている"

    def test_get_thumb_uses_direct_coordinates(self):
        """_get_thumb が region 座標を直接使用することを確認"""
        import inspect
        from descriptive_scorer import DescriptiveReviewGUI
        src = inspect.getsource(DescriptiveReviewGUI._get_thumb)
        # region[0] を scale なしで int に変換している
        assert "int(region[" in src, "region座標の直接変換がない"
        # scale_x / scale_y による乗算がないこと
        assert "scale_x" not in src, "scale_x が残っている"
        assert "scale_y" not in src, "scale_y が残っている"


class TestReviewGUIGetThumb:
    """DescriptiveReviewGUI._get_thumb の実機テスト（GUIなし）"""

    def test_thumb_crop_coordinates_large_image(self, tmp_path):
        """大きい画像（記述のみモード想定）でもリージョン座標が正しく適用される"""
        # 2400×3400 の白画像に赤い矩形を描画
        boxed = tmp_path / "00_Processing"
        boxed.mkdir()
        img = np.ones((3400, 2400, 3), dtype=np.uint8) * 255
        cv2.rectangle(img, (500, 1000), (1500, 2000), (0, 0, 255), -1)
        cv2.imencode('.jpg', img)[1].tofile(str(boxed / "test.jpg"))

        region = [500, 1000, 1500, 2000]

        # 画像を読み込んで直接切り出し（_get_thumb 内部ロジックと同等）
        img_array = np.fromfile(str(boxed / "test.jpg"), dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        h, w = image.shape[:2]

        x1 = max(0, min(int(region[0]), w))
        y1 = max(0, min(int(region[1]), h))
        x2 = max(0, min(int(region[2]), w))
        y2 = max(0, min(int(region[3]), h))

        cropped = image[y1:y2, x1:x2]
        assert cropped.size > 0, "切り出し結果が空"
        assert cropped.shape[1] == 1000, f"幅が1000でない: {cropped.shape[1]}"
        assert cropped.shape[0] == 1000, f"高さが1000でない: {cropped.shape[0]}"

    def test_thumb_crop_coordinates_595x842(self, tmp_path):
        """595×842 画像（OMRモード想定）でもリージョン座標が正しく適用される"""
        boxed = tmp_path / "00_Processing"
        boxed.mkdir()
        img = np.ones((842, 595, 3), dtype=np.uint8) * 255
        cv2.rectangle(img, (100, 400), (300, 500), (0, 255, 0), -1)
        cv2.imencode('.jpg', img)[1].tofile(str(boxed / "test.jpg"))

        region = [100, 400, 300, 500]

        img_array = np.fromfile(str(boxed / "test.jpg"), dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        h, w = image.shape[:2]

        x1 = max(0, min(int(region[0]), w))
        y1 = max(0, min(int(region[1]), h))
        x2 = max(0, min(int(region[2]), w))
        y2 = max(0, min(int(region[3]), h))

        cropped = image[y1:y2, x1:x2]
        assert cropped.size > 0, "切り出し結果が空"
        assert cropped.shape[1] == 200, f"幅が200でない: {cropped.shape[1]}"
        assert cropped.shape[0] == 100, f"高さが100でない: {cropped.shape[0]}"

    def test_old_scaling_would_fail_large_image(self, tmp_path):
        """旧コード（595×842基準スケーリング）が大画像で失敗することを確認"""
        boxed = tmp_path / "00_Processing"
        boxed.mkdir()
        img = np.ones((3400, 2400, 3), dtype=np.uint8) * 255
        cv2.imencode('.jpg', img)[1].tofile(str(boxed / "test.jpg"))

        region = [500, 1000, 1500, 2000]

        img_array = np.fromfile(str(boxed / "test.jpg"), dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        h, w = image.shape[:2]

        # 旧スケーリング（バグ）
        scale_x = w / 595.0
        scale_y = h / 842.0
        x1_old = max(0, int(region[0] * scale_x))
        y1_old = max(0, int(region[1] * scale_y))
        x2_old = min(w, int(region[2] * scale_x))
        y2_old = min(h, int(region[3] * scale_y))

        # y2_old がhを超えるか、座標が大きすぎて不正な切り出しになる
        assert y1_old > h or y2_old > h or x2_old > w, \
            "旧スケーリングが大画像で正常に見えてしまう（テスト前提の確認）"


class TestIntegratedDescriptiveSetupStructure:
    """IntegratedDescriptiveSetup (Phase 2A) の構造テスト"""

    def test_class_exists_with_canvas_and_treeview(self):
        """統合設定ウィンドウがCanvas＋Treeviewを持つ"""
        import inspect
        from descriptive_scorer import IntegratedDescriptiveSetup
        src = inspect.getsource(IntegratedDescriptiveSetup)
        assert "_canvas" in src, "Canvas属性がない"
        assert "_tree" in src or "Treeview" in src, "Treeview属性がない"
        assert "ドラッグで領域を選択" in src, "Canvas説明ラベルがない"

    def test_drag_handlers(self):
        """ドラッグハンドラ（press/drag/release）が実装されている"""
        import inspect
        from descriptive_scorer import IntegratedDescriptiveSetup
        assert hasattr(IntegratedDescriptiveSetup, "_on_press"), "_on_press がない"
        assert hasattr(IntegratedDescriptiveSetup, "_on_drag"), "_on_drag がない"
        assert hasattr(IntegratedDescriptiveSetup, "_on_release"), "_on_release がない"

    def test_inline_editing(self):
        """Treeviewのダブルクリック編集が実装されている"""
        import inspect
        from descriptive_scorer import IntegratedDescriptiveSetup
        src = inspect.getsource(IntegratedDescriptiveSetup)
        assert "_on_tree_double_click" in src, "ダブルクリック編集メソッドがない"
        assert "Double-1" in src, "Double-1 イベントバインドがない"

    def test_delete_and_save(self):
        """削除・保存機能が存在する"""
        import inspect
        from descriptive_scorer import IntegratedDescriptiveSetup
        assert hasattr(IntegratedDescriptiveSetup, "_delete_selected"), "_delete_selected がない"
        assert hasattr(IntegratedDescriptiveSetup, "_on_save"), "_on_save がない"
        src = inspect.getsource(IntegratedDescriptiveSetup._on_save)
        assert "save_descriptive_config" in src, "設定保存呼び出しがない"

    def test_overlay_colors(self):
        """オーバーレイ色定義が存在する"""
        from descriptive_scorer import _OVERLAY_COLORS_RGB
        assert len(_OVERLAY_COLORS_RGB) >= 7, "オーバーレイ色が7色未満"

    def test_wrapper_function_exists(self):
        """setup_descriptive_regions_integrated ラッパー関数が存在する"""
        from descriptive_scorer import setup_descriptive_regions_integrated
        import inspect
        sig = inspect.signature(setup_descriptive_regions_integrated)
        params = list(sig.parameters.keys())
        assert "image_folder" in params, "image_folder パラメータがない"
        assert "config_save_path" in params, "config_save_path パラメータがない"
        assert "parent" in params, "parent パラメータがない"


class TestScoringQuestionListLayout:
    """採点問題一覧が小さい画面でも操作を隠さない構造か検証する。"""

    def test_uses_responsive_grid_and_content_fitting(self):
        import inspect
        from descriptive_gui import DescriptiveScorerGUI

        src = inspect.getsource(DescriptiveScorerGUI._show_question_list)
        assert 'frame.grid_rowconfigure(3, weight=1' in src
        assert 'scroll_container.grid(row=3' in src
        assert 'btn_frame.grid(row=4' in src
        assert 'fit_window_to_content(win' in src
        assert 'win.geometry("600x520")' not in src

    def test_heading_is_simply_scoring(self):
        import inspect
        from descriptive_gui import DescriptiveScorerGUI

        src = inspect.getsource(DescriptiveScorerGUI._show_question_list)
        assert 'text="採点"' in src
        assert 'text="記述問題 採点"' not in src

    def test_settings_and_footer_buttons_stay_inside_window(self, tmp_path):
        import tkinter as tk
        from descriptive_gui import DescriptiveScorerGUI

        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError:
            pytest.skip("Tkinter not available")

        scorer = DescriptiveScorerGUI(
            root,
            {
                "questions": [
                    {"id": "D1", "name": "記述1", "max_score": 5, "aspect": 1},
                    {"id": "D2", "name": "記述2", "max_score": 5, "aspect": 1},
                ]
            },
            str(tmp_path),
            str(tmp_path / "descriptive_scores.json"),
        )
        scorer._trimmed = {
            "D1": {"001.jpg": "unused"},
            "D2": {"001.jpg": "unused"},
        }

        try:
            with patch.object(tk.Toplevel, "wait_window"), \
                    patch.object(tk.Toplevel, "grab_set"):
                scorer._show_question_list()
            win = scorer._list_win
            win.update_idletasks()

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            buttons = {
                child.cget("text"): child
                for child in descendants(win)
                if isinstance(child, tk.Button)
            }
            for text in ("設定", "✔ 採点完了・保存", "キャンセル"):
                button = buttons[text]
                assert button.winfo_rootx() >= win.winfo_rootx()
                assert button.winfo_rooty() >= win.winfo_rooty()
                assert button.winfo_rootx() + button.winfo_width() <= \
                    win.winfo_rootx() + win.winfo_width()
                assert button.winfo_rooty() + button.winfo_height() <= \
                    win.winfo_rooty() + win.winfo_height()
        finally:
            if scorer._list_win and scorer._list_win.winfo_exists():
                scorer._list_win.destroy()
            root.destroy()


class TestGridModeScorerStructure:
    """_SingleQuestionScorer のグリッド一覧モード (Phase 2B) の構造テスト"""

    def test_mode_switcher_exists(self):
        """モード切替ドロップダウンが存在する"""
        import inspect
        from descriptive_scorer import _SingleQuestionScorer
        src = inspect.getsource(_SingleQuestionScorer)
        assert "_mode_var" in src, "モード切替変数がない"
        assert "1枚ずつ" in src, "1枚ずつモードがない"
        assert "一覧" in src, "一覧モードがない"
        assert "_on_mode_change" in src, "モード切替メソッドがない"

    def test_grid_panel_build(self):
        """グリッドパネル構築メソッドが存在する"""
        from descriptive_scorer import _SingleQuestionScorer
        assert hasattr(_SingleQuestionScorer, "_build_grid_panel"), "_build_grid_panel がない"
        assert hasattr(_SingleQuestionScorer, "_refresh_grid"), "_refresh_grid がない"

    def test_continuous_click_scoring(self):
        """連続クリック採点の仕組みが存在する"""
        import inspect
        from descriptive_scorer import _SingleQuestionScorer
        src = inspect.getsource(_SingleQuestionScorer)
        assert "_grid_active_score" in src, "アクティブ得点変数がない"
        assert "_on_grid_score_btn" in src, "得点ボタンハンドラがない"
        assert "_on_grid_card_click" in src, "カードクリックハンドラがない"

    def test_grid_sort_and_colors(self):
        """グリッドモードでのソートと色分けが存在する"""
        import inspect
        from descriptive_scorer import _SingleQuestionScorer
        src = inspect.getsource(_SingleQuestionScorer._refresh_grid)
        assert "得点 昇順" in src, "得点昇順ソートがない"
        assert "得点 降順" in src, "得点降順ソートがない"
        # 色定義は _score_to_card_style に抽出されている
        style_src = inspect.getsource(_SingleQuestionScorer._score_to_card_style)
        assert "#E3F2FD" in style_src, "満点の背景色がない"
        assert "#FFEBEE" in style_src, "0点の背景色がない"
        assert "#FFF3E0" in style_src, "中間点の背景色がない"

    def test_grid_thumb_cache(self):
        """サムネイルキャッシュが存在する"""
        import inspect
        from descriptive_scorer import _SingleQuestionScorer
        src = inspect.getsource(_SingleQuestionScorer)
        assert "_grid_thumb_cache" in src, "グリッドサムネイルキャッシュがない"
        assert "_load_grid_thumb" in src, "サムネイル読み込みメソッドがない"

    def test_differential_card_update_exists(self):
        """カードクリック時に全体再描画ではなく差分更新が行われる"""
        import inspect
        from descriptive_scorer import _SingleQuestionScorer
        # _on_grid_card_click が _update_single_card を呼ぶ
        click_src = inspect.getsource(_SingleQuestionScorer._on_grid_card_click)
        assert "_update_single_card" in click_src, \
            "_on_grid_card_click は _update_single_card を呼ぶべき"
        assert "_refresh_grid" not in click_src, \
            "_on_grid_card_click で _refresh_grid を呼ぶと全カード再描画になる"
        # _update_single_card メソッドが存在
        assert hasattr(_SingleQuestionScorer, "_update_single_card"), \
            "_update_single_card メソッドがない"

    def test_score_to_card_style_logic(self):
        """_score_to_card_style が正しいスタイルを返す"""
        from descriptive_scorer import _SingleQuestionScorer
        fn = _SingleQuestionScorer._score_to_card_style
        # 未採点
        bg, mark, fg = fn(None, 5)
        assert mark == "─"
        # 満点
        bg, mark, fg = fn(5, 5)
        assert mark == "○" and bg == "#E3F2FD"
        # 0点
        bg, mark, fg = fn(0, 5)
        assert mark == "×" and bg == "#FFEBEE"
        # 中間点
        bg, mark, fg = fn(3, 5)
        assert mark == "△" and bg == "#FFF3E0"

    def test_scroll_enter_leave_pattern(self):
        """グリッドCanvasにEnter/LeaveパターンでMouseWheelをバインドしている"""
        import inspect
        from descriptive_scorer import _SingleQuestionScorer
        src = inspect.getsource(_SingleQuestionScorer._build_grid_panel)
        assert '<Enter>' in src, "Canvasに<Enter>バインドがない"
        assert '<Leave>' in src, "Canvasに<Leave>バインドがない"
        assert 'unbind_all' in src, "Leaveでunbind_allしていない"


# ============================================================
# trim_descriptive_regions テスト
# ============================================================


class TestTrimDescriptiveRegions:
    """trim_descriptive_regions のユニットテスト"""

    @pytest.fixture
    def image_folder(self, tmp_path):
        """テスト用画像フォルダを作成する"""
        from PIL import Image as PILImage
        folder = tmp_path / "00_Processing"
        folder.mkdir()
        for i in range(3):
            img = PILImage.new("RGB", (595, 842), color=(255, 255, 255))
            img.save(str(folder / f"image_{i:03d}.jpg"))
        return str(folder)

    @pytest.fixture
    def large_image_folder(self, tmp_path):
        """高解像度テスト用画像フォルダを作成する（記述のみモード想定）"""
        from PIL import Image as PILImage
        folder = tmp_path / "00_Processing"
        folder.mkdir()
        for i in range(3):
            img = PILImage.new("RGB", (2400, 3400), color=(255, 255, 255))
            img.save(str(folder / f"image_{i:03d}.jpg"))
        return str(folder)

    @pytest.fixture
    def config_two_questions(self):
        """2問の記述問題設定"""
        return {
            "questions": [
                {"id": "D1", "name": "記述1", "region": [100, 400, 300, 500], "max_score": 5, "aspect": 1},
                {"id": "D2", "name": "記述2", "region": [100, 510, 300, 600], "max_score": 10, "aspect": 2},
            ],
        }

    def test_basic_trim_without_highres(self, image_folder, config_two_questions, tmp_path):
        """高解像度モードなしでの基本切り出し"""
        from descriptive_scorer import trim_descriptive_regions
        output = str(tmp_path / "output")
        result = trim_descriptive_regions(image_folder, config_two_questions, output)
        assert "D1" in result
        assert "D2" in result
        assert len(result["D1"]) == 3, "3枚すべて切り出されるべき"
        assert len(result["D2"]) == 3

    def test_trim_produces_valid_images(self, image_folder, config_two_questions, tmp_path):
        """切り出し画像が有効なファイルとして存在する"""
        from descriptive_scorer import trim_descriptive_regions
        from PIL import Image as PILImage
        output = str(tmp_path / "output")
        result = trim_descriptive_regions(image_folder, config_two_questions, output)
        for q_id, images in result.items():
            for filename, path in images.items():
                assert Path(path).exists(), f"{path} が存在しない"
                with PILImage.open(path) as img:
                    assert img.size[0] > 0 and img.size[1] > 0

    def test_trim_empty_image_folder(self, tmp_path):
        """空のフォルダでは空の結果が返る"""
        from descriptive_scorer import trim_descriptive_regions
        empty = tmp_path / "empty"
        empty.mkdir()
        config = {"questions": [{"id": "D1", "name": "Q", "region": [0, 0, 100, 100], "max_score": 1, "aspect": 1}]}
        result = trim_descriptive_regions(str(empty), config, str(tmp_path / "out"))
        assert result == {"D1": {}}

    def test_trim_empty_questions(self, image_folder, tmp_path):
        """問題が空なら結果も空"""
        from descriptive_scorer import trim_descriptive_regions
        config = {"questions": []}
        result = trim_descriptive_regions(image_folder, config, str(tmp_path / "out"))
        assert result == {}

    def test_trim_with_original_folder_no_markers(self, image_folder, config_two_questions, tmp_path):
        """original_image_folder指定でマーカーなし画像 → フォールバックで切り出し成功"""
        from descriptive_scorer import trim_descriptive_regions
        from PIL import Image as PILImage
        # original_image_folder として同じ画像を用意
        orig_folder = tmp_path / "originals"
        orig_folder.mkdir()
        for f in Path(image_folder).iterdir():
            import shutil
            shutil.copy2(str(f), str(orig_folder / f.name))
        output = str(tmp_path / "output")
        result = trim_descriptive_regions(
            image_folder, config_two_questions, output,
            original_image_folder=str(orig_folder),
        )
        # フォールバックによりすべて切り出される
        assert len(result["D1"]) == 3
        assert len(result["D2"]) == 3

    def test_trim_large_images_no_highres(self, large_image_folder, tmp_path):
        """高解像度原画像でhighresなしでの切り出し（記述のみモード想定）"""
        from descriptive_scorer import trim_descriptive_regions
        config = {
            "questions": [
                {"id": "D1", "name": "Q", "region": [500, 1000, 1500, 2000], "max_score": 5, "aspect": 1},
            ],
        }
        output = str(tmp_path / "output")
        result = trim_descriptive_regions(large_image_folder, config, output)
        assert len(result["D1"]) == 3, "全画像が切り出されるべき"

    def test_trim_region_out_of_bounds_clamped(self, image_folder, tmp_path):
        """領域が画像外にはみ出した場合はクランプされる"""
        from descriptive_scorer import trim_descriptive_regions
        config = {
            "questions": [
                {"id": "D1", "name": "Q", "region": [500, 700, 800, 900], "max_score": 5, "aspect": 1},
            ],
        }
        output = str(tmp_path / "output")
        result = trim_descriptive_regions(image_folder, config, output)
        # 領域の right=800 > img_w=595 → clamped to 595
        # left=500 < right=595 なので切り出し成功
        assert len(result["D1"]) == 3


# ============================================================
# .bak 残留バグ修正テスト
# ============================================================


class TestBakFileCleanup:
    """atomic_json_save の .bak ファイルが load_json_safe で復元される問題のテスト"""

    def test_load_json_safe_recovers_from_bak(self, tmp_path):
        """本体削除後も .bak から復元できることを確認（修正前の問題動作）"""
        from constants import atomic_json_save, load_json_safe
        config_path = tmp_path / "descriptive_config.json"
        data = {"questions": [{"id": "D1"}]}

        # 2回保存 → 2回目で .bak が作成される
        atomic_json_save(str(config_path), data)
        atomic_json_save(str(config_path), data)

        # .bak が作成されている
        bak_path = config_path.with_suffix(".json.bak")
        assert bak_path.exists(), "atomic_json_save の2回目で .bak が作成されるべき"

        # 本体を削除
        config_path.unlink()
        assert not config_path.exists()

        # load_json_safe は .bak から復元する
        recovered = load_json_safe(str(config_path), required_keys=["questions"])
        assert recovered is not None, ".bak からの復元が動作するべき"
        assert recovered["questions"][0]["id"] == "D1"

    def test_bak_deleted_prevents_recovery(self, tmp_path):
        """本体と .bak の両方を削除すると復元できないことを確認"""
        from constants import atomic_json_save, load_json_safe
        config_path = tmp_path / "descriptive_config.json"
        data = {"questions": [{"id": "D1"}]}

        # 2回保存して .bak 作成
        atomic_json_save(str(config_path), data)
        atomic_json_save(str(config_path), data)

        # 本体と .bak 両方削除
        config_path.unlink()
        bak_path = config_path.with_suffix(".json.bak")
        if bak_path.exists():
            bak_path.unlink()

        result = load_json_safe(str(config_path), required_keys=["questions"])
        assert result is None, "本体と .bak 両方削除後は None を返すべき"

    def test_reset_deletes_bak_files(self, tmp_path):
        """_reset_descriptive_data 相当の処理で .bak も削除されることを検証"""
        from constants import atomic_json_save, load_json_safe

        # 3つのファイルを保存（2回ずつで .bak を生成）
        config_path = tmp_path / "descriptive_config.json"
        scores_path = tmp_path / "descriptive_scores.json"
        total_path = tmp_path / "total_display_config.json"

        for path, data in [
            (config_path, {"questions": [{"id": "D1"}]}),
            (scores_path, {"scores": {}}),
            (total_path, {"total_display_region": [0, 0, 100, 100]}),
        ]:
            atomic_json_save(str(path), data)
            atomic_json_save(str(path), data)  # 2回目で .bak 作成

        # リセット操作をシミュレート（修正版: .bak も削除）
        for path in [config_path, scores_path, total_path]:
            if path.exists():
                path.unlink()
            bak_atomic = path.with_suffix(path.suffix + ".bak")
            if bak_atomic.exists():
                bak_atomic.unlink()

        # 復元できないことを確認
        assert load_json_safe(str(config_path), required_keys=["questions"]) is None
        assert load_json_safe(str(scores_path), required_keys=["scores"]) is None
        assert load_json_safe(str(total_path), required_keys=["total_display_region"]) is None
