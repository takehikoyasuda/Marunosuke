#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
id_area_config_gui.py — 学籍番号欄の位置を、初回のみ検出/設定させるダイアログ。

答案画像全体から、桁ごとに独立して印刷された赤枠を自動検出し、結果をプレビュー
表示して教員に確認させる（四隅コーナーマーカーの割合計算には一切依存しない）。
自動検出に失敗した場合のみ、教員が画像上で1桁ずつ枠をドラッグして手動指定する
（記述式採点の採点範囲指定と同じドラッグ選択パターンを流用）。

位置が確定したマス（自動検出成功時、または手動指定が全桁完了した時）は、クリックで
「数字マス／英字マス」を切り替えられる。学籍番号中の英字は位置は固定でも文字自体
(A〜Z)は事前に分からないことが多いため、位置だけ教員が指定し、その位置は
digit_ocr_recognizer.LocalDigitOcrRecognizer の英字専用モデルで認識する
(main_src/id_area_config.py の alpha_positions 参照)。
"""

import logging
import tkinter as tk
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageTk

from constants import get_ui_font_family, get_ui_font_size
from id_area_color_detector import detect_red_digit_boxes
from image_alignment import imread_unicode

logger = logging.getLogger(__name__)

UI_FONT = get_ui_font_family()

MAX_DISPLAY_WIDTH = 600
MAX_DISPLAY_HEIGHT = 750
MIN_DRAG_SIZE = 6  # 表示座標でこの値未満のドラッグは無視する


class IdAreaConfigDialog:
    """学籍番号欄の位置(自動検出結果、または手動指定)を確定させるモーダルダイアログ。"""

    def __init__(self, parent, first_image_path: str, default_digit_count: int = 8):
        self.parent = parent
        self._result: Optional[Dict] = None
        self._photo_ref = None
        self._default_digit_count = default_digit_count

        bgr = imread_unicode(first_image_path)
        if bgr is None:
            raise ValueError(f"サンプル画像を読み込めませんでした: {first_image_path}")
        self._bgr_image = bgr
        self._img_h, self._img_w = bgr.shape[:2]

        with Image.open(first_image_path) as img:
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
            text="学籍番号の桁ごとに印刷された\n赤枠を自動検出します（桁数も自動判定）",
            justify=tk.LEFT, font=(UI_FONT, get_ui_font_size(10), "bold"),
        ).pack(pady=(0, 4), anchor=tk.W)

        alpha_hint_frame = tk.Frame(
            form_frame, bg="#FFF3CD", highlightbackground="#F0AD4E", highlightthickness=1,
        )
        alpha_hint_frame.pack(pady=(0, 12), anchor=tk.W, fill=tk.X)
        tk.Label(
            alpha_hint_frame,
            text="💡 マスをクリックすると「英字マス」に\n　　切り替えられます",
            justify=tk.LEFT, bg="#FFF3CD", fg="#8A6D00",
            font=(UI_FONT, get_ui_font_size(9), "bold"), wraplength=210,
        ).pack(padx=6, pady=(6, 2), anchor=tk.W)
        tk.Label(
            alpha_hint_frame,
            text="（未指定なら全桁を数字として認識）",
            justify=tk.LEFT, bg="#FFF3CD", fg="#8A6D00",
            font=(UI_FONT, get_ui_font_size(8)), wraplength=210,
        ).pack(padx=6, pady=(0, 6), anchor=tk.W)

        digit_row = tk.Frame(form_frame)
        digit_row.pack(fill=tk.X, pady=3)
        tk.Label(digit_row, text="桁数", width=9, anchor=tk.W, font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT)
        self._digit_var = tk.StringVar(value="")
        tk.Entry(digit_row, textvariable=self._digit_var, width=8, justify=tk.RIGHT).pack(side=tk.LEFT)
        tk.Label(
            form_frame, text="空欄なら検出数をそのまま桁数にします\n"
                             "（分かっている桁数と違う時だけ入力）",
            justify=tk.LEFT, fg="#555555", font=(UI_FONT, get_ui_font_size(8)), wraplength=210,
        ).pack(pady=(0, 4), anchor=tk.W)

        tk.Button(
            form_frame, text="🔍 自動検出を試す", command=self._run_auto_detect,
            font=(UI_FONT, get_ui_font_size(9)),
        ).pack(pady=(10, 4), anchor=tk.W)

        self._status_label = tk.Label(
            form_frame, text="", fg="#C62828", font=(UI_FONT, get_ui_font_size(8)),
            wraplength=200, justify=tk.LEFT,
        )
        self._status_label.pack(pady=(4, 0), anchor=tk.W)

        self._manual_guide_label = tk.Label(
            form_frame, text="", fg="#1565C0", font=(UI_FONT, get_ui_font_size(9), "bold"),
            wraplength=200, justify=tk.LEFT,
        )
        self._manual_guide_label.pack(pady=(10, 0), anchor=tk.W)

        self._alpha_guide_label = tk.Label(
            form_frame, text="", fg="#EF6C00", font=(UI_FONT, get_ui_font_size(9), "bold"),
            wraplength=200, justify=tk.LEFT,
        )
        self._alpha_guide_label.pack(pady=(4, 0), anchor=tk.W)

        tk.Button(
            form_frame, text="やり直す", command=self._reset_manual,
            font=(UI_FONT, get_ui_font_size(8)),
        ).pack(pady=(4, 0), anchor=tk.W)

        btn_frame = tk.Frame(form_frame)
        btn_frame.pack(pady=20, side=tk.BOTTOM)
        self._save_button = tk.Button(
            btn_frame, text="保存", command=self._on_save,
            bg="#2E7D32", fg="black", font=(UI_FONT, get_ui_font_size(10), "bold"),
            state=tk.DISABLED,
        )
        self._save_button.pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="キャンセル", command=self._on_cancel, font=(UI_FONT, get_ui_font_size(9))).pack(
            side=tk.LEFT, padx=5
        )

        # 検出結果 / 手動指定の状態
        self._auto_detected = False
        self._manual_mode = False
        self._manual_rects: List[Tuple[int, int, int, int]] = []  # 元画像座標系(絶対px)
        # 位置が確定したマス（自動検出成功時、または手動指定が全桁完了した時のみ設定）
        self._final_rects: Optional[List[Tuple[int, int, int, int]]] = None
        self._alpha_positions: set = set()  # 英字マスとして指定した0-indexedの桁位置
        self._drag_state = {"active": False, "start_x": 0, "start_y": 0, "rect_id": None}

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        self._run_auto_detect()
        self.window.grab_set()

    def run(self) -> Optional[Dict]:
        """モーダル表示し、閉じられたら結果(保存された設定 or None)を返す。"""
        self.window.wait_window()
        return self._result

    # ------------------------------------------------------------

    def _parse_digit_count(self) -> Optional[int]:
        """桁数欄をパースする。手動指定モード(ドラッグ・保存)では桁数が必須。"""
        try:
            count = int(self._digit_var.get().strip())
        except ValueError:
            self._status_label.config(text="「桁数」に整数を入力してください。")
            return None
        if count < 1:
            self._status_label.config(text="桁数は1以上にしてください。")
            return None
        return count

    def _parse_expected_digit_count(self) -> Tuple[bool, Optional[int]]:
        """桁数欄をパースする。空欄は「検出数をそのまま桁数にする(自動決定)」を意味する。

        Returns:
            (成功したか, 桁数 or None(=自動決定))。失敗時はステータスラベルにエラー表示。
        """
        text = self._digit_var.get().strip()
        if not text:
            return True, None
        try:
            count = int(text)
        except ValueError:
            self._status_label.config(text="「桁数」に整数を入力するか、空欄のままにしてください。")
            return False, None
        if count < 1:
            self._status_label.config(text="桁数は1以上にしてください。")
            return False, None
        return True, count

    def _clear_overlay(self):
        self.canvas.delete("id_box_preview")

    def _draw_rect_overlay(self, rects, color):
        for (x0, y0, x1, y1) in rects:
            dx0, dy0 = x0 * self._display_ratio, y0 * self._display_ratio
            dx1, dy1 = x1 * self._display_ratio, y1 * self._display_ratio
            self.canvas.create_rectangle(dx0, dy0, dx1, dy1, outline=color, width=2, tag="id_box_preview")

    def _run_auto_detect(self):
        ok, expected_count = self._parse_expected_digit_count()
        if not ok:
            return

        self._manual_mode = False
        self._manual_rects = []
        self._auto_detected = False
        self._final_rects = None
        self._alpha_positions = set()
        self._clear_overlay()
        self._manual_guide_label.config(text="")
        self._alpha_guide_label.config(text="")
        self._save_button.config(state=tk.DISABLED)

        try:
            rects = detect_red_digit_boxes(self._bgr_image, expected_count)
        except ValueError as e:
            logger.info("学籍番号欄の自動検出に失敗: %s", e)
            self._status_label.config(
                text=f"自動検出できませんでした（{e}）。\n"
                     f"右の画像上で、1桁ずつ枠をドラッグして指定してください。"
            )
            self._start_manual_mode(expected_count)
            return

        self._auto_detected = True
        self._status_label.config(text="")
        self._final_rects = list(rects)
        self._digit_var.set(str(len(rects)))  # 検出数をそのまま桁数として欄に反映
        self._redraw_final_overlay()
        self._manual_guide_label.config(text=f"検出成功: {len(rects)}個のマスが見つかりました。")
        self._save_button.config(state=tk.NORMAL)

    def _start_manual_mode(self, digit_count: Optional[int]):
        self._manual_mode = True
        if digit_count is None:
            # 桁数が未確定(自動検出も0件)のため、手動指定にはデフォルト値を仮入力する
            if not self._digit_var.get().strip():
                self._digit_var.set(str(self._default_digit_count))
            ok, digit_count = self._parse_expected_digit_count()
            if not ok or digit_count is None:
                return
        self._update_manual_guide(digit_count)

    def _update_manual_guide(self, digit_count: int):
        done = len(self._manual_rects)
        if done < digit_count:
            self._manual_guide_label.config(
                text=f"{done + 1}桁目の枠をドラッグしてください（{done}/{digit_count}個 完了）"
            )
            self._save_button.config(state=tk.DISABLED)
        else:
            self._manual_guide_label.config(text=f"{digit_count}個すべて指定しました。保存できます。")
            self._save_button.config(state=tk.NORMAL)

    def _reset_manual(self):
        self._manual_rects = []
        self._final_rects = None
        self._alpha_positions = set()
        self._clear_overlay()
        self._alpha_guide_label.config(text="")
        digit_count = self._parse_digit_count()
        if self._manual_mode and digit_count is not None:
            self._update_manual_guide(digit_count)
        else:
            self._save_button.config(state=tk.DISABLED)

    # ------------------------------------------------------------
    # ドラッグ矩形選択（descriptive_gui.py の採点範囲指定と同じ実装パターン）。
    # マス位置が確定済み(self._final_rects設定後)は、ドラッグではなく単純クリックで
    # 英字/数字マスのトグルとして扱う。

    def _on_press(self, event):
        self._drag_state["active"] = True
        self._drag_state["start_x"] = event.x
        self._drag_state["start_y"] = event.y
        if self._drag_state.get("rect_id"):
            self.canvas.delete(self._drag_state["rect_id"])
        self._drag_state["rect_id"] = None

    def _on_drag(self, event):
        if not self._drag_state["active"]:
            return
        if self._final_rects is not None or not self._manual_mode:
            return  # 確定済み、または手動指定モードでない間はドラッグでの新規矩形描画はしない
        ex = max(0, min(self._display_w, event.x))
        ey = max(0, min(self._display_h, event.y))
        if self._drag_state["rect_id"]:
            self.canvas.coords(
                self._drag_state["rect_id"],
                self._drag_state["start_x"], self._drag_state["start_y"], ex, ey,
            )
        else:
            self._drag_state["rect_id"] = self.canvas.create_rectangle(
                self._drag_state["start_x"], self._drag_state["start_y"], ex, ey,
                outline="#1565C0", width=2, dash=(4, 2),
            )

    def _on_release(self, event):
        if not self._drag_state["active"]:
            return
        self._drag_state["active"] = False

        ex = max(0, min(self._display_w, event.x))
        ey = max(0, min(self._display_h, event.y))
        sx, sy = self._drag_state["start_x"], self._drag_state["start_y"]
        # is_click: ほぼ動かず離した(トグル対象) / too_small: 矩形として小さすぎる(いずれかの軸)
        is_click = abs(ex - sx) < MIN_DRAG_SIZE and abs(ey - sy) < MIN_DRAG_SIZE
        too_small = abs(ex - sx) < MIN_DRAG_SIZE or abs(ey - sy) < MIN_DRAG_SIZE

        if self._final_rects is not None:
            if self._drag_state.get("rect_id"):
                self.canvas.delete(self._drag_state["rect_id"])
            if is_click:
                self._toggle_alpha_at(ex, ey)
            return

        if not self._manual_mode:
            if self._drag_state.get("rect_id"):
                self.canvas.delete(self._drag_state["rect_id"])
            return

        digit_count = self._parse_digit_count()
        if digit_count is None or len(self._manual_rects) >= digit_count or too_small:
            if self._drag_state.get("rect_id"):
                self.canvas.delete(self._drag_state["rect_id"])
            return

        x0 = round(min(sx, ex) / self._display_ratio)
        y0 = round(min(sy, ey) / self._display_ratio)
        x1 = round(max(sx, ex) / self._display_ratio)
        y1 = round(max(sy, ey) / self._display_ratio)
        self._manual_rects.append((x0, y0, x1, y1))

        if self._drag_state.get("rect_id"):
            self.canvas.delete(self._drag_state["rect_id"])
        self._draw_rect_overlay([(x0, y0, x1, y1)], "#1565C0")
        self._update_manual_guide(digit_count)

        if len(self._manual_rects) == digit_count:
            self._final_rects = list(self._manual_rects)
            self._redraw_final_overlay()

    def _toggle_alpha_at(self, display_x: float, display_y: float):
        """確定済みマスをクリックした位置に応じて英字/数字マスをトグルする。"""
        if not self._final_rects:
            return
        img_x = display_x / self._display_ratio
        img_y = display_y / self._display_ratio
        for i, (x0, y0, x1, y1) in enumerate(self._final_rects):
            if x0 <= img_x <= x1 and y0 <= img_y <= y1:
                if i in self._alpha_positions:
                    self._alpha_positions.discard(i)
                else:
                    self._alpha_positions.add(i)
                self._redraw_final_overlay()
                return

    def _redraw_final_overlay(self):
        """確定済みマスを描き直す。

        色(緑/橙)だけでは区別しにくいとの指摘を踏まえ、線種(実線/破線)と
        マス内のテキストラベル(「数」/「英」+桁番号)でも英字/数字を明示する。
        """
        if not self._final_rects:
            return
        self._clear_overlay()
        for i, rect in enumerate(self._final_rects):
            is_alpha = i in self._alpha_positions
            color = "#EF6C00" if is_alpha else "#2E7D32"
            x0, y0, x1, y1 = rect
            dx0, dy0 = x0 * self._display_ratio, y0 * self._display_ratio
            dx1, dy1 = x1 * self._display_ratio, y1 * self._display_ratio
            rect_kwargs = {"outline": color, "width": 3, "tag": "id_box_preview"}
            if is_alpha:
                rect_kwargs["dash"] = (5, 3)
            self.canvas.create_rectangle(dx0, dy0, dx1, dy1, **rect_kwargs)
            label_text = f"{i + 1}:A" if is_alpha else f"{i + 1}:数"

            # ラベルは枠の内側左上に描くと記入済みの数字を隠してしまうため、
            # 枠の上に描く。枠がキャンバス上端に近すぎて収まらない場合のみ
            # 従来通り枠内側にフォールバックする。
            label_gap = 4
            label_y = dy0 - label_gap
            font_size_px = get_ui_font_size(8) + 4  # ラベル高さの概算
            if label_y - font_size_px < 0:
                label_anchor, label_y = "n", dy0 + 2
            else:
                label_anchor = "s"

            self.canvas.create_text(
                dx0, label_y, text=label_text, fill=color, anchor=label_anchor,
                font=(UI_FONT, get_ui_font_size(8), "bold"), tag="id_box_preview",
            )
        if self._alpha_positions:
            pos_str = "、".join(str(i + 1) for i in sorted(self._alpha_positions))
            self._alpha_guide_label.config(text=f"英字マスに指定: {pos_str}桁目")
        else:
            self._alpha_guide_label.config(text="")

    # ------------------------------------------------------------

    def _on_save(self):
        digit_count = self._parse_digit_count()
        if digit_count is None:
            return

        config: Dict = {"digit_count": digit_count}

        if self._manual_mode:
            if len(self._manual_rects) != digit_count:
                self._status_label.config(
                    text=f"あと{digit_count - len(self._manual_rects)}個、マスを指定してください。"
                )
                return
            config["manual_digit_rects_frac"] = [
                [x0 / self._img_w, y0 / self._img_h, (x1 - x0) / self._img_w, (y1 - y0) / self._img_h]
                for (x0, y0, x1, y1) in self._manual_rects
            ]
        elif not self._auto_detected:
            self._status_label.config(text="先に自動検出を実行してください。")
            return

        if self._alpha_positions:
            config["alpha_positions"] = sorted(self._alpha_positions)

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
