#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_page_number_checker.py — page_number_checker.py（印刷ページ番号の取り違え確認ツール）のテスト。

OCRモデル自体の認識精度は test_student_id_ocr.py 側で検証済みのため、ここでは
`recognize_page_numbers`（矩形クロップ→多数決→不一致フラグ付け）のロジックを、
`LocalDigitOcrRecognizer.recognize` をモックして検証する。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from digit_ocr_recognizer import DigitOcrCandidate


def _make_dummy_images(tmpdir, filenames):
    paths = []
    for filename in filenames:
        path = Path(tmpdir) / filename
        Image.new('RGB', (50, 50), color=(255, 255, 255)).save(path)
        paths.append(str(path))
    return paths


class TestRecognizePageNumbers(unittest.TestCase):
    """recognize_page_numbers() のテスト（OCR結果はモック）"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_page_number_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_all_matching_no_mismatch(self):
        from page_number_checker import recognize_page_numbers
        image_files = _make_dummy_images(self.test_dir, ["a.png", "b.png", "c.png"])
        candidates = [
            DigitOcrCandidate(value="2", confidence=0.95),
            DigitOcrCandidate(value="2", confidence=0.90),
            DigitOcrCandidate(value="2", confidence=0.88),
        ]
        with patch("digit_ocr_recognizer.LocalDigitOcrRecognizer.recognize", side_effect=candidates):
            results = recognize_page_numbers(image_files, (0, 0, 10, 10))

        self.assertEqual(len(results), 3)
        for filename in ("a.png", "b.png", "c.png"):
            self.assertEqual(results[filename]['value'], "2")
            self.assertFalse(results[filename]['mismatch'])

    def test_02_outlier_flagged_as_mismatch(self):
        from page_number_checker import recognize_page_numbers
        image_files = _make_dummy_images(self.test_dir, ["a.png", "b.png", "c.png"])
        # ソート順(a,b,c)に対応させる: 2件が"1"、1件だけ"3"の混入
        candidates = [
            DigitOcrCandidate(value="1", confidence=0.9),
            DigitOcrCandidate(value="1", confidence=0.9),
            DigitOcrCandidate(value="3", confidence=0.9),
        ]
        with patch("digit_ocr_recognizer.LocalDigitOcrRecognizer.recognize", side_effect=candidates):
            results = recognize_page_numbers(image_files, (0, 0, 10, 10))

        self.assertFalse(results["a.png"]['mismatch'])
        self.assertFalse(results["b.png"]['mismatch'])
        self.assertTrue(results["c.png"]['mismatch'])
        self.assertEqual(results["c.png"]['value'], "3")

    def test_03_unrecognized_digit_flagged_as_mismatch(self):
        """OCR失敗(value=None)のファイルも不一致として扱われること"""
        from page_number_checker import recognize_page_numbers
        image_files = _make_dummy_images(self.test_dir, ["a.png", "b.png"])
        candidates = [
            DigitOcrCandidate(value="5", confidence=0.9),
            DigitOcrCandidate(value=None, confidence=0.0),
        ]
        with patch("digit_ocr_recognizer.LocalDigitOcrRecognizer.recognize", side_effect=candidates):
            results = recognize_page_numbers(image_files, (0, 0, 10, 10))

        self.assertFalse(results["a.png"]['mismatch'])
        self.assertTrue(results["b.png"]['mismatch'])
        self.assertIsNone(results["b.png"]['value'])

    def test_04_missing_image_file_safe_fallback(self):
        """画像が読み込めない(壊れている/存在しない)場合も例外にならないこと"""
        from page_number_checker import recognize_page_numbers
        image_files = _make_dummy_images(self.test_dir, ["a.png"])
        image_files.append(str(Path(self.test_dir) / "does_not_exist.png"))
        candidates = [DigitOcrCandidate(value="4", confidence=0.9)]
        with patch("digit_ocr_recognizer.LocalDigitOcrRecognizer.recognize", side_effect=candidates):
            results = recognize_page_numbers(image_files, (0, 0, 10, 10))

        self.assertEqual(results["a.png"]['value'], "4")
        self.assertFalse(results["a.png"]['mismatch'])
        self.assertIsNone(results["does_not_exist.png"]['value'])
        self.assertTrue(results["does_not_exist.png"]['mismatch'])

    def test_05_no_recognizable_digits_no_crash(self):
        """全ファイルが認識失敗の場合でも例外にならず、全件不一致にならないこと"""
        from page_number_checker import recognize_page_numbers
        image_files = _make_dummy_images(self.test_dir, ["a.png", "b.png"])
        candidates = [
            DigitOcrCandidate(value=None, confidence=0.0),
            DigitOcrCandidate(value=None, confidence=0.0),
        ]
        with patch("digit_ocr_recognizer.LocalDigitOcrRecognizer.recognize", side_effect=candidates):
            results = recognize_page_numbers(image_files, (0, 0, 10, 10))

        for info in results.values():
            self.assertIsNone(info['value'])
            self.assertFalse(info['mismatch'])


if __name__ == '__main__':
    unittest.main()
