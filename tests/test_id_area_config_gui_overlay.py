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

        # 数字マスの青とは大きく色相の異なる暖色系であること
        # （どちらも「濃い彩度の色」で似て見える、という以前の問題を防ぐ）。
        self.assertNotEqual(ALPHA_BOX_COLOR, DIGIT_BOX_COLOR)

        self.dialog._redraw_final_overlay()
        rectangles = self._overlay_items("rectangle")
        self.assertEqual(len(rectangles), 3)
        outlines = [self.dialog.canvas.itemcget(item, "outline") for item in rectangles]
        # 描画順を「数字マスを先に、英字マスを後(前面)に」変更したため、
        # canvasへの作成順は idx0(digit), idx2(digit), idx1(alpha) になる。
        self.assertEqual(outlines, [DIGIT_BOX_COLOR, DIGIT_BOX_COLOR, ALPHA_BOX_COLOR])

    def test_alpha_is_dashed_and_digits_are_solid(self):
        self.dialog._redraw_final_overlay()
        rectangles = self._overlay_items("rectangle")
        # 作成順: idx0(digit), idx2(digit), idx1(alpha)
        self.assertEqual(self.dialog.canvas.itemcget(rectangles[0], "dash"), "")
        self.assertEqual(self.dialog.canvas.itemcget(rectangles[1], "dash"), "")
        self.assertNotEqual(self.dialog.canvas.itemcget(rectangles[2], "dash"), "")

    def test_all_final_boxes_use_thick_lines(self):
        self.dialog._redraw_final_overlay()
        for item in self._overlay_items("rectangle"):
            self.assertEqual(float(self.dialog.canvas.itemcget(item, "width")), 4.0)

    def test_alpha_box_extends_vertically_without_changing_final_rects(self):
        """英字マスは上下の枠線だけ表示上わずかに外側へ張り出す。

        実座標(_final_rects、検出・保存に使う)は変更されないことも確認する。
        """
        from id_area_config_gui import ALPHA_BOX_VERTICAL_EXPAND

        original_rects = list(self.dialog._final_rects)
        self.dialog._redraw_final_overlay()

        rectangles = self._overlay_items("rectangle")
        # 作成順: idx0(digit), idx2(digit), idx1(alpha)
        digit_coords = [self.dialog.canvas.coords(item) for item in rectangles[:2]]
        alpha_coords = self.dialog.canvas.coords(rectangles[2])

        ratio = self.dialog._display_ratio
        digit_x0, digit_y0, digit_x1, digit_y1 = original_rects[0]
        alpha_x0, alpha_y0, alpha_x1, alpha_y1 = original_rects[1]

        # 数字マスは表示座標に単純にratioを掛けた位置のまま
        self.assertAlmostEqual(digit_coords[0][1], digit_y0 * ratio, places=3)
        self.assertAlmostEqual(digit_coords[0][3], digit_y1 * ratio, places=3)

        # 英字マスは上下だけ ALPHA_BOX_VERTICAL_EXPAND 分外側に広がっている
        self.assertAlmostEqual(alpha_coords[1], alpha_y0 * ratio - ALPHA_BOX_VERTICAL_EXPAND, places=3)
        self.assertAlmostEqual(alpha_coords[3], alpha_y1 * ratio + ALPHA_BOX_VERTICAL_EXPAND, places=3)
        # x方向は変化しない
        self.assertAlmostEqual(alpha_coords[0], alpha_x0 * ratio, places=3)
        self.assertAlmostEqual(alpha_coords[2], alpha_x1 * ratio, places=3)

        # 実座標(_final_rects)自体は変更されていない
        self.assertEqual(self.dialog._final_rects, original_rects)


if __name__ == "__main__":
    unittest.main()
