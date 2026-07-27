#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_student_id_ocr.py — 学籍番号OCR関連モジュールのテスト

テスト内容:
    Part 1: digit_ocr_preprocessing / digit_ocr_recognizer 単体テスト
    Part 2: roster_loader 単体テスト
    Part 3: student_id_ocr（桁分割・StudentIdOcrTrimmer）単体テスト
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from PIL import Image


class _FakeClassifier:
    """sklearn互換の最小限のダミー分類器(joblib.dumpでシリアライズしてテストに使う)。

    常に固定のproba配列を返す。classes_の並び順がpredict_probaの列インデックスと
    一致しない(=argmaxのインデックスをそのままラベルとして使うと壊れる)ケースを
    再現するために使う。
    """

    def __init__(self, classes, proba_row):
        self.classes_ = np.array(classes)
        self._proba_row = np.array(proba_row, dtype=np.float64)

    def predict_proba(self, X):
        return np.tile(self._proba_row, (X.shape[0], 1))


def _inked_image():
    img = np.full((40, 40, 3), 255, dtype=np.uint8)
    img[10:30, 10:30] = 0
    return img


# ============================================================
# Part 1: digit_ocr_preprocessing / digit_ocr_recognizer
# ============================================================

class TestDigitOcrPreprocessing(unittest.TestCase):
    """preprocess_digit_image() のテスト"""

    def test_01_blank_image_returns_none(self):
        """空欄(白一色)の画像はNoneを返すこと"""
        from digit_ocr_preprocessing import preprocess_digit_image
        blank = np.full((40, 40, 3), 255, dtype=np.uint8)
        self.assertIsNone(preprocess_digit_image(blank))

    def test_02_inked_image_returns_normalized_array(self):
        """インクのある画像はshape(784,)・dtype float32・値域[0,1]で返ること"""
        from digit_ocr_preprocessing import preprocess_digit_image
        img = np.full((40, 40, 3), 255, dtype=np.uint8)
        img[10:30, 10:30] = 0  # 中央に黒い塊 = インク
        result = preprocess_digit_image(img)
        self.assertIsNotNone(result)
        self.assertEqual(result.shape, (784,))
        self.assertEqual(result.dtype, np.float32)
        self.assertGreaterEqual(result.min(), 0.0)
        self.assertLessEqual(result.max(), 1.0)

    def test_03_grayscale_input_accepted(self):
        """グレースケール(2次元)画像でも動作すること"""
        from digit_ocr_preprocessing import preprocess_digit_image
        img = np.full((40, 40), 255, dtype=np.uint8)
        img[10:30, 10:30] = 0
        result = preprocess_digit_image(img)
        self.assertIsNotNone(result)
        self.assertEqual(result.shape, (784,))


