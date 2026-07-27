#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
image_alignment.py — 答案画像の読み込み・コーナーマーカー検出・射影補正。

マーク採点(OMR認識)専用だった omr_engine.py から、記述式採点・学籍番号OCR・
氏名欄トリミングなど採点モードを問わず共通で使う画像アライメント処理だけを
切り出したモジュール。マーク認識・採点ロジックへの依存は一切ない。

主な機能:
- imread_unicode: 日本語パス対応の画像読み込み
- detect_corner_markers: 四隅マーカー検出
- apply_perspective_transform: 射影変換による画像補正
- compute_output_scale: 元画像解像度に応じた出力スケール計算
"""

import logging

import cv2
import numpy as np

from constants import (
    MARK2_WIDTH,
    MARK2_HEIGHT,
    MARKER_X_FRAC_LEFT,
    MARKER_X_FRAC_RIGHT,
    MARKER_Y_FRAC_TOP,
    MARKER_Y_FRAC_BOTTOM,
    OUTPUT_SCALE_MAX,
)

logger = logging.getLogger(__name__)

# コーナーマーカー検出の「マーカーらしさ」判定閾値。
# サーチ領域内の最大連結成分を無条件にマーカー扱いしていたため、マーカーが
# 実際には印刷されていないページ(異なる様式の混入・白紙・スキャンノイズ等)でも
# ノイズやゴミを誤ってマーカーとして採用し、正常なページとして処理されてしまう
# 問題があった。実物のMark2マーカーはサーチ領域(30%×8%)に対して数%程度を占める
# ほぼ正方形の黒塗り四角であるため、その範囲から大きく外れる成分は除外する。
MARKER_MIN_AREA_FRAC = 0.005   # サーチ領域面積に対する最小割合(小さすぎるノイズを除外)
MARKER_MAX_AREA_FRAC = 0.25    # サーチ領域面積に対する最大割合(領域全体が暗い異常ケースを除外)
MARKER_MIN_ASPECT = 0.5        # 幅/高さの下限(細長い罫線等を除外)
MARKER_MAX_ASPECT = 2.0        # 幅/高さの上限


def imread_unicode(filepath):
    """日本語パスに対応した画像読み込み（np.fromfile + cv2.imdecode）"""
    try:
        img_array = np.fromfile(str(filepath), dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        logger.error("画像読み込みエラー (%s): %s", filepath, e)
        return None


def detect_corner_markers(image, debug=False):
    """
    画像の四隅近くにある黒い正方形マーカーを検出

    Returns:
        markers: [(x1, y1), (x2, y2), (x3, y3), (x4, y4)] 左上、右上、右下、左下の順
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Mark2のアルゴリズム: 四隅から1%マージン、30%×8%のサーチエリア
    margin_x = int(w * 0.01)
    margin_y = int(h * 0.01)
    search_w = int(w * 0.3)
    search_h = int(w * 0.08)

    # 4つのサーチ領域を定義
    search_regions = [
        {'name': '左上', 'x': margin_x, 'y': margin_y, 'w': search_w, 'h': search_h},
        {'name': '右上', 'x': w - margin_x - search_w, 'y': margin_y, 'w': search_w, 'h': search_h},
        {'name': '右下', 'x': w - margin_x - search_w, 'y': h - margin_y - search_h, 'w': search_w, 'h': search_h},
        {'name': '左下', 'x': margin_x, 'y': h - margin_y - search_h, 'w': search_w, 'h': search_h},
    ]

    markers = []
    debug_img = image.copy() if debug else None

    for region in search_regions:
        x, y, rw, rh = region['x'], region['y'], region['w'], region['h']

        # サーチ領域を切り出し
        roi = gray[y:y+rh, x:x+rw]

        # 二値化（Otsu's法）
        _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 連結成分解析
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

        # 「マーカーらしさ」(サーチ領域に対する面積比・アスペクト比)を満たす
        # 成分の中で最大面積のものを採用する（背景を除く）。単純に最大連結成分を
        # 無条件採用すると、マーカーが実際には印刷されていないページでも
        # ノイズ・罫線・文字等を誤ってマーカーとして採用してしまうため。
        region_area = float(rw * rh)
        best_area = 0
        best_label = -1

        for i in range(1, num_labels):  # 0はバックグラウンド
            area = stats[i, cv2.CC_STAT_AREA]
            area_frac = area / region_area if region_area > 0 else 0
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]
            aspect = bw / bh if bh > 0 else 0
            if not (MARKER_MIN_AREA_FRAC <= area_frac <= MARKER_MAX_AREA_FRAC):
                continue
            if not (MARKER_MIN_ASPECT <= aspect <= MARKER_MAX_ASPECT):
                continue
            if area > best_area:
                best_area = area
                best_label = i

        if best_label >= 0:
            # マーカーの中心座標（画像全体座標系）
            center_x = int(centroids[best_label][0]) + x
            center_y = int(centroids[best_label][1]) + y
            markers.append((center_x, center_y))

            if debug:
                # サーチ領域を描画
                cv2.rectangle(debug_img, (x, y), (x + rw, y + rh), (255, 0, 0), 2)
                # マーカー中心を描画
                cv2.circle(debug_img, (center_x, center_y), 10, (0, 0, 255), -1)

    if len(markers) != 4:
        raise ValueError(f"4個のマーカーが必要ですが、{len(markers)}個しか検出されませんでした")

    if debug:
        return markers, debug_img
    else:
        return markers


