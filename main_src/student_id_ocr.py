#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
student_id_ocr.py — 学籍番号エリアの切り出し＋OCR認識(候補生成のみ)。

学籍番号欄の位置は、桁ごとに独立して印刷された赤枠を答案画像全体から色検出
(id_area_color_detector.detect_red_digit_boxes)することで求める。四隅コーナー
マーカー(omr_engine.detect_corner_markers)の割合計算には一切依存しない、独立
した仕組み。自動検出に失敗した場合のみ、教員が id_area_config_gui.IdAreaConfigDialog
で1マスずつ手動指定した矩形(id_area_config.py の manual_digit_rects_frac)を
使う（経緯は student_id_area_requirements.md 参照）。

認識結果はあくまで「候補」であり、このモジュール単体では確定を行わない。
候補を教員が答案画像と見比べて確認・修正するのは student_id_review_gui.py の役割。
"""

import logging
import shutil
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Dict, Optional, Tuple

import cv2
from PIL import Image

from constants import get_app_temp_dir
from digit_ocr_recognizer import LocalDigitOcrRecognizer
from id_area_color_detector import detect_red_digit_boxes, mask_red_border
from id_area_config import compute_manual_digit_box_rect, load_id_area_config, save_id_area_config
from name_trimmer import get_image_files
from image_alignment import (
    apply_perspective_transform,
    compute_output_scale,
    detect_corner_markers,
    imread_unicode,
)

logger = logging.getLogger(__name__)

# Excel埋め込み用サムネイルの高さ（氏名欄画像と揃える）
THUMBNAIL_MAX_HEIGHT = 50


def _clamp_rect(rect: Tuple[int, int, int, int], img_w: int, img_h: int) -> Tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    x0 = max(0, min(x0, img_w))
    y0 = max(0, min(y0, img_h))
    x1 = max(x0 + 1, min(x1, img_w))
    y1 = max(y0 + 1, min(y1, img_h))
    return x0, y0, x1, y1


def _load_working_image(filename: str, image_folder: str, original_image_folder: Optional[str]):
    """高解像度パスがあれば射影補正した画像とscaleを、なければboxed画像とscale=1.0を返す。"""
    if original_image_folder:
        orig_path = Path(original_image_folder) / filename
        if orig_path.exists():
            orig_img = imread_unicode(str(orig_path))
            if orig_img is not None:
                try:
                    markers = detect_corner_markers(orig_img)
                    scale = compute_output_scale(orig_img)
                    corrected, _ = apply_perspective_transform(orig_img, markers, output_scale=scale)
                    return corrected, scale
                except Exception as e:
                    logger.debug("高解像度補正に失敗、通常画像にフォールバック: %s — %s", filename, e)

    boxed_path = Path(image_folder) / filename
    return imread_unicode(str(boxed_path)), 1.0


def _save_thumbnail(bgr_crop, output_path: str):
    rgb = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    if img.height > THUMBNAIL_MAX_HEIGHT:
        ratio = THUMBNAIL_MAX_HEIGHT / img.height
        img = img.resize((max(1, int(img.width * ratio)), THUMBNAIL_MAX_HEIGHT), Image.LANCZOS)
    img.save(output_path, quality=90)


def recognize_student_ids(
    image_folder: str,
    id_area_config: Dict,
    output_folder: str,
    original_image_folder: Optional[str] = None,
) -> Dict[str, Dict]:
    """全画像の学籍番号エリアを切り出し、OCRで候補を生成する。

    学籍番号欄の位置は、id_area_config に manual_digit_rects_frac（手動指定）が
    あればそれを画像サイズに合わせて使い、なければ画像全体からの赤枠自動検出
    （id_area_color_detector.detect_red_digit_boxes）で求める。いずれも四隅
    コーナーマーカーの割合計算には依存しない。

    id_area_config の alpha_positions（0-indexedの桁位置リスト）で指定された
    位置だけは英字専用モデルで認識する（LocalDigitOcrRecognizer.recognize の
    alpha_mask 引数経由）。

    Returns:
        {ファイル名: {'thumbnail_path': str, 'text': Optional[str],
                      'confidence': float, 'per_digit': list}}
    """
    thumb_dir = Path(output_folder) / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    image_files = get_image_files(image_folder)
    recognizer = LocalDigitOcrRecognizer()
    digit_count = id_area_config["digit_count"]
    manual_rects_frac = id_area_config.get("manual_digit_rects_frac")
    alpha_positions = set(id_area_config.get("alpha_positions", []))
    results: Dict[str, Dict] = {}

    for image_path in image_files:
        filename = Path(image_path).name
        try:
            image, _scale = _load_working_image(filename, image_folder, original_image_folder)
            if image is None:
                raise ValueError("画像を読み込めませんでした")

            img_h, img_w = image.shape[:2]
            if manual_rects_frac:
                box_rects = [
                    compute_manual_digit_box_rect(img_w, img_h, rect_frac)
                    for rect_frac in manual_rects_frac
                ]
            else:
                box_rects = detect_red_digit_boxes(image, digit_count)

            digit_images = []
            for box_rect in box_rects:
                x0, y0, x1, y1 = _clamp_rect(box_rect, img_w, img_h)
                crop = mask_red_border(image[y0:y1, x0:x1])
                digit_images.append(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))

            alpha_mask = [i in alpha_positions for i in range(len(digit_images))]
            candidate = recognizer.recognize(digit_images, alpha_mask=alpha_mask)

            # サムネイル: 全マスをまとめた外接矩形を1枚の画像として保存
            whole_rect = (
                min(r[0] for r in box_rects), min(r[1] for r in box_rects),
                max(r[2] for r in box_rects), max(r[3] for r in box_rects),
            )
            wx0, wy0, wx1, wy1 = _clamp_rect(whole_rect, img_w, img_h)
            thumb_path = thumb_dir / filename
            _save_thumbnail(image[wy0:wy1, wx0:wx1], str(thumb_path))

            results[filename] = {
                'thumbnail_path': str(thumb_path),
                'text': candidate.value,
                'confidence': candidate.confidence,
                'per_digit': candidate.per_digit,
            }
        except Exception as e:
            logger.warning("学籍番号OCRエラー（スキップ）: %s — %s", filename, e)
            results[filename] = {
                'thumbnail_path': None,
                'text': None,
                'confidence': 0.0,
                'per_digit': [],
            }

    return results


class StudentIdOcrTrimmer:
    """学籍番号欄の位置設定(初回のみ)→一括OCRを一気通貫で提供するクラス。

    NameTrimmer と対になる構造。確認・修正はこのクラスの責務ではなく、
    戻り値の候補辞書を student_id_review_gui.StudentIdReviewGUI に渡して行う。
    """

    def __init__(self):
        self._temp_dir: Optional[str] = None

    def run(
        self,
        image_folder: str,
        parent: Optional[tk.Tk] = None,
        original_image_folder: Optional[str] = None,
        config_path: Optional[str] = None,
        default_digit_count: int = 8,
    ) -> Optional[Dict[str, Dict]]:
        image_files = get_image_files(image_folder)
        if not image_files:
            logger.error("画像フォルダに画像がありません: %s", image_folder)
            if parent:
                messagebox.showerror(
                    "エラー",
                    f"指定フォルダに画像がありません:\n{image_folder}",
                    parent=parent,
                )
            return None

        config = load_id_area_config(config_path) if config_path else None
        if config is None:
            from id_area_config_gui import IdAreaConfigDialog
            dialog = IdAreaConfigDialog(parent, image_files[0], default_digit_count=default_digit_count)
            config = dialog.run()
            if config is None:
                logger.info("学籍番号欄の位置設定がキャンセルされました。")
                return None
            if config_path:
                save_id_area_config(config_path, config)
                logger.info("✓ 学籍番号欄の位置設定を保存しました: %s", config_path)
        else:
            logger.info("✓ 学籍番号欄の位置設定を読み込みました: %s", config_path)

        _app_temp = get_app_temp_dir(str(Path(image_folder).parent.parent))
        temp_dir = tempfile.mkdtemp(prefix="student_id_ocr_", dir=_app_temp)
        self._temp_dir = temp_dir

        results = recognize_student_ids(
            image_folder, config, temp_dir,
            original_image_folder=original_image_folder,
        )
        logger.info("学籍番号OCR完了: %d枚", len(results))
        return results

    def cleanup(self):
        """一時ファイルを削除する。"""
        if self._temp_dir and Path(self._temp_dir).exists():
            try:
                shutil.rmtree(self._temp_dir)
                logger.debug("一時ファイルを削除しました。")
            except Exception as e:
                logger.warning("一時ファイルの削除に失敗しました: %s", e)
            finally:
                self._temp_dir = None
