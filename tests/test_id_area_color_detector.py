#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_id_area_color_detector.py — id_area_color_detector.py（赤枠色検出・赤枠マスキング）のテスト。
"""

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))


def _draw_red_boxes(shape=(300, 800, 3), count=4, box_w=80, box_h=100, gap=20, top=100, thickness=2):
    """白背景に、count個の赤い矩形枠を横一列に等間隔で描画した画像を返す。

    Returns:
        (image, expected_rects): expected_rectsは (left, top, right, bottom) のリスト（左から右の順）
    """
    img = np.full(shape, 255, dtype=np.uint8)
    expected = []
    for i in range(count):
        x0 = 50 + i * (box_w + gap)
        x1 = x0 + box_w
        y1 = top + box_h
        cv2.rectangle(img, (x0, top), (x1, y1), (0, 0, 255), thickness)  # BGR: 赤
        expected.append((x0, top, x1, y1))
    return img, expected


class TestDetectRedDigitBoxes(unittest.TestCase):
    """detect_red_digit_boxes() のテスト"""

    def test_01_detects_expected_count_left_to_right(self):
        from id_area_color_detector import detect_red_digit_boxes
        img, expected = _draw_red_boxes(count=4)
        rects = detect_red_digit_boxes(img, 4)
        self.assertEqual(len(rects), 4)
        # 左から右の順にソートされていること、位置がおおむね一致すること
        for (left, top, right, bottom), (ex0, ey0, ex1, ey1) in zip(rects, expected):
            self.assertAlmostEqual(left, ex0, delta=3)
            self.assertAlmostEqual(top, ey0, delta=3)
            self.assertAlmostEqual(right, ex1, delta=3)
            self.assertAlmostEqual(bottom, ey1, delta=3)

    def test_02_count_mismatch_raises_value_error(self):
        from id_area_color_detector import detect_red_digit_boxes
        img, _ = _draw_red_boxes(count=3)
        with self.assertRaises(ValueError):
            detect_red_digit_boxes(img, 4)  # 3個しかないのに4個期待

    def test_03_ignores_black_ruled_lines_and_non_red_ink(self):
        """黒罫線・グレー/青系の筆跡風の塗りつぶしは赤として誤検出しないこと"""
        from id_area_color_detector import detect_red_digit_boxes
        img, expected = _draw_red_boxes(count=2)
        # 黒い罫線を追加（画像全体を横切る線）
        cv2.line(img, (0, 250), (800, 250), (0, 0, 0), 2)
        # 手書き風の塗りつぶし(グレー・青系)を追加
        cv2.rectangle(img, (500, 100), (550, 150), (80, 80, 80), -1)  # グレー
        cv2.rectangle(img, (600, 100), (650, 150), (200, 100, 0), -1)  # 青系(BGR)

        rects = detect_red_digit_boxes(img, 2)
        self.assertEqual(len(rects), 2)
        for (left, top, right, bottom), (ex0, ey0, ex1, ey1) in zip(rects, expected):
            self.assertAlmostEqual(left, ex0, delta=3)
            self.assertAlmostEqual(right, ex1, delta=3)

    def test_04_size_variance_too_large_raises_value_error(self):
        """検出数が一致しても、マスの大きさのばらつきが大きすぎる場合はエラーにすること"""
        from id_area_color_detector import detect_red_digit_boxes
        img = np.full((300, 800, 3), 255, dtype=np.uint8)
        cv2.rectangle(img, (50, 100), (130, 200), (0, 0, 255), 2)   # 80x100
        cv2.rectangle(img, (200, 100), (210, 110), (0, 0, 255), 2)  # 10x10（極端に小さい誤検出）
        with self.assertRaises(ValueError):
            detect_red_digit_boxes(img, 2)


class TestMaskRedBorder(unittest.TestCase):
    """mask_red_border() のテスト"""

    def test_01_red_pixels_replaced_with_white(self):
        from id_area_color_detector import mask_red_border
        img = np.full((40, 40, 3), 255, dtype=np.uint8)
        cv2.rectangle(img, (2, 2), (37, 37), (0, 0, 255), 2)  # 赤枠
        result = mask_red_border(img)
        # 元は赤だった枠のピクセルが白に置換されていること
        self.assertTrue(np.array_equal(result[2, 20], [255, 255, 255]))

    def test_02_non_red_pixels_unchanged(self):
        from id_area_color_detector import mask_red_border
        img = np.full((40, 40, 3), 255, dtype=np.uint8)
        cv2.rectangle(img, (2, 2), (37, 37), (0, 0, 255), 2)  # 赤枠
        img[15:25, 15:25] = (0, 0, 0)  # 中央に黒インク(手書き想定)
        result = mask_red_border(img)
        self.assertTrue(np.array_equal(result[20, 20], [0, 0, 0]))  # 黒インクは維持される

    def test_03_no_red_present_is_noop(self):
        from id_area_color_detector import mask_red_border
        img = np.full((40, 40, 3), 255, dtype=np.uint8)
        img[10:30, 10:30] = (0, 0, 0)
        result = mask_red_border(img)
        self.assertTrue(np.array_equal(result, img))


if __name__ == '__main__':
    unittest.main()
