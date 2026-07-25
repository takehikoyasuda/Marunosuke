"""
image_renderer.py - 画像描画・採点結果レンダリングモジュール

採点結果を画像上に描画し、スコア付き答案画像を生成する。
合計得点の描画、○×マーク描画、正答番号表示などを担当。
"""

from pathlib import Path
import json
import logging
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

from constants import (
    RESULTS_FOLDER,
    SCORED_FOLDER,
    RESULTS_DATA_FOLDER,
    MARKER_CACHE_FILE,
    MARK_FORMAT_STANDARD,
    MARK_FORMAT_MULTI_DIGIT,
    get_cjk_font_path,
)
from scoring_engine import (
    number_to_circled,
    choice_to_position_index,
    load_template,
    load_mark2_results,
    score_answers,
)
from omr_engine import (
    parse_excel_coordinates,
    detect_corner_markers,
    compute_output_scale,
    apply_perspective_transform,
)

# ---------------------------------------------------------------------------
# フォントキャッシュ — サイズごとに1回だけディスクI/Oを行いキャッシュする
# ---------------------------------------------------------------------------
_FONT_PATH, _FONT_INDEX = get_cjk_font_path()
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def _get_cached_font(size: int) -> ImageFont.FreeTypeFont:
    """キャッシュ付きフォント取得。同一サイズの再読込を完全に排除する。"""
    font = _font_cache.get(size)
    if font is None:
        try:
            font = ImageFont.truetype(_FONT_PATH, size, index=_FONT_INDEX)
        except Exception:
            font = ImageFont.load_default()  # type: ignore[assignment]
        _font_cache[size] = font
    return font  # type: ignore[return-value]


