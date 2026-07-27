#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
digit_ocr_preprocessing.py — 手書き数字OCR用の前処理

答案から切り出した1マス分の画像を、MNIST学習済みモデルが期待する形式
(28x28グレースケール、数字を20x20に収めた上で重心を中心に置く)に変換する。

MNIST自体がこの手順(bounding boxで20x20に正規化し、重心を28x28の中心に合わせる)で
作られているため、同じ前処理をすることで学習済みモデルへの転移精度が上がる。

元コード: ~/Developer/grading-app の app/student_id/digit_preprocessing.py を移植。
"""

from typing import Optional

import cv2
import numpy as np

MARGIN_FRAC = 0.12  # 枠線(fboxの黒枠)を除外するため、周辺をこの割合だけ内側に詰める
MIN_INK_PIXELS = 5  # これより少ない場合は空欄とみなす


def preprocess_digit_image(image: np.ndarray) -> Optional[np.ndarray]:
    """成功時は (784,) float32([0,1]) を返す。空欄・検出失敗時はNone。"""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    h, w = gray.shape
    mx, my = int(w * MARGIN_FRAC), int(h * MARGIN_FRAC)
    inner = gray[my:h - my, mx:w - mx]
    if inner.size == 0:
        return None

    _, binary = cv2.threshold(inner, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    ys, xs = np.nonzero(binary)
    if len(xs) < MIN_INK_PIXELS:
        return None

    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    digit = binary[y0:y1 + 1, x0:x1 + 1]

    dh, dw = digit.shape
    scale = 20.0 / max(dh, dw)
    new_w = max(1, round(dw * scale))
    new_h = max(1, round(dh * scale))
    resized = cv2.resize(digit.astype(np.uint8), (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((28, 28), dtype=np.float32)
    off_y = (28 - new_h) // 2
    off_x = (28 - new_w) // 2
    canvas[off_y:off_y + new_h, off_x:off_x + new_w] = resized

    ys2, xs2 = np.nonzero(canvas)
    if len(xs2) > 0:
        cy, cx = ys2.mean(), xs2.mean()
        shift_y = int(round(14 - cy))
        shift_x = int(round(14 - cx))
        canvas = np.roll(canvas, shift_y, axis=0)
        canvas = np.roll(canvas, shift_x, axis=1)

    return (canvas.reshape(-1) / 255.0).astype(np.float32)
