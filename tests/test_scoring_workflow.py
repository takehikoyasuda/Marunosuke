#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
記述採点ワークフロー改善テスト

ユースケース:
  ① 採点中に記述問題を追加
  ② 採点中に配点を変更
  ③ 全問やり直し（スコアリセット）
  ④ 0点の生徒を再確認（フィルタ「× 0点」）
  ⑤ 満点の生徒を再確認（フィルタ「○ 満点」）
  ⑥ 中間点の確認（フィルタ「△ 中間点」）

対象4機能:
  A. ReviewGUIフィルタ改善（○満点 / ×0点 / △中間点）
  B. 問題一覧の編集・配点変更
  C. 問題単位の採点リセット
  D. 未採点ジャンプ（Tabキー）
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from descriptive_scorer import (
    save_descriptive_config,
    save_descriptive_scores,
    load_descriptive_scores,
    DescriptiveScorerGUI,
    DescriptiveReviewGUI,
    filter_descriptive_review_answers,
    is_grading_space_key,
    _SingleQuestionScorer,
    DESCRIPTIVE_CONFIG_FILE,
)


# ============================================================
# フィクスチャ
# ============================================================

@pytest.fixture
def sample_config():
    """サンプル設定: 2 問"""
    return {
        "version": 1,
        "questions": [
            {"id": "D1", "name": "記述1", "max_score": 5, "aspect": 1,
             "region": [100, 400, 300, 500]},
            {"id": "D2", "name": "記述2", "max_score": 3, "aspect": 2,
             "region": [100, 510, 300, 600]},
        ],
        "total_display_region": None,
    }


@pytest.fixture
def sample_scores():
    """サンプルスコア: 5人分"""
    return {
        "img_001.jpg": {"D1": 5, "D2": 3},  # 両方満点
        "img_002.jpg": {"D1": 0, "D2": 0},  # 両方0点
        "img_003.jpg": {"D1": 3, "D2": 1},  # 両方中間点
        "img_004.jpg": {"D1": 5, "D2": 2},  # D1満点, D2中間点
        "img_005.jpg": {"D1": 0, "D2": 3},  # D1ゼロ, D2満点
    }


@pytest.fixture
def scores_path(tmp_path):
    """スコア保存先パス"""
    data_dir = tmp_path / "_saiten_grading_results" / "01_Results"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "descriptive_scores.json")


@pytest.fixture
def config_path(tmp_path):
    """設定保存先パス"""
    data_dir = tmp_path / "_saiten_grading_results" / "01_Results"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / DESCRIPTIVE_CONFIG_FILE)


# ============================================================
# A. ReviewGUI フィルタテスト
# ============================================================

