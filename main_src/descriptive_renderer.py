#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descriptive_renderer.py — 記述問題描画モジュール

descriptive_scorer.py から描画関連コードを分離・抽出したモジュール。
記述問題の得点描画 (draw_descriptive_on_image) および
マーク+記述合計得点描画 (draw_combined_total) を提供する。
"""

import logging
import unicodedata
from typing import Optional, Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from constants import (
    get_rendering_settings, DESCRIPTIVE_OVERLAY_OPACITY, get_cjk_font_path,
    number_to_circled,
)

logger = logging.getLogger(__name__)


# ============================================================
# 定数
# ============================================================

# 描画設定
SCORE_FONT_SIZE = 14
SCORE_COLOR_RGB = (255, 0, 0)   # 赤色 (RGB, PIL用)
TOTAL_COLOR_RGB = (0, 0, 255)   # 青色 (RGB, PIL用)

# 合計点表示ボックスのデフォルトサイズ
DEFAULT_TOTAL_BOX_WIDTH = 200
DEFAULT_TOTAL_BOX_HEIGHT = 60
COMMENT_MAX_LINES = 3


def _display_width(text: str) -> int:
    """日本語を2桁、半角文字を1桁として表示幅を概算する。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WFA" else 1 for ch in text)


def wrap_student_comment(text: str, max_width: int, max_lines: int = COMMENT_MAX_LINES) -> List[str]:
    """生徒向けコメントを表示幅で折り返し、超過時は末尾を省略する。"""
    if max_width <= 0 or max_lines <= 0:
        return []
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    lines: List[str] = []
    current = ""
    consumed = 0
    for ch in normalized:
        candidate = current + ch
        if current and _display_width(candidate) > max_width:
            lines.append(current)
            current = ch
            if len(lines) == max_lines:
                consumed -= len(current)
                break
        else:
            current = candidate
        consumed += 1
    if len(lines) < max_lines and current:
        lines.append(current)
    if consumed < len(normalized) and lines:
        while lines[-1] and _display_width(lines[-1] + "…") > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


# ============================================================
# フォントキャッシュ
# ============================================================

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def _get_font(size: int):
    """日本語フォントを取得（キャッシュ付き）。失敗時はデフォルトフォント。"""
    font = _font_cache.get(size)
    if font is None:
        try:
            font_path, font_index = get_cjk_font_path()
            font = ImageFont.truetype(font_path, size, index=font_index)
        except Exception:
            font = ImageFont.load_default()
        _font_cache[size] = font
    return font


# ============================================================
# 画像描画: 記述得点
# ============================================================

