#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
name_area_config.py — Step1で選択した氏名欄矩形の永続化。

id_area_config.py の manual_digit_rects_frac と同じ考え方で、矩形を画像全体
の幅・高さに対する割合(fraction)で保存する。画像サイズが多少違っても
崩れないようにするため、絶対座標ではなく割合で持つ。
"""

from typing import Optional, Tuple

from constants import atomic_json_save, load_json_safe

NAME_AREA_CONFIG_FILE = "name_area_config.json"

REQUIRED_CONFIG_KEYS = ["rect_frac"]


def load_name_area_config(config_path: str) -> Optional[Tuple[float, float, float, float]]:
    """name_area_config.json を読み込む。ファイル不在や破損時は None。"""
    data = load_json_safe(config_path, required_keys=REQUIRED_CONFIG_KEYS)
    return tuple(data["rect_frac"]) if data else None


def save_name_area_config(
    config_path: str, rect_frac: Tuple[float, float, float, float],
) -> None:
    """name_area_config.json をアトミックに保存する。

    Args:
        rect_frac: (left_frac, top_frac, right_frac, bottom_frac)
            画像全体の幅・高さに対する割合
    """
    atomic_json_save(config_path, {"rect_frac": list(rect_frac)})


def resolve_rect_for_image(
    rect_frac: Tuple[float, float, float, float], img_w: int, img_h: int,
) -> Tuple[int, int, int, int]:
    """割合表現の矩形を、指定サイズの画像に対する絶対座標(px)に変換する。"""
    left_frac, top_frac, right_frac, bottom_frac = rect_frac
    return (
        round(left_frac * img_w), round(top_frac * img_h),
        round(right_frac * img_w), round(bottom_frac * img_h),
    )