class TestLocalDigitOcrRecognizer(unittest.TestCase):
    """LocalDigitOcrRecognizer のテスト"""

    def test_01_import_and_instantiate(self):
        from digit_ocr_recognizer import LocalDigitOcrRecognizer, DigitOcrCandidate
        recognizer = LocalDigitOcrRecognizer()
        self.assertIsNotNone(recognizer)

    def test_02_empty_list_returns_safe_fallback(self):
        """空リストを渡しても例外にならず、value=Noneで返ること"""
        from digit_ocr_recognizer import LocalDigitOcrRecognizer
        recognizer = LocalDigitOcrRecognizer()
        candidate = recognizer.recognize([])
        self.assertIsNone(candidate.value)
        self.assertEqual(candidate.confidence, 0.0)
        self.assertEqual(candidate.per_digit, [])

    def test_03_model_file_exists(self):
        """モデルファイル(resources/digit_classifier.joblib)が配置されていること"""
        from constants import resource_path
        model_path = resource_path("resources/digit_classifier.joblib")
        self.assertTrue(Path(model_path).exists(), f"モデルファイルが見つかりません: {model_path}")

    def test_04_recognize_returns_per_digit_matching_input_length(self):
        """per_digit の長さが入力画像数と一致すること（精度自体はアサートしない）"""
        from digit_ocr_recognizer import LocalDigitOcrRecognizer
        recognizer = LocalDigitOcrRecognizer()
        digit_images = [_inked_image() for _ in range(4)]
        candidate = recognizer.recognize(digit_images)
        self.assertEqual(len(candidate.per_digit), 4)
        for digit_str, conf in candidate.per_digit:
            self.assertIsInstance(digit_str, str)
            self.assertGreaterEqual(conf, 0.0)
            self.assertLessEqual(conf, 1.0)

    def test_05_letter_model_file_exists(self):
        """英字分類モデル(resources/letter_classifier.joblib)が配置されていること"""
        from constants import resource_path
        model_path = resource_path("resources/letter_classifier.joblib")
        self.assertTrue(Path(model_path).exists(), f"モデルファイルが見つかりません: {model_path}")

    def test_06_label_uses_classes_not_argmax_index(self):
        """予測ラベルは classes_[argmax] から取得すること(argmaxのインデックスを
        そのまま数字化する実装だと、classes_の並び順がインデックスと一致しない
        場合に誤ったラベルを返す回帰バグがある)。"""
        import joblib
        from digit_ocr_recognizer import LocalDigitOcrRecognizer

        with tempfile.TemporaryDirectory() as tmpdir:
            # classes_ = ['0','5','9']、インデックス1が最大確率 → 正しくは'5'
            # (インデックスをそのまま文字列化する実装だと'1'を返してしまう)
            model_path = os.path.join(tmpdir, "fake_digit.joblib")
            joblib.dump(_FakeClassifier(["0", "5", "9"], [0.1, 0.8, 0.1]), model_path)

            recognizer = LocalDigitOcrRecognizer(model_path=model_path, letter_model_path=model_path)
            candidate = recognizer.recognize([_inked_image()])
            self.assertEqual(candidate.per_digit[0][0], "5")

    def test_07_alpha_mask_routes_to_letter_model(self):
        """alpha_maskがTrueの位置だけ英字分類器が使われること"""
        import joblib
        from digit_ocr_recognizer import LocalDigitOcrRecognizer

        with tempfile.TemporaryDirectory() as tmpdir:
            digit_model_path = os.path.join(tmpdir, "fake_digit.joblib")
            letter_model_path = os.path.join(tmpdir, "fake_letter.joblib")
            joblib.dump(_FakeClassifier(["3", "7"], [0.2, 0.9]), digit_model_path)
            joblib.dump(_FakeClassifier(["A", "B"], [0.9, 0.1]), letter_model_path)

            recognizer = LocalDigitOcrRecognizer(model_path=digit_model_path, letter_model_path=letter_model_path)
            digit_images = [_inked_image(), _inked_image()]
            candidate = recognizer.recognize(digit_images, alpha_mask=[False, True])

            self.assertEqual(candidate.per_digit[0][0], "7")  # 数字マス → 数字分類器
            self.assertEqual(candidate.per_digit[1][0], "A")  # 英字マス → 英字分類器
            self.assertEqual(candidate.value, "7A")

    def test_08_alpha_mask_none_matches_all_digit_behavior(self):
        """alpha_mask省略時は既存動作(全桁数字分類器)と同じになること"""
        import joblib
        from digit_ocr_recognizer import LocalDigitOcrRecognizer

        with tempfile.TemporaryDirectory() as tmpdir:
            digit_model_path = os.path.join(tmpdir, "fake_digit.joblib")
            letter_model_path = os.path.join(tmpdir, "fake_letter.joblib")
            joblib.dump(_FakeClassifier(["3", "7"], [0.2, 0.9]), digit_model_path)
            joblib.dump(_FakeClassifier(["A", "B"], [0.9, 0.1]), letter_model_path)

            recognizer = LocalDigitOcrRecognizer(model_path=digit_model_path, letter_model_path=letter_model_path)
            digit_images = [_inked_image(), _inked_image()]
            candidate = recognizer.recognize(digit_images)  # alpha_mask省略

            self.assertEqual(candidate.value, "77")

    def test_09_alpha_mask_length_mismatch_raises(self):
        from digit_ocr_recognizer import LocalDigitOcrRecognizer
        recognizer = LocalDigitOcrRecognizer()
        with self.assertRaises(ValueError):
            recognizer.recognize([_inked_image(), _inked_image()], alpha_mask=[True])


# ============================================================
# Part 2: roster_loader
# ============================================================