def draw_descriptive_on_image(
    image: np.ndarray,
    config: dict,
    scores_for_image: dict,
    output_scale: float = 1.0,
    rendering_settings: dict = None,
    comments_for_image: dict = None,
) -> np.ndarray:
    """
    1枚の補正済み画像に記述問題の得点を描画する。

    各記述領域の中央80%エリアに、できるだけ大きく「○ 3 ②」形式で表示。
    マーク式と同じ表記（改行なし）。

    描画ルール:
    - 満点 → ○（透過赤色、太字）
    - 部分点 → △（透過赤色、太字）
    - 0点 → ×（透過赤色、太字）
    - 得点と観点 → 黒文字、透過
    - 透過率は rendering_settings['descriptive_opacity'] で制御
    - 各表示項目は rendering_settings で個別にON/OFF可能

    Args:
        image: OpenCV画像 (BGR)
        config: descriptive_config
        scores_for_image: {question_id: score, ...}
        output_scale: 出力スケール (1.0 = 595x842)
        rendering_settings: 描画設定辞書（Noneならデフォルト）
        comments_for_image: {question_id: 生徒向けコメント}。教員用メモは渡さない。

    Returns:
        描画済み画像 (OpenCV BGR)
    """
    from constants import get_rendering_settings, DESCRIPTIVE_OVERLAY_OPACITY
    rs = get_rendering_settings(rendering_settings)
    
    s = output_scale
    result = image.copy()

    # RGBA に変換して透過描画を可能にする
    pil_img = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGBA))
    # 透過描画用オーバーレイ
    overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 透過率を設定から取得
    opacity = rs.get('descriptive_opacity', DESCRIPTIVE_OVERLAY_OPACITY)
    alpha_value = int(255 * opacity)
    RED_ALPHA = (255, 0, 0, alpha_value)
    BLACK_ALPHA = (0, 0, 0, alpha_value)
    comments_for_image = comments_for_image or {}

    for q in config["questions"]:
        q_id = q["id"]
        region = q["region"]  # [left, top, right, bottom]
        aspect = q.get("aspect", 1)
        max_score = q["max_score"]
        score = scores_for_image.get(q_id)

        # 領域の中央80%エリアを計算
        left = int(region[0] * s)
        top = int(region[1] * s)
        right = int(region[2] * s)
        bottom = int(region[3] * s)

        region_w = right - left
        region_h = bottom - top

        # 80%の有効エリア（中央部に余白10%ずつ確保）
        usable_w = int(region_w * 0.8)
        usable_h = int(region_h * 0.8)
        usable_x = left + int(region_w * 0.1)
        usable_y = top + int(region_h * 0.1)

        # コメントは得点が未入力でも返却答案へ表示できる。
        comment = comments_for_image.get(q_id, "")
        if rs.get('descriptive_show_comment', True) and str(comment).strip():
            comment_font_size = max(10, min(int(region_h * 0.15), int(18 * s)))
            comment_font = _get_font(comment_font_size)
            approx_chars = max(4, int(usable_w / max(comment_font_size, 1)))
            lines = wrap_student_comment(str(comment), approx_chars * 2)
            if lines:
                line_h = comment_font_size + max(2, int(2 * s))
                block_h = line_h * len(lines) + 4
                box_top = max(top, bottom - block_h - 2)
                draw.rounded_rectangle(
                    (usable_x, box_top, usable_x + usable_w, bottom - 2),
                    radius=max(2, int(3 * s)), fill=(255, 255, 255, min(235, alpha_value + 80)),
                    outline=(220, 0, 0, alpha_value), width=max(1, int(s)),
                )
                for line_index, line in enumerate(lines):
                    draw.text(
                        (usable_x + 3, box_top + 2 + line_index * line_h), line,
                        font=comment_font, fill=(180, 0, 0, alpha_value),
                    )

        if score is None:
            continue

        # ○×△ の判定
        if score >= max_score:
            symbol = "○"
        elif score > 0:
            symbol = "△"
        else:
            symbol = "×"

        # 表示項目の決定
        d_show_mark = rs.get('descriptive_show_mark', True)
        d_show_score = rs.get('descriptive_show_score', True)
        d_show_aspect = False
        
        score_text = str(score)
        aspect_text = number_to_circled(aspect)
        
        # テキスト構成: 表示項目に応じて動的に構築
        parts = []
        if d_show_mark:
            parts.append(symbol)
        if d_show_score:
            parts.append(score_text)
        if d_show_aspect:
            parts.append(aspect_text)
        
        if not parts:
            continue  # 全て非表示なら何も描画しない
        
        full_text = " ".join(parts)

        # フォントサイズの自動調整（有効エリアに収まる最大サイズを探索）
        max_font = max(int(60 * s), 20)
        min_font = max(int(8 * s), 8)
        best_font_size = min_font

        for try_size in range(max_font, min_font - 1, -1):
            try_font = _get_font(try_size)
            bbox = draw.textbbox((0, 0), full_text, font=try_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            if tw <= usable_w and th <= usable_h:
                best_font_size = try_size
                break

        font_main = _get_font(best_font_size)

        # テキスト全体のサイズを取得（中央配置の計算用）
        full_bbox = draw.textbbox((0, 0), full_text, font=font_main)
        total_w = full_bbox[2] - full_bbox[0]
        total_h = full_bbox[3] - full_bbox[1]

        # 有効エリアの中央に配置
        text_x = usable_x + (usable_w - total_w) // 2
        text_y = usable_y + (usable_h - total_h) // 2

        # 個別パーツを順番に描画（○△×は赤、得点と観点は黒）
        # 表示フラグに基づいて、表示されるパーツのみ描画
        current_x = text_x

        # スペース幅の計算
        space_bbox = draw.textbbox((0, 0), " ", font=font_main)
        space_w = space_bbox[2] - space_bbox[0]

        if d_show_mark:
            # パーツ1: ○△× マーク（赤色、太字効果=2重描画）
            for dx, dy in [(0, 0), (1, 0), (0, 1), (1, 1)]:
                draw.text((current_x + dx, text_y + dy), symbol, font=font_main, fill=RED_ALPHA)
            sym_bbox = draw.textbbox((0, 0), symbol, font=font_main)
            sym_w = sym_bbox[2] - sym_bbox[0]
            current_x += sym_w + space_w

        if d_show_score:
            # パーツ2: 得点（黒色）
            draw.text((current_x, text_y), score_text, font=font_main, fill=BLACK_ALPHA)
            score_text_bbox = draw.textbbox((0, 0), score_text, font=font_main)
            score_w = score_text_bbox[2] - score_text_bbox[0]
            current_x += score_w + space_w

        if d_show_aspect:
            # パーツ3: 観点（黒色）
            draw.text((current_x, text_y), aspect_text, font=font_main, fill=BLACK_ALPHA)


    # オーバーレイを合成
    pil_img = Image.alpha_composite(pil_img, overlay)
    # BGR に戻す
    result_rgb = pil_img.convert("RGB")
    return cv2.cvtColor(np.array(result_rgb), cv2.COLOR_RGB2BGR)


def draw_combined_total(
    image: np.ndarray,
    mark_scoring_result: dict,
    config: dict,
    descriptive_scores_for_image: dict,
    coordinates: list = None,
    output_scale: float = 1.0,
) -> np.ndarray:
    """
    マーク得点 + 記述得点の合計を画像に描画する。

    total_display_region が指定されている場合、ボックス内にテキストを
    収まるよう自動的にフォントサイズを調整して描画する。

    Args:
        image: OpenCV画像
        mark_scoring_result: saitensamurai.score_answers() の戻り値
        config: descriptive_config
        descriptive_scores_for_image: {question_id: score, ...}
        coordinates: マーク座標リスト (total_display_region 未指定時のフォールバック用)
        output_scale: 出力スケール (1.0 = 595x842)

    Returns:
        描画済み画像
    """
    s = output_scale
    result = image.copy()

    # --- 得点計算 ---
    mark_total = mark_scoring_result['total_score']
    mark_max = sum(mark_scoring_result['aspect_max_scores'].values())

    desc_total = 0
    desc_max = 0
    for q in config["questions"]:
        desc_max += q["max_score"]
        sc = descriptive_scores_for_image.get(q["id"])
        if sc is not None:
            desc_total += sc

    combined_total = mark_total + desc_total
    combined_max = mark_max + desc_max

    # --- 観点別スコア計算 ---
    aspect_scores = dict(mark_scoring_result['aspect_scores'])
    aspect_max_scores = dict(mark_scoring_result['aspect_max_scores'])

    for q in config["questions"]:
        asp = q.get("aspect", 1)
        if asp not in aspect_max_scores:
            aspect_max_scores[asp] = 0
        if asp not in aspect_scores:
            aspect_scores[asp] = 0
        aspect_max_scores[asp] += q["max_score"]
        sc = descriptive_scores_for_image.get(q["id"])
        if sc is not None:
            aspect_scores[asp] += sc

    sorted_aspects = sorted(aspect_max_scores.keys())
    parts = []
    for asp in sorted_aspects:
        circled = number_to_circled(asp)
        parts.append(f"観点{circled}:{aspect_scores.get(asp, 0)}/{aspect_max_scores[asp]}")
    line2_text = " ".join(parts) if parts else ""

    # --- 描画位置の決定 ---
    total_region = config.get("total_display_region")

    if total_region:
        # ボックスモード: 指定領域内にテキストを収める（スケール適用）
        box_x1, box_y1, box_x2, box_y2 = (
            int(total_region[0] * s), int(total_region[1] * s),
            int(total_region[2] * s), int(total_region[3] * s)
        )
        box_w = box_x2 - box_x1
        box_h = box_y2 - box_y1
    else:
        # フォールバック: 固定位置（スケール適用）
        if coordinates:
            max_q_no = max(c['question_no'] for c in coordinates)
            last_coords = [c for c in coordinates if c['question_no'] == max_q_no]
            if last_coords:
                box_x1 = int((last_coords[0]['x'] - 40) * s)
                box_y1 = int((last_coords[0]['y'] + last_coords[0]['height'] + 14) * s)
            else:
                box_x1, box_y1 = int(50 * s), int(780 * s)
        else:
            box_x1, box_y1 = int(50 * s), int(780 * s)
        box_w = int(DEFAULT_TOTAL_BOX_WIDTH * s)
        box_h = int(DEFAULT_TOTAL_BOX_HEIGHT * s)
        box_x2 = box_x1 + box_w
        box_y2 = box_y1 + box_h

    # --- PIL描画 ---
    pil_img = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    # テキスト
    line1 = f"得点：{combined_total} / {combined_max}"

    # フォントサイズの自動調整（ボックスサイズ基準）
    # ボックス高さの50%をフォント上限とし、実画像サイズに適応する
    box_based_font = max(int(box_h * 0.5), SCORE_FONT_SIZE)
    scale_based_font = max(int(SCORE_FONT_SIZE * s), SCORE_FONT_SIZE)
    max_font = max(box_based_font, scale_based_font)
    min_font = max(int(box_h * 0.1), int(6 * s), 6)
    font_size = max_font
    line2_font_size = max(min_font, max_font - 2)
    for attempt_size in range(max_font, min_font - 1, -1):
        font_test = _get_font(attempt_size)
        bbox1 = draw.textbbox((0, 0), line1, font=font_test)
        w1 = bbox1[2] - bbox1[0]
        h1 = bbox1[3] - bbox1[1]
        total_h = h1 + int(4 * s)
        max_w = w1

        if line2_text:
            font_test2 = _get_font(max(min_font, attempt_size - int(2 * s)))
            bbox2 = draw.textbbox((0, 0), line2_text, font=font_test2)
            w2 = bbox2[2] - bbox2[0]
            h2 = bbox2[3] - bbox2[1]
            total_h += h2
            max_w = max(max_w, w2)

        if max_w <= box_w - int(6 * s) and total_h <= box_h - int(4 * s):
            font_size = attempt_size
            line2_font_size = max(min_font, attempt_size - int(2 * s))
            break
    else:
        font_size = min_font
        line2_font_size = max(min_font - 2, 6)

    font = _get_font(font_size)
    font_small = _get_font(line2_font_size)

    # 1行目: 合計得点
    draw.text((box_x1 + int(3 * s), box_y1 + int(2 * s)), line1, font=font, fill=TOTAL_COLOR_RGB)

    # 2行目: 観点別
    if line2_text:
        line1_bbox = draw.textbbox((0, 0), line1, font=font)
        line1_h = line1_bbox[3] - line1_bbox[1]

        # 2行目がボックスに収まるか確認、収まらなければ省略表示
        bbox2_test = draw.textbbox((0, 0), line2_text, font=font_small)
        w2_test = bbox2_test[2] - bbox2_test[0]
        if w2_test > box_w - int(6 * s):
            # 省略: 観点記号だけ
            short_parts = []
            for asp in sorted_aspects:
                circled = number_to_circled(asp)
                short_parts.append(f"{circled}:{aspect_scores.get(asp, 0)}")
            line2_text = " ".join(short_parts)

        draw.text((box_x1 + int(3 * s), box_y1 + line1_h + int(4 * s)), line2_text, font=font_small, fill=TOTAL_COLOR_RGB)

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
