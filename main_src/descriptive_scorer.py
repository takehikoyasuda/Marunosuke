#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descriptive_scorer.py — 記述問題 コアロジックモジュール

JSON永続化、バッチ処理、画像トリミングなどコアロジックを提供する。
GUIクラスは descriptive_gui.py に、描画関数は descriptive_renderer.py に分離済み。

後方互換のため、分離されたシンボルも本モジュールから re-export する。
"""

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

from name_trimmer import select_region_on_image, get_image_files
from constants import (
    get_app_temp_dir, atomic_json_save, load_json_safe,
    MARKER_X_FRAC_LEFT, MARKER_X_FRAC_RIGHT, MARKER_Y_FRAC_BOTTOM,
    number_to_circled,
)

from descriptive_renderer import (
    SCORE_FONT_SIZE, SCORE_COLOR_RGB, TOTAL_COLOR_RGB,
    DEFAULT_TOTAL_BOX_WIDTH, DEFAULT_TOTAL_BOX_HEIGHT,
    _font_cache, _get_font,
    draw_descriptive_on_image, draw_combined_total,
)

logger = logging.getLogger(__name__)


# ============================================================
# 定数
# ============================================================

DESCRIPTIVE_CONFIG_FILE = "descriptive_config.json"
DESCRIPTIVE_SCORES_FILE = "descriptive_scores.json"
DESCRIPTIVE_ANNOTATIONS_FILE = "descriptive_annotations.json"
TOTAL_DISPLAY_CONFIG_FILE = "total_display_config.json"
COMMENT_HISTORY_LIMIT = 50
# 教員用メモもコメントと同じ履歴上限・最近使用順で管理する。
MEMO_HISTORY_LIMIT = COMMENT_HISTORY_LIMIT
ANNOTATION_TAG_LIMIT = 10
ANNOTATION_TAG_MAX_LENGTH = 30


# ============================================================
# JSON 永続化
# ============================================================

def load_descriptive_config(config_path: str) -> Optional[dict]:
    """descriptive_config.json を読み込む。ファイル不在や破損時は .bak からリカバリ。"""
    return load_json_safe(config_path, required_keys=["questions"])


def save_descriptive_config(config_path: str, config: dict):
    """descriptive_config.json をアトミックに保存する。"""
    atomic_json_save(config_path, config)


def load_descriptive_scores(scores_path: str) -> Optional[dict]:
    """descriptive_scores.json を読み込む。ファイル不在や破損時は .bak からリカバリ。"""
    return load_json_safe(scores_path, required_keys=["scores"])


def save_descriptive_scores(scores_path: str, scores: dict):
    """descriptive_scores.json をアトミックに保存する。"""
    atomic_json_save(scores_path, scores)


def normalize_descriptive_annotations(data: Optional[dict]) -> dict:
    """注釈データを安全な正規形へ変換する。"""
    source = data if isinstance(data, dict) else {}
    normalized = dict(source)
    normalized["version"] = source.get("version", 1)

    answers = {}
    raw_answers = source.get("answers", {})
    if isinstance(raw_answers, dict):
        for filename, question_map in raw_answers.items():
            if not isinstance(filename, str) or not isinstance(question_map, dict):
                continue
            clean_questions = {}
            for question_id, annotation in question_map.items():
                if not isinstance(question_id, str) or not isinstance(annotation, dict):
                    continue
                memo = annotation.get("memo", "")
                comment = annotation.get("comment", "")
                memo = memo if isinstance(memo, str) else str(memo)
                comment = comment if isinstance(comment, str) else str(comment)
                held = annotation.get("held", False) is True
                raw_tags = annotation.get("tags", [])
                tags = normalize_annotation_tags(raw_tags if isinstance(raw_tags, list) else [])
                if memo or comment or held or tags:
                    clean_questions[question_id] = {
                        "memo": memo, "comment": comment,
                        "held": held, "tags": tags,
                    }
            if clean_questions:
                answers[filename] = clean_questions
    normalized["answers"] = answers

    history = {}
    raw_history = source.get("comment_history", {})
    if isinstance(raw_history, dict):
        for question_id, comments in raw_history.items():
            if not isinstance(question_id, str) or not isinstance(comments, list):
                continue
            clean_comments = []
            for comment in comments:
                if not isinstance(comment, str):
                    continue
                comment = comment.strip()
                if comment and comment not in clean_comments:
                    clean_comments.append(comment)
                if len(clean_comments) >= COMMENT_HISTORY_LIMIT:
                    break
            if clean_comments:
                history[question_id] = clean_comments
    normalized["comment_history"] = history
    memo_history = {}
    raw_memo_history = source.get("memo_history", {})
    if isinstance(raw_memo_history, dict):
        for question_id, memos in raw_memo_history.items():
            if not isinstance(question_id, str) or not isinstance(memos, list):
                continue
            clean_memos = []
            for memo in memos:
                if not isinstance(memo, str):
                    continue
                memo = memo.strip()
                if memo and memo not in clean_memos:
                    clean_memos.append(memo)
                if len(clean_memos) >= MEMO_HISTORY_LIMIT:
                    break
            if clean_memos:
                memo_history[question_id] = clean_memos
    # 旧ファイルの形を不要に変えないため、履歴キーは存在した場合だけ出力する。
    if "memo_history" in source or memo_history:
        normalized["memo_history"] = memo_history
    return normalized


def normalize_annotation_tags(tags) -> list:
    """タグをトリム・重複排除し、長さと件数の上限を適用する。"""
    result = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()[:ANNOTATION_TAG_MAX_LENGTH]
        if tag and tag not in result:
            result.append(tag)
        if len(result) >= ANNOTATION_TAG_LIMIT:
            break
    return result


def update_comment_history(history, comment: str) -> list:
    """コメントを重複なしの最近使用順で履歴へ追加する。"""
    comment = comment.strip()
    existing = history if isinstance(history, list) else []
    result = [comment] if comment else []
    for item in existing:
        if isinstance(item, str):
            item = item.strip()
            if item and item not in result:
                result.append(item)
        if len(result) >= COMMENT_HISTORY_LIMIT:
            break
    return result


def load_descriptive_annotations(annotations_path: str) -> dict:
    """回答注釈を読み込む。未作成・破損時は空の正規形を返す。"""
    return normalize_descriptive_annotations(load_json_safe(annotations_path))


def save_descriptive_annotations(annotations_path: str, annotations: dict):
    """回答注釈を正規化してアトミックに保存する。"""
    atomic_json_save(annotations_path, normalize_descriptive_annotations(annotations))


def load_total_display_config(config_path: str) -> Optional[dict]:
    """total_display_config.json を読み込む。ファイル不在や破損時は .bak からリカバリ。"""
    return load_json_safe(config_path, required_keys=["total_display_region"])


def save_total_display_config(config_path: str, region: list):
    """total_display_config.json をアトミックに保存する。"""
    data = {"total_display_region": region}
    atomic_json_save(config_path, data)


# ============================================================
# マーカー基準座標
# ============================================================

# マーカー基準座標は constants.py の共有定数を使用
# (apply_perspective_transform の dst_points と同一の値であることが保証される)
_MARKER_HALF_SIZE_FRAC = 0.013         # マーカー半幅 / 幅（約納）


def _calculate_marker_default_region(
    orig_w: int, orig_h: int, box_h: int
) -> tuple:
    """
    下部マーカー間のデフォルトボックス位置とサイズを計算する。

    補正済み画像は apply_perspective_transform により
    マーカーが固定比率の位置にマップされるため、
    画像サイズから直接計算できる。

    配置ルール:
    - 左辺: 左下マーカー内側 + わずかなスペース
    - 右辺: 右下マーカー内側 - わずかなスペース
    - 幅: マーカー間の利用可能幅いっぱい
    - Y中心: マーカーの中心と揃う

    Args:
        orig_w: 元画像幅 (px)
        orig_h: 元画像高さ (px)
        box_h: ボックス高さ (元画像座標系, px)

    Returns:
        (x, y, w, h) ボックスの左上座標と幅・高さ（元画像座標系）
    """
    margin_frac = 0.005  # マーカー内側からの余白
    left_inner = (MARKER_X_FRAC_LEFT + _MARKER_HALF_SIZE_FRAC + margin_frac) * orig_w
    right_inner = (MARKER_X_FRAC_RIGHT - _MARKER_HALF_SIZE_FRAC - margin_frac) * orig_w
    marker_cy = MARKER_Y_FRAC_BOTTOM * orig_h

    x = int(left_inner)
    w = int(right_inner - left_inner)
    # Y中心をマーカーに揃える
    y = int(marker_cy - box_h / 2)
    return x, y, w, box_h


# ============================================================
# 画像切り出し
# ============================================================

def trim_descriptive_regions(
    image_folder: str,
    config: dict,
    output_base: Optional[str] = None,
    original_image_folder: Optional[str] = None,
) -> Dict[str, Dict[str, str]]:
    """
    全補正済み画像から記述問題の領域を切り出して保存する。

    original_image_folder が指定された場合、元画像から射影補正して切り出す
    （00_Processing の 595x842 より高画質）。各画像は1回だけ補正し、
    全問題の領域を一括で切り出すため効率的。

    Args:
        image_folder: 補正済み画像フォルダ (00_Processing)
        config: descriptive_config
        output_base: 出力ベースフォルダ (None → 一時フォルダを自動生成)
        original_image_folder: 元画像フォルダ (指定時は高解像度で切り出し)

    Returns:
        {question_id: {image_filename: cropped_image_path, ...}, ...}
    """
    if output_base is None:
        _app_temp = get_app_temp_dir(str(Path(image_folder).parent.parent))
        output_base = tempfile.mkdtemp(prefix="desc_trim_", dir=_app_temp)

    output_base = Path(output_base)  # type: ignore[assignment]
    image_files = get_image_files(image_folder)
    questions = config["questions"]

    logger.info(
        "trim_descriptive_regions: %d画像, %d問題, highres=%s",
        len(image_files), len(questions), original_image_folder is not None,
    )

    if not image_files:
        logger.warning("trim_descriptive_regions: 画像ファイルが見つかりません: %s", image_folder)
    if not questions:
        logger.warning("trim_descriptive_regions: 問題が設定されていません")

    # 出力フォルダ準備
    result: Dict[str, Dict[str, str]] = {}
    for q in questions:
        q_folder = output_base / q["id"]
        q_folder.mkdir(parents=True, exist_ok=True)
        result[q["id"]] = {}

    # 元画像からの高解像度切り出しモード
    use_highres = original_image_folder is not None
    if use_highres:
        from image_alignment import (
            detect_corner_markers, apply_perspective_transform,
            compute_output_scale,
        )

    # 画像ごとに1回だけ補正し、全問題を一括切り出し
    for img_path in image_files:
        filename = Path(img_path).name
        corrected_pil = None
        scale = 1.0

        try:
            if use_highres:
                orig_path = Path(original_image_folder) / filename
                if orig_path.exists():
                    with open(str(orig_path), 'rb') as f:
                        img_bytes = f.read()
                    orig_img = cv2.imdecode(
                        np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR
                    )
                    if orig_img is not None:
                        markers = detect_corner_markers(orig_img, debug=False)
                        scale = compute_output_scale(orig_img)
                        corrected, _ = apply_perspective_transform(
                            orig_img, markers, output_scale=scale
                        )
                        corrected_pil = Image.fromarray(
                            cv2.cvtColor(corrected, cv2.COLOR_BGR2RGB)
                        )
                        logger.debug(
                            "  高解像度切り出し: %s scale=%.2f size=%s",
                            filename, scale, corrected_pil.size,
                        )
                        del orig_img, corrected  # メモリ解放
                else:
                    logger.debug("  元画像が見つかりません: %s", orig_path)

            # 高解像度変換に失敗した場合は00_Processing画像を使用
            if corrected_pil is None:
                corrected_pil = Image.open(img_path)
                scale = 1.0
                logger.debug("  00_Processing使用: %s size=%s", filename, corrected_pil.size)

            img_w, img_h = corrected_pil.size

            # 全問題の領域を一括切り出し
            for q in questions:
                q_id = q["id"]
                region = q["region"]  # [left, top, right, bottom]
                left = max(0, min(int(region[0] * scale), img_w))
                top = max(0, min(int(region[1] * scale), img_h))
                right = max(0, min(int(region[2] * scale), img_w))
                bottom = max(0, min(int(region[3] * scale), img_h))

                if left >= right or top >= bottom:
                    logger.warning(
                        "  領域スキップ: %s %s region=%s scaled=[%d,%d,%d,%d] img=%dx%d",
                        filename, q_id, region, left, top, right, bottom, img_w, img_h,
                    )
                    continue

                cropped = corrected_pil.crop((left, top, right, bottom))
                out_path = output_base / q_id / filename
                cropped.save(str(out_path), quality=90)
                result[q_id][filename] = str(out_path)

        except Exception as e:
            logger.warning("  高解像度切り出し失敗 (%s): %s — フォールバック", filename, e)
            # エラー時は00_Processing画像からフォールバック
            try:
                with Image.open(img_path) as fallback_img:
                    fb_w, fb_h = fallback_img.size
                    for q in questions:
                        q_id = q["id"]
                        region = q["region"]
                        left = max(0, min(int(region[0]), fb_w))
                        top = max(0, min(int(region[1]), fb_h))
                        right = max(0, min(int(region[2]), fb_w))
                        bottom = max(0, min(int(region[3]), fb_h))
                        if left < right and top < bottom:
                            cropped = fallback_img.crop((left, top, right, bottom))
                            out_path = output_base / q_id / filename
                            cropped.save(str(out_path), quality=90)
                            result[q_id][filename] = str(out_path)
            except Exception as e2:
                logger.error("  切り出しエラー: %s: %s (フォールバックも失敗: %s)", filename, e, e2)
        finally:
            if corrected_pil is not None:
                corrected_pil.close()

    total_cropped = sum(len(v) for v in result.values())
    logger.info(
        "trim_descriptive_regions 完了: 問題数=%d, 切り出し画像総数=%d",
        len(result), total_cropped,
    )
    return result


# ============================================================
#   記述のみモード: 採点済み答案生成
# ============================================================

def generate_descriptive_only_sheets(
    boxed_folder: str,
    config: dict,
    descriptive_scores: dict,
    output_folder: str,
    log_callback=None,
    rendering_settings=None,
    annotations=None,
) -> dict:
    """記述のみモード: 記述得点のみを描画した返却答案を生成する。

    マーク採点を行わず、画像に記述採点の結果（○△×・得点・観点）と
    合計点のみを描画して出力する。

    Args:
        boxed_folder: 00_Processing フォルダパス
        config: descriptive_config dict (questions, total_display_region)
        descriptive_scores: {filename: {question_id: score, ...}}
        output_folder: 出力フォルダパス
        log_callback: ログ出力コールバック
        rendering_settings: 描画設定 dict
        annotations: 回答注釈。生徒向けコメントだけを答案へ描画する。

    Returns:
        {'total_count', 'success_count', 'error_count'}
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            logger.info(msg)

    boxed_path = Path(boxed_folder)
    out_path = Path(output_folder)
    out_path.mkdir(parents=True, exist_ok=True)

    # 画像ファイル一覧
    image_files = sorted([
        f for f in boxed_path.iterdir()
        if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif')
    ])

    if not image_files:
        log("エラー: 00_Processing フォルダに画像がありません")
        return {'total_count': 0, 'success_count': 0, 'error_count': 0}

    log(f"{'='*60}")
    log("返却答案生成開始（記述のみモード）")
    log(f"{'='*60}")
    log(f"✓ 対象画像: {len(image_files)}件")
    log(f"✓ 記述問題: {len(config.get('questions', []))}問")
    log(f"✓ 出力先: {out_path}")
    log("")

    # マーク採点結果ダミー（mark_scoring_result の互換用）
    empty_mark_result = {
        'total_score': 0,
        'aspect_scores': {},
        'aspect_max_scores': {},
    }

    success_count = 0
    error_count = 0
    annotation_answers = (annotations or {}).get("answers", {})

    for idx, img_path in enumerate(image_files, 1):
        fname = img_path.name
        try:
            log(f"[{idx}/{len(image_files)}] {fname}")

            # Unicode パス対応: cv2.imdecode + np.fromfile
            image = cv2.imdecode(
                np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if image is None:
                log(f"  ⚠ 画像読み込み失敗: {fname}")
                error_count += 1
                continue

            # 記述のみモードでは座標は画像の実ピクセル基準で保存されている
            # ため output_scale = 1.0 とし、二重スケーリングを防ぐ。
            output_scale = 1.0

            # 記述採点の描画
            scores_for_img = descriptive_scores.get(fname, {})
            question_annotations = annotation_answers.get(fname, {})
            comments_for_img = {
                qid: annotation.get("comment", "")
                for qid, annotation in question_annotations.items()
                if isinstance(annotation, dict) and annotation.get("comment")
            }
            image = draw_descriptive_on_image(
                image, config, scores_for_img,
                output_scale=output_scale,
                rendering_settings=rendering_settings,
                comments_for_image=comments_for_img,
            )

            # 合計点描画（マーク = 0、記述得点のみ）
            image = draw_combined_total(
                image,
                mark_scoring_result=empty_mark_result,
                config=config,
                descriptive_scores_for_image=scores_for_img,
                coordinates=None,
                output_scale=output_scale,
            )

            # 保存（Unicode パス対応: cv2.imencode + tofile）
            out_file = out_path / fname
            ext = out_file.suffix.lower() if out_file.suffix else '.jpg'
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85] if ext in ('.jpg', '.jpeg') else []
            success_enc, buf = cv2.imencode(ext, image, encode_params)
            if success_enc:
                buf.tofile(str(out_file))
                success_count += 1
            else:
                log(f"  ⚠ 画像エンコード失敗: {fname}")
                error_count += 1

        except Exception as e:
            log(f"  ✕ エラー ({fname}): {e}")
            error_count += 1

    log("")
    log(f"{'='*60}")
    log("返却答案生成完了（記述のみモード）")
    log(f"{'='*60}")
    log(f"✓ 成功: {success_count}件")
    log(f"✓ エラー: {error_count}件")
    log(f"✓ 出力先: {output_folder}")
    log("")

    return {
        'total_count': len(image_files),
        'success_count': success_count,
        'error_count': error_count,
    }




# ============================================================
# 後方互換 re-export
# ============================================================
# descriptive_gui.py / descriptive_renderer.py から分離されたシンボルを
# 本モジュール経由でもインポート可能にする。
# descriptive_renderer のシンボルは上部 import で既にモジュール名前空間に存在。
# descriptive_gui のシンボルはここで追加する（循環回避のためファイル末尾に配置）。

from descriptive_gui import (  # noqa: F401, E402
    MAX_KEYBOARD_SCORE,
    _OVERLAY_COLORS_RGB,
    setup_descriptive_regions,
    _ask_add_more,
    _create_overlay_image,
    IntegratedDescriptiveSetup,
    setup_descriptive_regions_integrated,
    select_total_position,
    _ask_question_info,
    DescriptiveScorerGUI,
    _SingleQuestionScorer,
    DescriptiveReviewGUI,
    filter_descriptive_review_answers,
    is_grading_space_key,
)
