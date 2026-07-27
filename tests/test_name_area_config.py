#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_name_area_config.py — name_area_config.py（氏名欄矩形の永続化・座標変換）のテスト。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))


class TestNameAreaConfigPersistence(unittest.TestCase):
    """load_name_area_config() / save_name_area_config() のテスト"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_name_area_config_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_round_trip(self):
        from name_area_config import load_name_area_config, save_name_area_config
        config_path = str(Path(self.test_dir) / "name_area_config.json")
        rect_frac = (0.1, 0.05, 0.4, 0.15)
        save_name_area_config(config_path, rect_frac)
        loaded = load_name_area_config(config_path)
        self.assertEqual(loaded, rect_frac)

    def test_02_missing_file_returns_none(self):
        from name_area_config import load_name_area_config
        config_path = str(Path(self.test_dir) / "does_not_exist.json")
        self.assertIsNone(load_name_area_config(config_path))

    def test_03_missing_required_key_returns_none(self):
        from name_area_config import load_name_area_config
        import json
        config_path = str(Path(self.test_dir) / "incomplete.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"not_rect_frac": []}, f)
        self.assertIsNone(load_name_area_config(config_path))


class TestResolveRectForImage(unittest.TestCase):
    """resolve_rect_for_image() のテスト"""

    def test_01_known_fraction(self):
        from name_area_config import resolve_rect_for_image
        rect_frac = (0.1, 0.2, 0.5, 0.6)
        left, top, right, bottom = resolve_rect_for_image(rect_frac, 1000, 2000)
        self.assertEqual((left, top, right, bottom), (100, 400, 500, 1200))

    def test_02_returns_ints(self):
        from name_area_config import resolve_rect_for_image
        rect = resolve_rect_for_image((0.111, 0.222, 0.333, 0.444), 999, 777)
        for v in rect:
            self.assertIsInstance(v, int)

    def test_03_different_image_size_scales_proportionally(self):
        """画像サイズが変わっても割合を保ったまま座標が変換されること"""
        from name_area_config import resolve_rect_for_image
        rect_frac = (0.25, 0.25, 0.75, 0.75)
        small = resolve_rect_for_image(rect_frac, 400, 400)
        large = resolve_rect_for_image(rect_frac, 800, 800)
        self.assertEqual(small, (100, 100, 300, 300))
        self.assertEqual(large, (200, 200, 600, 600))


if __name__ == '__main__':
    unittest.main()
