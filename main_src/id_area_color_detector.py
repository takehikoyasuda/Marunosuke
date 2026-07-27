#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
id_area_color_detector.py — 学籍番号欄の各桁マスを、赤枠の色検出で位置特定する。

四隅コーナーマーカー(omr_engine.detect_corner_markers)の割合計算とは完全に独立した
仕組み。学籍番号のマス目は答案用紙側で桁ごとに独立した赤(RGB(255,0,0)推奨)の枠線
として印刷される前提とし、答案画像全体(射影補正済み)からHSV色空間で赤色領域を
検出する。黒罫線・黒/青ペンの手書き文字とは色空間で明確に分離できるため、過去に
撤回した「学籍番号欄専用マーカー」方式の失敗要因(罫線・筆跡との誤認)を解消する
狙い。詳細は student_id_area_requirements.md 参照。

検出はあくまで「候補位置」であり、期待した桁数と一致しない場合は例外を送出する。
呼び出し元(student_id_ocr.py)はこれを自動検出失敗として扱い、手動指定へフォール
バックする。
"""

import logging
from typing import List, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 赤色のHSV閾値(OpenCVのHueは0-179)。赤は色相環の両端にまたがるため2レンジで取る。
_HUE_LOW_MAX = 10
_HUE_HIGH_MIN = 170
_SAT_MIN = 80
_VAL_MIN = 60

# 検出候補の面積フィルタ(画像全体に対する比率)。ノイズ・巨大な誤検出領域を除外する。
MIN_AREA_FRAC = 0.00005
MAX_AREA_FRAC = 0.01

# 検出したマス同士の幅・高さのばらつき許容度(平均に対する変動係数)。
# 大きく外れる場合は赤枠以外の誤検出が混ざっていると判断する。
MAX_SIZE_CV_FRAC = 0.5


def _red_mask(bgr_image: np.ndarray) -> np.ndarray:
    """BGR画像から赤色ピクセルのマスク(0/255の2値画像)を返す。"""
    hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
    lower1 = np.array([0, _SAT_MIN, _VAL_MIN])
    upper1 = np.array([_HUE_LOW_MAX, 255, 255])
    lower2 = np.array([_HUE_HIGH_MIN, _SAT_MIN, _VAL_MIN])
    upper2 = np.array([180, 255, 255])
    mask1 = cv2.inRange(hsv, lower1, upper1)
    mask2 = cv2.inRange(hsv, lower2, upper2)
    return cv2.bitwise_or(mask1, mask2)


def detect_red_digit_boxes(
    image: np.ndarray, expected_digit_count: int,
) -> List[Tuple[int, int, int, int]]:
    """画像全体から赤枠のマスを expected_digit_count 個検出し、左から右の順で返す。

    四隅マーカーの位置・割合には一切依存しない(画像全体を検索範囲とする)。

    Raises:
        ValueError: 検出数が一致しない、またはマスの大きさのばらつきが
            大きすぎる場合(=自動検出失敗)。

    Returns:
        List[Tuple[int,int,int,int]]: 各マスの (left, top, right, bottom)。
    """
    h, w = image.shape[:2]
    img_area = float(h * w)
    mask = _red_mask(image)

    num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    candidates: List[Tuple[int, int, int, int]] = []
    for i in range(1, num_labels):  # 0は背景
        area = stats[i, cv2.CC_STAT_AREA]
        area_frac = area / img_area
        if area_frac < MIN_AREA_FRAC or area_frac > MAX_AREA_FRAC:
            continue
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        candidates.append((x, y, x + bw, y + bh))

    if len(candidates) != expected_digit_count:
        raise ValueError(
            f"赤枠のマスが{expected_digit_count}個期待されるところ"
            f"{len(candidates)}個検出されました"
        )

    candidates.sort(key=lambda r: r[0])

    widths = np.array([r[2] - r[0] for r in candidates], dtype=np.float64)
    heights = np.array([r[3] - r[1] for r in candidates], dtype=np.float64)
    if widths.mean() > 0 and widths.std() / widths.mean() > MAX_SIZE_CV_FRAC:
        raise ValueError("検出した赤枠マスの幅のばらつきが大きすぎます（誤検出の疑い）")
    if heights.mean() > 0 and heights.std() / heights.mean() > MAX_SIZE_CV_FRAC:
        raise ValueError("検出した赤枠マスの高さのばらつきが大きすぎます（誤検出の疑い）")

    return candidates


def mask_red_border(
    bgr_crop: np.ndarray, fill_color: Tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    """クロップ済み1マス分のBGR画像から赤枠ピクセルを検出し、fill_colorで塗りつぶす。

    グレースケール化・二値化(digit_ocr_preprocessing.preprocess_digit_image)に
    渡す前に必ず呼ぶこと。赤枠を印刷していない手動指定モードの画像に対しては
    実質no-opになる。
    """
    mask = _red_mask(bgr_crop)
    result = bgr_crop.copy()
    result[mask > 0] = fill_color
    return result