def apply_perspective_transform(image, markers, output_scale=1.0):
    """
    射影変換で画像を補正（Mark2アルゴリズムに準拠）

    Args:
        image: 入力画像
        markers: コーナーマーカー座標
        output_scale: 出力スケール倍率（1.0 = 595x842, 大きいほど高解像度）

    Returns:
        corrected_image: 補正後の画像（595*scale x 842*scale）
        transform_matrix: 変換行列
    """
    # Mark2の基準サイズ
    w = int(595 * output_scale)
    h = int(842 * output_scale)

    # Mark2のマーカー位置（基準座標系、スケール適用後）
    xp1 = w * MARKER_X_FRAC_LEFT    # 左上 X
    yp1 = h * MARKER_Y_FRAC_TOP     # 左上 Y
    xp2 = w * MARKER_X_FRAC_RIGHT   # 右上 X
    yp2 = h * MARKER_Y_FRAC_TOP     # 右上 Y
    xp3 = w * MARKER_X_FRAC_RIGHT   # 右下 X
    yp3 = h * MARKER_Y_FRAC_BOTTOM  # 右下 Y
    xp4 = w * MARKER_X_FRAC_LEFT    # 左下 X
    yp4 = h * MARKER_Y_FRAC_BOTTOM  # 左下 Y

    src_points = np.float32(markers)

    # 画像のマーカー位置を、Mark2の基準座標系のマーカー位置にマッピング
    dst_points = np.float32([
        [xp1, yp1],  # 左上
        [xp2, yp2],  # 右上
        [xp3, yp3],  # 右下
        [xp4, yp4]   # 左下
    ])

    # 変換行列を計算
    transform_matrix = cv2.getPerspectiveTransform(src_points, dst_points)

    # 射影変換を適用（595*scale x 842*scale のサイズで出力）
    corrected_image = cv2.warpPerspective(image, transform_matrix, (w, h))

    return corrected_image, transform_matrix


def compute_output_scale(image):
    """元画像の解像度からoutput_scaleを計算する

    元画像の解像度を極力活かすスケールを返す。OUTPUT_SCALE_MAXで上限を制限。

    Args:
        image: OpenCV画像 (BGR)
    Returns:
        float: output_scale値
    """
    img_h, img_w = image.shape[:2]
    scale_w = img_w / MARK2_WIDTH
    scale_h = img_h / MARK2_HEIGHT
    scale = min(scale_w, scale_h, OUTPUT_SCALE_MAX)
    return max(scale, 1.0)
