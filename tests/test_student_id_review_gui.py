#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""student_id_review_gui.StudentIdReviewGUI の名簿候補自動採用ロジックのテスト。"""

import os
import sys
import tkinter as tk
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "main_src"))

from conftest import get_shared_tk_root  # noqa: E402
from student_id_review_gui import StudentIdReviewGUI  # noqa: E402


def _make_ocr_result(per_digit_proba, text, confidence=0.9):
    return {
        'thumbnail_path': None,
        'text': text,
        'confidence': confidence,
        'per_digit': [],
        'per_digit_proba': per_digit_proba,
    }


class TestStudentIdReviewGuiRosterAutoApply(unittest.TestCase):

    def setUp(self):
        self.root = get_shared_tk_root()

    def test_01_auto_applies_top_candidate_when_no_exact_match(self):
        """OCR生文字列("723")は名簿に無いが、名簿には"123"がある(1桁目のみ誤読)。

        集計に使われる 'text'/'name' が、生のOCR文字列ではなく名簿照合済みの
        最有力候補で自動的に埋まっていることを確認する。
        """
        per_digit_proba = [
            {"7": 0.55, "1": 0.40, "0": 0.05},
            {"2": 0.97, "8": 0.03},
            {"3": 0.98, "9": 0.02},
        ]
        ocr_results = {"a.jpg": _make_ocr_result(per_digit_proba, "723")}
        roster = {"123": "正解太郎", "156": "無関係次郎"}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster)
        try:
            entry = gui.confirmed["a.jpg"]
            self.assertEqual(entry['text'], "123")
            self.assertEqual(entry['name'], "正解太郎")
            self.assertTrue(entry['auto_applied'])
            self.assertFalse(entry['edited'])
        finally:
            gui.window.destroy()

    def test_02_exact_match_does_not_mark_auto_applied(self):
        """OCR生文字列がそのまま名簿に完全一致する場合は自動採用扱いにしない。"""
        per_digit_proba = [{"1": 0.99}, {"2": 0.99}, {"3": 0.99}]
        ocr_results = {"a.jpg": _make_ocr_result(per_digit_proba, "123")}
        roster = {"123": "正解太郎"}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster)
        try:
            entry = gui.confirmed["a.jpg"]
            self.assertEqual(entry['text'], "123")
            self.assertEqual(entry['name'], "正解太郎")
            self.assertFalse(entry['auto_applied'])
        finally:
            gui.window.destroy()

    def test_03_ambiguous_candidates_not_auto_applied(self):
        """候補同士が拮抗している(最有力候補でも閾値未満)場合は自動採用せず、
        生の値のまま残す。"""
        per_digit_proba = [{"1": 0.34, "2": 0.33, "3": 0.33}]
        ocr_results = {"a.jpg": _make_ocr_result(per_digit_proba, "9")}
        roster = {"1": "Aさん", "2": "Bさん", "3": "Cさん"}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster)
        try:
            entry = gui.confirmed["a.jpg"]
            self.assertFalse(entry['auto_applied'])
            self.assertEqual(entry['text'], "9")
            self.assertIsNone(entry['name'])
        finally:
            gui.window.destroy()

    def test_04_manual_edit_overrides_and_clears_auto_applied_flag(self):
        """教員が単体表示で値を修正した場合、その値が最終的に採用され
        auto_applied フラグはクリアされる(表示上「推定」のままにならない)。"""
        per_digit_proba = [
            {"7": 0.55, "1": 0.40},
            {"2": 0.97},
            {"3": 0.98},
        ]
        ocr_results = {"a.jpg": _make_ocr_result(per_digit_proba, "723")}
        roster = {"123": "正解太郎", "156": "無関係次郎"}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster)
        try:
            self.assertTrue(gui.confirmed["a.jpg"]['auto_applied'])

            gui._current_index = 0
            gui._filenames = ["a.jpg"]
            gui._current_entry = tk.Entry(self.root)
            gui._current_entry.insert(0, "999")
            gui._confirm_current()

            entry = gui.confirmed["a.jpg"]
            self.assertEqual(entry['text'], "999")
            self.assertTrue(entry['edited'])
            self.assertFalse(entry['auto_applied'])
        finally:
            gui.window.destroy()

    def test_05_no_roster_never_auto_applies(self):
        """名簿が渡されない場合、そもそも候補判定自体を行わない。"""
        per_digit_proba = [{"7": 0.55, "1": 0.40}]
        ocr_results = {"a.jpg": _make_ocr_result(per_digit_proba, "7")}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster=None)
        try:
            entry = gui.confirmed["a.jpg"]
            self.assertFalse(entry['auto_applied'])
            self.assertEqual(entry['roster_candidates'], [])
            self.assertEqual(entry['text'], "7")
        finally:
            gui.window.destroy()

    def test_06_close_runner_up_blocks_auto_apply(self):
        """末尾1桁違いの学生が複数いる名簿を模したケース: 1位候補が閾値(50%)を
        超えていても、2位候補（＝別の実在学生）との差が僅かなら自動採用しない。

        例: 学籍番号の末尾だけが違う"...7"さんと"...1"さんが両方名簿にいて、
        OCRがその桁を55% vs 45%としか判定できなかった場合、安易にどちらかへ
        自動確定すると誤って別人の答案にしてしまうリスクがある。
        """
        per_digit_proba = [{"7": 0.55, "1": 0.45}]
        ocr_results = {"a.jpg": _make_ocr_result(per_digit_proba, "7")}
        roster = {"7": "末尾7さん", "1": "末尾1さん"}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster)
        try:
            entry = gui.confirmed["a.jpg"]
            self.assertFalse(entry['auto_applied'], "僅差の2位候補がある場合は自動採用しないべき")
            self.assertEqual(len(entry['roster_candidates']), 2)
        finally:
            gui.window.destroy()

    def test_07_quick_select_candidate_updates_confirmed_without_single_view(self):
        """グリッドカードの候補ボタン相当の操作(_quick_select_candidate)で、
        単体表示を開かずにその場で学籍番号を選び直せること。"""
        per_digit_proba = [{"7": 0.55, "1": 0.45}]
        ocr_results = {"a.jpg": _make_ocr_result(per_digit_proba, "7")}
        roster = {"7": "末尾7さん", "1": "末尾1さん"}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster)
        try:
            gui._quick_select_candidate("a.jpg", "1")
            entry = gui.confirmed["a.jpg"]
            self.assertEqual(entry['text'], "1")
            self.assertEqual(entry['name'], "末尾1さん")
            self.assertTrue(entry['edited'])
            self.assertFalse(entry['auto_applied'])
        finally:
            gui.window.destroy()

    def test_08_duplicate_ids_detected(self):
        """同じ学籍番号が2枚に割り当てられている場合、_duplicate_ids で検出できる。"""
        ocr_results = {
            "a.jpg": _make_ocr_result([], "111"),
            "b.jpg": _make_ocr_result([], "111"),
            "c.jpg": _make_ocr_result([], "222"),
        }
        gui = StudentIdReviewGUI(self.root, ocr_results, roster=None)
        try:
            duplicates = gui._duplicate_ids()
            self.assertEqual(set(duplicates.keys()), {"111"})
            self.assertEqual(set(duplicates["111"]), {"a.jpg", "b.jpg"})
        finally:
            gui.window.destroy()

    def test_09_missing_students_detected(self):
        """名簿にいるが、どの答案の確定値にも現れない学籍番号を検出できる。"""
        ocr_results = {
            "a.jpg": _make_ocr_result([], "111"),
            "b.jpg": _make_ocr_result([], "222"),
        }
        roster = {"111": "Aさん", "222": "Bさん", "333": "Cさん"}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster)
        try:
            missing = gui._missing_students()
            self.assertEqual(missing, {"333": "Cさん"})
        finally:
            gui.window.destroy()

    def test_10_no_duplicates_or_missing_when_all_match(self):
        ocr_results = {
            "a.jpg": _make_ocr_result([], "111"),
            "b.jpg": _make_ocr_result([], "222"),
        }
        roster = {"111": "Aさん", "222": "Bさん"}
        gui = StudentIdReviewGUI(self.root, ocr_results, roster)
        try:
            self.assertEqual(gui._duplicate_ids(), {})
            self.assertEqual(gui._missing_students(), {})
        finally:
            gui.window.destroy()


if __name__ == "__main__":
    unittest.main()
