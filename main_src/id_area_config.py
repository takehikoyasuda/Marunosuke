#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
id_area_config.py — 学籍番号OCRの設定(桁数・手動指定フォールバック)の永続化。

学籍番号欄の位置は、四隅コーナーマーカーの割合計算には一切依存せず、答案画像
全体からの赤枠色検出(id_area_color_detector.detect_red_digit_boxes)で求める。
このモジュールが保持するのは以下のみ:

- digit_count: 学籍番号の桁数(自動検出の期待値としても使う)
- manual_digit_rects_frac: 自動検出に失敗した場合のみ存在する、教員が1マスずつ
  ドラッグ指定した矩形(画像全体の幅・高さに対する割合、桁ごとに個別の値)
- alpha_positions: 任意。英字マスとして扱う0-indexedの桁位置のリスト
  (例: [2] なら3桁目が英字)。学籍番号中の英字は位置が固定でも文字自体(A〜Z)は
  事前に分からないため、教員が id_area_config_gui.IdAreaConfigDialog で位置だけ
  指定し、その位置は digit_ocr_recognizer.LocalDigitOcrRecognizer の英字専用モデル
  (resources/letter_classifier.joblib)で認識する。省略時は空リスト(全桁数字)。

四隅マーカーが作る四角形を基準にした割合計算(旧方式)は撤回した経緯を
student_id_area_requirements.md に記録している。
"""

from typing import Dict, List, Optional, Tuple

from constants import atomic_json_save, load_json_safe

ID_AREA_CONFIG_FILE = "student_id_area_config.json"

REQUIRED_CONFIG_KEYS = ["digit_count"]


def compute_manual_digit_box_rect(
    img_w: int, img_h: int, rect_frac: List[float],
) -> Tuple[int, int, int, int]:
    """1桁分の手動指定矩形(画像全体に対する割合)を、画像サイズに合わせた絶対座標に変換する。

    Args:
        img_w, img_h: 対象画像のサイズ
        rect_frac: [left_frac, top_frac, width_frac, height_frac]
            （画像全体の幅・高さに対する割合。四隅マーカーとは無関係）

    Returns:
        (left, top, right, bottom)
    """
    left_frac, top_frac, width_frac, height_frac = rect_frac
    left = left_frac * img_w
    top = top_frac * img_h
    width = width_frac * img_w
    height = height_frac * img_h
    return round(left), round(top), round(left + width), round(top + height)


def load_id_area_config(config_path: str) -> Optional[Dict]:
    """student_id_area_config.json を読み込む。ファイル不在や破損時は None。"""
    return load_json_safe(config_path, required_keys=REQUIRED_CONFIG_KEYS)


def save_id_area_config(config_path: str, config: Dict) -> None:
    """student_id_area_config.json をアトミックに保存する。"""
    atomic_json_save(config_path, config)