class TestRosterLoader(unittest.TestCase):
    """load_roster() のテスト"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_roster_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_valid_roster(self):
        from roster_loader import load_roster
        df = pd.DataFrame({
            '学籍番号': ['20230001', '20230002'],
            '氏名': ['山田太郎', '佐藤花子'],
        })
        path = os.path.join(self.test_dir, "roster.xlsx")
        df.to_excel(path, index=False)

        roster = load_roster(path)
        self.assertEqual(roster['20230001'], '山田太郎')
        self.assertEqual(roster['20230002'], '佐藤花子')

    def test_02_missing_column_raises(self):
        from roster_loader import load_roster
        df = pd.DataFrame({'学籍番号': ['20230001'], '名前': ['山田太郎']})
        path = os.path.join(self.test_dir, "roster_bad.xlsx")
        df.to_excel(path, index=False)

        with self.assertRaises(ValueError):
            load_roster(path)


# ============================================================
# Part 3: student_id_ocr
# ============================================================

class TestRecognizeStudentIdsIntegration(unittest.TestCase):
    """recognize_student_ids() の統合テスト（赤枠自動検出／手動指定の両経路）"""

    SAMPLE_IMAGE = Path(__file__).parent.parent / "sample_basefile" / "sample_marksheet.jpg"

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_recognize_sid_")
        self.image_folder = os.path.join(self.test_dir, "boxed")
        os.makedirs(self.image_folder, exist_ok=True)
        shutil.copy(str(self.SAMPLE_IMAGE), os.path.join(self.image_folder, "page_001.jpg"))
        self.output_folder = os.path.join(self.test_dir, "out")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_no_red_frames_yields_safe_fallback_entry(self):
        """赤枠が印刷されていないサンプル画像では自動検出が失敗し、安全な
        フォールバック値（confidence=0.0等）が返ること。"""
        from student_id_ocr import recognize_student_ids
        config = {"digit_count": 6}
        results = recognize_student_ids(self.image_folder, config, self.output_folder)
        self.assertEqual(len(results), 1)
        entry = results["page_001.jpg"]
        self.assertIsNone(entry["thumbnail_path"])
        self.assertIsNone(entry["text"])
        self.assertEqual(entry["confidence"], 0.0)
        self.assertEqual(entry["per_digit"], [])

    def test_02_invalid_image_yields_safe_fallback_entry(self):
        """壊れた画像でも例外を投げず、安全なフォールバック値を返すこと"""
        from student_id_ocr import recognize_student_ids
        bad_folder = os.path.join(self.test_dir, "bad")
        os.makedirs(bad_folder, exist_ok=True)
        with open(os.path.join(bad_folder, "broken.jpg"), "wb") as f:
            f.write(b"not an image")
        config = {"digit_count": 6}
        results = recognize_student_ids(bad_folder, config, self.output_folder)
        entry = results["broken.jpg"]
        self.assertIsNone(entry["thumbnail_path"])
        self.assertIsNone(entry["text"])
        self.assertEqual(entry["confidence"], 0.0)
        self.assertEqual(entry["per_digit"], [])

    def test_03_manual_digit_rects_used_when_present(self):
        """manual_digit_rects_fracがある場合、赤枠自動検出を経由せずそれを使って
        画像ごとに候補が返ること（桁数分のper_digitが返る）。"""
        from student_id_ocr import recognize_student_ids
        config = {
            "digit_count": 3,
            "manual_digit_rects_frac": [
                [0.10, 0.10, 0.05, 0.03],
                [0.16, 0.10, 0.05, 0.03],
                [0.22, 0.10, 0.05, 0.03],
            ],
        }
        results = recognize_student_ids(self.image_folder, config, self.output_folder)
        entry = results["page_001.jpg"]
        self.assertIsNotNone(entry["thumbnail_path"])
        self.assertTrue(Path(entry["thumbnail_path"]).exists())
        self.assertEqual(len(entry["per_digit"]), 3)
        self.assertGreaterEqual(entry["confidence"], 0.0)

    def test_05_alpha_positions_routes_to_letter_model(self):
        """alpha_positionsで指定した桁が英字分類器で処理され、例外なく完走すること"""
        from student_id_ocr import recognize_student_ids
        config = {
            "digit_count": 3,
            "manual_digit_rects_frac": [
                [0.10, 0.10, 0.05, 0.03],
                [0.16, 0.10, 0.05, 0.03],
                [0.22, 0.10, 0.05, 0.03],
            ],
            "alpha_positions": [1],
        }
        results = recognize_student_ids(self.image_folder, config, self.output_folder)
        entry = results["page_001.jpg"]
        self.assertEqual(len(entry["per_digit"]), 3)

    def test_04_red_frames_detected_and_used(self):
        """赤枠を合成した画像では自動検出が成功し、画像ごとに候補が返ること。"""
        import cv2
        import numpy as np
        from student_id_ocr import recognize_student_ids

        img = np.full((300, 800, 3), 255, dtype=np.uint8)
        digit_count = 4
        box_w, box_h, gap, top = 80, 100, 20, 100
        for i in range(digit_count):
            x0 = 50 + i * (box_w + gap)
            cv2.rectangle(img, (x0, top), (x0 + box_w, top + box_h), (0, 0, 255), 2)
        red_folder = os.path.join(self.test_dir, "red_boxed")
        os.makedirs(red_folder, exist_ok=True)
        # JPEG圧縮による赤色のにじみ(色ズレ)を避けるためPNG(可逆圧縮)で保存する
        cv2.imwrite(os.path.join(red_folder, "page_001.png"), img)

        config = {"digit_count": digit_count}
        results = recognize_student_ids(red_folder, config, self.output_folder)
        entry = results["page_001.png"]
        self.assertIsNotNone(entry["thumbnail_path"])
        self.assertEqual(len(entry["per_digit"]), digit_count)


class TestStudentIdOcrTrimmerCleanup(unittest.TestCase):
    """StudentIdOcrTrimmer.cleanup() のテスト"""

    def test_01_cleanup_removes_temp_dir(self):
        from student_id_ocr import StudentIdOcrTrimmer
        trimmer = StudentIdOcrTrimmer()
        temp_dir = tempfile.mkdtemp(prefix="test_id_cleanup_")
        trimmer._temp_dir = temp_dir
        self.assertTrue(Path(temp_dir).exists())

        trimmer.cleanup()
        self.assertFalse(Path(temp_dir).exists())
        self.assertIsNone(trimmer._temp_dir)

    def test_02_cleanup_when_no_temp(self):
        from student_id_ocr import StudentIdOcrTrimmer
        trimmer = StudentIdOcrTrimmer()
        trimmer.cleanup()  # 例外が発生しないこと
        self.assertIsNone(trimmer._temp_dir)

