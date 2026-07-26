#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_id_area_config.py — id_area_config.py（学籍番号欄の位置を割合設定から計算する
ロジック）のテスト。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from constants import (
    MARKER_X_FRAC_LEFT,
    MARKER_X_FRAC_RIGHT,
    MARKER_Y_FRAC_TOP,
    MARKER_Y_FRAC_BOTTOM,
)


class TestComputeMarkerRect(unittest.TestCase):
    """compute_marker_rect() のテスト"""

    def test_01_known_image_size(self):
        from id_area_config import compute_marker_rect
        img_w, img_h = 1000, 2000
        left, top, right, bottom = compute_marker_rect(img_w, img_h)
        self.assertAlmostEqual(left, MARKER_X_FRAC_LEFT * img_w)
        self.assertAlmostEqual(right, MARKER_X_FRAC_RIGHT * img_w)
        self.assertAlmostEqual(top, MARKER_Y_FRAC_TOP * img_h)
        self.assertAlmostEqual(bottom, MARKER_Y_FRAC_BOTTOM * img_h)


class TestComputeIdBoxRect(unittest.TestCase):
    """compute_id_box_rect() のテスト"""

    def test_01_zero_offset_full_size_matches_marker_rect(self):
        """left_frac=top_frac=0, width_frac=height_frac=1 でマーカー矩形と一致すること"""
        from id_area_config import compute_marker_rect, compute_id_box_rect
        img_w, img_h = 1000, 2000
        config = {"left_frac": 0.0, "top_frac": 0.0, "width_frac": 1.0, "height_frac": 1.0}
        marker_left, marker_top, marker_right, marker_bottom = compute_marker_rect(img_w, img_h)
        left, top, right, bottom = compute_id_box_rect(img_w, img_h, config)
        self.assertAlmostEqual(left, marker_left, delta=1)
        self.assertAlmostEqual(top, marker_top, delta=1)
        self.assertAlmostEqual(right, marker_right, delta=1)
        self.assertAlmostEqual(bottom, marker_bottom, delta=1)

    def test_02_offset_and_size_applied_relative_to_marker_rect(self):
        from id_area_config import compute_marker_rect, compute_id_box_rect
        img_w, img_h = 2466, 3483
        config = {"left_frac": 0.10, "top_frac": 0.20, "width_frac": 0.30, "height_frac": 0.05}
        marker_left, marker_top, marker_right, marker_bottom = compute_marker_rect(img_w, img_h)
        marker_w = marker_right - marker_left
        marker_h = marker_bottom - marker_top

        left, top, right, bottom = compute_id_box_rect(img_w, img_h, config)
        self.assertAlmostEqual(left, marker_left + 0.10 * marker_w, delta=1)
        self.assertAlmostEqual(top, marker_top + 0.20 * marker_h, delta=1)
        self.assertAlmostEqual(right - left, 0.30 * marker_w, delta=1)
        self.assertAlmostEqual(bottom - top, 0.05 * marker_h, delta=1)

    def test_03_returns_ints(self):
        from id_area_config import compute_id_box_rect
        config = {"left_frac": 0.1, "top_frac": 0.1, "width_frac": 0.3, "height_frac": 0.05}
        rect = compute_id_box_rect(1000, 1500, config)
        for v in rect:
            self.assertIsInstance(v, int)


class TestConfigPersistence(unittest.TestCase):
    """load_id_area_config() / save_id_area_config() のテスト"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_id_area_config_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_round_trip(self):
        from id_area_config import load_id_area_config, save_id_area_config
        config_path = str(Path(self.test_dir) / "student_id_area_config.json")
        config = {
            "left_frac": 0.1, "top_frac": 0.2, "width_frac": 0.3,
            "height_frac": 0.05, "digit_count": 8,
        }
        save_id_area_config(config_path, config)
        loaded = load_id_area_config(config_path)
        self.assertEqual(loaded, config)

    def test_02_missing_file_returns_none(self):
        from id_area_config import load_id_area_config
        config_path = str(Path(self.test_dir) / "does_not_exist.json")
        self.assertIsNone(load_id_area_config(config_path))

    def test_03_missing_required_key_returns_none(self):
        from id_area_config import load_id_area_config
        import json
        config_path = str(Path(self.test_dir) / "incomplete.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"left_frac": 0.1, "top_frac": 0.2}, f)
        self.assertIsNone(load_id_area_config(config_path))


if __name__ == '__main__':
    unittest.main()
