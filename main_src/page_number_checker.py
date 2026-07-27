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
from typing import Dict, Optional, Tuple

import cv2
from PIL import Image, ImageTk

from constants import get_ui_font_family, get_ui_font_size, fit_window_to_content
from digit_ocr_recognizer import LocalDigitOcrRecognizer
from name_trimmer import get_image_files
from omr_engine import imread_unicode

logger = logging.getLogger(__name__)

UI_FONT = get_ui_font_family()

# ズーム対応の矩形選択ダイアログ用の定数
VIEWPORT_WIDTH = 700
VIEWPORT_HEIGHT = 700
MIN_ZOOM = 1.0
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25


def _select_region_with_zoom(
    image_path: str,
    parent: Optional[tk.Tk] = None,
    title: str = "エリアの選択 — ドラッグで矩形を描いてください",
    label_text: str = "選択エリア",
    instruction_text: str = "",
) -> Optional[Tuple[int, int, int, int]]:
    """マウスホイール／＋－ボタンで拡大縮小できる矩形選択ダイアログ。

    name_trimmer.select_region_on_image と同じ「モーダルで開いて矩形を返す」
    様式だが、対象（印刷されたページ番号の数字）が小さく、拡大しないと
    精密な選択が難しいため、ズーム機能を追加した専用版。
    氏名欄トリミングで使われている select_region_on_image 自体は変更しない。

    Returns:
        (left, top, right, bottom) の元画像実寸座標。キャンセル時は None。
    """
    original_img = Image.open(image_path).convert("RGB")
    orig_w, orig_h = original_img.size

    # zoom=1.0 のとき画像全体がビューポートに収まる基準スケール
    base_scale = min(VIEWPORT_WIDTH / orig_w, VIEWPORT_HEIGHT / orig_h, 1.0)

    state = {
        'zoom': 1.0,
        'rect_orig': None,   # 確定済み矩形（元画像実寸座標）
        'drag_id': None,     # ドラッグ中の仮矩形のcanvas item id
        'start_x': 0.0, 'start_y': 0.0,
        'photo': None,       # PhotoImage参照保持(GC対策)
        'overlay_photo': None,
    }

    owns_root = False
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        owns_root = True
    else:
        root = parent

    win = tk.Toplevel(root)
    win.title(title)

    main_frame = tk.Frame(win)
    main_frame.pack(fill=tk.BOTH, expand=True)

    canvas_frame = tk.Frame(main_frame)
    canvas_frame.pack(side=tk.LEFT, padx=5, pady=5)

    button_frame = tk.Frame(main_frame)
    button_frame.pack(side=tk.RIGHT, padx=10, pady=10, fill=tk.Y)

    h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
    v_scroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
    canvas = tk.Canvas(
        canvas_frame, width=VIEWPORT_WIDTH, height=VIEWPORT_HEIGHT, bg="black",
        highlightthickness=0, xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set,
    )
    h_scroll.config(command=canvas.xview)
    v_scroll.config(command=canvas.yview)
    canvas.grid(row=0, column=0)
    v_scroll.grid(row=0, column=1, sticky='ns')
    h_scroll.grid(row=1, column=0, sticky='ew')

    def _total_scale():
        return base_scale * state['zoom']

    def _redraw_confirmed_rect():
        canvas.delete("region_overlay")
        canvas.delete("region_rect")
        canvas.delete("region_label")
        if state['rect_orig'] is None:
            return
        scale = _total_scale()
        ox1, oy1, ox2, oy2 = state['rect_orig']
        x1, y1, x2, y2 = ox1 * scale, oy1 * scale, ox2 * scale, oy2 * scale
        overlay_img = Image.new('RGBA', (max(1, round(x2 - x1)), max(1, round(y2 - y1))), (0, 200, 0, 80))
        overlay_tk = ImageTk.PhotoImage(overlay_img, master=win)
        state['overlay_photo'] = overlay_tk
        canvas.create_image(x1, y1, image=overlay_tk, anchor='nw', tag="region_overlay")
        canvas.create_rectangle(x1, y1, x2, y2, outline="green", width=2, tag="region_rect")
        canvas.create_text(
            (x1 + x2) / 2, (y1 + y2) / 2, text=label_text, fill="white",
            font=("", 14, "bold"), tag="region_label",
        )

    def _redraw_image():
        scale = _total_scale()
        disp_w = max(1, round(orig_w * scale))
        disp_h = max(1, round(orig_h * scale))
        resized = original_img.resize((disp_w, disp_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(resized, master=win)
        state['photo'] = photo
        canvas.delete("bg_image")
        canvas.create_image(0, 0, image=photo, anchor=tk.NW, tag="bg_image")
        canvas.tag_lower("bg_image")
        canvas.configure(scrollregion=(0, 0, disp_w, disp_h))
        _zoom_label.config(text=f"{state['zoom'] * 100:.0f}%")
        _redraw_confirmed_rect()

    def _on_press(event):
        state['start_x'] = canvas.canvasx(event.x)
        state['start_y'] = canvas.canvasy(event.y)
        if state['drag_id'] is not None:
            canvas.delete(state['drag_id'])
            state['drag_id'] = None
        canvas.delete("region_overlay")
        canvas.delete("region_rect")
        canvas.delete("region_label")

    def _on_drag(event):
        cx = canvas.canvasx(event.x)
        cy = canvas.canvasy(event.y)
        if state['drag_id'] is not None:
            canvas.coords(state['drag_id'], state['start_x'], state['start_y'], cx, cy)
        else:
            state['drag_id'] = canvas.create_rectangle(
                state['start_x'], state['start_y'], cx, cy,
                outline="red", width=2, dash=(4, 4),
            )

    def _on_release(event):
        cx = canvas.canvasx(event.x)
        cy = canvas.canvasy(event.y)
        sx, sy = state['start_x'], state['start_y']

        if abs(cx - sx) < 5 or abs(cy - sy) < 5:
            return

        x1, x2 = min(sx, cx), max(sx, cx)
        y1, y2 = min(sy, cy), max(sy, cy)

        if state['drag_id'] is not None:
            canvas.delete(state['drag_id'])
            state['drag_id'] = None

        scale = _total_scale()
        state['rect_orig'] = (x1 / scale, y1 / scale, x2 / scale, y2 / scale)
        _redraw_confirmed_rect()

    canvas.bind("<ButtonPress-1>", _on_press)
    canvas.bind("<B1-Motion>", _on_drag)
    canvas.bind("<ButtonRelease-1>", _on_release)

    def _zoom(factor):
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, state['zoom'] * factor))
        if new_zoom == state['zoom']:
            return
        state['zoom'] = new_zoom
        _redraw_image()

    def _on_mousewheel(event):
        _zoom(ZOOM_STEP if event.delta > 0 else 1 / ZOOM_STEP)

    canvas.bind("<MouseWheel>", _on_mousewheel)

    # --- 説明・ズーム操作 ---
    tk.Label(button_frame, text="操作方法", font=("", 12, "bold")).pack(pady=(0, 10))
    tk.Label(
        button_frame, text=instruction_text, justify=tk.LEFT, wraplength=160,
    ).pack(pady=(0, 15))

    zoom_group = tk.Frame(button_frame)
    zoom_group.pack(pady=(0, 20))
    tk.Label(zoom_group, text="拡大縮小（マウスホイールでも可）", font=("", 9), wraplength=160, justify=tk.LEFT).pack()
    zoom_btns = tk.Frame(zoom_group)
    zoom_btns.pack(pady=5)
    tk.Button(zoom_btns, text="－", width=3, command=lambda: _zoom(1 / ZOOM_STEP)).pack(side=tk.LEFT, padx=2)
    _zoom_label = tk.Label(zoom_btns, text="100%", width=6)
    _zoom_label.pack(side=tk.LEFT, padx=4)
    tk.Button(zoom_btns, text="＋", width=3, command=lambda: _zoom(ZOOM_STEP)).pack(side=tk.LEFT, padx=2)

    # --- 決定・キャンセル ---
    def _confirm():
        if state['rect_orig'] is None:
            messagebox.showwarning(
                "未選択", "エリアが選択されていません。\n画像上でドラッグしてください。", parent=win,
            )
            return
        win.destroy()

    def _cancel():
        state['rect_orig'] = None
        win.destroy()

    tk.Button(
        button_frame, text="✔ 決定", command=_confirm, width=15, height=2,
        bg="#4CAF50", fg="black", font=("", 11, "bold"),
    ).pack(pady=5)
    tk.Button(button_frame, text="✖ キャンセル", command=_cancel, width=15, height=2).pack(pady=5)

    win.protocol("WM_DELETE_WINDOW", _cancel)

    _redraw_image()

    win.grab_set()
    win.wait_window()

    if owns_root:
        root.destroy()

    if state['rect_orig'] is None:
        return None
    return tuple(round(v) for v in state['rect_orig'])


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

    rect = _select_region_with_zoom(
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