def _load_marker_cache(results_folder: Path) -> dict:
    """Step 1 で保存されたマーカー座標キャッシュを読み込む。

    キャッシュが存在しない場合は空dictを返す（フォールバック: 再検出）。
    """
    cache_path = results_folder / RESULTS_DATA_FOLDER / MARKER_CACHE_FILE
    if cache_path.exists():
        try:
            with open(str(cache_path), 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def draw_text_on_image(image, text, x, y, font_size=20, color=(0, 0, 0), center_in_box=None):
    """
    画像にテキストを描画（日本語対応）
    
    Args:
        image: OpenCV画像（BGR）
        text: 描画するテキスト
        x, y: テキスト位置
        font_size: フォントサイズ
        color: テキスト色（BGR）
        center_in_box: (width, height) - ボックス内で中央揃えする場合のボックスサイズ
    
    Returns:
        描画後のOpenCV画像
    """
    # OpenCV画像をPIL画像に変換
    pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    font = _get_cached_font(font_size)
    
    # 中央揃え: 水平＋垂直（フォントのベアリングオフセットを補正）
    if center_in_box:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        box_width, box_height = center_in_box
        x = x + (box_width - text_width) // 2 - bbox[0]
        y = y + (box_height - text_height) // 2 - bbox[1]
    
    # テキスト描画（RGBに変換）
    rgb_color = (color[2], color[1], color[0])
    draw.text((x, y), text, font=font, fill=rgb_color)
    
    # PIL画像をOpenCV画像に戻す
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def draw_mixed_text_on_image(image, text1, font_size1, text2, font_size2, x, y, color=(0, 0, 0), center_in_box=None):
    """
    異なるフォントサイズの2つのテキストを連続して描画（日本語対応）
    
    Args:
        image: OpenCV画像（BGR）
        text1: 最初のテキスト（得点など）
        font_size1: 最初のテキストのフォントサイズ
        text2: 2番目のテキスト（観点など）
        font_size2: 2番目のテキストのフォントサイズ
        x, y: テキスト開始位置
        color: テキスト色（BGR）
        center_in_box: (width, height) - ボックス内で中央揃えする場合のボックスサイズ
    
    Returns:
        描画後のOpenCV画像
    """
    # OpenCV画像をPIL画像に変換
    pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    font1 = _get_cached_font(font_size1)
    font2 = _get_cached_font(font_size2)
    
    # テキストサイズを計算
    bbox1 = draw.textbbox((0, 0), text1, font=font1)
    text1_width = bbox1[2] - bbox1[0]
    text1_height = bbox1[3] - bbox1[1]
    
    bbox2 = draw.textbbox((0, 0), text2, font=font2)
    text2_height = bbox2[3] - bbox2[1]
    
    # 全体の高さ（大きい方に合わせる）
    max_height = max(text1_height, text2_height)
    
    # 上下中央揃えの場合
    if center_in_box:
        box_width, box_height = center_in_box
        y_offset = (box_height - max_height) // 2
        y = y + y_offset
    
    # RGBに変換
    rgb_color = (color[2], color[1], color[0])
    
    # 最初のテキストを描画
    draw.text((x, y), text1, font=font1, fill=rgb_color)
    
    # 2番目のテキストを直後に描画（2ピクセルの間隔）
    x2 = x + text1_width + 2  # 2ピクセルの間隔
    y2 = y + (text1_height - text2_height) // 2  # 小さい文字を少し下げる（同じサイズなら0）
    draw.text((x2, y2), text2, font=font2, fill=rgb_color)
    
    # PIL画像をOpenCV画像に戻す
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def _draw_scoring_on_pil(draw, coordinates, scoring_result, skip_questions=0,
                         output_scale=1.0, rendering_settings=None,
                         mark_format=MARK_FORMAT_STANDARD):
    """PIL DrawオブジェクトにO/X・得点・正答を直接描画（in-place）。

    cv2↔PIL変換を行わない内部関数。draw_scoring_results / draw_all_results から呼ばれる。

    複数桁モード(mark_format=MARK_FORMAT_MULTI_DIGIT)では、resultsの'span'に従い
    ○×・得点はグループ先頭行に1つだけ、誤答時の正答赤表示はグループ各行の
    正しいマーク位置に1文字ずつ描画する。
    """
    from constants import get_rendering_settings
    rs = get_rendering_settings(rendering_settings)

    s = output_scale
    results = scoring_result['results']
    base_font_size = int(14 * s)
    offset = float(rs['mark_result_offset'])
    base_font = _get_cached_font(base_font_size)

    bg_white = bool(rs.get('mark_result_bg_white', False))
    # 白塗りON時の描画キュー。○→得点→観点の順に即時描画すると、
    # 後から描く文字の白背景が直前の文字を上書きして潰してしまうため、
    # いったん全文字を溜めて「全白背景→全文字」の2パスで描画する
    pending_texts = []  # (text, draw_x, draw_y, font, rgb_color)

    def _draw_text_pil(text, x, y, font_size, color_bgr, center_in_box=None):
        """PIL上で直接テキスト描画 (draw_text_on_image 相当)"""
        try:
            font = _get_cached_font(font_size) if font_size != base_font_size else base_font
        except Exception:
            font = base_font
        rgb_color = (color_bgr[2], color_bgr[1], color_bgr[0])
        draw_x = x
        draw_y = y
        if center_in_box:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            box_width, box_height = center_in_box
            # 水平・垂直中央揃え（フォントのベアリングオフセットを補正）
            draw_x = x + (box_width - text_width) // 2 - bbox[0]
            draw_y = y + (box_height - text_height) // 2 - bbox[1]
        if bg_white:
            pending_texts.append((text, draw_x, draw_y, font, rgb_color))
        else:
            draw.text((draw_x, draw_y), text, font=font, fill=rgb_color)

    def _flush_pending_texts():
        """白塗りON時: 全文字の白背景を先に塗り、その後に全文字を描画する。

        マークシートの印字(選択肢9/0等)と重なっても読めるよう白塗りしつつ、
        白背景同士・白背景と文字の上下関係で文字が潰れないことを保証する。
        パディングは小さめに抑え、隣接するマス目や他の印字を隠しすぎない。
        """
        pad = max(1, int(2 * s))
        for text, dx, dy, font, _color in pending_texts:
            tb = draw.textbbox((dx, dy), text, font=font)
            draw.rectangle(
                (tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad),
                fill=(255, 255, 255),
            )
        for text, dx, dy, font, color in pending_texts:
            draw.text((dx, dy), text, font=font, fill=color)
        pending_texts.clear()

    for question_no, result_data in results.items():
        target_q_no = question_no + skip_questions
        question_coords = [c for c in coordinates if c['question_no'] == target_q_no]

        num_choices = len(question_coords)
        if num_choices < 3:
            logger.warning("問題%sの座標が不足しています（%s個、最低3個必要）", question_no, num_choices)
            continue

        default_index = num_choices - 2
        cell_width = question_coords[0]['width']
        pixel_offset = offset * cell_width

        base_coord = question_coords[default_index]
        mark_x = base_coord['x'] + pixel_offset
        mark_y = base_coord['y']
        mark_w = base_coord['width']
        mark_h = base_coord['height']

        # ○×マーク描画
        if rs['show_ox_mark']:
            symbol = "○" if result_data['correct'] else "×"
            _draw_text_pil(
                symbol, int(mark_x * s), int(mark_y * s),
                font_size=base_font_size, color_bgr=(0, 0, 255),
                center_in_box=(int(mark_w * s), int(mark_h * s))
            )

        # 得点・観点の描画
        show_score = rs['show_score']
        show_aspect = rs['show_aspect']

        if show_score or show_aspect:
            if rs['show_ox_mark']:
                symbol = "○" if result_data['correct'] else "×"
                symbol_bbox = draw.textbbox((0, 0), symbol, font=base_font)
                symbol_width = symbol_bbox[2] - symbol_bbox[0]
                score_x = int(mark_x * s) + symbol_width + 1
            else:
                score_x = int(mark_x * s)

            if show_score and show_aspect:
                aspect_circled = number_to_circled(result_data['aspect'])
                _draw_text_pil(
                    str(result_data['points']), score_x, int(mark_y * s),
                    font_size=base_font_size, color_bgr=(0, 0, 0),
                    center_in_box=(int(mark_w * s), int(mark_h * s))
                )
                pts_bbox = draw.textbbox((0, 0), str(result_data['points']), font=base_font)
                pts_w = pts_bbox[2] - pts_bbox[0]
                _draw_text_pil(
                    aspect_circled, score_x + pts_w + 2, int(mark_y * s),
                    font_size=base_font_size, color_bgr=(0, 0, 0),
                    center_in_box=(int(mark_w * s), int(mark_h * s))
                )
            elif show_score:
                _draw_text_pil(
                    str(result_data['points']), score_x, int(mark_y * s),
                    font_size=base_font_size, color_bgr=(0, 0, 0),
                    center_in_box=(int(mark_w * s), int(mark_h * s))
                )
            elif show_aspect:
                aspect_circled = number_to_circled(result_data['aspect'])
                _draw_text_pil(
                    aspect_circled, score_x, int(mark_y * s),
                    font_size=base_font_size, color_bgr=(0, 0, 0),
                    center_in_box=(int(mark_w * s), int(mark_h * s))
                )

        # ×の場合、正答の選択肢位置に赤字で正答番号を表示
        # (選択肢"0"=10番目の位置の解決を含め、位置変換は共通ヘルパーに委譲)
        if not result_data['correct'] and rs['show_correct_answer']:
            correct_answer = result_data['correct_answer']
            if mark_format == MARK_FORMAT_MULTI_DIGIT:
                # 複数桁グループ: 各行の正答記号を、その行の正しいマーク位置に赤描画
                span = result_data.get('span', 1)
                for i, char in enumerate(str(correct_answer)[:span]):
                    row_coords = [c for c in coordinates if c['question_no'] == target_q_no + i]
                    row_coords.sort(key=lambda c: c['choice'])
                    target_index = choice_to_position_index(char, len(row_coords), mark_format)
                    if target_index is None or target_index >= len(row_coords):
                        continue
                    correct_mark = row_coords[target_index]
                    _draw_text_pil(
                        char,
                        int(correct_mark['x'] * s), int(correct_mark['y'] * s),
                        font_size=base_font_size, color_bgr=(0, 0, 255),
                        center_in_box=(int(correct_mark['width'] * s), int(correct_mark['height'] * s))
                    )
            else:
                target_index = choice_to_position_index(correct_answer, num_choices)
                if target_index is not None and target_index < len(question_coords):
                    correct_mark = question_coords[target_index]
                    _draw_text_pil(
                        str(correct_answer),
                        int(correct_mark['x'] * s), int(correct_mark['y'] * s),
                        font_size=base_font_size, color_bgr=(0, 0, 255),
                        center_in_box=(int(correct_mark['width'] * s), int(correct_mark['height'] * s))
                    )

        # 特例(全員正解)の設問: 正答位置に★を表示して特例適用を視認できるようにする。
        # 正答が未登録(空欄)の場合は左端の選択肢位置に★を置く(特例適用のしるし)
        # 複数桁グループでは先頭行の正答1文字目の位置に★を1つ表示する
        if result_data.get('special') == '全員正解' and rs.get('show_all_correct_star', True):
            correct_answer = str(result_data['correct_answer'])
            if mark_format == MARK_FORMAT_MULTI_DIGIT:
                star_index = choice_to_position_index(correct_answer[:1], num_choices, mark_format)
            else:
                star_index = choice_to_position_index(correct_answer, num_choices)
            if star_index is None or star_index >= len(question_coords):
                star_index = 0
            star_mark = question_coords[star_index]
            _draw_text_pil(
                "★",
                int(star_mark['x'] * s), int(star_mark['y'] * s),
                font_size=base_font_size, color_bgr=(0, 0, 255),
                center_in_box=(int(star_mark['width'] * s), int(star_mark['height'] * s))
            )

    if bg_white:
        _flush_pending_texts()


def draw_scoring_results(image, coordinates, scoring_result, skip_questions=0, output_scale=1.0, rendering_settings=None, mark_format=MARK_FORMAT_STANDARD):
    """
    採点結果を画像に描画

    ○×マークのデフォルト位置は後ろから2番目のマークエリア（インデックス -2）。
    rendering_settings の mark_result_offset でオフセット調整が可能。

    全ての選択肢エリアが模範解答の対象となる。
    不正解時の正答位置表示は correct_answer_int - 1 のインデックスに描画される。

    Args:
        output_scale: 座標・フォントのスケール倍率（高解像度出力用）
        rendering_settings: 描画設定辞書（Noneならデフォルト）
        mark_format: マーク形式（MARK_FORMAT_MULTI_DIGIT でグループ描画）
    """
    result_image = image.copy()
    pil_img = Image.fromarray(cv2.cvtColor(result_image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    _draw_scoring_on_pil(draw, coordinates, scoring_result, skip_questions, output_scale, rendering_settings, mark_format)
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def draw_total_score(image, coordinates, scoring_result, total_display_config=None, output_scale=1.0):
    """
    合計得点を画像に描画（2行表示）
    
    total_display_config が指定されている場合、ボックス内にテキストを
    収まるよう自動的にフォントサイズを調整して描画する。
    
    Args:
        image: OpenCV画像
        coordinates: マーク座標リスト
        scoring_result: score_answers() の戻り値
        total_display_config: {"total_display_region": [x1,y1,x2,y2]} or None
        output_scale: 座標・フォントのスケール倍率
    """
    s = output_scale
    result_image = image.copy()
    layout = _prepare_total_score_layout(result_image, scoring_result, total_display_config, s)
    line1, line2, sorted_aspects, aspect_scores, box_x1, box_y1, box_w, box_h = layout
    return _draw_total_score_in_box(result_image, line1, line2, sorted_aspects,
                                    aspect_scores, box_x1, box_y1, box_w, box_h,
                                    output_scale=s)


def _draw_total_score_on_pil(draw, line1, line2, sorted_aspects, aspect_scores,
                             box_x1, box_y1, box_w, box_h, output_scale=1.0):
    """PIL Drawオブジェクトに合計得点を直接描画（in-place）。

    cv2↔PIL変換を行わない内部関数。_draw_total_score_in_box / draw_all_results から呼ばれる。
    """
    s = output_scale

    # フォントサイズの自動調整（スケールに応じた範囲で探索）
    max_font = int(14 * s)
    min_font = max(int(6 * s), 6)
    font_size = max_font
    line2_font_size = int(12 * s)
    gap = max(int(4 * s), 4)
    margin_w = max(int(6 * s), 6)
    margin_h = max(int(4 * s), 4)
    for attempt_size in range(max_font, min_font, -1):
        font_test = _get_cached_font(attempt_size)
        bbox1 = draw.textbbox((0, 0), line1, font=font_test)
        w1 = bbox1[2] - bbox1[0]
        h1 = bbox1[3] - bbox1[1]
        total_h = h1 + gap
        max_w = w1

        if line2:
            font_test2 = _get_cached_font(max(min_font, attempt_size - int(2 * s)))
            bbox2 = draw.textbbox((0, 0), line2, font=font_test2)
            w2 = bbox2[2] - bbox2[0]
            h2 = bbox2[3] - bbox2[1]
            total_h += h2
            max_w = max(max_w, w2)

        if max_w <= box_w - margin_w and total_h <= box_h - margin_h:
            font_size = attempt_size
            line2_font_size = max(min_font, attempt_size - int(2 * s))
            break
    else:
        font_size = max(int(7 * s), 7)
        line2_font_size = max(int(6 * s), 6)

    font = _get_cached_font(font_size)
    font_small = _get_cached_font(line2_font_size)

    # 青色 (RGB)
    color = (0, 0, 255)
    pad_x = max(int(3 * s), 3)
    pad_y = max(int(2 * s), 2)
    gap_y = max(int(4 * s), 4)
    margin = max(int(6 * s), 6)

    # 1行目: 合計得点
    draw.text((box_x1 + pad_x, box_y1 + pad_y), line1, font=font, fill=color)

    # 2行目: 観点別
    if line2:
        line1_bbox = draw.textbbox((0, 0), line1, font=font)
        line1_h = line1_bbox[3] - line1_bbox[1]

        bbox2_test = draw.textbbox((0, 0), line2, font=font_small)
        w2_test = bbox2_test[2] - bbox2_test[0]
        if w2_test > box_w - margin:
            short_parts = []
            for asp in sorted_aspects:
                circled = number_to_circled(asp)
                short_parts.append(f"{circled}:{aspect_scores.get(asp, 0)}")
            line2 = " ".join(short_parts)

        draw.text((box_x1 + pad_x, box_y1 + line1_h + gap_y), line2, font=font_small, fill=color)


def _prepare_total_score_layout(image, scoring_result, total_display_config, output_scale):
    """合計得点描画のテキストとボックス位置を計算する（描画は行わない）。

    Returns:
        (line1, line2, sorted_aspects, aspect_scores, box_x1, box_y1, box_w, box_h)
    """
    s = output_scale
    total_score = scoring_result['total_score']
    total_max_score = sum(scoring_result['aspect_max_scores'].values())
    line1 = f"得点：{total_score} / {total_max_score}"

    aspect_scores = scoring_result['aspect_scores']
    aspect_max_scores = scoring_result['aspect_max_scores']
    sorted_aspects = sorted(aspect_max_scores.keys())

    aspect_parts = []
    for aspect in sorted_aspects:
        circled = number_to_circled(aspect)
        score = aspect_scores.get(aspect, 0)
        max_score = aspect_max_scores[aspect]
        aspect_parts.append(f"観点{circled}：{score}/{max_score}")
    line2 = "(" + " ".join(aspect_parts) + ")" if aspect_parts else ""

    if total_display_config and "total_display_region" in total_display_config:
        region = total_display_config["total_display_region"]
        box_x1, box_y1 = int(region[0] * s), int(region[1] * s)
        box_x2, box_y2 = int(region[2] * s), int(region[3] * s)
        box_w = box_x2 - box_x1
        box_h = box_y2 - box_y1
    else:
        h, w = image.shape[:2]
        orig_w = int(w / s) if s > 0 else w
        orig_h = int(h / s) if s > 0 else h
        from descriptive_scorer import _calculate_marker_default_region, DEFAULT_TOTAL_BOX_HEIGHT
        box_h_orig = DEFAULT_TOTAL_BOX_HEIGHT
        mx, my, mw, mh = _calculate_marker_default_region(orig_w, orig_h, box_h_orig)
        box_x1 = int(mx * s)
        box_y1 = int(my * s)
        box_w = int(mw * s)
        box_h = int(mh * s)

    return (line1, line2, sorted_aspects, aspect_scores, box_x1, box_y1, box_w, box_h)


def _draw_total_score_in_box(image, line1, line2, sorted_aspects, aspect_scores,
                             box_x1, box_y1, box_w, box_h, output_scale=1.0):
    """ボックス内にテキストを自動フォントサイズで描画（後方互換ラッパー）"""
    pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    _draw_total_score_on_pil(draw, line1, line2, sorted_aspects, aspect_scores,
                              box_x1, box_y1, box_w, box_h, output_scale)
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def _draw_total_score_fallback(image, line1, line2, coordinates, output_scale=1.0):
    """最後のマーク座標から固定オフセットで描画（従来のフォールバック）"""
    s = output_scale
    result_image = image
    
    # 最後の問題番号を取得
    max_question_no = max([c['question_no'] for c in coordinates]) if coordinates else 0
    last_question_coords = [c for c in coordinates if c['question_no'] == max_question_no]
    
    if not last_question_coords:
        return result_image
    
    choice1_coord = last_question_coords[0]
    
    base_font_size = int(14 * s)
    base_font_size_small = int(12 * s)
    
    # 最後のマーク枠の下限からオフセット
    text_y = int((choice1_coord['y'] + choice1_coord['height'] + 14) * s)
    text_x = int((choice1_coord['x'] - 40) * s)
    
    # 1行目：得点（青色）
    result_image = draw_text_on_image(
        result_image, line1, text_x, text_y,
        font_size=base_font_size, color=(255, 0, 0), center_in_box=None
    )
    
    # 1行目のテキストの高さを計算して2行目の位置を決定
    temp_font = _get_cached_font(base_font_size)
    
    temp_img = Image.new('RGB', (100, 100))
    temp_draw = ImageDraw.Draw(temp_img)
    first_line_bbox = temp_draw.textbbox((0, 0), line1, font=temp_font)
    first_line_height = first_line_bbox[3] - first_line_bbox[1]
    
    second_line_y = text_y + first_line_height
    
    # 2行目：観点別得点（青色）
    if line2:
        result_image = draw_text_on_image(
            result_image, line2, text_x, second_line_y,
            font_size=base_font_size_small, color=(255, 0, 0), center_in_box=None
        )
    
    return result_image


def draw_all_results(image, coordinates, scoring_result, skip_questions=0,
                     output_scale=1.0, rendering_settings=None, total_display_config=None,
                     mark_format=MARK_FORMAT_STANDARD):
    """○×描画 + 合計得点描画を PIL 変換1回で完了する統合関数。

    process_scoring のイメージ処理ループで draw_scoring_results ＋ draw_total_score を
    個別に呼ぶと cv2↔PIL 変換が2回発生する。本関数は1回の変換で両方の描画を行い
    約50%のピクセルコピーを削減する。

    Args:
        image: OpenCV画像（BGR）
        coordinates: マーク座標リスト
        scoring_result: score_answers() の戻り値
        skip_questions: スキップ問題数
        output_scale: スケール倍率
        rendering_settings: 描画設定辞書
        total_display_config: 合計得点表示設定
    """
    s = output_scale
    result_image = image.copy()

    # --- cv2→PIL 1回だけ ---
    pil_img = Image.fromarray(cv2.cvtColor(result_image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    # ○×・得点・正答の描画
    _draw_scoring_on_pil(draw, coordinates, scoring_result, skip_questions, s, rendering_settings, mark_format)

    # 合計得点の描画
    layout = _prepare_total_score_layout(result_image, scoring_result, total_display_config, s)
    line1, line2, sorted_aspects, aspect_scores, box_x1, box_y1, box_w, box_h = layout
    _draw_total_score_on_pil(draw, line1, line2, sorted_aspects, aspect_scores,
                              box_x1, box_y1, box_w, box_h, s)

    # --- PIL→cv2 1回だけ ---
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def process_scoring(image_folder, coord_excel_path, template_path, mark2_result_path,
                   skip_questions=0, output_base_folder=None, log_callback=None,
                   rendering_settings=None, progress_callback=None, cancel_event=None,
                   mark_format=MARK_FORMAT_STANDARD):
    """採点処理を実行

    Args:
        rendering_settings: 描画設定辞書（Noneならデフォルト）
        progress_callback: 進捗コールバック(current, total)（オプション、GUIプログレスバー用）
        cancel_event: threading.Event — set()されると処理を中断
        mark_format: マーク形式（MARK_FORMAT_MULTI_DIGIT で複数桁グループ採点）
    """
    
    # ログ出力用関数
    def log(message, replace_last=False):
        if log_callback:
            try:
                log_callback(message, replace_last=replace_last)
            except TypeError:
                log_callback(message)
        else:
            logger.info(message)
            
    image_folder = Path(image_folder)
    
    # 出力先ベースフォルダを決定
    if output_base_folder is None:
        output_base_folder = image_folder
    else:
        output_base_folder = Path(output_base_folder)
    
    # 結果フォルダ構造
    results_folder = output_base_folder / RESULTS_FOLDER
    scored_folder = results_folder / SCORED_FOLDER
    
    scored_folder.mkdir(parents=True, exist_ok=True)
    
    log(f"{'='*60}")
    log(f"採点処理")
    log(f"{'='*60}")
    log(f"✓ 入力フォルダ: {image_folder}")
    log(f"✓ 出力フォルダ: {scored_folder}")
    log(f"✓ テンプレート: {Path(template_path).name}")
    log(f"✓ Mark2結果: {Path(mark2_result_path).name}")
    log("")
    
    # テンプレート読み込み
    template_dict = load_template(template_path, mark_format=mark_format)
    log(f"✓ テンプレート読込: {len(template_dict)}問")

    # Mark2結果読み込み
    mark2_results = load_mark2_results(mark2_result_path, skip_questions)
    log(f"✓ Mark2結果読込: {len(mark2_results)}件")

    # 座標データ読み込み（Excelから直接）
    # coordinates.csvではなく、Excelから詳細な座標を取得する
    coordinates, _ = parse_excel_coordinates(coord_excel_path, skip_questions)
    log(f"✓ 座標データ読込: {len(coordinates)}個")

    # 複数桁モード: answer_keyの範囲が座標定義のマーク行数を超えていないか検証
    if mark_format == MARK_FORMAT_MULTI_DIGIT:
        coord_q_nos = {c['question_no'] for c in coordinates}
        max_row = max((q - skip_questions) for q in coord_q_nos if isinstance(q, (int, float))) if coord_q_nos else 0
        overruns = [t.get('group_label', str(q)) for q, t in template_dict.items()
                    if q + t.get('span', 1) - 1 > max_row]
        if overruns:
            raise ValueError(
                f"answer_keyの問題番号範囲が座標定義のマーク行数({int(max_row)}行)を超えています: "
                f"{', '.join(overruns)}")
    
    # 合計点表示位置の設定を読み込み
    total_display_config = None
    try:
        from descriptive_scorer import load_total_display_config, TOTAL_DISPLAY_CONFIG_FILE
        results_data_folder = results_folder / RESULTS_DATA_FOLDER
        config_path = str(results_data_folder / TOTAL_DISPLAY_CONFIG_FILE)
        total_display_config = load_total_display_config(config_path)
        if total_display_config:
            log(f"✓ 合計点表示位置: カスタム設定を使用")
    except Exception:
        pass  # 設定ファイルなし → デフォルト位置で描画
    
    # マーカーキャッシュを読み込み（Step 1 で保存済みなら再検出をスキップ）
    marker_cache = _load_marker_cache(results_folder)
    if marker_cache:
        log(f"✓ マーカーキャッシュ: {len(marker_cache)}件（高速モード）")
    
    log("")
    
    # 各学生の採点処理
    success_count = 0
    error_count = 0
    
    for idx, result_data in enumerate(mark2_results, 1):
        # 中断チェック
        if cancel_event and cancel_event.is_set():
            log(f"⏹ 中断されました ({idx-1}/{len(mark2_results)}件処理済み)")
            break
        image_name = result_data['image']
        student_answers = result_data['answers']
        if progress_callback:
            try:
                progress_callback(idx, len(mark2_results))
            except Exception:
                pass
        
        try:
            # 元画像を読み込み
            image_path = image_folder / image_name
            if not image_path.exists():
                raise FileNotFoundError(f"画像ファイルが見つかりません: {image_path}")
            
            # 画像読み込み
            with open(str(image_path), 'rb') as f:
                image_data_bytes = f.read()
            image = cv2.imdecode(np.frombuffer(image_data_bytes, np.uint8), cv2.IMREAD_COLOR)
            
            if image is None:
                raise ValueError("画像を読み込めません")
            
            # マーカー検出（キャッシュがあればスキップ）
            cached = marker_cache.get(image_name)
            if cached:
                markers = cached
            else:
                markers = detect_corner_markers(image, debug=False)
            output_scale = compute_output_scale(image)
            corrected_image, _ = apply_perspective_transform(image, markers, output_scale=output_scale)
            
            # 採点
            scoring_result = score_answers(student_answers, template_dict, mark_format=mark_format)

            # 補正済み画像に採点結果 + 合計得点をPIL変換1回で描画
            result_image = draw_all_results(corrected_image, coordinates, scoring_result, skip_questions,
                                            output_scale=output_scale, rendering_settings=rendering_settings,
                                            total_display_config=total_display_config,
                                            mark_format=mark_format)
            
            # 保存 (JPEG品質85: 画質と容量のバランス)
            output_path = scored_folder / image_name
            is_success, encoded_img = cv2.imencode('.jpg', result_image,
                                                    [cv2.IMWRITE_JPEG_QUALITY, 85])
            if is_success:
                encoded_img.tofile(str(output_path))
            
            log(f"  [{idx}/{len(mark2_results)}] ✓ {image_name}: {scoring_result['total_score']}/{scoring_result['max_score']}点", replace_last=True)
            success_count += 1
            
        except Exception as e:
            log(f"  [{idx}/{len(mark2_results)}] ✗ エラー: {image_name} - {e}", replace_last=False)
            error_count += 1
    
    log("")
    log(f"{'='*60}")
    log(f"採点処理完了")
    log(f"{'='*60}")
    log(f"✓ 成功: {success_count}件")
    log(f"✓ エラー: {error_count}件")
    log(f"✓ 出力先: {scored_folder}")
    log("")
    
    return {
        'total_count': len(mark2_results),
        'success_count': success_count,
        'error_count': error_count
    }