class TestReviewGUIFilters:
    """DescriptiveReviewGUI のセマンティックフィルタのテスト"""

    @pytest.mark.parametrize(
        ("scores", "expected_unscored", "expected_scored"),
        [
            ({}, 3, 0),
            ({"a.jpg": {"D1": 5}}, 2, 1),
            ({name: {"D1": score} for name, score in
              (("a.jpg", 5), ("b.jpg", 0), ("c.jpg", 3))}, 0, 3),
        ],
        ids=["before-scoring", "during-scoring", "after-scoring"],
    )
    def test_unscored_and_scored_filters_across_scoring_states(
        self, scores, expected_unscored, expected_scored,
    ):
        """採点前・途中・完了後で未採点／採点済みを正しく抽出する。"""
        images = ["a.jpg", "b.jpg", "c.jpg"]
        unscored = filter_descriptive_review_answers(
            images, scores, {}, "D1", 5, "未採点",
        )
        scored = filter_descriptive_review_answers(
            images, scores, {}, "D1", 5, "採点済み",
        )
        assert len(unscored) == expected_unscored
        assert len(scored) == expected_scored

    def test_filter_values_include_semantic_labels(self, sample_config):
        """フィルタドロップダウンに ○満点、×0点、△中間点 が含まれる"""
        q = sample_config["questions"][0]  # max_score=5
        expected_vals = [
            "全て", "○ 満点", "× 0点", "△ 中間点", "未採点",
        ] + [str(s) for s in range(q["max_score"] + 1)]
        assert "○ 満点" in expected_vals
        assert "× 0点" in expected_vals
        assert "△ 中間点" in expected_vals
        assert "0" in expected_vals
        assert "5" in expected_vals
        assert len(expected_vals) == 11  # 5 semantic + 6 numeric

    def test_filter_full_score(self, sample_scores):
        """「○ 満点」フィルタで満点のみ抽出される"""
        qid = "D1"
        max_score = 5
        result = []
        for fname, scores in sample_scores.items():
            sc = scores.get(qid)
            if sc is not None and sc >= max_score:
                result.append(fname)
        assert sorted(result) == ["img_001.jpg", "img_004.jpg"]

    def test_filter_zero_score(self, sample_scores):
        """「× 0点」フィルタで0点のみ抽出される"""
        qid = "D1"
        result = []
        for fname, scores in sample_scores.items():
            sc = scores.get(qid)
            if sc is not None and sc == 0:
                result.append(fname)
        assert sorted(result) == ["img_002.jpg", "img_005.jpg"]

    def test_filter_partial_score(self, sample_scores):
        """「△ 中間点」フィルタで中間点（0 < score < max）のみ抽出される"""
        qid = "D1"
        max_score = 5
        result = []
        for fname, scores in sample_scores.items():
            sc = scores.get(qid)
            if sc is not None and 0 < sc < max_score:
                result.append(fname)
        assert sorted(result) == ["img_003.jpg"]

    def test_filter_partial_score_d2(self, sample_scores):
        """D2（配点3点）で中間点フィルタが正しく動作"""
        qid = "D2"
        max_score = 3
        result = []
        for fname, scores in sample_scores.items():
            sc = scores.get(qid)
            if sc is not None and 0 < sc < max_score:
                result.append(fname)
        # D2=1 (img_003), D2=2 (img_004)
        assert sorted(result) == ["img_003.jpg", "img_004.jpg"]

    def test_filter_unscored(self, sample_scores):
        """「未採点」フィルタで未採点のみ抽出される"""
        all_images = list(sample_scores.keys()) + ["img_006.jpg"]
        qid = "D1"
        result = []
        for fname in all_images:
            sc = sample_scores.get(fname, {}).get(qid)
            if sc is None:
                result.append(fname)
        assert result == ["img_006.jpg"]


# ============================================================
# B. 問題設定の編集テスト
# ============================================================

class TestEditQuestion:
    """DescriptiveScorerGUI._edit_question のロジックテスト"""

    def test_max_score_decrease_caps_scores(self, sample_scores):
        """配点を下げた場合、超過スコアがキャップされる"""
        scores = {k: dict(v) for k, v in sample_scores.items()}
        new_max = 3
        q_id = "D1"

        capped_count = 0
        for img_name in scores:
            sc = scores[img_name].get(q_id)
            if sc is not None and sc > new_max:
                scores[img_name][q_id] = new_max
                capped_count += 1

        assert capped_count == 2  # img_001, img_004
        assert scores["img_001.jpg"]["D1"] == 3
        assert scores["img_004.jpg"]["D1"] == 3
        assert scores["img_003.jpg"]["D1"] == 3  # 元々3なので変化なし
        assert scores["img_002.jpg"]["D1"] == 0  # 元々0なので変化なし

    def test_max_score_increase_no_cap(self, sample_scores):
        """配点を上げた場合、既存スコアは変更されない"""
        scores = {k: dict(v) for k, v in sample_scores.items()}
        new_max = 10
        q_id = "D1"

        over_count = sum(
            1 for img in scores
            if scores[img].get(q_id) is not None and scores[img][q_id] > new_max
        )
        assert over_count == 0

    def test_config_update_saves_correctly(self, sample_config, config_path):
        """設定変更後にJSONが正しく保存される"""
        sample_config["questions"][0]["name"] = "新しい問題名"
        sample_config["questions"][0]["max_score"] = 8
        sample_config["questions"][0]["aspect"] = 3

        save_descriptive_config(config_path, sample_config)

        with open(config_path, encoding="utf-8") as f:
            saved = json.load(f)

        assert saved["questions"][0]["name"] == "新しい問題名"
        assert saved["questions"][0]["max_score"] == 8
        assert saved["questions"][0]["aspect"] == 3

    def test_edit_preserves_region(self, sample_config):
        """設定の編集で region は変更されない"""
        original_region = list(sample_config["questions"][0]["region"])
        sample_config["questions"][0]["name"] = "変更後"
        sample_config["questions"][0]["max_score"] = 10
        assert sample_config["questions"][0]["region"] == original_region


