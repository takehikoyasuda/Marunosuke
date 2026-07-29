#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_components.py — サブウィンドウGUIコンポーネント

記述式採点アプリケーションで使用するサブウィンドウクラスを定義する。

  - RenderingSettingsGUI:    採点結果描画の詳細設定
"""

# 標準ライブラリ
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# サードパーティライブラリ
import tkinter as tk
from tkinter import messagebox, ttk
import cv2
import numpy as np
from PIL import Image, ImageTk

# 共通定数・ユーティリティ（constants.pyから）
from constants import (
    MODE_MARK_ONLY, MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY,
    get_ui_font_family, get_ui_font_size, fit_window_to_content,
)

# 日本語UIフォント（Windows: Yu Gothic UI, Mac: Hiragino Sans）
UI_FONT = get_ui_font_family()


class RenderingSettingsGUI:
    """採点結果描画の詳細設定ウィンドウ。

    描画位置のオフセットや表示項目（○×、得点、観点）の ON/OFF、
    記述式採点の透過率などをカスタマイズする。
    ウィンドウを閉じると on_apply コールバックで設定を返す。
    """

    def __init__(self, parent_window, current_settings, on_apply,
                 image_folder="", coord_excel_path="", template_path="",
                 mark2_result_path="", skip_questions="4", app_mode=None):
        """
        Args:
            parent_window: 親ウィンドウ (tk.Tk or tk.Toplevel)
            current_settings: 現在の設定辞書 (DEFAULT_RENDERING_SETTINGS 形式)
            on_apply: 適用時に呼ばれるコールバック (dict -> None)
            image_folder: 画像フォルダパス（位置プレビュー用）
            coord_excel_path: 座標Excelパス（位置プレビュー用）
            template_path: テンプレートパス（位置プレビュー用）
            mark2_result_path: Mark2結果パス（位置プレビュー用）
            skip_questions: スキップ問題数
            app_mode: アプリモード (MODE_MARK_ONLY / MODE_MARK_AND_DESCRIPTIVE / MODE_DESCRIPTIVE_ONLY)
        """
        from constants import get_rendering_settings, DEFAULT_RENDERING_SETTINGS, MODE_MARK_ONLY, MODE_DESCRIPTIVE_ONLY, MODE_MARK_AND_DESCRIPTIVE

        self.parent = parent_window
        self.on_apply = on_apply
        self.app_mode = app_mode or MODE_MARK_AND_DESCRIPTIVE
        self._show_mark_section = self.app_mode in (MODE_MARK_ONLY, MODE_MARK_AND_DESCRIPTIVE)
        self._show_desc_section = self.app_mode in (MODE_DESCRIPTIVE_ONLY, MODE_MARK_AND_DESCRIPTIVE)
        self.image_folder = image_folder
        self.coord_excel_path = coord_excel_path
        self.template_path = template_path
        self.mark2_result_path = mark2_result_path
        try:
            self.skip_questions = int(skip_questions)
        except (ValueError, TypeError):
            self.skip_questions = 4

        # 現在の設定を取得（デフォルトとマージ済み）
        self.original_settings = get_rendering_settings(current_settings)
        self._defaults = DEFAULT_RENDERING_SETTINGS.copy()

        # ウィンドウ作成
        self.window = tk.Toplevel(parent_window)
        self.window.title("⚙ 採点結果描画 詳細設定")
        self.window.resizable(True, True)
        self.window.transient(parent_window)
        self.window.grab_set()
        self.window.focus_set()
        self.window.configure(bg="#F5F7FA")

        # tkinter 変数
        self._create_vars()

        # UI構築
        self._create_widgets()

        # ウィンドウ閉じ処理
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # モードに応じた最小ウィンドウサイズ（実際のコンテンツがこれより大きければ広げる）
        if self._show_mark_section and self._show_desc_section:
            fit_window_to_content(self.window, min_width=480, min_height=520)
        else:
            fit_window_to_content(self.window, min_width=480, min_height=320)

    # ─────────────────────────────────────────────
    # 変数初期化
    # ─────────────────────────────────────────────

    def _create_vars(self):
        """チェックボックス・スライダー用の tkinter 変数を初期化"""
        s = self.original_settings
        self.var_show_correct = tk.BooleanVar(value=s['show_correct_answer'])
        self.var_show_ox = tk.BooleanVar(value=s['show_ox_mark'])
        self.var_show_score = tk.BooleanVar(value=s['show_score'])
        self.var_show_aspect = tk.BooleanVar(value=s['show_aspect'])
        self.var_show_star = tk.BooleanVar(value=s['show_all_correct_star'])
        self.var_bg_white = tk.BooleanVar(value=s['mark_result_bg_white'])
        self.var_offset = tk.DoubleVar(value=float(s['mark_result_offset']))
        self.var_desc_opacity = tk.DoubleVar(value=s['descriptive_opacity'])
        self.var_desc_show_mark = tk.BooleanVar(value=s['descriptive_show_mark'])
        self.var_desc_show_score = tk.BooleanVar(value=s['descriptive_show_score'])
        self.var_desc_show_aspect = tk.BooleanVar(value=s['descriptive_show_aspect'])
        self.var_desc_show_comment = tk.BooleanVar(value=s['descriptive_show_comment'])

    # ─────────────────────────────────────────────
    # UI 構築
    # ─────────────────────────────────────────────

    def _create_widgets(self):
        BG = "#F5F7FA"
        SEC_BG = "#FFFFFF"
        FONT = (UI_FONT, get_ui_font_size(9))
        FONT_B = (UI_FONT, get_ui_font_size(9), "bold")
        FONT_S = (UI_FONT, get_ui_font_size(8))
        HEADER_FG = "#546E7A"

        main = tk.Frame(self.window, bg=BG, padx=12, pady=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ===== セクション2: 記述式採点結果 =====
        sec2 = tk.LabelFrame(main, text="記述式採点結果", font=FONT_B,
                             bg=SEC_BG, fg=HEADER_FG, padx=10, pady=8)
        if self._show_desc_section:
            sec2.pack(fill=tk.X, pady=(0, 8))

        # --- 透過率 ---
        opa_frame = tk.Frame(sec2, bg=SEC_BG)
        opa_frame.pack(fill=tk.X)

        tk.Label(opa_frame, text="透過率:", font=FONT, bg=SEC_BG, fg="#333").pack(side=tk.LEFT)
        self._opacity_value_label = tk.Label(opa_frame, text="", font=FONT_S,
                                             bg=SEC_BG, fg="#1976D2")
        self._opacity_value_label.pack(side=tk.RIGHT)

        self._opacity_scale = tk.Scale(
            sec2, from_=0.0, to=1.0, resolution=0.05,
            orient=tk.HORIZONTAL, variable=self.var_desc_opacity,
            font=FONT_S, bg=SEC_BG, highlightthickness=0,
            showvalue=False, length=300,
            command=self._update_opacity_label,
        )
        self._opacity_scale.pack(fill=tk.X, padx=(15, 0))
        self._update_opacity_label()

        # --- 表示項目 ---
        tk.Frame(sec2, bg="#E0E0E0", height=1).pack(fill=tk.X, pady=(5, 5))
        tk.Label(sec2, text="表示項目:", font=FONT, bg=SEC_BG, fg="#333").pack(anchor=tk.W)

        desc_chk_frame = tk.Frame(sec2, bg=SEC_BG)
        desc_chk_frame.pack(fill=tk.X, padx=(15, 0), pady=(2, 0))

        for text, var in [
            ("○×△マークを表示", self.var_desc_show_mark),
            ("得点を表示", self.var_desc_show_score),
            ("生徒向けコメントを表示", self.var_desc_show_comment),
        ]:
            tk.Checkbutton(desc_chk_frame, text=text, variable=var,
                           font=FONT_S, bg=SEC_BG, anchor=tk.W,
                           cursor="hand2").pack(fill=tk.X)

        # ===== ボタン行 =====
        btn_frame = tk.Frame(main, bg=BG)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        tk.Button(btn_frame, text="デフォルトに戻す", font=FONT_S,
                  command=self._reset_to_defaults,
                  relief=tk.FLAT, bg="#EEEEEE", cursor="hand2").pack(side=tk.LEFT)

        tk.Button(btn_frame, text="キャンセル", font=FONT,
                  command=self._on_cancel,
                  relief=tk.FLAT, bg="#EEEEEE", cursor="hand2",
                  width=10).pack(side=tk.RIGHT, padx=(5, 0))

        tk.Button(btn_frame, text="適用", font=(UI_FONT, get_ui_font_size(9), "bold"),
                  command=self._on_apply,
                  relief=tk.FLAT, bg="#A5D6A7", cursor="hand2",
                  width=10).pack(side=tk.RIGHT)

    # ─────────────────────────────────────────────
    # コールバック
    # ─────────────────────────────────────────────

    def _update_opacity_label(self, *_args):
        """透過率ラベルを更新"""
        val = self.var_desc_opacity.get()
        self._opacity_value_label.config(text=f"{val:.0%}")

    def _reset_to_defaults(self):
        """デフォルト値に戻す"""
        d = self._defaults
        self.var_show_correct.set(d['show_correct_answer'])
        self.var_show_ox.set(d['show_ox_mark'])
        self.var_show_score.set(d['show_score'])
        self.var_show_aspect.set(d['show_aspect'])
        self.var_show_star.set(d['show_all_correct_star'])
        self.var_bg_white.set(d['mark_result_bg_white'])
        self.var_offset.set(d['mark_result_offset'])
        self.var_desc_opacity.set(d['descriptive_opacity'])
        self.var_desc_show_mark.set(d['descriptive_show_mark'])
        self.var_desc_show_score.set(d['descriptive_show_score'])
        self.var_desc_show_aspect.set(d['descriptive_show_aspect'])
        self.var_desc_show_comment.set(d['descriptive_show_comment'])

    def _collect_settings(self):
        """現在のGUI状態から設定辞書を作成"""
        return {
            'show_correct_answer': self.var_show_correct.get(),
            'show_ox_mark': self.var_show_ox.get(),
            'show_score': self.var_show_score.get(),
            'show_aspect': self.var_show_aspect.get(),
            'show_all_correct_star': self.var_show_star.get(),
            'mark_result_bg_white': self.var_bg_white.get(),
            'mark_result_offset': self.var_offset.get(),
            'descriptive_opacity': self.var_desc_opacity.get(),
            'descriptive_show_mark': self.var_desc_show_mark.get(),
            'descriptive_show_score': self.var_desc_show_score.get(),
            'descriptive_show_aspect': False,
            'descriptive_show_comment': self.var_desc_show_comment.get(),
        }

    def _on_apply(self):
        """適用ボタン — コールバックを呼んで閉じる"""
        settings = self._collect_settings()
        if self.on_apply:
            self.on_apply(settings)
        self.window.grab_release()
        self.window.destroy()

    def _on_cancel(self):
        """キャンセル — 変更せずに閉じる"""
        self.window.grab_release()
        self.window.destroy()
