#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
page_number_checker.py — 印刷されたページ番号の取り違え確認ツール。

同じページ番号の答案だけをまとめて1つのフォルダ/PDFにして読み込む運用を前提に、
「このバッチに本当に同じページ番号の答案だけが入っているか」を機械的に検証する
単発ツール。答案用紙に印刷された大きめの数字一文字を、教員が最初の1枚に対して
一度だけ矩形選択し、その矩形をそのまま全画像に適用してOCRする。

学籍番号OCR(student_id_ocr.py)と異なり、四隅コーナーマーカーや射影変換には
一切依存しない（教員が毎回手動で矩形を選ぶため、位置検出のロジックが不要）。
確認のみを目的とし、結果を集計Excelや他の確認画面には統合しない。
"""

import logging
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, Optional

import cv2

from constants import get_ui_font_family, get_ui_font_size, fit_window_to_content
from digit_ocr_recognizer import LocalDigitOcrRecognizer
from name_trimmer import get_image_files, select_region_on_image
from omr_engine import imread_unicode

logger = logging.getLogger(__name__)

UI_FONT = get_ui_font_family()


def recognize_page_numbers(image_files, rect) -> Dict[str, Dict]:
    """画像ファイルのリストに対し、同じ矩形位置の印刷ページ番号をOCRし、不一致を検出する。

    GUI(矩形選択・結果表示)に依存しない純粋ロジック部分。

    Args:
        image_files: 画像ファイルパスのリスト
        rect: 全画像に共通で適用する (left, top, right, bottom) 実寸ピクセル座標

    Returns:
        {ファイル名: {'value': str|None, 'confidence': float, 'mismatch': bool}}
    """
    recognizer = LocalDigitOcrRecognizer()
    x0, y0, x1, y1 = rect
    raw_results: Dict[str, Optional[str]] = {}
    confidences: Dict[str, float] = {}

    for image_path in image_files:
        filename = Path(image_path).name
        image = imread_unicode(image_path)
        if image is None:
            raw_results[filename] = None
            confidences[filename] = 0.0
            continue
        img_h, img_w = image.shape[:2]
        cx0, cy0 = max(0, min(x0, img_w)), max(0, min(y0, img_h))
        cx1, cy1 = max(cx0 + 1, min(x1, img_w)), max(cy0 + 1, min(y1, img_h))
        crop = cv2.cvtColor(image[cy0:cy1, cx0:cx1], cv2.COLOR_BGR2RGB)
        candidate = recognizer.recognize([crop])
        raw_results[filename] = candidate.value
        confidences[filename] = candidate.confidence

    value_counts = Counter(v for v in raw_results.values() if v is not None)
    majority_value = value_counts.most_common(1)[0][0] if value_counts else None

    results: Dict[str, Dict] = {}
    for filename, value in raw_results.items():
        results[filename] = {
            'value': value,
            'confidence': confidences[filename],
            'mismatch': value != majority_value,
        }
    return results


def check_page_numbers(image_folder: str, parent: Optional[tk.Tk] = None) -> Optional[Dict[str, Dict]]:
    """フォルダ内の全画像から、同じ矩形位置の印刷ページ番号をOCRし、不一致を検出する。

    教員に最初の1枚で矩形を選択させ(GUI)、`recognize_page_numbers`で認識した上で
    結果一覧をポップアップ表示する(GUI)。

    Returns:
        {ファイル名: {'value': str|None, 'confidence': float, 'mismatch': bool}}
        キャンセル時や画像が無い場合は None。
    """
    image_files = get_image_files(image_folder)
    if not image_files:
        messagebox.showerror("エラー", f"指定フォルダに画像がありません:\n{image_folder}", parent=parent)
        return None

    rect = select_region_on_image(
        image_files[0], parent,
        title="ページ番号エリアの選択 — ドラッグで矩形を描いてください",
        label_text="ページ番号",
        instruction_text=(
            "画像上でマウスを\nドラッグして、\n印刷されたページ番号\nの数字を囲んで\n"
            "ください。\n\n数字が小さい場合は\n＋ボタンや\nマウスホイールで\n拡大してから\n"
            "選択してください。\n\n何度でも\nやり直せます。"
        ),
    )
    if rect is None:
        return None

    results = recognize_page_numbers(image_files, rect)
    value_counts = Counter(info['value'] for info in results.values() if info['value'] is not None)
    majority_value = value_counts.most_common(1)[0][0] if value_counts else None
    _show_result_dialog(parent, results, majority_value)
    return results


def _show_result_dialog(parent, results: Dict[str, Dict], majority_value: Optional[str]):
    window = tk.Toplevel(parent)
    window.title("ページ番号確認結果")

    mismatch_count = sum(1 for info in results.values() if info['mismatch'])
    summary_text = f"多数決のページ番号: {majority_value if majority_value is not None else '(認識できず)'}　／　不一致: {mismatch_count}件"
    tk.Label(
        window, text=summary_text, font=(UI_FONT, get_ui_font_size(10), 'bold'),
        fg='#C62828' if mismatch_count else '#2E7D32',
    ).pack(pady=8)

    tree_frame = tk.Frame(window)
    tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    columns = ('file', 'value', 'confidence')
    tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
    tree.heading('file', text='ファイル名')
    tree.heading('value', text='認識結果')
    tree.heading('confidence', text='確信度')
    tree.column('file', width=260)
    tree.column('value', width=80, anchor=tk.CENTER)
    tree.column('confidence', width=80, anchor=tk.CENTER)

    scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    tree.tag_configure('mismatch', background='#FFCDD2')

    for filename in sorted(results.keys()):
        info = results[filename]
        display_value = info['value'] if info['value'] is not None else '(認識不可)'
        tree.insert(
            '', tk.END,
            values=(filename, display_value, f"{info['confidence']:.0%}"),
            tags=('mismatch',) if info['mismatch'] else (),
        )

    tk.Button(window, text="閉じる", command=window.destroy,
              font=(UI_FONT, get_ui_font_size(9))).pack(pady=(0, 10))

    fit_window_to_content(window, min_width=500, min_height=450)
    window.grab_set()
    window.wait_window()