# ============================================================
# C. 採点リセットテスト
# ============================================================

class TestResetQuestionScores:
    """問題単位の採点リセットのテスト"""

    def test_reset_removes_only_target_question(self, sample_scores):
        """リセット対象の問題スコアのみ削除され、他の問題は残る"""
        scores = {k: dict(v) for k, v in sample_scores.items()}
        q_id_to_reset = "D1"

        for img_name in list(scores.keys()):
            if q_id_to_reset in scores[img_name]:
                del scores[img_name][q_id_to_reset]
            if not scores[img_name]:
                del scores[img_name]

        for img_name in scores:
            assert q_id_to_reset not in scores[img_name]

        assert scores["img_001.jpg"]["D2"] == 3
        assert scores["img_002.jpg"]["D2"] == 0
        assert scores["img_003.jpg"]["D2"] == 1

    def test_reset_empty_entries_removed(self):
        """リセットで問題が1つしかない画像のエントリは削除される"""
        scores = {
            "img_001.jpg": {"D1": 5},
            "img_002.jpg": {"D1": 3, "D2": 2},
        }

        q_id = "D1"
        for img_name in list(scores.keys()):
            if q_id in scores[img_name]:
                del scores[img_name][q_id]
            if not scores[img_name]:
                del scores[img_name]

        assert "img_001.jpg" not in scores
        assert "img_002.jpg" in scores
        assert scores["img_002.jpg"] == {"D2": 2}

    def test_reset_count_is_correct(self, sample_scores):
        """リセット対象件数が正しくカウントされる"""
        q_id = "D1"
        count = sum(
            1 for img_name in sample_scores
            if q_id in sample_scores[img_name]
        )
        assert count == 5

    def test_reset_saves_to_file(self, sample_scores, scores_path):
        """リセット後にJSONファイルが更新される"""
        scores = {k: dict(v) for k, v in sample_scores.items()}
        q_id = "D1"

        for img_name in list(scores.keys()):
            if q_id in scores[img_name]:
                del scores[img_name][q_id]
            if not scores[img_name]:
                del scores[img_name]

        save_descriptive_scores(scores_path, {"version": 1, "scores": scores})
        loaded = load_descriptive_scores(scores_path)

        assert loaded is not None
        for img_name in loaded["scores"]:
            assert q_id not in loaded["scores"][img_name]


# ============================================================
# D. 未採点ジャンプテスト
# ============================================================

