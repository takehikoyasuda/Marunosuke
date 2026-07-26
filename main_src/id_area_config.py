#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
id_area_config.py — 学籍番号欄の位置を「検出」ではなく「設定値による計算」で求めるための
ロジック(GUI非依存)。

学籍番号欄専用のマーカーを答案画像ごとに検出する方式は、実データ検証の結果
ユーザーの矩形選択に非現実的な精度が必要になることが分かった(詳細は
student_id_area_requirements.md 参照)。そこで、用紙全体の四隅マーカー
(omr_engine.detect_corner_markers / apply_perspective_transform、既存の
実績ある仕組み)を基準に、学籍番号欄の位置を割合(%)で一度だけ設定し、
以降は毎回その割合から数学的に位置を計算する方式に変更した。

割合は絶対mmではなく「四隅マーカーが作る四角形」の幅・高さに対する割合で
持つ。これにより用紙サイズ(A4/B4等)が変わっても同じ設定を使い回せる。
基準点はマーカーの中心(重心)。
"""

from typing import Dict, Optional, Tuple

from constants import (
    MARKER_X_FRAC_LEFT,
    MARKER_X_FRAC_RIGHT,
    MARKER_Y_FRAC_TOP,
    MARKER_Y_FRAC_BOTTOM,
    atomic_json_save,
    load_json_safe,
)

ID_AREA_CONFIG_FILE = "student_id_area_config.json"

REQUIRED_CONFIG_KEYS = ["left_frac", "top_frac", "width_frac", "height_frac", "digit_count"]


def compute_marker_rect(img_w: int, img_h: int) -> Tuple[float, float, float, float]:
    """用紙全体の四隅マーカー(の中心)が作る四角形を、与えられた画像サイズでのピクセル座標で返す。

    Returns:
        (left, top, right, bottom)
    """
    left = MARKER_X_FRAC_LEFT * img_w
    right = MARKER_X_FRAC_RIGHT * img_w
    top = MARKER_Y_FRAC_TOP * img_h
    bottom = MARKER_Y_FRAC_BOTTOM * img_h
    return left, top, right, bottom


def compute_id_box_rect(img_w: int, img_h: int, config: Dict) -> Tuple[int, int, int, int]:
    """設定値(割合)から、学籍番号欄の絶対ピクセル矩形を計算する。

    Args:
        img_w, img_h: 対象画像のサイズ
        config: {'left_frac','top_frac','width_frac','height_frac', ...}
            いずれも「四隅マーカーが作る四角形」の幅・高さに対する割合(0.0〜1.0)

    Returns:
        (left, top, right, bottom)
    """
    marker_left, marker_top, marker_right, marker_bottom = compute_marker_rect(img_w, img_h)
    marker_w = marker_right - marker_left
    marker_h = marker_bottom - marker_top

    left = marker_left + config["left_frac"] * marker_w
    top = marker_top + config["top_frac"] * marker_h
    width = config["width_frac"] * marker_w
    height = config["height_frac"] * marker_h

    return round(left), round(top), round(left + width), round(top + height)


def load_id_area_config(config_path: str) -> Optional[Dict]:
    """student_id_area_config.json を読み込む。ファイル不在や破損時は None。"""
    return load_json_safe(config_path, required_keys=REQUIRED_CONFIG_KEYS)


def save_id_area_config(config_path: str, config: Dict) -> None:
    """student_id_area_config.json をアトミックに保存する。"""
    atomic_json_save(config_path, config)
