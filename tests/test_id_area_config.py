#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_id_area_config.py — id_area_config.py（学籍番号OCR設定の永続化・手動指定矩形の
座標変換）のテスト。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))


class TestComputeManualDigitBoxRect(unittest.TestCase):
    """compute_manual_digit_box_rect() のテスト"""

    def test_01_known_fraction(self):
        from id_area_config import compute_manual_digit_box_rect
        img_w, img_h = 1000, 2000
        rect_frac = [0.1, 0.2, 0.05, 0.03]
        left, top, right, bottom = compute_manual_digit_box_rect(img_w, img_h, rect_frac)
        self.assertAlmostEqual(left, 100, delta=1)
        self.assertAlmostEqual(top, 400, delta=1)
        self.assertAlmostEqual(right - left, 50, delta=1)
        self.assertAlmostEqual(bottom - top, 60, delta=1)

    def test_02_returns_ints(self):
        from id_area_config import compute_manual_digit_box_rect
        rect = compute_manual_digit_box_rect(1000, 1500, [0.1, 0.1, 0.05, 0.03])
        for v in rect:
            self.assertIsInstance(v, int)

    def test_03_different_fracs_per_digit(self):
        """桁ごとに個別のfracを与えても、均等分割ではなくそれぞれ独立に変換されること"""
        from id_area_config import compute_manual_digit_box_rect
        img_w, img_h = 2000, 1000
        rect_frac_1 = [0.10, 0.50, 0.05, 0.10]
        rect_frac_2 = [0.30, 0.51, 0.06, 0.09]  # 幅・位置とも1桁目と異なる実測値
        r1 = compute_manual_digit_box_rect(img_w, img_h, rect_frac_1)
        r2 = compute_manual_digit_box_rect(img_w, img_h, rect_frac_2)
        self.assertNotEqual(r1[2] - r1[0], r2[2] - r2[0])  # 幅が異なる


class TestConfigPersistence(unittest.TestCase):
    """load_id_area_config() / save_id_area_config() のテスト"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_id_area_config_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_round_trip_auto_mode(self):
        """自動検出モード（manual_digit_rects_fracなし）の往復保存"""
        from id_area_config import load_id_area_config, save_id_area_config
        config_path = str(Path(self.test_dir) / "student_id_area_config.json")
        config = {"digit_count": 8}
        save_id_area_config(config_path, config)
        loaded = load_id_area_config(config_path)
        self.assertEqual(loaded, config)

    def test_02_round_trip_manual_mode(self):
        """手動指定モード（manual_digit_rects_fracあり）の往復保存"""
        from id_area_config import load_id_area_config, save_id_area_config
        config_path = str(Path(self.test_dir) / "student_id_area_config.json")
        config = {
            "digit_count": 3,
            "manual_digit_rects_frac": [
                [0.10, 0.20, 0.05, 0.03],
                [0.16, 0.20, 0.05, 0.03],
                [0.22, 0.20, 0.05, 0.03],
            ],
        }
        save_id_area_config(config_path, config)
        loaded = load_id_area_config(config_path)
        self.assertEqual(loaded, config)

    def test_02b_round_trip_manual_mode_with_alpha_positions(self):
        """英字マス指定(alpha_positions)込みの往復保存"""
        from id_area_config import load_id_area_config, save_id_area_config
        config_path = str(Path(self.test_dir) / "student_id_area_config.json")
        config = {
            "digit_count": 3,
            "manual_digit_rects_frac": [
                [0.10, 0.20, 0.05, 0.03],
                [0.16, 0.20, 0.05, 0.03],
                [0.22, 0.20, 0.05, 0.03],
            ],
            "alpha_positions": [1],
        }
        save_id_area_config(config_path, config)
        loaded = load_id_area_config(config_path)
        self.assertEqual(loaded, config)

    def test_03_missing_file_returns_none(self):
        from id_area_config import load_id_area_config
        config_path = str(Path(self.test_dir) / "does_not_exist.json")
        self.assertIsNone(load_id_area_config(config_path))

    def test_04_missing_required_key_returns_none(self):
        from id_area_config import load_id_area_config
        import json
        config_path = str(Path(self.test_dir) / "incomplete.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"manual_digit_rects_frac": []}, f)
        self.assertIsNone(load_id_area_config(config_path))


if __name__ == '__main__':
    unittest.main()
