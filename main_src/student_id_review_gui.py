#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
student_id_review_gui.py — 学籍番号OCR候補の確認・修正画面。

student_id_ocr.py が生成したOCR候補（{ファイル名: {'thumbnail_path','text',
'confidence','per_digit'}}）を、教員が答案画像を見ながら確認・修正するための
モーダル画面。main_src/gui_components.py の MarkCheckerGUI（OMRの未マーク/
ダブルマークを画像を見ながら確認する画面）と同じ設計思想を踏襲する:

    - デフォルトはグリッド一覧（サムネイル＋OCR候補を並べて一覧表示）
    - 確信度が低いカードは枠を目立たせる
    - カードをクリックすると単体表示に切り替わり、Entry で修正できる
    - クリックしなかったカードは OCR 候補をそのまま採用する

MarkCheckerGUI が独立ツール(fire-and-forget)として動くのに対し、この画面は
name_trimmer.select_region_on_image() と同様に「モーダルで開いて、閉じたら
結果を返す」同期的な使い方をする(run() が最終結果を返す)。
"""

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Dict, List, Optional

from PIL import Image, ImageTk

from constants import get_ui_font_family, get_ui_font_size, fit_window_to_content

logger = logging.getLogger(__name__)

UI_FONT = get_ui_font_family()

LOW_CONFIDENCE_THRESHOLD = 0.80

GRID_THUMB_WIDTH = 140
GRID_COLUMNS = 4

SINGLE_THUMB_WIDTH = 420


class StudentIdReviewGUI:
    """学籍番号OCR候補の確認・修正画面。"""

    def __init__(self, parent, ocr_results: Dict[str, Dict], roster: Optional[Dict[str, str]] = None):
        self.parent = parent
        self.roster = roster or {}
        self._photo_refs = []  # ImageTk.PhotoImage の参照保持(GC対策)

        self._filenames: List[str] = sorted(ocr_results.keys())
        # 確認前の候補をそのままコピーして「確定値」の初期状態とする
        self.confirmed: Dict[str, Dict] = {}
        for filename, info in ocr_results.items():
            name = self.roster.get((info.get('text') or '').strip()) if self.roster else None
            self.confirmed[filename] = {
                'thumbnail_path': info.get('thumbnail_path'),
                'text': info.get('text') or '',
                'confidence': info.get('confidence', 0.0),
                'name': name,
                'edited': False,
            }

        self._current_index = 0

        self.window = tk.Toplevel(parent)
        self.window.title("学籍番号OCR候補の確認")
        self.window.geometry("900x650")
        self.window.protocol("WM_DELETE_WINDOW", self._finish)

        self._grid_frame = tk.Frame(self.window)
        self._single_frame = tk.Frame(self.window)

        self._build_grid_view()
        self._grid_frame.pack(fill=tk.BOTH, expand=True)
        fit_window_to_content(self.window, min_width=640, min_height=480)

        self.window.grab_set()

    def run(self) -> Dict[str, Dict]:
        """モーダル表示し、閉じられたら確定結果を返す。"""
        self.window.wait_window()
        return self.confirmed

    # ------------------------------------------------------------
    # グリッド一覧
    # ------------------------------------------------------------

    def _build_grid_view(self):
        for child in self._grid_frame.winfo_children():
            child.destroy()

        header = tk.Frame(self._grid_frame, bg="#37474F")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="学籍番号OCR候補の確認 — おかしいものだけクリックして修正してください",
            font=(UI_FONT, get_ui_font_size(11), 'bold'), bg="#37474F", fg="white",
        ).pack(side=tk.LEFT, padx=10, pady=8)
        tk.Button(
            header, text="完了", command=self._finish,
            bg="#2E7D32", fg="black", font=(UI_FONT, get_ui_font_size(10), 'bold'),
        ).pack(side=tk.RIGHT, padx=10, pady=6)

        canvas = tk.Canvas(self._grid_frame, bg="#ECEFF1", highlightthickness=0)
        scrollbar = tk.Scrollbar(self._grid_frame, orient=tk.VERTICAL, command=canvas.yview)
        inner = tk.Frame(canvas, bg="#ECEFF1")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        for i, filename in enumerate(self._filenames):
            row, col = divmod(i, GRID_COLUMNS)
            self._create_grid_card(inner, filename, row, col)

    def _create_grid_card(self, parent, filename, row, col):
        info = self.confirmed[filename]
        confidence = info.get('confidence', 0.0)
        edited = info.get('edited', False)

        if edited:
            border_color = '#81C784'  # 緑: 修正済み
        elif confidence < LOW_CONFIDENCE_THRESHOLD:
            border_color = '#EF5350'  # 赤: 要確認
        else:
            border_color = '#E0E0E0'  # グレー: 通常

        card = tk.Frame(parent, bg=border_color, padx=2, pady=2)
        card.grid(row=row, column=col, padx=6, pady=6, sticky='nsew')
        parent.columnconfigure(col, weight=1)

        inner = tk.Frame(card, bg='white')
        inner.pack(fill=tk.BOTH, expand=True)

        photo = self._load_photo(info.get('thumbnail_path'), GRID_THUMB_WIDTH)
        if photo:
            img_label = tk.Label(inner, image=photo, bg='white')
        else:
            img_label = tk.Label(inner, text="(画像なし)", bg='white', fg='gray')
        img_label.pack(padx=2, pady=2)

        name_text = info.get('name')
        if self.roster and not name_text:
            name_text = "名簿に一致なし"
        display_text = info.get('text') or "(空欄)"
        if name_text:
            display_text += f"\n{name_text}"

        info_label = tk.Label(
            inner, text=display_text, font=(UI_FONT, get_ui_font_size(9)),
            bg='white', fg='#333', justify=tk.CENTER,
        )
        info_label.pack(padx=2, pady=(0, 4))

        def on_click(event, target=filename):
            self._switch_to_single(target)
        for widget in (card, inner, img_label, info_label):
            widget.bind("<Button-1>", on_click)
            widget.configure(cursor='hand2')

    # ------------------------------------------------------------
    # 単体表示（修正画面）
    # ------------------------------------------------------------

    def _switch_to_single(self, filename):
        self._current_index = self._filenames.index(filename)
        self._grid_frame.pack_forget()
        self._build_single_view()
        self._single_frame.pack(fill=tk.BOTH, expand=True)

    def _build_single_view(self):
        for child in self._single_frame.winfo_children():
            child.destroy()

        filename = self._filenames[self._current_index]
        info = self.confirmed[filename]

        header = tk.Frame(self._single_frame, bg="#37474F")
        header.pack(fill=tk.X)
        tk.Label(
            header, text=f"{filename}  ({self._current_index + 1}/{len(self._filenames)})",
            font=(UI_FONT, get_ui_font_size(11), 'bold'), bg="#37474F", fg="white",
        ).pack(side=tk.LEFT, padx=10, pady=8)
        tk.Button(
            header, text="一覧に戻る", command=self._back_to_grid,
            bg="#546E7A", fg="black", font=(UI_FONT, get_ui_font_size(9)),
        ).pack(side=tk.RIGHT, padx=10, pady=6)

        photo = self._load_photo(info.get('thumbnail_path'), SINGLE_THUMB_WIDTH)
        img_label = tk.Label(self._single_frame, image=photo, bg='white', relief=tk.SUNKEN)
        img_label.pack(padx=20, pady=20)

        input_frame = tk.Frame(self._single_frame)
        input_frame.pack(pady=10)
        tk.Label(input_frame, text="学籍番号:", font=(UI_FONT, get_ui_font_size(10))).pack(side=tk.LEFT)
        entry = tk.Entry(input_frame, font=(UI_FONT, get_ui_font_size(12)), width=16, justify=tk.CENTER)
        entry.insert(0, info.get('text') or '')
        entry.pack(side=tk.LEFT, padx=8)
        entry.focus_set()
        entry.selection_range(0, tk.END)
        self._current_entry = entry

        self._match_label = tk.Label(self._single_frame, text='', font=(UI_FONT, get_ui_font_size(10)), fg='#1565C0')
        self._match_label.pack(pady=(0, 10))
        self._update_match_label(entry.get())
        entry.bind('<KeyRelease>', lambda e: self._update_match_label(entry.get()))
        entry.bind('<Return>', lambda e: self._confirm_and_next())

        nav_frame = tk.Frame(self._single_frame)
        nav_frame.pack(pady=10)
        tk.Button(nav_frame, text="◀ 前へ", command=self._go_previous,
                  font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text="確定 (Enter)", command=self._confirm_and_next,
                  bg="#2E7D32", fg="black", font=(UI_FONT, get_ui_font_size(10), 'bold')).pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text="次へ ▶", command=self._go_next,
                  font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT, padx=5)

    def _update_match_label(self, text):
        text = text.strip()
        name = self.roster.get(text) if self.roster else None
        if not self.roster:
            self._match_label.config(text='')
        elif name:
            self._match_label.config(text=f"名簿照合: {name}", fg='#1565C0')
        else:
            self._match_label.config(text="名簿に一致する学籍番号がありません", fg='#C62828')

    def _confirm_current(self):
        filename = self._filenames[self._current_index]
        info = self.confirmed[filename]
        new_text = self._current_entry.get().strip()
        name = self.roster.get(new_text) if self.roster else None
        info['edited'] = info['edited'] or (new_text != (info.get('text') or ''))
        info['text'] = new_text
        info['name'] = name

    def _confirm_and_next(self):
        self._confirm_current()
        self._go_next()

    def _go_next(self):
        self._confirm_current_silent_if_unsaved()
        if self._current_index < len(self._filenames) - 1:
            self._current_index += 1
            self._build_single_view()
        else:
            self._back_to_grid()

    def _go_previous(self):
        self._confirm_current_silent_if_unsaved()
        if self._current_index > 0:
            self._current_index -= 1
            self._build_single_view()

    def _confirm_current_silent_if_unsaved(self):
        """前へ/次へ移動時、Entryの内容を確定してから移動する。"""
        self._confirm_current()

    def _back_to_grid(self):
        self._confirm_current()
        self._single_frame.pack_forget()
        self._build_grid_view()
        self._grid_frame.pack(fill=tk.BOTH, expand=True)

    def _finish(self):
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    # ------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------

    def _load_photo(self, path, max_width):
        if not path or not Path(path).exists():
            return None
        try:
            with Image.open(path) as img:
                w, h = img.size
                if w > max_width:
                    ratio = max_width / w
                    img = img.resize((max_width, max(1, int(h * ratio))), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img, master=self.window)
        except Exception as e:
            logger.warning("画像の読み込みに失敗しました: %s — %s", path, e)
            return None
        self._photo_refs.append(photo)
        return photo