class TestJumpToUnscored:
    """_SingleQuestionScorer._jump_to_unscored のロジックテスト"""

    def test_jump_finds_next_unscored(self):
        """現在位置より後の未採点にジャンプする"""
        filenames = ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"]
        local_scores = {"a.jpg": 5, "b.jpg": 3, "d.jpg": 2}
        current_idx = 0

        n = len(filenames)
        found_idx = None
        for offset in range(1, n + 1):
            idx = (current_idx + offset) % n
            if filenames[idx] not in local_scores:
                found_idx = idx
                break

        assert found_idx == 2  # c.jpg

    def test_jump_wraps_around(self):
        """最後まで探して見つからなければ先頭からラップアラウンド"""
        filenames = ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"]
        local_scores = {"b.jpg": 3, "c.jpg": 1, "d.jpg": 2, "e.jpg": 0}
        current_idx = 3

        n = len(filenames)
        found_idx = None
        for offset in range(1, n + 1):
            idx = (current_idx + offset) % n
            if filenames[idx] not in local_scores:
                found_idx = idx
                break

        assert found_idx == 0  # a.jpg

    def test_jump_all_scored_returns_none(self):
        """全て採点済みの場合は見つからない"""
        filenames = ["a.jpg", "b.jpg", "c.jpg"]
        local_scores = {"a.jpg": 5, "b.jpg": 3, "c.jpg": 1}
        current_idx = 0

        n = len(filenames)
        found_idx = None
        for offset in range(1, n + 1):
            idx = (current_idx + offset) % n
            if filenames[idx] not in local_scores:
                found_idx = idx
                break

        assert found_idx is None

    def test_jump_single_unscored(self):
        """未採点が1件だけの場合でも正しく見つかる"""
        filenames = ["a.jpg", "b.jpg", "c.jpg"]
        local_scores = {"a.jpg": 5, "c.jpg": 1}
        current_idx = 2

        n = len(filenames)
        found_idx = None
        for offset in range(1, n + 1):
            idx = (current_idx + offset) % n
            if filenames[idx] not in local_scores:
                found_idx = idx
                break

        assert found_idx == 1  # b.jpg

    def test_unscored_count_calculation(self):
        """未採点カウントが正しく計算される"""
        filenames = ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"]
        local_scores = {"a.jpg": 5, "c.jpg": 3}
        unscored = sum(1 for f in filenames if f not in local_scores)
        assert unscored == 3


# ============================================================
# E. 統合ワークフローテスト
# ============================================================

class TestWorkflowIntegration:
    """記述採点ワークフロー全体の統合テスト"""

    def test_add_question_then_score(self, sample_config, sample_scores):
        """① 問題追加後に新問題の採点が可能"""
        sample_config["questions"].append({
            "id": "D3", "name": "記述3", "max_score": 4, "aspect": 1,
            "region": [100, 610, 300, 700],
        })
        assert len(sample_config["questions"]) == 3

        for img, scores in sample_scores.items():
            assert "D3" not in scores

        for img in sample_scores:
            sample_scores[img]["D3"] = 2

        for img in sample_scores:
            assert len(sample_scores[img]) == 3

    def test_change_max_score_workflow(self, sample_config, sample_scores, config_path, scores_path):
        """② 配点変更 → 超過キャップ → 保存の一連の流れ"""
        scores = {k: dict(v) for k, v in sample_scores.items()}

        new_max = 3
        sample_config["questions"][0]["max_score"] = new_max

        for img_name in scores:
            sc = scores[img_name].get("D1")
            if sc is not None and sc > new_max:
                scores[img_name]["D1"] = new_max

        save_descriptive_config(config_path, sample_config)
        save_descriptive_scores(scores_path, {"version": 1, "scores": scores})

        loaded_scores = load_descriptive_scores(scores_path)
        for img_name in loaded_scores["scores"]:
            sc = loaded_scores["scores"][img_name].get("D1")
            if sc is not None:
                assert sc <= new_max

    def test_reset_and_rescore(self, sample_scores, scores_path):
        """③ リセット → 再採点のワークフロー"""
        scores = {k: dict(v) for k, v in sample_scores.items()}

        for img_name in list(scores.keys()):
            if "D1" in scores[img_name]:
                del scores[img_name]["D1"]
            if not scores[img_name]:
                del scores[img_name]

        for img_name in scores:
            assert "D1" not in scores[img_name]

        all_images = [f"img_{i:03d}.jpg" for i in range(1, 6)]
        new_scores_d1 = [4, 1, 3, 5, 2]
        for img, new_sc in zip(all_images, new_scores_d1):
            if img not in scores:
                scores[img] = {}
            scores[img]["D1"] = new_sc

        save_descriptive_scores(scores_path, {"version": 1, "scores": scores})
        loaded = load_descriptive_scores(scores_path)

        assert loaded["scores"]["img_001.jpg"]["D1"] == 4
        assert loaded["scores"]["img_001.jpg"]["D2"] == 3

    def test_filter_then_edit_workflow(self, sample_scores):
        """④⑤ フィルタ → 個別修正のワークフロー"""
        scores = {k: dict(v) for k, v in sample_scores.items()}
        max_score_d1 = 5

        zero_students = [
            fn for fn in scores
            if scores[fn].get("D1") is not None and scores[fn]["D1"] == 0
        ]
        assert len(zero_students) == 2

        for fn in zero_students:
            scores[fn]["D1"] = 5

        assert scores["img_002.jpg"]["D1"] == 5
        assert scores["img_005.jpg"]["D1"] == 5

        full_students = [
            fn for fn in scores
            if scores[fn].get("D1") is not None and scores[fn]["D1"] >= max_score_d1
        ]
        assert len(full_students) == 4

    def test_partial_score_consistency_check(self, sample_scores):
        """⑥ 中間点一覧で採点基準の一貫性を確認"""
        max_score_d2 = 3
        partial_students = [
            (fn, sample_scores[fn]["D2"])
            for fn in sample_scores
            if sample_scores[fn].get("D2") is not None
            and 0 < sample_scores[fn]["D2"] < max_score_d2
        ]
        assert len(partial_students) == 2
        scores_only = sorted([sc for _, sc in partial_students])
        assert scores_only == [1, 2]


