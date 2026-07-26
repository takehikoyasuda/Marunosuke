#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
id_area_config_gui.py — 学籍番号欄の位置設定を、初回のみ入力させるダイアログ。

答案用紙に印字された「学籍番号欄の位置(割合)」の数値を教員がそのまま入力し、
入力するたびに計算結果の矩形を画像上にオーバーレイ表示することで、
打ち間違いに気付けるようにする。ドラッグでの矩形選択は行わない
(用紙自体に位置情報が印字されている前提のため)。
"""

import logging
import tkinter as tk
from tkinter import messagebox
from typing import Dict, Optional

from PIL import Image, ImageTk

from constants import get_ui_font_family, get_ui_font_size
from id_area_config import compute_id_box_rect

logger = logging.getLogger(__name__)

UI_FONT = get_ui_font_family()

MAX_DISPLAY_WIDTH = 500
MAX_DISPLAY_HEIGHT = 700

FIELD_LABELS = [
    ("left_frac", "左 (%)"),
    ("top_frac", "上 (%)"),
    ("width_frac", "幅 (%)"),
    ("height_frac", "高さ (%)"),
]


class IdAreaConfigDialog:
    """学籍番号欄の位置(割合)＋桁数を入力させるモーダルダイアログ。"""

    def __init__(self, parent, first_image_path: str, default_digit_count: int = 8):
        self.parent = parent
        self._result: Optional[Dict] = None
        self._photo_ref = None

        with Image.open(first_image_path) as img:
            self._img_w, self._img_h = img.size
            display_img = img.convert("RGB").copy()

        ratio = min(MAX_DISPLAY_WIDTH / self._img_w, MAX_DISPLAY_HEIGHT / self._img_h, 1.0)
        self._display_ratio = ratio
        self._display_w = max(1, int(self._img_w * ratio))
        self._display_h = max(1, int(self._img_h * ratio))
        display_img = display_img.resize((self._display_w, self._display_h), Image.LANCZOS)

        self.window = tk.Toplevel(parent)
        self.window.title("学籍番号欄の位置設定（初回のみ）")
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)

        main_frame = tk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True)

        canvas_frame = tk.Frame(main_frame)
        canvas_frame.pack(side=tk.LEFT, padx=8, pady=8)
        self.canvas = tk.Canvas(canvas_frame, width=self._display_w, height=self._display_h, bg="white")
        self.canvas.pack()
        self._photo_ref = ImageTk.PhotoImage(display_img, master=self.window)
        self.canvas.create_image(0, 0, image=self._photo_ref, anchor=tk.NW)

        form_frame = tk.Frame(main_frame)
        form_frame.pack(side=tk.RIGHT, padx=10, pady=10, fill=tk.Y)

        tk.Label(
            form_frame,
            text="答案用紙に印字された\n学籍番号欄の位置(割合)を\nそのまま入力してください",
            justify=tk.LEFT, font=(UI_FONT, get_ui_font_size(10), "bold"),
        ).pack(pady=(0, 12), anchor=tk.W)

        self._vars: Dict[str, tk.StringVar] = {}
        for key, label in FIELD_LABELS:
            row = tk.Frame(form_frame)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=label, width=9, anchor=tk.W, font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT)
            var = tk.StringVar()
            var.trace_add("write", lambda *_args: self._update_preview())
            entry = tk.Entry(row, textvariable=var, width=8, justify=tk.RIGHT)
            entry.pack(side=tk.LEFT)
            self._vars[key] = var

        digit_row = tk.Frame(form_frame)
        digit_row.pack(fill=tk.X, pady=(14, 3))
        tk.Label(digit_row, text="桁数", width=9, anchor=tk.W, font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT)
        self._digit_var = tk.StringVar(value=str(default_digit_count))
        tk.Entry(digit_row, textvariable=self._digit_var, width=8, justify=tk.RIGHT).pack(side=tk.LEFT)

        self._status_label = tk.Label(
            form_frame, text="", fg="#C62828", font=(UI_FONT, get_ui_font_size(8)), wraplength=160, justify=tk.LEFT,
        )
        self._status_label.pack(pady=(8, 0), anchor=tk.W)

        btn_frame = tk.Frame(form_frame)
        btn_frame.pack(pady=20)
        tk.Button(
            btn_frame, text="保存", command=self._on_save,
            bg="#2E7D32", fg="white", font=(UI_FONT, get_ui_font_size(10), "bold"),
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="キャンセル", command=self._on_cancel, font=(UI_FONT, get_ui_font_size(9))).pack(
            side=tk.LEFT, padx=5
        )

        self._update_preview()
        self.window.grab_set()

    def run(self) -> Optional[Dict]:
        """モーダル表示し、閉じられたら結果(保存された設定 or None)を返す。"""
        self.window.wait_window()
        return self._result

    # ------------------------------------------------------------

    def _parse_config(self, show_error: bool) -> Optional[Dict]:
        config: Dict = {}
        for key, label in FIELD_LABELS:
            raw = self._vars[key].get().strip()
            try:
                config[key] = float(raw) / 100.0
            except ValueError:
                if show_error:
                    self._status_label.config(text=f"「{label}」に数値を入力してください。")
                return None
        try:
            config["digit_count"] = int(self._digit_var.get().strip())
        except ValueError:
            if show_error:
                self._status_label.config(text="「桁数」に整数を入力してください。")
            return None
        if config["digit_count"] < 1:
            if show_error:
                self._status_label.config(text="桁数は1以上にしてください。")
            return None
        self._status_label.config(text="")
        return config

    def _update_preview(self):
        self.canvas.delete("id_box_preview")
        config = self._parse_config(show_error=False)
        if config is None:
            return
        try:
            left, top, right, bottom = compute_id_box_rect(self._img_w, self._img_h, config)
        except Exception as e:
            logger.debug("プレビュー計算エラー: %s", e)
            return
        dl, dt = left * self._display_ratio, top * self._display_ratio
        dr, db = right * self._display_ratio, bottom * self._display_ratio
        self.canvas.create_rectangle(dl, dt, dr, db, outline="red", width=2, tag="id_box_preview")

    def _on_save(self):
        config = self._parse_config(show_error=True)
        if config is None:
            return
        self._result = config
        self._close()

    def _on_cancel(self):
        self._result = None
        self._close()

    def _close(self):
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()
