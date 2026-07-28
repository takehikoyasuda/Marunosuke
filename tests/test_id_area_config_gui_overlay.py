#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""学籍番号マスの種別オーバーレイ表示を検証する。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from PIL import Image

from conftest import get_shared_tk_root


class TestRedrawFinalOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="test_id_overlay_")
        cls.image_path = str(Path(cls.test_dir) / "sample.jpg")
        Image.new("RGB", (600, 800), color="white").save(cls.image_path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        from id_area_config_gui import IdAreaConfigDialog
        root = get_shared_tk_root()
        self.dialog = IdAreaConfigDialog(root, self.image_path, default_digit_count=3)
        self.dialog._final_rects = [
            (50, 100, 90, 140), (100, 100, 140, 140), (150, 100, 190, 140),
        ]
        self.dialog._alpha_positions = {1}

    def tearDown(self):
        self.dialog.window.destroy()

    def _overlay_items(self, item_type):
        return [
            item_id for item_id in self.dialog.canvas.find_withtag("id_box_preview")
            if self.dialog.canvas.type(item_id) == item_type
        ]

    def test_no_text_labels_are_drawn_over_answer_boxes(self):
        self.dialog._redraw_final_overlay()
        self.assertEqual(self._overlay_items("text"), [])

    def test_digit_and_alpha_use_distinct_high_contrast_colors(self):
        from id_area_config_gui import ALPHA_BOX_COLOR, DIGIT_BOX_COLOR

        self.dialog._redraw_final_overlay()
        rectangles = self._overlay_items("rectangle")
        self.assertEqual(len(rectangles), 3)
        outlines = [self.dialog.canvas.itemcget(item, "outline") for item in rectangles]
        self.assertEqual(outlines, [DIGIT_BOX_COLOR, ALPHA_BOX_COLOR, DIGIT_BOX_COLOR])

    def test_alpha_is_dashed_and_digits_are_solid(self):
        self.dialog._redraw_final_overlay()
        rectangles = self._overlay_items("rectangle")
        self.assertEqual(self.dialog.canvas.itemcget(rectangles[0], "dash"), "")
        self.assertNotEqual(self.dialog.canvas.itemcget(rectangles[1], "dash"), "")
        self.assertEqual(self.dialog.canvas.itemcget(rectangles[2], "dash"), "")

    def test_all_final_boxes_use_thick_lines(self):
        self.dialog._redraw_final_overlay()
        for item in self._overlay_items("rectangle"):
            self.assertEqual(float(self.dialog.canvas.itemcget(item, "width")), 4.0)


if __name__ == "__main__":
    unittest.main()