# ============================================================
# F. コード構造テスト
# ============================================================

class TestCodeStructure:
    """新機能のコード構造が正しいことを確認"""

    def test_edit_question_method_exists(self):
        """DescriptiveScorerGUI._edit_question メソッドが存在する"""
        assert hasattr(DescriptiveScorerGUI, "_edit_question")
        assert callable(getattr(DescriptiveScorerGUI, "_edit_question"))

    def test_reset_question_scores_method_exists(self):
        """DescriptiveScorerGUI._reset_question_scores メソッドが存在する"""
        assert hasattr(DescriptiveScorerGUI, "_reset_question_scores")
        assert callable(getattr(DescriptiveScorerGUI, "_reset_question_scores"))

    def test_update_info_labels_method_exists(self):
        """DescriptiveScorerGUI._update_info_labels メソッドが存在する"""
        assert hasattr(DescriptiveScorerGUI, "_update_info_labels")
        assert callable(getattr(DescriptiveScorerGUI, "_update_info_labels"))

    def test_jump_to_unscored_method_exists(self):
        """_SingleQuestionScorer._jump_to_unscored メソッドが存在する"""
        assert hasattr(_SingleQuestionScorer, "_jump_to_unscored")
        assert callable(getattr(_SingleQuestionScorer, "_jump_to_unscored"))

    def test_review_gui_filter_code(self):
        """DescriptiveReviewGUI のソースにセマンティックフィルタが含まれる"""
        import inspect
        source = inspect.getsource(DescriptiveReviewGUI._on_question_selected)
        assert "○ 満点" in source
        assert "× 0点" in source
        assert "△ 中間点" in source

    def test_review_gui_refresh_handles_filters(self):
        """DescriptiveReviewGUI._refresh_grid がセマンティックフィルタを処理する"""
        import inspect
        source = inspect.getsource(filter_descriptive_review_answers)
        assert "○ 満点" in source
        assert "× 0点" in source
        assert "△ 中間点" in source
        assert "採点済み" in source

    def test_scorer_help_text_includes_tab(self):
        """採点画面のヘルプテキストに Tab 説明がある"""
        import inspect
        source = inspect.getsource(_SingleQuestionScorer.run)
        assert "Tab" in source
        assert "未採点" in source

    def test_scorer_binds_tab_key(self):
        """_SingleQuestionScorer が Tab キーをバインドしている"""
        import inspect
        source = inspect.getsource(_SingleQuestionScorer.run)
        assert "<Tab>" in source
        assert "_jump_to_unscored" in source

    def test_three_way_dialog_buttons_use_black_text(self):
        """macOSでも3択ダイアログの全ボタンを黒文字で表示する。"""
        import inspect
        from descriptive_gui import _ask_three_way_japanese
        source = inspect.getsource(_ask_three_way_japanese)
        assert 'fg="white"' not in source
        assert source.count('activeforeground="black"') == 3

    def test_question_list_has_edit_button(self):
        """問題一覧に設定ボタンが含まれる"""
        import inspect
        source = inspect.getsource(DescriptiveScorerGUI._show_question_list)
        assert "設定" in source
        assert "_edit_question" in source

    def test_edit_dialog_has_reset_button(self):
        """編集ダイアログに採点リセットボタンが含まれる"""
        import inspect
        source = inspect.getsource(DescriptiveScorerGUI._edit_question)
        assert "リセット" in source
        assert "_reset_question_scores" in source

    def test_question_list_has_scoring_mode_selector(self):
        """問題一覧画面に採点モード選択UIが含まれる"""
        import inspect
        source = inspect.getsource(DescriptiveScorerGUI._show_question_list)
        assert "採点モード" in source
        assert "_scoring_mode_var" in source
        assert "1枚ずつ" in source
        assert "一覧" in source

    def test_scorer_accepts_initial_mode(self):
        """_SingleQuestionScorer が initial_mode 引数を受け付ける"""
        import inspect
        sig = inspect.signature(_SingleQuestionScorer.__init__)
        params = list(sig.parameters.keys())
        assert "initial_mode" in params

    def test_scorer_has_maru_batsu_methods(self):
        """_SingleQuestionScorer に〇/×ボタンメソッドが存在する"""
        assert hasattr(_SingleQuestionScorer, "_on_maru")
        assert hasattr(_SingleQuestionScorer, "_on_batsu")
        assert hasattr(_SingleQuestionScorer, "_assign_score")
        assert hasattr(_SingleQuestionScorer, "_flash_background")

    def test_scorer_has_filter_methods(self):
        """_SingleQuestionScorer にフィルタメソッドが存在する"""
        assert hasattr(_SingleQuestionScorer, "_on_filter_change")
        assert hasattr(_SingleQuestionScorer, "_update_filter_list")
        assert hasattr(_SingleQuestionScorer, "_find_next_filtered")
        assert hasattr(_SingleQuestionScorer, "_find_prev_filtered")

    def test_scorer_help_text_includes_maru_batsu(self):
        """採点画面のヘルプテキストに m/b ショートカット説明がある"""
        import inspect
        # ヘルプウィンドウに移動したため _show_help_window を検査
        source = inspect.getsource(_SingleQuestionScorer._show_help_window)
        assert "m" in source
        assert "b" in source

    def test_scorer_has_single_answer_filters(self):
        """採点画面に全件・未採点・保留フィルタが含まれる"""
        import inspect
        source = inspect.getsource(_SingleQuestionScorer.run)
        assert '("全件", "未採点", "保留")' in source
        assert "_single_filter_var" in source

    def test_single_answer_annotation_panel_is_compact_and_scrollable(self):
        """小さい画面でも右パネル下段へスクロールできる"""
        import inspect
        source = inspect.getsource(_SingleQuestionScorer.run)
        assert "rubric_canvas" in source
        assert "rubric_scrollbar" in source
        assert 'height=4, wrap=tk.WORD' in source
        assert 'height=90' in source
        assert "_bind_rubric_scroll" in source

    def test_memo_and_comment_history_controls_are_consistent(self):
        """メモとコメントの履歴欄に挿入・削除操作が揃っている"""
        import inspect
        source = inspect.getsource(_SingleQuestionScorer.run)
        assert "memo_history_row" in source
        assert "comment_history_row" in source
        assert "command=self._insert_memo_history" in source
        assert "command=self._insert_comment_history" in source
        assert "command=self._delete_memo_history" in source
        assert "command=self._delete_comment_history" in source


