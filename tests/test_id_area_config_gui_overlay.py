#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_id_area_config_gui_overlay.py — IdAreaConfigDialog._redraw_final_overlay()
の2つのバグ修正の検証。

バグA: 認識済み桁位置ラベルが枠の内側左上に描画され、記入された数字を隠して
        いた → 枠の上に描画されるように修正。
バグB: 英字マスのラベルが「N:英」(漢字)になっていた → 数字マスの「N:数」と
        表記を揃えて「N:A」に修正。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from PIL import Image

from conftest import get_shared_tk_root


class TestRedrawFinalOverlay(unittest.TestCase):
    """_redraw_final_overlay() を直接呼び、キャンバス上の描画結果を検証する"""

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
        # 手動で3マス分の確定済み矩形を用意する(自動検出結果には依存しない)
        self.dialog._final_rects = [
            (50, 100, 90, 140), (100, 100, 140, 140), (150, 100, 190, 140),
        ]
        self.dialog._alpha_positions = {1}  # 2桁目(0-indexed=1)だけ英字マス

    def tearDown(self):
        self.dialog.window.destroy()

    def _label_items(self):
        """id_box_preview タグのcreate_textアイテムだけを (text, anchor, y) で返す"""
        items = []
        for item_id in self.dialog.canvas.find_withtag("id_box_preview"):
            if self.dialog.canvas.type(item_id) != "text":
                continue
            text = self.dialog.canvas.itemcget(item_id, "text")
            anchor = self.dialog.canvas.itemcget(item_id, "anchor")
            y = self.dialog.canvas.coords(item_id)[1]
            items.append((text, anchor, y))
        return items

    def test_bug_b_alpha_label_uses_ascii_a(self):
        """英字マスのラベルが「2:英」ではなく「2:A」になっていること"""
        self.dialog._redraw_final_overlay()
        labels = {text for text, _anchor, _y in self._label_items()}
        self.assertIn("2:A", labels)
        self.assertNotIn("2:英", labels)

    def test_bug_b_digit_label_unchanged(self):
        """数字マスのラベルは従来通り「N:数」のままであること"""
        self.dialog._redraw_final_overlay()
        labels = {text for text, _anchor, _y in self._label_items()}
        self.assertIn("1:数", labels)
        self.assertIn("3:数", labels)

    def test_bug_a_label_drawn_above_box_not_inside(self):
        """枠が上端から十分離れている場合、ラベルは枠の上(anchor='s')に描かれ、
        枠の内側(dy0+2)には描画されないこと"""
        self.dialog._redraw_final_overlay()
        dy0 = 100 * self.dialog._display_ratio
        for text, anchor, y in self._label_items():
            self.assertEqual(anchor, "s")
            self.assertLess(y, dy0, f"label {text!r} should be above the box top, not inside it")

    def test_bug_a_falls_back_inside_when_near_canvas_top(self):
        """枠がキャンバス上端に近すぎる場合は、従来通り枠内側にフォールバックすること"""
        self.dialog._final_rects = [(50, 1, 90, 20)]
        self.dialog._alpha_positions = set()
        self.dialog._redraw_final_overlay()
        labels = self._label_items()
        self.assertEqual(len(labels), 1)
        text, anchor, y = labels[0]
        self.assertEqual(anchor, "n")
        dy0 = 1 * self.dialog._display_ratio
        self.assertGreater(y, dy0)


if __name__ == '__main__':
    unittest.main()
