#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""roster_matcher.rank_roster_candidates のテスト。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "main_src"))

from roster_matcher import rank_roster_candidates  # noqa: E402


class TestRankRosterCandidates(unittest.TestCase):

    def test_01_empty_per_digit_proba_returns_empty(self):
        roster = {"12345": "山田太郎"}
        self.assertEqual(rank_roster_candidates([], roster), [])

    def test_02_empty_roster_returns_empty(self):
        per_digit_proba = [{"1": 0.9, "2": 0.1}]
        self.assertEqual(rank_roster_candidates(per_digit_proba, {}), [])

    def test_03_digit_count_mismatch_excluded(self):
        # per_digit_probaは3桁だが、名簿は4桁・5桁のみ → どちらも対象外
        per_digit_proba = [{"1": 1.0}, {"2": 1.0}, {"3": 1.0}]
        roster = {"1234": "A", "12345": "B"}
        self.assertEqual(rank_roster_candidates(per_digit_proba, roster), [])

    def test_04_exact_argmax_match_ranks_first(self):
        # 各桁とも1位候補がそのまま名簿の学籍番号と一致するケース
        per_digit_proba = [
            {"1": 0.9, "2": 0.1},
            {"2": 0.9, "3": 0.1},
            {"3": 0.9, "4": 0.1},
        ]
        roster = {"123": "正解太郎", "124": "不正解次郎", "999": "無関係花子"}
        result = rank_roster_candidates(per_digit_proba, roster)
        self.assertEqual(result[0][0], "123")
        self.assertEqual(result[0][1], "正解太郎")
        # 名簿内で最有力なので相対確率も高いはず
        self.assertGreater(result[0][2], result[1][2])

    def test_05_single_digit_misread_still_recovers_correct_id(self):
        """1桁だけ1位候補が誤読でも、名簿という有限候補集合の中では正解が浮上する。

        実際の手書き数字OCRで多い「8桁中1桁だけ間違う」パターンを模したテスト:
        1桁目は"7"が1位候補(誤読)だが、正解の"1"にも僅かに確率が乗っている。
        1位候補をそのまま連結した"723"は名簿に存在しない学籍番号(＝実在しない)
        なので、名簿に実在する"123"が候補として浮上するべき。単純な完全一致
        (OCR文字列 == 名簿の文字列)では「名簿に一致なし」としか出せない
        ケースに相当する。
        """
        per_digit_proba = [
            {"7": 0.55, "1": 0.40, "0": 0.05},  # 誤読しやすい桁(1位は誤り)
            {"2": 0.97, "8": 0.03},
            {"3": 0.98, "9": 0.02},
        ]
        roster = {
            "123": "正解太郎",   # 1桁目の1位候補との単純文字列比較では一致しない
            "156": "無関係次郎",  # "723"は名簿に実在しない前提
            "999": "無関係花子",
        }
        result = rank_roster_candidates(per_digit_proba, roster, top_k=3)
        self.assertEqual(result[0][0], "123", "名簿に実在する候補の中から正解が浮上するべき")

    def test_06_top_k_limits_result_count(self):
        per_digit_proba = [{"1": 0.5, "2": 0.5}]
        roster = {"1": "A", "2": "B"}
        result = rank_roster_candidates(per_digit_proba, roster, top_k=1)
        self.assertEqual(len(result), 1)

    def test_07_probabilities_sum_to_roughly_100(self):
        per_digit_proba = [{"1": 0.6, "2": 0.4}]
        roster = {"1": "A", "2": "B"}
        result = rank_roster_candidates(per_digit_proba, roster, top_k=2)
        total_pct = sum(pct for _, _, pct in result)
        self.assertAlmostEqual(total_pct, 100.0, places=5)


if __name__ == "__main__":
    unittest.main()