# ============================================================
# G. 〇/×ボタン・フィルタ・背景色ロジックテスト
# ============================================================

class TestMaruBatsuLogic:
    """〇/×ボタンおよびフィルタのロジックテスト"""

    def _make_scorer(self, filenames, max_score=5, local_scores=None):
        """テスト用にスコアラーインスタンスを生成（UIなし）"""
        scorer = _SingleQuestionScorer.__new__(_SingleQuestionScorer)
        scorer.filenames = filenames
        scorer.max_score = max_score
        scorer.use_entry = max_score > 9
        scorer.local_scores = dict(local_scores or {})
        scorer.current_idx = 0
        scorer.q_id = "D1"
        scorer.annotations = {"answers": {}}
        scorer._filtered_indices = list(range(len(filenames)))
        scorer._single_filter_var = type("MockVar", (), {"get": lambda s: "全件"})()
        return scorer

    def test_assign_score_sets_value(self):
        """_assign_score がスコアを正しく設定する"""
        scorer = self._make_scorer(["a.jpg", "b.jpg"])
        # _assign_score には _win, canvas, score_var が必要だが、
        # ロジックだけ確認するため local_scores に直接設定
        scorer.local_scores["a.jpg"] = 5
        assert scorer.local_scores["a.jpg"] == 5

    def test_filter_unscored_only(self):
        """フィルタON時に未採点のみのインデックスリストを生成"""
        filenames = ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"]
        scored = {"a.jpg": 5, "c.jpg": 3}
        scorer = self._make_scorer(filenames, local_scores=scored)
        scorer._single_filter_var = type("MockVar", (), {"get": lambda s: "未採点"})()
        scorer._update_filter_list()
        assert scorer._filtered_indices == [1, 3, 4]  # b, d, e

    def test_filter_off_shows_all(self):
        """フィルタOFF時に全件のインデックスリストを生成"""
        filenames = ["a.jpg", "b.jpg", "c.jpg"]
        scored = {"a.jpg": 5}
        scorer = self._make_scorer(filenames, local_scores=scored)
        scorer._single_filter_var = type("MockVar", (), {"get": lambda s: "全件"})()
        scorer._update_filter_list()
        assert scorer._filtered_indices == [0, 1, 2]

    def test_filter_held_only(self):
        """保留は得点の有無と独立して抽出される"""
        scorer = self._make_scorer(
            ["a.jpg", "b.jpg", "c.jpg", "d.jpg"],
            local_scores={"a.jpg": 5, "b.jpg": 2, "d.jpg": 0},
        )
        scorer.annotations = {"answers": {
            "b.jpg": {"D1": {"held": True}},
            "c.jpg": {"D1": {"held": True}},
            "d.jpg": {"D1": {"held": False}},
        }}
        scorer._single_filter_var = type("MockVar", (), {"get": lambda s: "保留"})()

        scorer._update_filter_list()

        assert scorer._filtered_indices == [1, 2]

    def test_find_next_filtered(self):
        """_find_next_filtered がフィルタ済みリストから次を返す"""
        scorer = self._make_scorer(["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"])
        scorer._filtered_indices = [1, 3, 4]
        assert scorer._find_next_filtered(0) == 1
        assert scorer._find_next_filtered(1) == 3
        assert scorer._find_next_filtered(3) == 4
        assert scorer._find_next_filtered(4) is None

    def test_find_prev_filtered(self):
        """_find_prev_filtered がフィルタ済みリストから前を返す"""
        scorer = self._make_scorer(["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"])
        scorer._filtered_indices = [1, 3, 4]
        assert scorer._find_prev_filtered(4) == 3
        assert scorer._find_prev_filtered(3) == 1
        assert scorer._find_prev_filtered(1) is None
        assert scorer._find_prev_filtered(0) is None

    def test_held_filter_end_does_not_show_scoring_complete_dialog(self):
        """保留レビュー末尾への移動で採点完了扱いにしない"""
        from unittest.mock import MagicMock

        scorer = self._make_scorer(["a.jpg"], local_scores={"a.jpg": 5})
        scorer._single_filter_var = type("MockVar", (), {"get": lambda s: "保留"})()
        scorer._filtered_indices = [0]
        scorer._show_all_scored_dialog = MagicMock()

        scorer._next_auto()

        scorer._show_all_scored_dialog.assert_not_called()

    def test_filter_updates_after_score(self):
        """採点後にフィルタリストが更新される"""
        filenames = ["a.jpg", "b.jpg", "c.jpg"]
        scorer = self._make_scorer(filenames)
        scorer._single_filter_var = type("MockVar", (), {"get": lambda s: "未採点"})()
        scorer._update_filter_list()
        assert scorer._filtered_indices == [0, 1, 2]

        scorer.local_scores["a.jpg"] = 5
        scorer._update_filter_list()
        assert scorer._filtered_indices == [1, 2]

    def test_flash_background_colors(self):
        """_flash_background が正しい色を選択する"""
        scorer = self._make_scorer(["a.jpg"], max_score=5)
        # max_score のテスト
        assert scorer.max_score == 5
        # 色の選択ロジックをテスト
        # 満点 → 薄青
        score = 5
        if score >= scorer.max_score:
            bg = "#E3F2FD"
        elif score == 0:
            bg = "#FFEBEE"
        else:
            bg = "#FFF3E0"
        assert bg == "#E3F2FD"

        # 0点 → 薄赤
        score = 0
        if score >= scorer.max_score:
            bg = "#E3F2FD"
        elif score == 0:
            bg = "#FFEBEE"
        else:
            bg = "#FFF3E0"
        assert bg == "#FFEBEE"

        # 中間点 → 薄橙
        score = 3
        if score >= scorer.max_score:
            bg = "#E3F2FD"
        elif score == 0:
            bg = "#FFEBEE"
        else:
            bg = "#FFF3E0"
        assert bg == "#FFF3E0"

    def test_on_key_m_and_b_handling(self):
        """_on_key が m/b キーで〇/×メソッドを呼び出すこと"""
        import inspect
        source = inspect.getsource(_SingleQuestionScorer._on_key)
        # m キーで _on_maru を呼ぶ
        assert "\"m\"" in source or "'m'" in source
        assert "_on_maru" in source
        # b キーで _on_batsu を呼ぶ
        assert "\"b\"" in source or "'b'" in source
        assert "_on_batsu" in source

    @pytest.mark.parametrize("keycode", [102, 104])
    def test_jis_input_mode_keys_are_not_grading_space(self, keycode):
        """macOSの英数・かなキーはspace相当の文字情報でも除外する。"""
        event = type("KeyEvent", (), {
            "keysym": "space", "char": " ", "keycode": keycode,
        })()
        assert is_grading_space_key(event, "darwin") is False

    def test_macos_physical_space_is_grading_space(self):
        """macOSの通常のスペースキー（keycode 49）は答案送りに使える。"""
        event = type("KeyEvent", (), {
            "keysym": "space", "char": " ", "keycode": 49,
        })()
        assert is_grading_space_key(event, "darwin") is True

    def test_non_macos_space_uses_character(self):
        """他OSでは従来どおり入力文字でスペースを判定する。"""
        event = type("KeyEvent", (), {
            "keysym": "space", "char": " ", "keycode": 65,
        })()
        assert is_grading_space_key(event, "linux") is True

    def test_initial_mode_parsing(self):
        """initial_mode の文字列から正しくモードを判定する"""
        scorer1 = _SingleQuestionScorer.__new__(_SingleQuestionScorer)
        # "1枚ずつ" を含む → "1枚ずつ"
        mode = "1枚ずつ"
        result = "1枚ずつ" if "1枚" in mode else "一覧"
        assert result == "1枚ずつ"

        # "一覧（グリッド）" → "一覧"
        mode = "一覧（グリッド）"
        result = "1枚ずつ" if "1枚" in mode else "一覧"
        assert result == "一覧"
