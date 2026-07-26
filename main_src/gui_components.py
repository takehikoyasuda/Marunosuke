#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_components.py — サブウィンドウGUIコンポーネント

Mark2統合アプリケーションで使用するサブウィンドウクラスを定義する。
saitensamurai.py から抽出された以下のクラスを含む:

  - MarkCheckerGUI:          マークエラーチェックGUI (Section 7)
  - StudentAnswerSheetViewer: 個別生徒の答案ビューア (Section 7.4)
  - ThresholdCalibratorGUI:  閾値キャリブレーションGUI (Section 7.5)
  - RenderingSettingsGUI:    採点結果描画の詳細設定
  - StartupModeDialog:       v4.0 起動モード選択ダイアログ
"""

# 標準ライブラリ
import json
import logging
import re
import sys
import shutil
import threading
from collections import OrderedDict
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# サードパーティライブラリ
import tkinter as tk
from tkinter import messagebox, ttk
import cv2
import pandas as pd
import numpy as np
from PIL import Image, ImageTk

# 共通定数・ユーティリティ（constants.pyから）
from constants import (
    ERROR_TYPE_NO_MARK, ERROR_TYPE_DOUBLE_MARK, ERROR_TYPE_INVALID,
    DEFAULT_CORRECTION, DEFAULT_SCALE_FACTOR,
    DEFAULT_EXPAND_FACTOR, DEFAULT_EXPAND_FACTOR_Y,
    DEFAULT_BACKUP_FOLDER,
    MARK2_BASE_WIDTH, MARK2_BASE_HEIGHT,
    WHITENESS_CACHE_FILE,
    MODE_MARK_ONLY, MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY,
    MARK_FORMAT_STANDARD, MARK_FORMAT_MULTI_DIGIT,
    get_ui_font_family, get_ui_font_size,
)

# 日本語UIフォント（Windows: Yu Gothic UI, Mac: Hiragino Sans）
UI_FONT = get_ui_font_family()

# Checker機能（mark_checker.pyから）
from mark_checker import (
    apply_corrections_checker,
    detect_errors_checker,
    detect_all_entries_checker,
    load_errors_checker,
    save_errors_checker,
    load_coordinates_csv_checker,
    get_display_image_checker,
    fit_image_to_display,
    pil_to_imagetk_checker,
    CorrectedImageCache,
    _load_and_correct_image,
    crop_from_corrected_image,
)

# 閾値キャリブレーション（threshold_calibrator.pyから）
from threshold_calibrator import (
    collect_mark_fill_ratios,
    run_threshold_calibration,
    reclassify_with_threshold,
    recollect_and_reclassify,
)


# ========================================
# セクション7: MarkCheckerGUIクラス
# ========================================

class MarkCheckerGUI:
    """マークエラーチェックGUIクラス"""
    def __init__(self, parent_window, image_folder, coords_csv_path, xlsx_path, skip_questions=0, template_path=None,
                 mark_format=MARK_FORMAT_STANDARD):
        self._original_stdout_ref = None  # stdout復帰用（SaitenSamuraiGUIから設定される）
        
        self.window = tk.Toplevel(parent_window)
        self.window.title("マークエラーチェック")
        self.window.geometry("1200x750")
        
        # ウィンドウを最前面に表示し、モーダルにする
        self.window.transient(parent_window)  # 親ウィンドウの前面に表示
        self.window.grab_set()  # モーダル化（親ウィンドウへの操作をブロック）
        self.window.focus_set()  # フォーカスをセット
        
        self.error_df = None
        self.coords_df = None
        self._all_entries_df = None
        self.current_index = 0
        self.photo_image = None
        self._bbox_map = {}
        
        # v4.5 高速化: 補正済み画像キャッシュ
        self._image_cache = CorrectedImageCache(max_size=32)
        # v3.9 高速化: 遅延CSV保存（ダーティフラグ）
        self._csv_dirty = False
        self._save_interval = 5  # N件ごとに保存
        self._unsaved_count = 0
        
        self.image_folder = Path(image_folder)
        self.coords_csv_path = Path(coords_csv_path)
        self.xlsx_path = Path(xlsx_path)
        self.skip_questions = skip_questions
        self.template_path = template_path
        self.mark_format = mark_format  # v4.7: 複数桁設問モード対応
        self.error_csv_path = self.xlsx_path.parent / "tmp_checking_dm_nm.csv"

        # v4.5 安定化: グリッド描画のページング
        self._grid_page_size = 100  # 1ページ上限（安定性重視）
        self._grid_current_page = 0
        self._grid_filtered_indices = []
        self._grid_render_job = None
        self._grid_resize_after = None
        self._grid_size_after = None

        # v4.5 選択肢カテゴリ用タブ: 薄い解答 / 濃い解答
        self._choice_tab_active = False  # タブモードが有効か
        self._choice_tab_current = "薄い"  # 現在のタブ: "薄い" or "濃い"

        # v4.5 安定化: サムネイル画像キャッシュ（PIL）
        self._thumb_cache = OrderedDict()
        self._thumb_cache_max = 200
        
        # 正答データ（マークチェック時の正答枠表示用）
        self._answer_key = self._load_answer_key()
        
        self.create_widgets()
        
        # ウィンドウが閉じられたときの処理
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # データの読み込みはウィンドウ表示後に行う（ダイアログが出るため）
        self.window.after(100, self.load_data)

    def _get_registered_questions(self):
        """テンプレートから採点対象の問題番号セットを取得する。
        
        template_pathが設定されていない場合はNoneを返し、全問チェックとなる。
        """
        if self.template_path is None:
            return None
        try:
            from scoring_engine import load_template
            template_dict = load_template(self.template_path, mark_format=self.mark_format)
            # 複数桁グループは先頭行のみがキーのため、グループ全行に展開する
            # (2行目以降の無マーク・ダブルマークもチェック対象に含める)
            questions = set()
            for q_no, data in template_dict.items():
                span = data.get('span', 1)
                questions.update(range(q_no, q_no + span))
            return questions
        except Exception as e:
            logger.warning("テンプレート読み込みエラー（全問チェックにフォールバック）: %s", e)
            return None

    def _load_answer_key(self):
        """テンプレートから正答データを読み込む。
        
        Returns:
            {question_no: {'正答': str, ...}} または空辞書
        """
        if not self.template_path:
            return {}
        try:
            from scoring_engine import load_template
            return load_template(self.template_path, mark_format=self.mark_format)
        except Exception as e:
            logger.warning("正答データ読み込みエラー: %s", e)
            return {}

    def _draw_answer_overlay(self, pil_img, filename, question_no):
        """正答の選択肢に赤色点線枠を描画する。
        
        mark_coords から該当選択肢の座標を取得し、
        crop_from_corrected_image と同じ座標変換を再現して描画する。
        
        Args:
            pil_img: 表示用にクロップ・拡大済みの PIL.Image
            filename: 画像ファイル名
            question_no: エラーDFの問題番号（skip後の番号）
        
        Returns:
            オーバーレイ描画済みの PIL.Image
        """
        if not self._answer_key:
            return pil_img

        if question_no in self._answer_key:
            entry = self._answer_key[question_no]
            correct_answer_str = entry['正答']
            if self.mark_format == MARK_FORMAT_MULTI_DIGIT:
                # グループ先頭行: 正答の1文字目がこの行の正答記号
                correct_answer_str = str(correct_answer_str)[:1]
        elif self.mark_format == MARK_FORMAT_MULTI_DIGIT:
            # 複数桁グループの2行目以降: question_no を含むグループを検索し、
            # 該当行の正答記号(1文字)を取り出す
            correct_answer_str = None
            for q_start, entry in self._answer_key.items():
                span = entry.get('span', 1)
                if q_start < question_no < q_start + span:
                    offset = question_no - q_start
                    ans = str(entry['正答'])
                    if offset < len(ans):
                        correct_answer_str = ans[offset]
                    break
            if not correct_answer_str:
                return pil_img
        else:
            return pil_img

        # 座標CSVは元の問題番号（skip込み）で記録されている
        original_q_no = question_no + self.skip_questions
        if self.coords_df is None:
            return pil_img

        row = self.coords_df[
            (self.coords_df['image_path'] == filename) &
            (self.coords_df['question_no'] == original_q_no)
        ]
        if row.empty:
            return pil_img

        # mark_coords をパース: choice0_x;y;w;h|choice1_x;y;w;h|...
        mark_coords_str = row.iloc[0].get('mark_coords', '')
        if pd.isna(mark_coords_str) or not mark_coords_str:
            return pil_img

        parts = str(mark_coords_str).split('|')
        # 正答の値→マーク位置の解決は共通ヘルパーに委譲
        # (選択肢"0"=10番目の位置、レガシー"10"表記も同じルールで扱う。
        #  複数桁モードでは -,0..9,a-d の並びで解決する)
        from scoring_engine import choice_to_position_index
        target_index = choice_to_position_index(correct_answer_str, len(parts), self.mark_format)
        if target_index is None:
            return pil_img

        choice_str = parts[target_index]
        try:
            mx, my, mw, mh = map(int, choice_str.split(';'))
        except (ValueError, IndexError):
            return pil_img
        
        # choices_bbox（クロップ元領域）をパース
        bbox_str = row.iloc[0]['choices_bbox']
        try:
            bx, by, bw, bh = map(int, bbox_str.split(';'))
        except (ValueError, IndexError):
            return pil_img
        
        # キャッシュから補正済み画像のサイズを取得
        corrected_img = self._image_cache.get(filename) if self._image_cache else None
        if corrected_img is None:
            img_path = self.image_folder / filename
            if img_path.exists():
                corrected_img = _load_and_correct_image(img_path)
            if corrected_img is None:
                return pil_img
        
        img_h, img_w = corrected_img.shape[:2]
        res_scale_x = img_w / MARK2_BASE_WIDTH
        res_scale_y = img_h / MARK2_BASE_HEIGHT
        
        # crop_from_corrected_image の座標変換を再現
        sx = int(bx * res_scale_x)
        sy = int(by * res_scale_y)
        sw = int(bw * res_scale_x)
        sh = int(bh * res_scale_y)
        
        center_x = sx + sw / 2
        center_y = sy + sh / 2
        expanded_w = sw * DEFAULT_EXPAND_FACTOR
        expanded_h = sh * DEFAULT_EXPAND_FACTOR * DEFAULT_EXPAND_FACTOR_Y
        crop_x = center_x - expanded_w / 2
        crop_y = center_y - expanded_h / 2
        
        crop_x = max(0, min(int(crop_x), img_w - 1))
        crop_y = max(0, min(int(crop_y), img_h - 1))
        expanded_w = min(int(expanded_w), img_w - crop_x)
        expanded_h = min(int(expanded_h), img_h - crop_y)
        
        # マーク座標をクロップ＋拡大後の画像座標に変換
        smx = mx * res_scale_x
        smy = my * res_scale_y
        smw = mw * res_scale_x
        smh = mh * res_scale_y
        
        draw_x = (smx - crop_x) * DEFAULT_SCALE_FACTOR
        draw_y = (smy - crop_y) * DEFAULT_SCALE_FACTOR
        draw_w = smw * DEFAULT_SCALE_FACTOR
        draw_h = smh * DEFAULT_SCALE_FACTOR
        
        # 赤色点線矩形を描画
        from PIL import ImageDraw
        draw = ImageDraw.Draw(pil_img)
        self._draw_dashed_rect(
            draw,
            int(draw_x), int(draw_y),
            int(draw_x + draw_w), int(draw_y + draw_h),
            color='red', dash=(6, 4), width=2,
        )
        return pil_img

    @staticmethod
    def _draw_dashed_rect(draw, x0, y0, x1, y1, color='red', dash=(6, 4), width=2):
        """PIL ImageDraw で点線矩形を描画する。"""
        import math
        lines = [(x0, y0, x1, y0), (x1, y0, x1, y1),
                 (x1, y1, x0, y1), (x0, y1, x0, y0)]
        for lx0, ly0, lx1, ly1 in lines:
            dx = lx1 - lx0
            dy = ly1 - ly0
            length = math.sqrt(dx * dx + dy * dy)
            if length == 0:
                continue
            ux, uy = dx / length, dy / length
            pos = 0.0
            drawing = True
            while pos < length:
                seg = dash[0] if drawing else dash[1]
                end_pos = min(pos + seg, length)
                if drawing:
                    sx = lx0 + ux * pos
                    sy = ly0 + uy * pos
                    ex = lx0 + ux * end_pos
                    ey = ly0 + uy * end_pos
                    draw.line([(sx, sy), (ex, ey)], fill=color, width=width)
                pos = end_pos
                drawing = not drawing

    def on_close(self):
        """ウィンドウが閉じられるときの処理"""
        # 「xlsxに反映」していない訂正が残っている場合は確認する
        # (訂正はCSVに保存されるため失われないが、反映せずにStep2採点を
        #  実行すると訂正前のデータで採点されてしまうため)
        try:
            pending = self._count_pending_corrections()
            if pending > 0:
                if not messagebox.askyesno(
                    "確認",
                    f"「xlsxに反映」していない訂正が {pending}件 あります。\n\n"
                    "反映せずに閉じると、採点(Step2)には訂正が反映されません。\n"
                    "（訂正内容は保存されており、次回チェッカーを開くと復元されます）\n\n"
                    "このまま閉じますか？",
                    parent=self.window,
                ):
                    return
        except Exception:
            pass
        self._cancel_grid_render()
        if self._grid_resize_after is not None:
            try:
                self.window.after_cancel(self._grid_resize_after)
            except Exception:
                pass
            self._grid_resize_after = None
        if self._grid_size_after is not None:
            try:
                self.window.after_cancel(self._grid_size_after)
            except Exception:
                pass
            self._grid_size_after = None
        # v3.9 高速化: 未保存のCSV変更をフラッシュ
        try:
            self._flush_csv()
        except Exception:
            pass
        # v3.9 高速化: キャッシュ解放
        self._image_cache.clear()
        self._thumb_cache.clear()
        self._grid_photo_refs.clear()
        # sys.stdoutが差し替えられていた場合、元に戻す
        try:
            if self._original_stdout_ref is not None:
                sys.stdout = self._original_stdout_ref
        except Exception:
            pass
        self.window.grab_release()
        self.window.destroy()
    
    def create_widgets(self):
        """ウィジェット作成"""
        file_info_frame = tk.Frame(self.window, bg='#e8f4f8', padx=10, pady=8, relief=tk.RIDGE, bd=2)
        file_info_frame.pack(fill=tk.X)
        
        tk.Label(file_info_frame, text="【入力ファイル情報】", font=('Arial', 10, 'bold'), bg='#e8f4f8').pack(anchor=tk.W)
        
        self.file_info_text = tk.Text(file_info_frame, height=4, font=('Consolas', 8), bg='#f5f5f5', relief=tk.FLAT, wrap=tk.NONE)
        self.file_info_text.pack(fill=tk.X, pady=(5, 0))
        self.file_info_text.config(state=tk.DISABLED)
        
        status_frame = tk.Frame(self.window, bg='lightblue', padx=10, pady=10)
        status_frame.pack(fill=tk.X)
        
        self.status_label = tk.Label(status_frame, text="読み込み中...", font=('Arial', 12, 'bold'), bg='lightblue')
        self.status_label.pack(side=tk.LEFT, expand=True)

        # ====== メインコンテンツ: 左サイドパネル + 右コンテンツ ======
        self._main_content = tk.Frame(self.window)
        self._main_content.pack(fill=tk.BOTH, expand=True)

        # --- 左サイドパネル ---
        self._side_panel = tk.Frame(self._main_content, bg='#F5F7FA', width=200)
        self._side_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0), pady=8)
        self._side_panel.pack_propagate(False)

        tk.Label(self._side_panel, text="カテゴリ", font=(UI_FONT, get_ui_font_size(12), 'bold'),
                 bg='#F5F7FA').pack(pady=(0, 5))

        # カテゴリリストボックス
        self._category_listbox = tk.Listbox(
            self._side_panel, font=(UI_FONT, get_ui_font_size(11)), activestyle='none',
            selectbackground='#42A5F5', selectforeground='white',
        )
        self._category_listbox.pack(fill=tk.BOTH, expand=True)
        self._category_listbox.bind('<<ListboxSelect>>', self._on_category_selected)

        # 並び順
        sort_frame = tk.Frame(self._side_panel, bg='#F5F7FA')
        sort_frame.pack(fill=tk.X, pady=(5, 0))
        tk.Label(sort_frame, text="並び順:", bg='#F5F7FA',
                 font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT)
        self._sort_var = tk.StringVar(value="白さ順（白い順）")
        self._sort_combo = ttk.Combobox(
            sort_frame, textvariable=self._sort_var,
            values=["画像名順", "白さ順（白い順）"],
            state='readonly', width=15,
        )
        self._sort_combo.pack(side=tk.LEFT, padx=3)
        self._sort_combo.bind('<<ComboboxSelected>>', lambda e: self._refresh_grid_view(reset_page=True))

        # 統計ラベル
        self._stats_label = tk.Label(self._side_panel, text="",
                                      bg='#F5F7FA', font=(UI_FONT, get_ui_font_size(9)),
                                      fg='#555', justify=tk.LEFT)
        self._stats_label.pack(fill=tk.X, pady=(5, 0))

        # 一括無効回答ボタン
        self._btn_batch_minus1 = tk.Button(
            self._side_panel, text="ノーマーク全件 → 無効回答(-1)",
            command=self._batch_set_minus1,
            bg='#FFCDD2', fg='#333', font=(UI_FONT, get_ui_font_size(9), 'bold'),
            relief=tk.FLAT, cursor='hand2',
        )
        # 初期状態では非表示（ノーマークカテゴリ選択時のみ表示）

        # xlsx 反映ボタン
        self._btn_apply = tk.Button(
            self._side_panel, text="データの更新(再読み込み)",
            command=self.apply_to_xlsx,
            bg='#2E7D32', fg='black', font=(UI_FONT, get_ui_font_size(10), 'bold'),
            relief=tk.FLAT, cursor='hand2',
        )
        self._btn_apply.pack(fill=tk.X, pady=(3, 0))

        # --- 右コンテンツエリア ---
        self._content_area = tk.Frame(self._main_content, bg='#FAFAFA')
        self._content_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8)

        # ====== グリッド表示フレーム (デフォルト) ======
        self._view_mode = "grid"
        self._grid_view_frame = tk.Frame(self._content_area)
        self._grid_photo_refs = []
        self._grid_thumb_size = 160
        self._grid_cols = 6
        self._build_grid_view()
        self._grid_view_frame.pack(fill=tk.BOTH, expand=True)

        # ====== 単体表示フレーム ======
        self._single_view_frame = tk.Frame(self._content_area)
        self._build_single_view()

        # 白さキャッシュ
        self._whiteness_cache = {}

    def _build_single_view(self):
        """単体表示フレームの内部ウィジェットを構築する"""
        display_frame = tk.Frame(self._single_view_frame, padx=10, pady=10)
        display_frame.pack(fill=tk.BOTH, expand=True)

        info_frame = tk.Frame(display_frame)
        info_frame.pack(fill=tk.X, pady=(0, 10))

        self.info_label = tk.Label(info_frame, text="ファイル: --- / 問題番号: --- / カテゴリ: ---",
                                    font=('Arial', 10))
        self.info_label.pack()

        self.image_label = tk.Label(display_frame, bg='white', relief=tk.SUNKEN)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        self.image_label.config(width=1100)

        control_frame = tk.Frame(self._single_view_frame, padx=10, pady=10)
        control_frame.pack(fill=tk.X)

        result_frame = tk.Frame(control_frame)
        result_frame.pack(pady=(0, 10))

        tk.Label(result_frame, text="読み取り結果:", font=('Arial', 10)).pack(side=tk.LEFT, padx=(0, 10))
        self.before_label = tk.Label(result_frame, text="---", font=('Arial', 12, 'bold'), fg='red')
        self.before_label.pack(side=tk.LEFT)

        # --- 選択肢ボタン行（動的に生成） ---
        self._choice_btn_frame = tk.Frame(control_frame)
        self._choice_btn_frame.pack(pady=(0, 5))
        self._choice_buttons = []
        self._max_choices = 10
        self._build_choice_buttons(self._max_choices)

        input_frame = tk.Frame(control_frame)
        input_frame.pack(pady=(0, 10))

        tk.Label(input_frame, text="修正:", font=('Arial', 9), fg='gray').pack(side=tk.LEFT, padx=(0, 5))
        self.correction_entry = tk.Entry(input_frame, font=('Arial', 10), width=6, fg='#555')
        self.correction_entry.pack(side=tk.LEFT, padx=(0, 5))
        self.correction_entry.bind('<Return>', lambda e: self._save_single_and_back())

        self._hint_label = tk.Label(input_frame, text="(1-10, -1=無効回答 / Enterで保存)",
                                     font=('Arial', 8), fg='#999')
        self._hint_label.pack(side=tk.LEFT)

        # ナビゲーション: グリッドに戻るボタンのみ
        nav_frame = tk.Frame(control_frame)
        nav_frame.pack(pady=(0, 10))

        self._btn_save_back = tk.Button(
            nav_frame, text="保存してグリッドに戻る",
            command=self._save_single_and_back,
            bg='#4CAF50', fg='black', font=('Arial', 10, 'bold'), width=22,
        )
        self._btn_save_back.pack(side=tk.LEFT, padx=5)

        self._btn_cancel_back = tk.Button(
            nav_frame, text="キャンセル（グリッドに戻る）",
            command=self._switch_to_grid,
            bg='#78909C', fg='black', font=('Arial', 10), width=22,
        )
        self._btn_cancel_back.pack(side=tk.LEFT, padx=5)
    
    def _build_grid_view(self):
        """グリッド表示フレームの内部ウィジェットを構築する (v4.5)"""
        # ツールバー（カードサイズスライダーのみ）
        toolbar = tk.Frame(self._grid_view_frame, bg='#37474F', padx=10, pady=6)
        toolbar.pack(fill=tk.X)

        # グリッドの件数ラベル
        self._grid_count_label = tk.Label(
            toolbar, text="", font=(UI_FONT, get_ui_font_size(9)), bg='#37474F', fg='#FFD54F',
        )
        self._grid_count_label.pack(side=tk.LEFT, padx=10)

        # ページング
        self._pager_frame = tk.Frame(toolbar, bg='#37474F')
        self._pager_frame.pack(side=tk.LEFT)
        self._btn_prev_page = tk.Button(
            self._pager_frame, text="◀", width=3, command=self._prev_grid_page,
            bg='#546E7A', fg='black', relief=tk.FLAT, cursor='hand2',
        )
        self._btn_prev_page.pack(side=tk.LEFT, padx=(8, 2))
        self._page_label = tk.Label(
            self._pager_frame, text="1/1", font=(UI_FONT, get_ui_font_size(9)), bg='#37474F', fg='white',
        )
        self._page_label.pack(side=tk.LEFT, padx=2)
        self._btn_next_page = tk.Button(
            self._pager_frame, text="▶", width=3, command=self._next_grid_page,
            bg='#546E7A', fg='black', relief=tk.FLAT, cursor='hand2',
        )
        self._btn_next_page.pack(side=tk.LEFT, padx=(2, 8))

        # 選択肢カテゴリ用タブ（初期状態では非表示）
        self._tab_frame = tk.Frame(toolbar, bg='#37474F')
        self._btn_tab_light = tk.Button(
            self._tab_frame, text="薄い解答(ノーマーク疑惑)",
            command=lambda: self._switch_choice_tab("薄い"),
            bg='#42A5F5', fg='black', font=(UI_FONT, get_ui_font_size(9), 'bold'),
            relief=tk.FLAT, cursor='hand2', padx=8,
        )
        self._btn_tab_light.pack(side=tk.LEFT, padx=(8, 2))
        self._btn_tab_dark = tk.Button(
            self._tab_frame, text="濃い解答(複数マーク疑惑)",
            command=lambda: self._switch_choice_tab("濃い"),
            bg='#546E7A', fg='black', font=(UI_FONT, get_ui_font_size(9)),
            relief=tk.FLAT, cursor='hand2', padx=8,
        )
        self._btn_tab_dark.pack(side=tk.LEFT, padx=(2, 8))

        # カードサイズスライダー
        self._grid_size_var = tk.IntVar(value=self._grid_thumb_size)
        tk.Label(toolbar, text="サイズ:", font=(UI_FONT, get_ui_font_size(9)),
                 bg='#37474F', fg='white').pack(side=tk.RIGHT)
        self._grid_size_slider = tk.Scale(
            toolbar, variable=self._grid_size_var, from_=80, to=300,
            orient=tk.HORIZONTAL, length=120, showvalue=False,
            bg='#37474F', fg='white', highlightthickness=0,
            troughcolor='#546E7A', activebackground='#90CAF9',
            command=self._on_grid_size_changed,
        )
        self._grid_size_slider.pack(side=tk.RIGHT, padx=(0, 5))

        # スクロール可能キャンバス
        canvas_frame = tk.Frame(self._grid_view_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self._grid_canvas = tk.Canvas(canvas_frame, bg='#FAFAFA', highlightthickness=0)
        self._grid_scrollbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self._grid_canvas.yview)
        self._grid_inner_frame = tk.Frame(self._grid_canvas, bg='#FAFAFA')

        self._grid_inner_frame.bind(
            "<Configure>",
            lambda e: self._grid_canvas.configure(scrollregion=self._grid_canvas.bbox("all"))
        )
        self._grid_canvas_window = self._grid_canvas.create_window((0, 0), window=self._grid_inner_frame, anchor="nw")
        self._grid_canvas.configure(yscrollcommand=self._grid_scrollbar.set)

        self._grid_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._grid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # マウスホイール
        self._grid_canvas.bind("<Enter>", lambda e: self._grid_canvas.bind_all("<MouseWheel>", self._grid_on_mousewheel))
        self._grid_canvas.bind("<Leave>", lambda e: self._grid_canvas.unbind_all("<MouseWheel>"))

        # キャンバスリサイズ
        self._grid_canvas.bind("<Configure>", self._grid_on_canvas_resize)

    def _grid_on_mousewheel(self, event):
        try:
            self._grid_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _grid_on_canvas_resize(self, event):
        try:
            self._grid_canvas.itemconfig(self._grid_canvas_window, width=event.width)
        except Exception:
            pass
        new_cols = max(1, event.width // (self._grid_thumb_size + 20))
        if new_cols != self._grid_cols:
            self._grid_cols = new_cols
            if hasattr(self, '_grid_resize_after') and self._grid_resize_after:
                self.window.after_cancel(self._grid_resize_after)
            self._grid_resize_after = self.window.after(150, self._refresh_grid_view)

    def _on_grid_size_changed(self, _value=None):
        """カードサイズスライダーの変更ハンドラ (v4.5)"""
        new_size = self._grid_size_var.get()
        if new_size == self._grid_thumb_size:
            return
        self._grid_thumb_size = new_size
        try:
            canvas_w = self._grid_canvas.winfo_width()
            if canvas_w > 1:
                self._grid_cols = max(1, canvas_w // (self._grid_thumb_size + 20))
        except Exception:
            pass
        if hasattr(self, '_grid_size_after') and self._grid_size_after:
            self.window.after_cancel(self._grid_size_after)
        self._grid_size_after = self.window.after(200, self._refresh_grid_view)

    def _thumb_cache_get(self, key):
        """サムネイルキャッシュ取得（LRU更新）"""
        if key in self._thumb_cache:
            img = self._thumb_cache.pop(key)
            self._thumb_cache[key] = img
            return img
        return None

    def _thumb_cache_put(self, key, pil_img):
        """サムネイルキャッシュ格納（LRU）"""
        if key in self._thumb_cache:
            self._thumb_cache.pop(key)
        self._thumb_cache[key] = pil_img
        while len(self._thumb_cache) > self._thumb_cache_max:
            self._thumb_cache.popitem(last=False)

    def _get_grid_thumbnail(self, filename, original_q_no, thumb_size):
        """グリッドカード用サムネイルを取得（キャッシュ優先）"""
        key = (filename, int(original_q_no), int(thumb_size))
        cached = self._thumb_cache_get(key)
        if cached is not None:
            return cached

        pil_img = get_display_image_checker(
            self.coords_df, self.image_folder, filename, original_q_no,
            scale_factor=1.0, expand_factor=DEFAULT_EXPAND_FACTOR,
            cache=self._image_cache, bbox_map=self._bbox_map,
        )
        if pil_img is None:
            return None

        pil_img.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
        self._thumb_cache_put(key, pil_img)
        return pil_img

    def _prev_grid_page(self):
        """グリッド前ページへ移動"""
        if self._grid_current_page <= 0:
            return
        self._grid_current_page -= 1
        self._refresh_grid_view(reset_page=False)

    def _next_grid_page(self):
        """グリッド次ページへ移動"""
        if not self._grid_filtered_indices:
            return
        total_items = len(self._grid_filtered_indices)
        total_pages = max(1, (total_items + self._grid_page_size - 1) // self._grid_page_size)
        if self._grid_current_page >= total_pages - 1:
            return
        self._grid_current_page += 1
        self._refresh_grid_view(reset_page=False)

    def _update_grid_pager(self, total_items):
        """ページングラベル・ボタン状態を更新"""
        total_pages = max(1, (total_items + self._grid_page_size - 1) // self._grid_page_size)
        if self._grid_current_page >= total_pages:
            self._grid_current_page = total_pages - 1
        self._page_label.config(text=f"{self._grid_current_page + 1}/{total_pages}")
        self._btn_prev_page.config(state=(tk.NORMAL if self._grid_current_page > 0 else tk.DISABLED))
        self._btn_next_page.config(state=(tk.NORMAL if self._grid_current_page < total_pages - 1 else tk.DISABLED))

    def _cancel_grid_render(self):
        """進行中の分割描画ジョブをキャンセル"""
        if self._grid_render_job is not None:
            try:
                self.window.after_cancel(self._grid_render_job)
            except Exception:
                pass
            self._grid_render_job = None

    # --------------------------------------------------
    # 選択肢カテゴリ タブ切替
    # --------------------------------------------------

    def _is_choice_category(self, cat):
        """カテゴリが選択肢カテゴリかどうかを判定"""
        return cat.startswith('選択肢 ')

    def _switch_choice_tab(self, tab):
        """選択肢カテゴリのタブを切り替える（"薄い" or "濃い"）"""
        if self._choice_tab_current == tab:
            return
        self._choice_tab_current = tab
        self._update_tab_button_styles()
        self._refresh_grid_view()

    def _update_tab_button_styles(self):
        """タブボタンのアクティブ/非アクティブスタイルを更新"""
        if self._choice_tab_current == "薄い":
            self._btn_tab_light.config(bg='#42A5F5', font=(UI_FONT, get_ui_font_size(9), 'bold'))
            self._btn_tab_dark.config(bg='#546E7A', font=(UI_FONT, get_ui_font_size(9)))
        else:
            self._btn_tab_light.config(bg='#546E7A', font=(UI_FONT, get_ui_font_size(9)))
            self._btn_tab_dark.config(bg='#42A5F5', font=(UI_FONT, get_ui_font_size(9), 'bold'))

    def _show_tab_mode(self, show):
        """タブモードの表示/非表示を切り替える"""
        if show:
            self._pager_frame.pack_forget()
            self._tab_frame.pack(side=tk.LEFT)
            self._choice_tab_active = True
        else:
            self._tab_frame.pack_forget()
            self._pager_frame.pack(side=tk.LEFT)
            self._choice_tab_active = False

    # --------------------------------------------------
    # カテゴリサイドパネル
    # --------------------------------------------------

    def _on_category_selected(self, event=None):
        """サイドパネルでカテゴリが選択されたときにグリッドを更新"""
        cat = self._get_selected_category()
        # ノーマークカテゴリ時のみ一括ボタンを表示
        if cat == 'ノーマーク':
            if self._btn_batch_minus1.winfo_manager() == '':
                self._btn_batch_minus1.pack(fill=tk.X, pady=(8, 3),
                                           before=self._btn_apply)
        else:
            self._btn_batch_minus1.pack_forget()

        # 選択肢カテゴリの場合はタブモードに切替
        if self._is_choice_category(cat):
            self._choice_tab_current = "薄い"
            self._update_tab_button_styles()
            self._show_tab_mode(True)
        else:
            self._show_tab_mode(False)

        self._refresh_grid_view(reset_page=True)

    def _get_selected_category(self):
        """サイドパネルで現在選択中のカテゴリ名を返す"""
        sel = self._category_listbox.curselection()
        if not sel:
            return "要チェック"
        text = self._category_listbox.get(sel[0])
        # "選択肢 3  (45)" → "3" のようにカウント部分を除去
        # フォーマット: "カテゴリ名  (N)" or "─── カテゴリ名  (N)"
        text = text.lstrip('─ ')
        if '(' in text:
            text = text[:text.rfind('(')].strip()
        return text

    def _rebuild_category_list(self):
        """全エントリDFからサイドパネルのカテゴリリストを再構築する（選択保持）"""
        # 現在のカテゴリ選択を記憶
        prev_category = self._get_selected_category()

        self._category_listbox.delete(0, tk.END)
        if self._all_entries_df is None or len(self._all_entries_df) == 0:
            return

        df = self._all_entries_df

        # 要チェック件数: エラー型ありかつ after が -1 でないもの
        needs_check = df[
            (df['error_type'] != '') &
            ~((df['after'] == '-1') | (df['after'] == '-1.0'))
        ]
        needs_check_count = len(needs_check)

        # 要チェック
        self._category_listbox.insert(tk.END, f"要チェック  ({needs_check_count})")
        if needs_check_count > 0:
            self._category_listbox.itemconfig(0, fg='#D32F2F')

        # 区切り + 選択肢
        choice_cats = sorted(
            [c for c in df['category'].unique()
             if c not in ('ノーマーク', '複数マーク', '不正な値', '無効回答(-1)') and c != ''],
            key=lambda x: int(x) if x.isdigit() else 9999,
        )
        self._category_listbox.insert(tk.END, "───────────")
        sep_idx = self._category_listbox.size() - 1
        self._category_listbox.itemconfig(sep_idx, fg='#999', selectbackground='#F5F7FA')

        for cat in choice_cats:
            cnt = len(df[df['category'] == cat])
            self._category_listbox.insert(tk.END, f"選択肢 {cat}  ({cnt})")

        # エラーカテゴリ
        self._category_listbox.insert(tk.END, "───────────")
        sep_idx2 = self._category_listbox.size() - 1
        self._category_listbox.itemconfig(sep_idx2, fg='#999', selectbackground='#F5F7FA')

        for cat, label, color in [
            ('ノーマーク', 'ノーマーク', '#E65100'),
            ('複数マーク', '複数マーク', '#C62828'),
            ('不正な値', '不正な値', '#78909C'),
            ('無効回答(-1)', '無効回答(-1)', '#555'),
        ]:
            cnt = len(df[df['category'] == cat])
            if cnt > 0:
                idx = self._category_listbox.size()
                self._category_listbox.insert(tk.END, f"{label}  ({cnt})")
                self._category_listbox.itemconfig(idx, fg=color)

        # 前回のカテゴリ選択を復元（見つからなければ「要チェック」へフォールバック）
        restored = False
        if prev_category:
            for i in range(self._category_listbox.size()):
                item_text = self._category_listbox.get(i)
                # 「選択肢 3  (45)」などからカテゴリ名を抽出して比較
                clean = item_text.lstrip('─ ')
                if '(' in clean:
                    clean = clean[:clean.rfind('(')].strip()
                if clean == prev_category:
                    self._category_listbox.selection_set(i)
                    restored = True
                    break
        if not restored:
            # デフォルト: 「要チェック」(インデックス0)
            self._category_listbox.selection_set(0)

    # --------------------------------------------------
    # ビュー切り替え
    # --------------------------------------------------

    def _switch_to_grid(self):
        """単体表示からグリッド表示に戻る"""
        self._view_mode = "grid"
        self.window.unbind('<Key>')
        self._single_view_frame.pack_forget()
        # _main_content の子を正しい順序で再配置（サイドパネル → コンテンツ）
        # packは追加順で配置されるため、両方を外してから再 pack する
        self._side_panel.pack_forget()
        self._content_area.pack_forget()
        self._side_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0), pady=8)
        self._content_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._grid_view_frame.pack(fill=tk.BOTH, expand=True)
        self._refresh_grid_view()

    def _switch_to_single(self, df_idx):
        """グリッドから単体表示に切り替える"""
        self._view_mode = "single"
        self.current_index = df_idx
        self._grid_view_frame.pack_forget()
        if self._side_panel.winfo_manager() != "":
            self._side_panel.pack_forget()
        self._single_view_frame.pack(fill=tk.BOTH, expand=True)
        self.window.bind('<Key>', self._on_key_press)
        self.show_current()

    def _get_filtered_indices(self):
        """サイドパネルのカテゴリ選択に基づき、all_entries_dfのインデックスを返す"""
        if self._all_entries_df is None or len(self._all_entries_df) == 0:
            return []

        df = self._all_entries_df
        cat = self._get_selected_category()

        if cat == '要チェック':
            mask = (df['error_type'] != '') & \
                   ~((df['after'] == '-1') | (df['after'] == '-1.0'))
        elif cat.startswith('選択肢 '):
            choice_val = cat.replace('選択肢 ', '')
            mask = df['category'] == choice_val
        elif cat in ('ノーマーク', '複数マーク', '不正な値', '無効回答(-1)'):
            mask = df['category'] == cat
        else:
            mask = pd.Series(True, index=df.index)

        indices = list(df[mask].index)

        # ソート: 選択肢カテゴリは常に白さ順
        if self._is_choice_category(cat):
            self._build_whiteness_cache_for_indices(indices)
            indices.sort(key=lambda i: -self._whiteness_cache.get(i, 0.0))
        else:
            sort_mode = self._sort_var.get()
            if sort_mode == "白さ順（白い順）":
                self._build_whiteness_cache_for_indices(indices)
                indices.sort(key=lambda i: -self._whiteness_cache.get(i, 0.0))
            else:
                # 画像名順: filename → question_no
                indices.sort(key=lambda i: (df.at[i, 'filename'], df.at[i, 'question_no']))

        return indices

    def _refresh_grid_view(self, reset_page=False):
        """グリッド表示を再描画する (v4.5 安定版)
        
        「準備→一括表示」方式:
        1. Canvas から inner_frame を切り離す
        2. ローディング表示を出す
        3. 全カード (最大100件) を同期的に生成
        4. inner_frame を Canvas に再配置し一括で表示
        """
        self._cancel_grid_render()
        for w in self._grid_inner_frame.winfo_children():
            w.destroy()
        self._grid_photo_refs.clear()

        indices = self._get_filtered_indices()
        self._grid_filtered_indices = indices

        cat = self._get_selected_category()
        is_choice = self._is_choice_category(cat)

        if is_choice and self._choice_tab_active:
            # --- タブモード: 選択肢カテゴリ ---
            total = len(indices)
            if total <= 200:
                half = max(1, total // 2) if total > 0 else 0
            else:
                half = 100

            if self._choice_tab_current == "濃い":
                page_indices = indices[total - half:] if total > 0 else []
                display_label = f"濃い解答: {len(page_indices)}件 / 全{total}件"
            else:
                page_indices = indices[:half] if total > 0 else []
                display_label = f"薄い解答: {len(page_indices)}件 / 全{total}件"
            self._grid_count_label.config(text=display_label)
        else:
            # --- 通常ページモード ---
            if reset_page:
                self._grid_current_page = 0
            self._update_grid_pager(len(indices))

            start = self._grid_current_page * self._grid_page_size
            end = min(start + self._grid_page_size, len(indices))
            page_indices = indices[start:end]
            self._grid_count_label.config(text=f"表示: {start + 1 if page_indices else 0}-{end} / {len(indices)}件")

        # 統計更新
        self._update_stats_label()

        if not page_indices:
            tk.Label(self._grid_inner_frame, text="該当する項目はありません",
                     font=('Arial', 14), fg='gray', bg='#FAFAFA').grid(row=0, column=0, pady=40)
            return

        # --- 一括準備モード ---
        # Canvas から inner_frame を切り離して非表示にする
        self._grid_canvas.delete(self._grid_canvas_window)

        # ローディング表示
        canvas_w = max(200, self._grid_canvas.winfo_width())
        canvas_h = max(100, self._grid_canvas.winfo_height())
        loading_id = self._grid_canvas.create_text(
            canvas_w // 2, canvas_h // 3,
            text=f"読み込み中... ({len(page_indices)}件)",
            font=(UI_FONT, get_ui_font_size(14)), fill='gray',
        )
        self._grid_canvas.update_idletasks()

        # 全カードを同期的に作成（inner_frame は Canvas 非接続のため画面に出ない）
        try:
            for pos, idx in enumerate(page_indices):
                row_i = pos // self._grid_cols
                col_i = pos % self._grid_cols
                self._create_grid_card(self._grid_inner_frame, idx, row_i, col_i)
        except Exception as e:
            logger.warning("グリッドカード生成中にエラー: %s", e)

        # ローディング表示を削除して inner_frame を再配置 → 一気に表示
        self._grid_canvas.delete(loading_id)
        self._grid_canvas_window = self._grid_canvas.create_window(
            (0, 0), window=self._grid_inner_frame, anchor="nw"
        )
        try:
            if canvas_w > 1:
                self._grid_canvas.itemconfig(self._grid_canvas_window, width=canvas_w)
        except Exception:
            pass
        self._grid_canvas.configure(scrollregion=self._grid_canvas.bbox("all"))
        self._grid_canvas.yview_moveto(0)

    def _create_grid_card(self, parent, df_idx, row, col):
        """グリッド内の1枚のカードを作成する (v4.5)"""
        thumb_size = self._grid_thumb_size

        entry = self._all_entries_df.iloc[df_idx]
        filename = entry['filename']
        question_no = int(entry['question_no'])
        category = entry['category']
        error_type = entry['error_type']
        after_val = entry.get('after', '')

        # カード枠色
        is_corrected = pd.notna(after_val) and after_val != '' and after_val != 'skip'
        if is_corrected:
            border_color = '#81C784'  # 緑 (修正済み)
        elif error_type == ERROR_TYPE_NO_MARK:
            border_color = '#FFB74D'  # オレンジ (ノーマーク)
        elif error_type == ERROR_TYPE_DOUBLE_MARK:
            border_color = '#EF5350'  # 赤 (複数マーク)
        elif error_type == ERROR_TYPE_INVALID:
            border_color = '#FF7043'  # 深オレンジ (不正)
        else:
            border_color = '#E0E0E0'  # グレー (正常)

        card = tk.Frame(parent, bg=border_color, padx=2, pady=2)
        card.grid(row=row, column=col, padx=4, pady=4, sticky='nsew')
        parent.columnconfigure(col, weight=1)

        inner = tk.Frame(card, bg='white')
        inner.pack(fill=tk.BOTH, expand=True)

        # サムネイル画像
        try:
            original_q_no = question_no + self.skip_questions
            pil_img = self._get_grid_thumbnail(filename, original_q_no, thumb_size)
            if pil_img:
                photo = ImageTk.PhotoImage(pil_img)
                self._grid_photo_refs.append(photo)
                img_label = tk.Label(inner, image=photo, bg='white', cursor='hand2')
            else:
                img_label = tk.Label(inner, text="(画像なし)", bg='white', fg='gray',
                                     width=thumb_size // 8,
                                     height=thumb_size // 16)
        except MemoryError:
            img_label = tk.Label(inner, text="(軽量表示)", bg='white', fg='gray',
                                 width=thumb_size // 8,
                                 height=thumb_size // 16)
        except Exception:
            img_label = tk.Label(inner, text="(読込失敗)", bg='white', fg='gray',
                                 width=thumb_size // 8,
                                 height=thumb_size // 16)
        img_label.pack(padx=2, pady=2)

        # 情報ラベル
        cat_short = {
            'ノーマーク': 'ノーマ', '複数マーク': '複マ', '不正な値': '不正',
            '無効回答(-1)': '-1',
        }.get(category, category)
        status_text = f"→{after_val}" if is_corrected else ""
        info_text = f"{Path(filename).stem}\nQ{question_no} [{cat_short}] {status_text}"
        info_label = tk.Label(inner, text=info_text, font=(UI_FONT, get_ui_font_size(7)),
                              bg='white', fg='#333', justify=tk.CENTER,
                              wraplength=thumb_size)
        info_label.pack(padx=2, pady=(0, 2))

        # クリック → 単体表示に切り替え（カード全体が対象）
        def on_card_click(event, target_idx=df_idx):
            self._switch_to_single(target_idx)
        for widget in (card, inner, img_label, info_label):
            widget.bind("<Button-1>", on_card_click)
            widget.configure(cursor='hand2')

    def _batch_set_minus1(self):
        """ノーマーク全件を -1 に一括設定する (v4.5)"""
        if self._all_entries_df is None:
            return
        mask = (self._all_entries_df['error_type'] == ERROR_TYPE_NO_MARK) & \
               (self._all_entries_df['after'].isna() | (self._all_entries_df['after'] == ''))
        count = mask.sum()
        if count == 0:
            messagebox.showinfo("情報", "未修正のノーマーク項目はありません", parent=self.window)
            return
        ans = messagebox.askyesno(
            "一括設定の確認",
            f"未修正のノーマーク {count}件 を全て\n「無効回答(-1)」に設定します。\n\nよろしいですか?",
            parent=self.window,
        )
        if not ans:
            return
        self._all_entries_df.loc[mask, 'after'] = '-1'
        self._csv_dirty = True
        self._flush_csv()
        self._rebuild_category_list()
        self._refresh_grid_view()
        self._update_status_label()

    def _update_status_label(self):
        """ステータスラベルを最新状態に更新する"""
        if self._all_entries_df is None or len(self._all_entries_df) == 0:
            return
        df = self._all_entries_df
        total_errors = len(df[df['error_type'] != ''])
        corrected = len(df[(df['error_type'] != '') &
                           df['after'].notna() & (df['after'] != '')])
        remaining = total_errors - corrected
        self.status_label.config(
            text=f"エラー {total_errors}件 / 修正済 {corrected}件 / 未修正 {remaining}件"
        )

    def _update_stats_label(self):
        """サイドパネルの統計ラベルを更新する"""
        if self._all_entries_df is None:
            return
        df = self._all_entries_df
        total = len(df)
        errors = len(df[df['error_type'] != ''])
        corrected = len(df[(df['error_type'] != '') &
                           df['after'].notna() & (df['after'] != '')])
        self._stats_label.config(
            text=f"全エントリ: {total}\nエラー: {errors}\n修正済: {corrected}"
        )

    def _read_whiteness_json_map(self):
        """白さキャッシュJSONを辞書として読み込む（失敗時は空辞書）。"""
        whiteness_json_path = self.coords_csv_path.parent / WHITENESS_CACHE_FILE
        if not whiteness_json_path.exists():
            return {}
        try:
            with open(whiteness_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("白さキャッシュJSON読み込みエラー: %s", e)
            return {}

    def _build_fast_review_subset(self, all_entries_df, whiteness_map, top_n=100):
        """高速レビュー用途向けにエントリを縮約する。

        - エラー（ノーマーク/複数マーク/不正値）は全件保持
        - 各選択肢カテゴリ（数字）は、白さ上位 top_n + 下位 top_n を保持
        - 白さキャッシュが無い場合は従来互換で全件保持
        """
        if all_entries_df is None or len(all_entries_df) == 0:
            return all_entries_df

        # 白さキャッシュがない環境では従来挙動を維持
        if not whiteness_map:
            return all_entries_df

        df = all_entries_df
        selected = set()

        error_mask = (
            (df['category'].isin(['ノーマーク', '複数マーク', '不正な値', '無効回答(-1)'])) |
            (df['error_type'] != '')
        )
        selected.update(df[error_mask].index.tolist())

        choice_df = df[df['category'].astype(str).str.fullmatch(r'\d+')]
        for _choice, group in choice_df.groupby('category', sort=False):
            scored = []
            for idx, row in group.iterrows():
                filename = row['filename']
                q_no_base = str(int(row['question_no']))
                q_no_orig = str(int(row['question_no']) + self.skip_questions)
                score = 0.0
                try:
                    by_file = whiteness_map.get(filename, {})
                    # 互換: 旧データ/環境差異に備えて base/orig の両方を参照
                    score = float(by_file.get(q_no_orig, by_file.get(q_no_base, 0.0)))
                except Exception:
                    score = 0.0
                scored.append((idx, score))

            scored.sort(key=lambda x: x[1], reverse=True)
            top_indices = [idx for idx, _ in scored[:top_n]]
            if len(scored) <= top_n:
                bottom_indices = [idx for idx, _ in scored]
            else:
                bottom_indices = [idx for idx, _ in scored[-top_n:]]

            selected.update(top_indices)
            selected.update(bottom_indices)

        if not selected:
            return df

        reduced_df = df.loc[sorted(selected)].copy().reset_index(drop=True)
        logger.info("高速レビュー用に縮約: %d件 -> %d件", len(df), len(reduced_df))
        return reduced_df

    def _load_whiteness_from_json(self, whiteness_data=None):
        """OMR処理時に保存された白さキャッシュJSONを読み込む。

        Returns:
            True: JSONから全エントリ分の白さを読み込めた
            False: JSONが無いか不完全（フォールバック計算が必要）
        """
        if whiteness_data is None:
            whiteness_data = self._read_whiteness_json_map()
        if not whiteness_data:
            return False

        loaded = 0
        for idx in self._all_entries_df.index:
            entry = self._all_entries_df.iloc[idx]
            filename = entry['filename']
            q_no_base = str(int(entry['question_no']))
            q_no_orig = str(int(entry['question_no']) + self.skip_questions)

            by_file = whiteness_data.get(filename, {}) if isinstance(whiteness_data, dict) else {}
            value = by_file.get(q_no_orig, by_file.get(q_no_base, None))
            if value is not None:
                self._whiteness_cache[idx] = float(value)
                loaded += 1

        total = len(self._all_entries_df)
        logger.info("白さキャッシュJSONから読み込み: %d/%d件", loaded, total)
        return loaded > 0

    def _compute_whiteness(self, df_idx):
        """指定インデックスのマーク領域の白さ（平均輝度）を計算してキャッシュ"""
        if df_idx in self._whiteness_cache:
            return self._whiteness_cache[df_idx]

        entry = self._all_entries_df.iloc[df_idx]
        filename = entry['filename']
        question_no = int(entry['question_no']) + self.skip_questions

        try:
            bbox = None
            if self.coords_df is not None:
                from mark_checker import get_bbox_for_question_checker
                bbox = get_bbox_for_question_checker(self.coords_df, filename, question_no)
            if bbox is None:
                self._whiteness_cache[df_idx] = 0.0
                return 0.0

            corrected_img = self._image_cache.get(filename)
            if corrected_img is None:
                img_path = self.image_folder / filename
                if not img_path.exists():
                    self._whiteness_cache[df_idx] = 0.0
                    return 0.0
                corrected_img = _load_and_correct_image(img_path)
                self._image_cache.put(filename, corrected_img)

            pil_img = crop_from_corrected_image(corrected_img, bbox, scale_factor=1.0,
                                                 expand_factor=1.0)
            gray = np.array(pil_img.convert('L'))
            brightness = float(np.mean(gray))
            self._whiteness_cache[df_idx] = brightness
            return brightness
        except Exception as e:
            logger.debug("白さ指標の計算に失敗したため0.0にフォールバック: %s Q%s — %s",
                         filename, question_no, e)
            self._whiteness_cache[df_idx] = 0.0
            return 0.0

    def _build_whiteness_cache_for_indices(self, indices):
        """白さキャッシュ未計算分をまとめて計算（画像単位で1回読込）"""
        if not indices or self._all_entries_df is None or self.coords_df is None:
            return

        uncached = [i for i in indices if i not in self._whiteness_cache]
        if not uncached:
            return

        # グリッド領域にローディング表示
        self._cancel_grid_render()
        for w in self._grid_inner_frame.winfo_children():
            w.destroy()
        self._grid_photo_refs.clear()
        self._grid_canvas.delete(self._grid_canvas_window)

        canvas_w = max(200, self._grid_canvas.winfo_width())
        canvas_h = max(100, self._grid_canvas.winfo_height())
        loading_id = self._grid_canvas.create_text(
            canvas_w // 2, canvas_h // 3,
            text=f"白さ指標を計算中... 0/{len(uncached)}件",
            font=(UI_FONT, get_ui_font_size(14)), fill='gray',
        )
        self._grid_canvas.update_idletasks()

        grouped = {}
        for idx in uncached:
            entry = self._all_entries_df.iloc[idx]
            grouped.setdefault(entry['filename'], []).append(idx)

        processed = 0
        total = len(uncached)
        for filename, idx_list in grouped.items():
            corrected_img = self._image_cache.get(filename)
            if corrected_img is None:
                img_path = self.image_folder / filename
                if img_path.exists():
                    try:
                        corrected_img = _load_and_correct_image(img_path)
                        self._image_cache.put(filename, corrected_img)
                    except Exception as e:
                        logger.debug("画像の読込・補正に失敗: %s — %s", filename, e)
                        corrected_img = None

            for idx in idx_list:
                try:
                    entry = self._all_entries_df.iloc[idx]
                    question_no = int(entry['question_no']) + self.skip_questions
                    bbox = self._bbox_map.get((filename, int(question_no)))
                    if corrected_img is None or bbox is None:
                        self._whiteness_cache[idx] = 0.0
                    else:
                        x, y, w, h = bbox
                        img_h, img_w = corrected_img.shape[:2]
                        sx = img_w / MARK2_BASE_WIDTH
                        sy = img_h / MARK2_BASE_HEIGHT
                        rx = int(x * sx)
                        ry = int(y * sy)
                        rw = max(1, int(w * sx))
                        rh = max(1, int(h * sy))
                        rx = max(0, min(rx, img_w - 1))
                        ry = max(0, min(ry, img_h - 1))
                        rw = min(rw, img_w - rx)
                        rh = min(rh, img_h - ry)
                        roi = corrected_img[ry:ry + rh, rx:rx + rw]
                        if roi.size == 0:
                            self._whiteness_cache[idx] = 0.0
                        else:
                            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                            self._whiteness_cache[idx] = float(np.mean(gray))
                except Exception as e:
                    logger.debug("白さ指標の一括計算に失敗したため0.0にフォールバック: %s idx=%s — %s",
                                 filename, idx, e)
                    self._whiteness_cache[idx] = 0.0

                processed += 1
                if processed % 100 == 0:
                    self._grid_canvas.itemconfig(
                        loading_id, text=f"白さ指標を計算中... {processed}/{total}件"
                    )
                    self._grid_canvas.update_idletasks()

        # ローディング表示を削除し inner_frame を再配置
        self._grid_canvas.delete(loading_id)
        self._grid_canvas_window = self._grid_canvas.create_window(
            (0, 0), window=self._grid_inner_frame, anchor="nw"
        )
        try:
            if canvas_w > 1:
                self._grid_canvas.itemconfig(self._grid_canvas_window, width=canvas_w)
        except Exception:
            pass

        self._update_status_label()

    def _save_single_and_back(self):
        """単体表示で修正を保存してグリッドに戻る"""
        if self.save_current_correction():
            self._rebuild_category_list()
            self._switch_to_grid()

    def _build_choice_buttons(self, num_choices):
        """選択肢ボタン行を（再）構築する"""
        for w in self._choice_btn_frame.winfo_children():
            w.destroy()
        self._choice_buttons = []
        
        tk.Label(self._choice_btn_frame, text="選択:", font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        for i in range(1, num_choices + 1):
            btn = tk.Button(
                self._choice_btn_frame, text=str(i), width=3,
                font=('Arial', 10, 'bold'), relief=tk.RAISED,
                bg='#E3F2FD', activebackground='#90CAF9',
                command=lambda v=i: self._on_choice_button(v))
            btn.pack(side=tk.LEFT, padx=1)
            self._choice_buttons.append((btn, i))
        
        # -1 ボタン
        btn_minus = tk.Button(
            self._choice_btn_frame, text="-1", width=3,
            font=('Arial', 10, 'bold'), relief=tk.RAISED,
            bg='#FFCDD2', activebackground='#EF9A9A',
            command=lambda: self._on_choice_button(-1))
        btn_minus.pack(side=tk.LEFT, padx=(5, 0))
        self._choice_buttons.append((btn_minus, -1))
    
    def _on_choice_button(self, value):
        """選択肢ボタン押下: Entryに値をセットして保存+グリッドに戻る"""
        self.correction_entry.delete(0, tk.END)
        self.correction_entry.insert(0, str(value))
        self._save_single_and_back()
    
    def _on_key_press(self, event):
        """キーボードショートカット: 数字キーで即入力+次へ
        
        1-9: 選択肢1-9
        0: 選択肢10
        マイナスキー: -1（マークなし）
        ただしEntryにフォーカスがある場合は通常入力に任せる
        """
        # Entryにフォーカスがある場合はスルー
        focused = self.window.focus_get()
        if focused == self.correction_entry:
            return
        
        if event.char and event.char in '1234567890':
            value = int(event.char)
            if value == 0:
                value = 10
            if value <= self._max_choices:
                self._on_choice_button(value)
        elif event.char == '-':
            self._on_choice_button(-1)
    
    def _get_num_choices_for_question(self, question_no):
        """座標CSVから指定問題の選択肢数を取得する"""
        if self.coords_df is None:
            return self._max_choices
        try:
            original_q_no = question_no + self.skip_questions
            rows = self.coords_df[self.coords_df['question_no'] == original_q_no]
            if rows.empty:
                return self._max_choices
            mark_coords_str = rows.iloc[0].get('mark_coords', '')
            if pd.isna(mark_coords_str) or not mark_coords_str:
                return self._max_choices
            return len(str(mark_coords_str).split('|'))
        except Exception:
            return self._max_choices
    
    def _update_max_choices_from_coords(self):
        """座標CSV全体から最大選択肢数を算出し、ボタンを再構築"""
        if self.coords_df is None:
            return
        try:
            max_c = 0
            for mc in self.coords_df['mark_coords'].dropna():
                n = len(str(mc).split('|'))
                if n > max_c:
                    max_c = n
            if max_c > 0:
                self._max_choices = max_c
                self._build_choice_buttons(self._max_choices)
        except Exception:
            pass

    def load_data(self):
        """データ読み込み — 全エントリ（正常＋エラー）をロードする"""
        try:
            self.update_file_info()

            # 全エントリをExcelから読み込む
            self._all_entries_df = detect_all_entries_checker(
                self.xlsx_path,
                registered_questions=self._get_registered_questions(),
            )
            logger.info("全エントリ読み込み: %d件", len(self._all_entries_df))

            # after列をobject型に統一
            if 'after' in self._all_entries_df.columns:
                self._all_entries_df['after'] = self._all_entries_df['after'].astype('object')

            # 前回の修正CSVがあればマージ
            if self.error_csv_path.exists():
                saved_df = load_errors_checker(self.error_csv_path)
                if len(saved_df) > 0:
                    corrected = len(saved_df[
                        saved_df['after'].notna() &
                        (saved_df['after'] != '') &
                        (saved_df['after'] != 'skip')
                    ])
                    if corrected > 0:
                        choice = messagebox.askyesno(
                            "作業継続の確認",
                            f"前回の修正データが見つかりました。\n\n"
                            f"  修正済: {corrected}件\n\n"
                            f"前回の修正を引き継ぎますか？",
                            parent=self.window,
                        )
                        if choice:
                            self._merge_corrections(saved_df)
                            logger.info("前回の修正を引き継ぎ: %d件", corrected)
                        else:
                            self.backup_csv(self.error_csv_path)
                            self.error_csv_path.unlink()
                            logger.info("既存の修正CSVをバックアップして削除しました")

            # 白さキャッシュJSON（高速レビュー抽出・白さキャッシュ投入の両方で使用）
            whiteness_map = self._read_whiteness_json_map()

            # 表示対象を縮約: エラー全件 + 各選択肢の薄い/濃い top100
            self._all_entries_df = self._build_fast_review_subset(
                self._all_entries_df,
                whiteness_map=whiteness_map,
                top_n=100,
            )

            # 座標CSV読み込み
            self.coords_df = load_coordinates_csv_checker(self.coords_csv_path)
            logger.info("座標CSV読み込み: %d行", len(self.coords_df))

            # 座標CSVから選択肢数を算出してボタン行を更新
            self._update_max_choices_from_coords()

            # 高速参照用のbboxインデックスを構築
            self._bbox_map = {}
            for _i, c_row in self.coords_df.iterrows():
                try:
                    image_name = str(c_row['image_path'])
                    q_no = int(c_row['question_no'])
                    bbox_parts = str(c_row['choices_bbox']).split(';')
                    if len(bbox_parts) == 4:
                        self._bbox_map[(image_name, q_no)] = tuple(map(int, bbox_parts))
                except Exception:
                    continue
            logger.info("座標インデックス構築: %d件", len(self._bbox_map))

            # 座標欠損の集計（個別ではなくサマリーで報告）
            missing_coords = []
            for _i, row in self._all_entries_df.iterrows():
                fn = row.get("filename", "")
                q = int(row.get("question_no", 0))
                orig_q = q + self.skip_questions
                if (fn, orig_q) not in self._bbox_map:
                    missing_coords.append((fn, orig_q))
            if missing_coords:
                # 影響画像数をカウント
                affected_images = len(set(fn for fn, _ in missing_coords))
                logger.info(
                    "座標が取得できなかったエントリ: %d件（%d枚の画像）"
                    "── マーカー検出精度の限界によるもので、正常動作です",
                    len(missing_coords), affected_images,
                )

            # サイドパネル構築
            self._rebuild_category_list()

            # ステータス更新
            self._update_status_label()

            # 後方互換: error_df を _all_entries_df の参照にする
            self.error_df = self._all_entries_df

            # 白さ指標: JSONキャッシュがあれば即座にロード、なければ画像から計算
            if len(self._all_entries_df) > 0:
                whiteness_loaded = self._load_whiteness_from_json(whiteness_map)
                if not whiteness_loaded:
                    all_indices = list(self._all_entries_df.index)
                    self._build_whiteness_cache_for_indices(all_indices)

            # グリッド表示（デフォルト）
            if len(self._all_entries_df) > 0:
                self._grid_current_page = 0
                self._refresh_grid_view(reset_page=True)
            else:
                self.status_label.config(text="✓ データがありません")

        except Exception as e:
            messagebox.showerror("エラー", f"データ読み込みエラー:\n{e}", parent=self.window)
            self.window.destroy()

    def _merge_corrections(self, saved_df):
        """保存済みの修正CSVを全エントリDFにマージする"""
        corrections = saved_df[
            saved_df['after'].notna() & (saved_df['after'] != '')
        ]
        for _, row in corrections.iterrows():
            mask = (
                (self._all_entries_df['filename'] == row['filename']) &
                (self._all_entries_df['question_no'] == int(row['question_no']))
            )
            if mask.any():
                self._all_entries_df.loc[mask, 'after'] = str(row['after'])
    
    def backup_csv(self, csv_path):
        """CSVファイルをバックアップ"""
        csv_path = Path(csv_path)
        if not csv_path.exists():
            return
        
        backup_dir = self.xlsx_path.parent / DEFAULT_BACKUP_FOLDER
        backup_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{timestamp}_{csv_path.name}"
        backup_path = backup_dir / backup_filename
        
        shutil.copy2(csv_path, backup_path)
        logger.info("CSVバックアップ作成: %s", backup_path.name)
    
    def update_file_info(self):
        """入力ファイル情報を更新して表示"""
        image_count = len(list(self.image_folder.glob('*.jpg'))) + len(list(self.image_folder.glob('*.png')))
        
        info_text = (
            f"画像フォルダ: {self.image_folder.absolute()}\n"
            f"座標CSV:     {self.coords_csv_path.absolute()}\n"
            f"Result Excel: {self.xlsx_path.absolute()}\n"
            f"画像枚数: {image_count}枚"
        )
        
        self.file_info_text.config(state=tk.NORMAL)
        self.file_info_text.delete('1.0', tk.END)
        self.file_info_text.insert('1.0', info_text)
        self.file_info_text.config(state=tk.DISABLED)
    
    def show_current(self):
        """現在のインデックスの項目を単体表示する"""
        df = self._all_entries_df
        if df is None or len(df) == 0:
            return

        if self.current_index < 0:
            self.current_index = 0
        if self.current_index >= len(df):
            self.current_index = len(df) - 1

        row = df.iloc[self.current_index]
        filename = row['filename']
        question_no = int(row['question_no'])
        before_value = row['before']
        after_value = row['after']
        error_type = row['error_type']
        category = row.get('category', '')

        # ステータス更新
        self._update_status_label()

        # カテゴリ表示
        cat_jp = {
            'ノーマーク': 'ノーマーク', '複数マーク': '複数マーク',
            '不正な値': '不正な値', '無効回答(-1)': '無効回答(-1)',
        }.get(category, f"選択肢 {category}")

        self.info_label.config(
            text=f"ファイル: {filename} / 問題番号: {question_no} / カテゴリ: {cat_jp}"
        )

        before_text = f"「{before_value}」" if before_value else "(空白)"
        self.before_label.config(text=before_text)

        # 問題ごとの選択肢数でヒント更新
        q_choices = self._get_num_choices_for_question(question_no)
        self._hint_label.config(text=f"(1-{q_choices}, -1=無効回答 / Enterで保存)")

        self.correction_entry.delete(0, tk.END)
        if pd.notna(after_value) and after_value != '':
            self.correction_entry.insert(0, str(after_value))
        elif error_type != '':
            # エラー項目にはデフォルト -1
            self.correction_entry.insert(0, DEFAULT_CORRECTION)

        try:
            original_q_no = question_no + self.skip_questions
            pil_img = get_display_image_checker(
                self.coords_df, self.image_folder, filename, original_q_no,
                scale_factor=DEFAULT_SCALE_FACTOR, expand_factor=DEFAULT_EXPAND_FACTOR,
                cache=self._image_cache, bbox_map=self._bbox_map,
            )
            if pil_img:
                pil_img = self._draw_answer_overlay(pil_img, filename, question_no)
                pil_img = fit_image_to_display(pil_img)

            if pil_img:
                self.photo_image = pil_to_imagetk_checker(pil_img)
                self.image_label.config(image=self.photo_image, text="",
                                         width=pil_img.width, height=pil_img.height)
            else:
                self.image_label.config(image='', text="画像を読み込めません",
                                         width=1100, height=150)
                self.photo_image = None
        except Exception as e:
            self.image_label.config(image='', text=f"画像エラー: {e}",
                                     width=1100, height=150)
            self.photo_image = None
    
    def save_current_correction(self):
        """現在の修正内容を保存"""
        if self._all_entries_df is None or self.current_index >= len(self._all_entries_df):
            return False

        correction = self.correction_entry.get().strip()

        if correction:
            self._all_entries_df['after'] = self._all_entries_df['after'].astype(object)
            if correction == '-1':
                self._all_entries_df.at[self.current_index, 'after'] = '-1'
            elif self.mark_format == MARK_FORMAT_MULTI_DIGIT:
                # 複数桁モード: 紙面記号1文字(-, 0〜9, a〜d)を受理(大文字は小文字化)
                from constants import MULTI_DIGIT_VALID_SYMBOLS
                symbol = correction.lower()
                if symbol in MULTI_DIGIT_VALID_SYMBOLS:
                    self._all_entries_df.at[self.current_index, 'after'] = symbol
                else:
                    messagebox.showwarning("入力エラー",
                                            "マーク記号1文字（- 0〜9 a〜d）または -1 を入力してください",
                                            parent=self.window)
                    return False
            elif re.match(r'^-?\d+$', correction):
                self._all_entries_df.at[self.current_index, 'after'] = correction
            else:
                messagebox.showwarning("入力エラー",
                                        "整数または -1 を入力してください",
                                        parent=self.window)
                return False
        else:
            # 空欄 → 修正取り消し
            self._all_entries_df.at[self.current_index, 'after'] = ''

        # 遅延CSV保存
        self._csv_dirty = True
        self._unsaved_count += 1
        if self._unsaved_count >= self._save_interval:
            self._flush_csv()
        return True

    def _count_pending_corrections(self):
        """「xlsxに反映」していない訂正の件数を返す。

        反映(apply_to_xlsx)後は refresh_data で after 列がクリアされるため、
        現在 after に値が残っている行 = 未反映の訂正。'skip'は意図的な保留なので除く。
        """
        if self._all_entries_df is None or 'after' not in self._all_entries_df.columns:
            return 0
        col = self._all_entries_df['after']
        mask = col.notna() & (~col.astype(str).isin(['', 'skip']))
        return int(mask.sum())

    def _flush_csv(self):
        """修正のあるエントリだけをCSVに書き出す"""
        if not self._csv_dirty or self._all_entries_df is None:
            return
        # 修正のあるエントリだけ抽出して保存（CSVを小さく保つ）
        mask = self._all_entries_df['after'].notna() & (self._all_entries_df['after'] != '')
        save_df = self._all_entries_df[mask][['filename', 'question_no', 'before', 'after', 'error_type']]
        save_errors_checker(save_df, self.error_csv_path)
        self._csv_dirty = False
        self._unsaved_count = 0

    def apply_to_xlsx(self):
        """xlsxに反映"""
        if self._view_mode == "single":
            self.save_current_correction()
        self._flush_csv()

        if self._all_entries_df is None:
            return

        corrected = len(self._all_entries_df[
            self._all_entries_df['after'].notna() &
            (self._all_entries_df['after'] != '')
        ])

        if corrected == 0:
            messagebox.showwarning("警告", "修正された項目がありません",
                                    parent=self.window)
            return

        result = messagebox.askyesno(
            "確認",
            f"{corrected}件の修正をxlsxに反映します。\n"
            f"元のファイルはbackupフォルダにコピーされます。\n\n実行しますか?",
            parent=self.window,
        )
        if not result:
            return

        try:
            backup_path, update_count = apply_corrections_checker(
                self.xlsx_path, self.error_csv_path,
            )
            messagebox.showinfo(
                "完了",
                f"xlsxファイルを更新しました。\n\n"
                f"更新件数: {update_count}件\n"
                f"バックアップ: {backup_path.name}\n\n"
                f"データを再読み込みして画面をリフレッシュします。",
                parent=self.window,
            )
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("エラー", f"xlsx更新エラー:\n{e}",
                                  parent=self.window)

    def refresh_data(self):
        """データを再読み込みしてGUIをリフレッシュ"""
        try:
            if self.error_csv_path.exists():
                self.backup_csv(self.error_csv_path)
                self.error_csv_path.unlink()
                logger.info("リフレッシュのため、CSVをバックアップして削除しました")

            self.current_index = 0
            self._whiteness_cache.clear()
            self._thumb_cache.clear()
            self._grid_current_page = 0
            self._view_mode = "grid"
            self._single_view_frame.pack_forget()
            if self._side_panel.winfo_manager() == "":
                self._side_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0), pady=8)
            self._grid_view_frame.pack(fill=tk.BOTH, expand=True)
            self.load_data()
        except Exception as e:
            messagebox.showerror("エラー", f"データ再読み込みエラー:\n{e}",
                                  parent=self.window)


# ========================================
# セクション7.4: StudentAnswerSheetViewer クラス
# （個別生徒の答案をリアルタイム閾値表示するサブウィンドウ）
# ========================================

class StudentAnswerSheetViewer:
    """
    個別生徒の答案画像を表示し、OMR閾値のリアルタイムプレビューを行うウィンドウ。

    ThresholdCalibratorGUI のギャラリーでサムネイルをクリックしたときに開く。
    - 全マーク領域を灰色枠で表示
    - area_threshold を超えるエリア（マーク有判定）を赤い太枠で表示
    - Color / Area スライダーでリアルタイム更新
    - 中間ファイルは一切生成しない（全てメモリ上で完結）
    """

    # 表示用の拡大倍率 (595×842 → 表示サイズ)
    DEFAULT_SCALE = 1.5

    def __init__(self, parent_window, image_name, gray_image, coordinates,
                 color_threshold=0.1, area_threshold=0.4, calibrator_gui=None,
                 highlight_question_no=None):
        """
        Args:
            parent_window: 親ウィンドウ（ThresholdCalibratorGUI の window）
            image_name: 画像ファイル名
            gray_image: 補正済みグレースケール画像 (595×842)
            coordinates: 全マーク領域リスト
            color_threshold: 初期 color_threshold
            area_threshold: 初期 area_threshold
            calibrator_gui: 親の ThresholdCalibratorGUI インスタンス（閾値同期用、任意）
            highlight_question_no: 注目している設問番号（該当設問を太枠でハイライト）
        """
        self.parent = parent_window
        self.image_name = image_name
        self.gray_image = gray_image
        self.coordinates = coordinates
        self.calibrator_gui = calibrator_gui
        self.highlight_question_no = highlight_question_no

        # 閾値変数（ローカル）
        self.color_var = tk.DoubleVar(value=color_threshold)
        self.area_var = tk.DoubleVar(value=area_threshold)

        # 表示用の参照保持（GC防止）
        self._display_image_ref = None

        # fill_ratio キャッシュ（color_threshold 変更時にのみ再計算）
        self._cached_fill_ratios = None
        self._cached_color_threshold = None

        # デバウンス用
        self._color_update_job = None
        self._area_update_job = None

        # ウィンドウ作成（非モーダル — 複数生徒を同時に開ける）
        self.window = tk.Toplevel(parent_window)
        self.window.title(f"📋 答案表示: {image_name}")
        self.window.configure(bg="#F5F7FA")

        # UI構築
        self._create_widgets()

        # ウィンドウサイズ計算（画像サイズ + コントロールパネル幅）
        display_w = int(595 * self.DEFAULT_SCALE)
        display_h = int(842 * self.DEFAULT_SCALE)
        window_w = display_w + 320  # コントロールパネル分
        window_h = max(display_h + 40, 600)
        self.window.geometry(f"{window_w}x{window_h}")

        # ウィンドウ閉じ処理
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        # 初回描画
        self.window.after(100, self._update_display)

    def _on_close(self):
        """ウィンドウを閉じる"""
        self._display_image_ref = None
        self.window.destroy()

    # ─────────────────────────────────────────────
    # UI 構築
    # ─────────────────────────────────────────────

    def _create_widgets(self):
        BG = "#F5F7FA"
        SEC_BG = "#FFFFFF"
        FONT = (UI_FONT, get_ui_font_size(9))
        FONT_B = (UI_FONT, get_ui_font_size(9), "bold")
        FONT_S = (UI_FONT, get_ui_font_size(8))

        main = tk.Frame(self.window, bg=BG, padx=4, pady=4)
        main.pack(fill=tk.BOTH, expand=True)

        # ===== 右パネル: コントロール =====
        right = tk.Frame(main, bg=SEC_BG, width=300, padx=10, pady=10, relief=tk.FLAT, bd=1)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        right.pack_propagate(False)

        tk.Label(right, text="📋 答案ビューア", font=(UI_FONT, get_ui_font_size(11), "bold"),
                 bg=SEC_BG, fg="#1565C0").pack(anchor=tk.W, pady=(0, 5))

        # ファイル名
        tk.Label(right, text=f"ファイル: {self.image_name}", font=FONT_S,
                 bg=SEC_BG, fg="#546E7A", wraplength=270, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 10))

        # --- 凡例 ---
        tk.Label(right, text="凡例", font=FONT_B, bg=SEC_BG, fg="#546E7A").pack(anchor=tk.W)
        tk.Frame(right, bg="#90CAF9", height=2).pack(fill=tk.X, pady=(2, 5))

        legend_frame = tk.Frame(right, bg=SEC_BG)
        legend_frame.pack(fill=tk.X, pady=(0, 10))

        # 灰色枠の凡例
        gray_legend = tk.Frame(legend_frame, bg=SEC_BG)
        gray_legend.pack(fill=tk.X, pady=1)
        gray_box = tk.Canvas(gray_legend, width=20, height=14, bg=SEC_BG, highlightthickness=0)
        gray_box.pack(side=tk.LEFT, padx=(0, 5))
        gray_box.create_rectangle(2, 2, 18, 12, outline="#9E9E9E", width=2)
        tk.Label(gray_legend, text="全マーク領域（灰色枠）", font=FONT_S,
                 bg=SEC_BG, fg="#616161").pack(side=tk.LEFT)

        # 赤枠の凡例
        red_legend = tk.Frame(legend_frame, bg=SEC_BG)
        red_legend.pack(fill=tk.X, pady=1)
        red_box = tk.Canvas(red_legend, width=20, height=14, bg=SEC_BG, highlightthickness=0)
        red_box.pack(side=tk.LEFT, padx=(0, 5))
        red_box.create_rectangle(2, 2, 18, 12, outline="#D32F2F", width=2)
        tk.Label(red_legend, text="マーク有判定（赤枠）", font=FONT_S,
                 bg=SEC_BG, fg="#C62828").pack(side=tk.LEFT)

        # シアン枠の凡例（注目設問）
        cyan_legend = tk.Frame(legend_frame, bg=SEC_BG)
        cyan_legend.pack(fill=tk.X, pady=1)
        cyan_box = tk.Canvas(cyan_legend, width=20, height=14, bg=SEC_BG, highlightthickness=0)
        cyan_box.pack(side=tk.LEFT, padx=(0, 5))
        cyan_box.create_rectangle(2, 2, 18, 12, outline="#00B4DC", width=3)
        tk.Label(cyan_legend, text="クリックした設問（注目）", font=FONT_S,
                 bg=SEC_BG, fg="#00838F").pack(side=tk.LEFT)

        # --- 閾値スライダー ---
        tk.Label(right, text="閾値調整", font=FONT_B, bg=SEC_BG, fg="#546E7A").pack(anchor=tk.W, pady=(5, 0))
        tk.Frame(right, bg="#CE93D8", height=2).pack(fill=tk.X, pady=(2, 5))

        tk.Label(right, text="Color Threshold:", font=FONT_S, bg=SEC_BG).pack(anchor=tk.W)
        self.color_scale = tk.Scale(right, variable=self.color_var, from_=0.03, to=0.35,
                                    resolution=0.005, orient=tk.HORIZONTAL, bg=SEC_BG,
                                    relief=tk.FLAT, length=260, command=self._on_color_changed)
        self.color_scale.pack(fill=tk.X)

        tk.Label(right, text="Area Threshold:", font=FONT_S, bg=SEC_BG).pack(anchor=tk.W, pady=(5, 0))
        self.area_scale = tk.Scale(right, variable=self.area_var, from_=0.05, to=0.80,
                                   resolution=0.01, orient=tk.HORIZONTAL, bg=SEC_BG,
                                   relief=tk.FLAT, length=260, command=self._on_area_changed)
        self.area_scale.pack(fill=tk.X)

        # --- 統計パネル ---
        tk.Label(right, text="この答案の統計", font=FONT_B, bg=SEC_BG, fg="#546E7A").pack(anchor=tk.W, pady=(15, 0))
        tk.Frame(right, bg="#A5D6A7", height=2).pack(fill=tk.X, pady=(2, 5))

        self.stats_text = tk.Text(right, height=8, font=("Consolas", 8), bg="#FAFAFA",
                                  relief=tk.FLAT, bd=1, state=tk.DISABLED, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.X)

        # --- 閾値同期ボタン ---
        tk.Label(right, text="操作", font=FONT_B, bg=SEC_BG, fg="#546E7A").pack(anchor=tk.W, pady=(15, 0))
        tk.Frame(right, bg="#FFCC80", height=2).pack(fill=tk.X, pady=(2, 5))

        if self.calibrator_gui is not None:
            tk.Button(right, text="↑ キャリブレーターに閾値を反映",
                      command=self._sync_to_calibrator,
                      bg="#BBDEFB", font=FONT, relief=tk.FLAT, cursor="hand2").pack(fill=tk.X, pady=(0, 3))

            tk.Button(right, text="↓ キャリブレーターから閾値を取得",
                      command=self._sync_from_calibrator,
                      bg="#C8E6C9", font=FONT, relief=tk.FLAT, cursor="hand2").pack(fill=tk.X, pady=(0, 3))

        tk.Button(right, text="閉じる", command=self._on_close,
                  bg="#EEEEEE", font=FONT, relief=tk.FLAT, cursor="hand2").pack(fill=tk.X, pady=(5, 0), side=tk.BOTTOM)

        # ===== 左パネル: 答案画像表示 =====
        left = tk.Frame(main, bg=SEC_BG, relief=tk.FLAT, bd=1)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # スクロール対応キャンバス
        self.img_canvas = tk.Canvas(left, bg="#E0E0E0", highlightthickness=0)
        v_scroll = tk.Scrollbar(left, orient=tk.VERTICAL, command=self.img_canvas.yview)
        h_scroll = tk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.img_canvas.xview)
        self.img_canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.img_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # マウスホイールスクロール
        def _on_mousewheel(event):
            self.img_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.img_canvas.bind("<MouseWheel>", _on_mousewheel)

    # ─────────────────────────────────────────────
    # 閾値スライダーイベント
    # ─────────────────────────────────────────────

    def _on_color_changed(self, _value):
        """Color スライダー変更 — fill_ratio 再計算が必要"""
        if self._color_update_job:
            self.window.after_cancel(self._color_update_job)
        self._color_update_job = self.window.after(300, self._update_display)

    def _on_area_changed(self, _value):
        """Area スライダー変更 — 再描画のみ"""
        if self._area_update_job:
            self.window.after_cancel(self._area_update_job)
        self._area_update_job = self.window.after(100, self._update_display)

    # ─────────────────────────────────────────────
    # 閾値同期
    # ─────────────────────────────────────────────

    def _sync_to_calibrator(self):
        """この答案ビューアの閾値をキャリブレーターに反映し、ギャラリーも更新"""
        if self.calibrator_gui is None:
            return
        ct = self.color_var.get()
        at = self.area_var.get()
        self.calibrator_gui.color_var.set(ct)
        self.calibrator_gui.area_var.set(at)
        # スライダーの set() では command コールバックが発火しないため、
        # キャリブレーターのギャラリーを明示的に再計算・更新する
        self.calibrator_gui.force_recollect_all()

    def _sync_from_calibrator(self):
        """キャリブレーターの現在の閾値をこの答案ビューアに取得"""
        if self.calibrator_gui is None:
            return
        self.color_var.set(self.calibrator_gui.color_var.get())
        self.area_var.set(self.calibrator_gui.area_var.get())
        self._update_display()

    # ─────────────────────────────────────────────
    # 答案画像の描画
    # ─────────────────────────────────────────────

    def _update_display(self):
        """現在の閾値で答案画像にマーク領域を描画して表示"""
        ct = self.color_var.get()
        at = self.area_var.get()

        # fill_ratio の計算（color_threshold が変わった場合のみ再計算）
        if self._cached_color_threshold != ct or self._cached_fill_ratios is None:
            self._cached_fill_ratios = collect_mark_fill_ratios(
                self.gray_image, self.coordinates, ct)
            self._cached_color_threshold = ct

        fill_ratios = self._cached_fill_ratios

        # 表示用画像を構築（元画像をコピーしてRGB変換）
        display_img = cv2.cvtColor(self.gray_image.copy(), cv2.COLOR_GRAY2RGB)

        # fill_ratio を座標からルックアップするための辞書
        ratio_map = {}
        for r in fill_ratios:
            key = (r['question_no'], r['choice'])
            ratio_map[key] = r['fill_ratio']

        # 全マーク領域を描画
        marked_count = 0
        unmarked_count = 0
        marked_ratios = []
        unmarked_ratios = []

        # 注目設問の全選択肢のバウンディングボックスを計算
        highlight_bbox = None
        if self.highlight_question_no is not None:
            hq_coords = [c for c in self.coordinates
                         if c['question_no'] == self.highlight_question_no]
            if hq_coords:
                hx1 = min(c['x'] for c in hq_coords)
                hy1 = min(c['y'] for c in hq_coords)
                hx2 = max(c['x'] + c['width'] for c in hq_coords)
                hy2 = max(c['y'] + c['height'] for c in hq_coords)
                # マージンを付けて設問全体を囲む
                margin = 6
                highlight_bbox = (hx1 - margin, hy1 - margin,
                                  hx2 + margin, hy2 + margin)

        for coord in self.coordinates:
            q_no = coord['question_no']
            choice = coord['choice']
            x, y = coord['x'], coord['y']
            w, h = coord['width'], coord['height']

            key = (q_no, choice)
            fill_ratio = ratio_map.get(key, 0.0)
            is_marked = fill_ratio > at

            if is_marked:
                # マーク有: 赤い枠線（外側に描画してマーク内容を隠さない）
                pad = 2  # マーク領域の外側に枠を描画
                cv2.rectangle(display_img,
                              (x - pad, y - pad), (x + w + pad, y + h + pad),
                              (220, 40, 40), 2)
                marked_count += 1
                marked_ratios.append(fill_ratio)
            else:
                # マーク無: 灰色枠 (1px)
                cv2.rectangle(display_img, (x, y), (x + w, y + h), (160, 160, 160), 1)
                unmarked_count += 1
                unmarked_ratios.append(fill_ratio)

        # 注目設問をシアン色の太枠で囲む（最前面に描画）
        if highlight_bbox is not None:
            bx1, by1, bx2, by2 = highlight_bbox
            cv2.rectangle(display_img, (bx1, by1), (bx2, by2), (0, 180, 220), 3)

        # スケーリング
        scale = self.DEFAULT_SCALE
        new_w = int(display_img.shape[1] * scale)
        new_h = int(display_img.shape[0] * scale)
        display_img = cv2.resize(display_img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        # PIL → ImageTk
        pil_img = Image.fromarray(display_img)
        self._display_image_ref = ImageTk.PhotoImage(pil_img)

        # キャンバスに表示
        self.img_canvas.delete("all")
        self.img_canvas.create_image(0, 0, anchor="nw", image=self._display_image_ref)
        self.img_canvas.configure(scrollregion=(0, 0, new_w, new_h))

        # 統計テキスト更新
        total = marked_count + unmarked_count
        avg_marked = np.mean(marked_ratios) if marked_ratios else 0.0
        avg_unmarked = np.mean(unmarked_ratios) if unmarked_ratios else 0.0

        stats_lines = [
            f"ファイル: {self.image_name}",
            f"",
            f"全マーク領域:  {total}",
            f"マーク有:      {marked_count}  ({marked_count/max(total,1)*100:.1f}%)",
            f"マーク無:      {unmarked_count}  ({unmarked_count/max(total,1)*100:.1f}%)",
            f"",
            f"有  平均fill:  {avg_marked:.3f}",
            f"無  平均fill:  {avg_unmarked:.3f}",
            f"",
            f"閾値: C={ct:.3f}  A={at:.3f}",
        ]
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert(tk.END, "\n".join(stats_lines))
        self.stats_text.config(state=tk.DISABLED)


# ========================================
# セクション7.5: ThresholdCalibratorGUIクラス
# （閾値自動判定・調整用サブウィンドウ）
# ========================================

class ThresholdCalibratorGUI:
    """
    閾値キャリブレーション用GUIウィンドウ。
    メインGUIから独立した Toplevel ウィンドウとして起動し、
    OMR読み取り用の2つの閾値 (color_threshold, area_threshold) を
    自動推定・手動調整・テスト読み取りで決定する。
    中間ファイルは一切生成しない（全てメモリ上で完結）。
    """

    # サムネイル設定
    THUMB_SIZE = 80           # サムネイル 1個の表示サイズ (px)
    GALLERY_COLS = 5          # ギャラリー1行あたりの表示数
    GALLERY_ROWS_PER_CAT = 2  # 各カテゴリの行数

    def __init__(self, parent_window, image_folder, coord_excel_path, skip_questions=0,
                 color_threshold_var=None, area_threshold_var=None):
        """
        Args:
            parent_window: 親ウィンドウ (tk.Tk or tk.Toplevel)
            image_folder: 画像フォルダのパス
            coord_excel_path: 座標定義Excelファイルのパス
            skip_questions: スキップする問題数
            color_threshold_var: メインGUIの tk.DoubleVar (適用時に更新)
            area_threshold_var: メインGUIの tk.DoubleVar (適用時に更新)
        """
        self.parent = parent_window
        self.image_folder = Path(image_folder)
        self.coord_excel_path = Path(coord_excel_path)
        self.skip_questions = skip_questions
        self.parent_color_var = color_threshold_var
        self.parent_area_var = area_threshold_var

        # キャリブレーション結果（メモリ上のみ）
        self.calibration_result = None
        self.all_ratios = None           # 全fill_ratioリスト
        self.corrected_images = None     # [(filename, gray_image), ...]
        self.coordinates = None          # 座標リスト
        self.current_analysis = None     # 現在の閾値での分類結果

        # サムネイル画像の参照保持（GC防止）
        self._thumb_refs = []

        # ウィンドウ作成
        self.window = tk.Toplevel(parent_window)
        self.window.title("🔧 閾値キャリブレーション")
        self.window.geometry("1100x700")
        self.window.transient(parent_window)
        self.window.grab_set()
        self.window.focus_set()
        self.window.configure(bg="#F5F7FA")

        # 閾値変数（ローカル）
        self.color_var = tk.DoubleVar(value=0.1)
        self.area_var = tk.DoubleVar(value=0.4)

        # UI構築
        self._create_widgets()

        # ウィンドウ閉じ処理
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        # バックグラウンドで自動計算を開始
        self.window.after(200, self._run_calibration_async)

    def _on_close(self):
        """ウィンドウを閉じる"""
        # bind_all で登録したマウスホイールイベントを解除
        if hasattr(self, '_gallery_mousewheel_handler'):
            self.window.unbind_all("<MouseWheel>")
        self.window.grab_release()
        self.window.destroy()

    def _toggle_detail_section(self):
        """詳細設定（テスト読み取り）の折りたたみを切り替え"""
        if self._detail_expanded:
            self._detail_frame.pack_forget()
            self._detail_toggle_btn.config(text="▶ 詳細設定（テスト読み取り）")
            self._detail_expanded = False
        else:
            self._detail_frame.pack(fill=tk.X, after=self._detail_toggle_btn)
            self._detail_toggle_btn.config(text="▼ 詳細設定（テスト読み取り）")
            self._detail_expanded = True

    # ─────────────────────────────────────────────
    # UI 構築
    # ─────────────────────────────────────────────

    def _create_widgets(self):
        BG = "#F5F7FA"
        SEC_BG = "#FFFFFF"
        FONT = (UI_FONT, get_ui_font_size(9))
        FONT_B = (UI_FONT, get_ui_font_size(9), "bold")
        FONT_S = (UI_FONT, get_ui_font_size(8))
        BTN_PURPLE = "#CE93D8"
        BTN_GRAY = "#EEEEEE"

        main = tk.Frame(self.window, bg=BG, padx=8, pady=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ===== 左パネル: コントロール =====
        left = tk.Frame(main, bg=SEC_BG, width=300, padx=10, pady=10, relief=tk.FLAT, bd=1)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left.pack_propagate(False)

        tk.Label(left, text="🔧 閾値キャリブレーション", font=(UI_FONT, get_ui_font_size(11), "bold"),
                 bg=SEC_BG, fg="#7B1FA2").pack(anchor=tk.W, pady=(0, 10))

        # --- 自動計算セクション ---
        tk.Label(left, text="自動計算", font=FONT_B, bg=SEC_BG, fg="#546E7A").pack(anchor=tk.W)
        tk.Frame(left, bg="#CE93D8", height=2).pack(fill=tk.X, pady=(2, 5))

        self.auto_btn = tk.Button(left, text="▶ 自動計算 実行", command=self._run_calibration_async,
                                  bg=BTN_PURPLE, font=FONT_B, relief=tk.FLAT, cursor="hand2")
        self.auto_btn.pack(fill=tk.X, pady=(0, 5))

        self.auto_status_label = tk.Label(left, text="計算中...", font=FONT_S, bg=SEC_BG, fg="gray")
        self.auto_status_label.pack(anchor=tk.W)

        self.recommend_label = tk.Label(left, text="推奨値: ---", font=FONT, bg=SEC_BG, fg="#1976D2")
        self.recommend_label.pack(anchor=tk.W, pady=(2, 8))

        # --- 手動調整セクション ---
        tk.Label(left, text="手動調整", font=FONT_B, bg=SEC_BG, fg="#546E7A").pack(anchor=tk.W)
        tk.Frame(left, bg="#90CAF9", height=2).pack(fill=tk.X, pady=(2, 5))

        tk.Label(left, text="色の読取感度:", font=FONT_S, bg=SEC_BG).pack(anchor=tk.W)
        self.color_scale = tk.Scale(left, variable=self.color_var, from_=0.03, to=0.35,
                                    resolution=0.005, orient=tk.HORIZONTAL, bg=SEC_BG,
                                    relief=tk.FLAT, length=250, command=self._on_color_changed)
        self.color_scale.pack(fill=tk.X)

        tk.Label(left, text="面積の読取感度:", font=FONT_S, bg=SEC_BG).pack(anchor=tk.W, pady=(5, 0))
        self.area_scale = tk.Scale(left, variable=self.area_var, from_=0.05, to=0.80,
                                   resolution=0.01, orient=tk.HORIZONTAL, bg=SEC_BG,
                                   relief=tk.FLAT, length=250, command=self._on_area_changed)
        self.area_scale.pack(fill=tk.X)

        self.recalc_btn = tk.Button(left, text="🔄 この閾値で再判定",
                                    command=self._on_recalc_clicked,
                                    bg="#B3E5FC", font=FONT, relief=tk.FLAT,
                                    cursor="hand2", state=tk.DISABLED)
        self.recalc_btn.pack(fill=tk.X, pady=(8, 0))

        # --- 統計情報 ---
        tk.Label(left, text="統計情報", font=FONT_B, bg=SEC_BG, fg="#546E7A").pack(anchor=tk.W, pady=(10, 0))
        tk.Frame(left, bg="#A5D6A7", height=2).pack(fill=tk.X, pady=(2, 5))

        self.stats_text = tk.Text(left, height=6, font=("Consolas", 8), bg="#FAFAFA",
                                  relief=tk.FLAT, bd=1, state=tk.DISABLED, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.X)

        # --- ボタン ---
        btn_frame = tk.Frame(left, bg=SEC_BG)
        btn_frame.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)

        tk.Button(btn_frame, text="✓ 適用して閉じる", command=self._apply_and_close,
                  bg="#A5D6A7", font=FONT_B, relief=tk.FLAT, cursor="hand2").pack(fill=tk.X, pady=(0, 3))
        tk.Button(btn_frame, text="キャンセル", command=self._on_close,
                  bg=BTN_GRAY, font=FONT, relief=tk.FLAT, cursor="hand2").pack(fill=tk.X)

        # ===== 右パネル: ギャラリー =====
        right = tk.Frame(main, bg=SEC_BG, padx=10, pady=10, relief=tk.FLAT, bd=1)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ギャラリー用のスクロール可能領域
        gallery_canvas = tk.Canvas(right, bg=SEC_BG, highlightthickness=0)
        gallery_scrollbar = tk.Scrollbar(right, orient=tk.VERTICAL, command=gallery_canvas.yview)
        self.gallery_frame = tk.Frame(gallery_canvas, bg=SEC_BG)

        self.gallery_frame.bind("<Configure>",
            lambda e: gallery_canvas.configure(scrollregion=gallery_canvas.bbox("all")))
        gallery_canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")
        gallery_canvas.configure(yscrollcommand=gallery_scrollbar.set)

        gallery_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        gallery_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # マウスホイールスクロール
        def _on_mousewheel(event):
            try:
                gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                # ウィンドウ破棄後にイベントが到達した場合は無視
                pass
        self._gallery_mousewheel_handler = _on_mousewheel
        gallery_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 初期メッセージ
        self._gallery_placeholder = tk.Label(self.gallery_frame, text="自動計算を実行中です...\nしばらくお待ちください",
                                             font=(UI_FONT, get_ui_font_size(12)), fg="gray", bg=SEC_BG)
        self._gallery_placeholder.pack(pady=50)

    # ─────────────────────────────────────────────
    # キャリブレーション実行
    # ─────────────────────────────────────────────

    def _run_calibration_async(self):
        """バックグラウンドスレッドでキャリブレーションを実行"""
        self.auto_btn.config(state=tk.DISABLED)
        self.auto_status_label.config(text="計算中...", fg="gray")

        def worker():
            try:
                result = run_threshold_calibration(
                    self.image_folder, self.coord_excel_path, self.skip_questions)
                self.window.after(0, lambda: self._on_calibration_done(result))
            except Exception as e:
                self.window.after(0, lambda: self._on_calibration_error(str(e)))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_calibration_done(self, result):
        """キャリブレーション完了後のUI更新"""
        self.calibration_result = result
        self.corrected_images = result['corrected_images']
        self.coordinates = result['coordinates']

        # 推奨値をスライダーに反映
        rc = result['recommended_color_threshold']
        ra = result['recommended_area_threshold']
        self.color_var.set(rc)
        self.area_var.set(ra)

        # 推奨値でfill_ratioを再収集（推奨color_thresholdでのデータ）
        self.all_ratios = []
        for img_name, gray in self.corrected_images:
            ratios = collect_mark_fill_ratios(gray, self.coordinates, rc)
            for r in ratios:
                r['image_name'] = img_name
            self.all_ratios.extend(ratios)

        # 分類
        self.current_analysis = reclassify_with_threshold(self.all_ratios, ra)

        # UI更新
        self.auto_status_label.config(text=f"✓ 完了 ({result['image_count']}枚分析)", fg="#2E7D32")
        self.recommend_label.config(text=f"推奨値: 色={rc:.3f}  面積={ra:.3f}")
        self.auto_btn.config(state=tk.NORMAL)
        self.recalc_btn.config(state=tk.NORMAL)

        self._update_stats()
        self._update_gallery()

    def _on_calibration_error(self, error_msg):
        """キャリブレーションエラー"""
        self.auto_status_label.config(text=f"✗ エラー: {error_msg}", fg="red")
        self.auto_btn.config(state=tk.NORMAL)

    # ─────────────────────────────────────────────
    # スライダー操作
    # ─────────────────────────────────────────────

    _color_update_job = None
    _area_update_job = None

    def _on_color_changed(self, _value):
        """Color スライダー変更 — fill_ratio 再計算が必要"""
        if self.corrected_images is None:
            return
        # デバウンス: 最後の操作から 300ms 後に実行
        if self._color_update_job:
            self.window.after_cancel(self._color_update_job)
        self._color_update_job = self.window.after(300, self._recollect_all)

    def _on_area_changed(self, _value):
        """Area スライダー変更 — 再分類のみ（fill_ratio 再計算不要）"""
        if self.all_ratios is None:
            return
        if self._area_update_job:
            self.window.after_cancel(self._area_update_job)
        self._area_update_job = self.window.after(150, self._reclassify_only)

    def _recollect_all(self):
        """color_threshold 変更時: fill_ratio を全画像で再収集し再分類"""
        ct = self.color_var.get()
        at = self.area_var.get()
        self.all_ratios, self.current_analysis = recollect_and_reclassify(
            self.corrected_images, self.coordinates, ct, at)
        self._update_stats()
        self._update_gallery()

    def force_recollect_all(self):
        """外部（StudentAnswerSheetViewer等）から呼ばれる再計算メソッド。
        現在のスライダー値で fill_ratio を再収集し、ギャラリーを更新する。"""
        if self.corrected_images is None:
            return
        self._recollect_all()

    def _on_recalc_clicked(self):
        """「この閾値で再判定」ボタン押下時のハンドラ"""
        if self.corrected_images is None:
            return
        self._recollect_all()

    def _reclassify_only(self):
        """area_threshold のみ変更時: 既存fill_ratioで再分類"""
        at = self.area_var.get()
        self.current_analysis = reclassify_with_threshold(self.all_ratios, at)
        self._update_stats()
        self._update_gallery()

    # ─────────────────────────────────────────────
    # 統計情報更新
    # ─────────────────────────────────────────────

    def _update_stats(self):
        """統計情報テキストを更新"""
        if self.current_analysis is None:
            return
        a = self.current_analysis
        text = (
            f"分析エリア数: {a['total_count']}\n"
            f"マーク有:     {a['marked_count']}    ({a['marked_count']/max(a['total_count'],1)*100:.1f}%)\n"
            f"マーク無:     {a['unmarked_count']}  ({a['unmarked_count']/max(a['total_count'],1)*100:.1f}%)\n"
            f"有/無平均:   {a['cluster_marked_mean']:.3f} / {a['cluster_unmarked_mean']:.3f}\n"
            f"閾値:        色={self.color_var.get():.3f}  面積={self.area_var.get():.3f}"
        )
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert(tk.END, text)
        self.stats_text.config(state=tk.DISABLED)

    # ─────────────────────────────────────────────
    # ギャラリー表示
    # ─────────────────────────────────────────────

    def _update_gallery(self):
        """4カテゴリのギャラリーを更新"""
        if self.current_analysis is None:
            return

        # 既存ウィジェットをクリア
        for w in self.gallery_frame.winfo_children():
            w.destroy()
        self._thumb_refs.clear()

        FONT_S = (UI_FONT, get_ui_font_size(8))
        FONT_B = (UI_FONT, get_ui_font_size(9), "bold")
        SEC_BG = "#FFFFFF"

        a = self.current_analysis

        # --- ギャラリーヘッダー: マーク/非マークのサマリ ---
        summary_frame = tk.Frame(self.gallery_frame, bg="#E8EAF6", padx=8, pady=5)
        summary_frame.pack(fill=tk.X, pady=(0, 4))
        marked_total = a['marked_count']
        unmarked_total = a['unmarked_count']
        border_marked = len(a['borderline_marked'])
        border_unmarked = len(a['borderline_unmarked'])
        summary_text = (
            f"全 {a['total_count']} エリア  |  "
            f"マーク有: {marked_total}  (うち境界付近: {border_marked})  |  "
            f"マーク無: {unmarked_total}  (うち境界付近: {border_unmarked})"
        )
        tk.Label(summary_frame, text=summary_text, font=(UI_FONT, get_ui_font_size(9)),
                 bg="#E8EAF6", fg="#283593").pack(anchor=tk.W)
        tk.Label(summary_frame, text="※ サムネイルをクリックすると答案を詳細表示できます",
                 font=(UI_FONT, get_ui_font_size(8)), bg="#E8EAF6", fg="#5C6BC0").pack(anchor=tk.W)

        categories = [
            ("✓ 確実にマーク有  (安定)", a['stable_marked'], "#2E7D32", "#E8F5E9"),
            ("▲ マーク有 (境界付近・薄い順)", a['borderline_marked'], "#F57F17", "#FFF8E1"),
            ("▼ マーク無 (境界付近・濃い順)", a['borderline_unmarked'], "#E65100", "#FFF3E0"),
            ("✕ 確実にマーク無  (安定)", a['stable_unmarked'], "#546E7A", "#ECEFF1"),
        ]

        for cat_title, items, title_color, bg_color in categories:
            # カテゴリヘッダー
            header = tk.Frame(self.gallery_frame, bg=bg_color, padx=5, pady=3)
            header.pack(fill=tk.X, pady=(8, 2))
            tk.Label(header, text=f"{cat_title}  ({len(items)}件)", font=FONT_B,
                     fg=title_color, bg=bg_color).pack(anchor=tk.W)

            if not items:
                tk.Label(self.gallery_frame, text="  (該当なし)", font=FONT_S,
                         fg="gray", bg=SEC_BG).pack(anchor=tk.W, padx=10)
                continue

            # サムネイルグリッド
            grid = tk.Frame(self.gallery_frame, bg=SEC_BG)
            grid.pack(fill=tk.X, padx=5, pady=2)

            for idx, item in enumerate(items):
                col = idx % self.GALLERY_COLS
                row = idx // self.GALLERY_COLS
                if row >= self.GALLERY_ROWS_PER_CAT:
                    break

                cell = tk.Frame(grid, bg=SEC_BG, padx=2, pady=2)
                cell.grid(row=row, column=col, sticky="nw")

                # サムネイル画像を生成
                thumb = self._create_thumbnail(item)
                if thumb:
                    self._thumb_refs.append(thumb)
                    thumb_label = tk.Label(cell, image=thumb, bg=SEC_BG, cursor="hand2")
                    thumb_label.pack()
                    # クリックで答案ビューアを開く（question_noも渡す）
                    thumb_label.bind("<Button-1>",
                        lambda e, img_name=item.get('image_name', ''), q_no=item.get('question_no'): self._open_student_viewer(img_name, q_no))
                else:
                    tk.Label(cell, text="[img]", width=10, height=4, bg="#EEE",
                             relief=tk.SUNKEN).pack()

                # 情報テキスト
                ratio_pct = item['fill_ratio'] * 100
                info = f"Q{item['question_no']}-C{item['choice']}\n{ratio_pct:.1f}%"
                if 'image_name' in item:
                    short_name = item['image_name'][-12:]
                    info += f"\n{short_name}"
                info_label = tk.Label(cell, text=info, font=("Consolas", 7), bg=SEC_BG,
                         justify=tk.CENTER, cursor="hand2")
                info_label.pack()
                # テキストクリックでも答案ビューアを開く
                info_label.bind("<Button-1>",
                    lambda e, img_name=item.get('image_name', ''), q_no=item.get('question_no'): self._open_student_viewer(img_name, q_no))

    def _open_student_viewer(self, image_name, highlight_question_no=None):
        """サムネイルクリック時に、対応する生徒の答案をStudentAnswerSheetViewerで開く"""
        if not self.corrected_images or not self.coordinates:
            return

        # 対応する画像を検索
        gray = None
        for name, g in self.corrected_images:
            if name == image_name:
                gray = g
                break
        if gray is None:
            return

        # 現在の閾値を取得
        ct = self.color_var.get()
        at = self.area_var.get()

        # 答案ビューアを開く（非モーダル — 複数同時に開ける）
        StudentAnswerSheetViewer(
            parent_window=self.window,
            image_name=image_name,
            gray_image=gray,
            coordinates=self.coordinates,
            color_threshold=ct,
            area_threshold=at,
            calibrator_gui=self,
            highlight_question_no=highlight_question_no
        )

    def _create_thumbnail(self, item):
        """マーク領域のサムネイル画像を生成"""
        try:
            img_name = item.get('image_name', '')
            # corrected_images から対応する画像を検索
            gray = None
            for name, g in self.corrected_images:
                if name == img_name:
                    gray = g
                    break
            if gray is None:
                return None

            x, y, w, h = item['x'], item['y'], item['w'], item['h']
            img_h, img_w = gray.shape[:2]

            # ROIを expand して周辺コンテキストも見せる
            expand = 2.5
            cx, cy = x + w / 2, y + h / 2
            ew, eh = int(w * expand), int(h * expand)
            ex, ey = int(cx - ew / 2), int(cy - eh / 2)
            ex = max(0, min(ex, img_w - 1))
            ey = max(0, min(ey, img_h - 1))
            ew = min(ew, img_w - ex)
            eh = min(eh, img_h - ey)

            roi = gray[ey:ey+eh, ex:ex+ew]
            if roi.size == 0:
                return None

            # RGB に変換してリサイズ
            rgb = cv2.cvtColor(roi, cv2.COLOR_GRAY2RGB)

            # マーク枠を描画（赤線）
            # 座標をROI基準に変換
            rx, ry = x - ex, y - ey
            cv2.rectangle(rgb, (rx, ry), (rx + w, ry + h), (255, 0, 0), 1)

            pil_img = Image.fromarray(rgb)
            pil_img = pil_img.resize((self.THUMB_SIZE, self.THUMB_SIZE), getattr(Image, 'LANCZOS', getattr(Image, 'Resampling', Image).LANCZOS))
            return ImageTk.PhotoImage(pil_img)
        except Exception:
            return None

    # ─────────────────────────────────────────────
    # テスト読み取り
    # ─────────────────────────────────────────────

    def _run_test_reading(self):
        """ランダムにマーク領域を選んで現在の閾値で読み取りテスト"""
        if not self.corrected_images or not self.coordinates:
            return

        import random

        ct = self.color_var.get()
        at = self.area_var.get()

        # ランダムに画像を1枚選択
        img_name, gray = random.choice(self.corrected_images)

        # ランダムに10個のマーク領域を選択
        sample_coords = random.sample(self.coordinates, min(10, len(self.coordinates)))

        # 選択した領域の fill_ratio を計算
        ratios = collect_mark_fill_ratios(gray, sample_coords, ct)

        # 結果をテキスト表示
        lines = [f"画像: ...{img_name[-20:]}", f"閾値: 色={ct:.3f} 面積={at:.3f}", ""]
        for r in ratios:
            ratio_pct = r['fill_ratio'] * 100
            is_marked = r['fill_ratio'] > at
            mark_str = "● マーク有" if is_marked else "○ マーク無"
            lines.append(f"Q{r['question_no']:>2}-C{r['choice']}: {ratio_pct:5.1f}% → {mark_str}")

        self.test_result_text.config(state=tk.NORMAL)
        self.test_result_text.delete("1.0", tk.END)
        self.test_result_text.insert(tk.END, "\n".join(lines))
        self.test_result_text.config(state=tk.DISABLED)

    # ─────────────────────────────────────────────
    # 適用
    # ─────────────────────────────────────────────

    def _apply_and_close(self):
        """決定した閾値をメインGUIに反映して閉じる"""
        ct = self.color_var.get()
        at = self.area_var.get()

        if self.parent_color_var is not None:
            self.parent_color_var.set(ct)
        if self.parent_area_var is not None:
            self.parent_area_var.set(at)

        self._on_close()


# ========================================
# 採点結果描画 詳細設定GUI
# ========================================

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
        # モードに応じたウィンドウサイズ
        if self._show_mark_section and self._show_desc_section:
            self.window.geometry("480x520")
        else:
            self.window.geometry("480x320")
        self.window.resizable(False, False)
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

        # ===== セクション1: マーク採点結果 =====
        sec1 = tk.LabelFrame(main, text="マーク採点結果", font=FONT_B,
                             bg=SEC_BG, fg=HEADER_FG, padx=10, pady=8)
        if self._show_mark_section:
            sec1.pack(fill=tk.X, pady=(0, 8))

        # --- 表示項目 ---
        tk.Label(sec1, text="表示項目:", font=FONT, bg=SEC_BG, fg="#333").pack(anchor=tk.W)

        chk_frame = tk.Frame(sec1, bg=SEC_BG)
        chk_frame.pack(fill=tk.X, padx=(15, 0), pady=(2, 5))

        for text, var in [
            ("正答選択肢番号を表示", self.var_show_correct),
            ("○×△マークを表示", self.var_show_ox),
            ("得点を表示", self.var_show_score),
            ("観点を表示", self.var_show_aspect),
            ("全員正解（特例）の正答位置に★を表示", self.var_show_star),
            ("文字の背景を白塗りする（9/0マークの印字と重なる場合に有効）", self.var_bg_white),
        ]:
            tk.Checkbutton(chk_frame, text=text, variable=var,
                           font=FONT_S, bg=SEC_BG, anchor=tk.W,
                           cursor="hand2").pack(fill=tk.X)

        # --- 描画位置オフセット ---
        tk.Frame(sec1, bg="#E0E0E0", height=1).pack(fill=tk.X, pady=(5, 5))

        pos_frame = tk.Frame(sec1, bg=SEC_BG)
        pos_frame.pack(fill=tk.X)

        tk.Label(pos_frame, text="描画位置オフセット:", font=FONT, bg=SEC_BG, fg="#333").pack(side=tk.LEFT)
        tk.Label(pos_frame, text="(0=デフォルト, ←負 / 正→, 枠外はみ出しOK)", font=FONT_S,
                 bg=SEC_BG, fg="#999").pack(side=tk.LEFT, padx=(5, 0))

        offset_ctrl = tk.Frame(sec1, bg=SEC_BG)
        offset_ctrl.pack(fill=tk.X, padx=(15, 0), pady=(2, 0))

        def _offset_step(delta):
            """offsetを小数点第1位で丸めて増減"""
            self.var_offset.set(round(self.var_offset.get() + delta, 1))

        tk.Button(offset_ctrl, text="◀◀", font=FONT_S, width=3,
                  command=lambda: _offset_step(-1.0),
                  relief=tk.FLAT, bg="#E0E0E0", cursor="hand2").pack(side=tk.LEFT, padx=(0, 1))
        tk.Button(offset_ctrl, text="◀", font=FONT_S, width=3,
                  command=lambda: _offset_step(-0.5),
                  relief=tk.FLAT, bg="#E0E0E0", cursor="hand2").pack(side=tk.LEFT, padx=(0, 1))
        tk.Button(offset_ctrl, text="◀.", font=FONT_S, width=3,
                  command=lambda: _offset_step(-0.1),
                  relief=tk.FLAT, bg="#F0F0F0", cursor="hand2").pack(side=tk.LEFT)

        self._offset_label = tk.Label(offset_ctrl, text="0.0",
                                      font=(UI_FONT, get_ui_font_size(11), "bold"), bg=SEC_BG,
                                      width=5, anchor=tk.CENTER)
        self._offset_label.pack(side=tk.LEFT, padx=5)
        # var_offset 変更時にラベル更新
        def _update_offset_label(*_):
            self._offset_label.config(text=f"{self.var_offset.get():.1f}")
        self.var_offset.trace_add("write", _update_offset_label)
        _update_offset_label()  # 初期表示

        tk.Button(offset_ctrl, text=".▶", font=FONT_S, width=3,
                  command=lambda: _offset_step(0.1),
                  relief=tk.FLAT, bg="#F0F0F0", cursor="hand2").pack(side=tk.LEFT)
        tk.Button(offset_ctrl, text="▶", font=FONT_S, width=3,
                  command=lambda: _offset_step(0.5),
                  relief=tk.FLAT, bg="#E0E0E0", cursor="hand2").pack(side=tk.LEFT, padx=(1, 0))
        tk.Button(offset_ctrl, text="▶▶", font=FONT_S, width=3,
                  command=lambda: _offset_step(1.0),
                  relief=tk.FLAT, bg="#E0E0E0", cursor="hand2").pack(side=tk.LEFT, padx=(1, 0))

        tk.Button(offset_ctrl, text="📐 位置プレビュー...", font=FONT_S,
                  command=self._open_position_preview,
                  relief=tk.FLAT, bg="#90CAF9", cursor="hand2").pack(side=tk.LEFT, padx=(15, 0))

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
            ("観点を表示", self.var_desc_show_aspect),
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
            'descriptive_show_aspect': self.var_desc_show_aspect.get(),
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

    # ─────────────────────────────────────────────
    # 位置プレビュー（サブウィンドウ）
    # ─────────────────────────────────────────────

    def _open_position_preview(self):
        """マーク採点結果の描画位置プレビューウィンドウを開く。

        最初の問題の補正済み画像を読み込み、現在のオフセットで
        どこに○×や得点が描画されるかをプレビューする。
        ◀▶ボタンでリアルタイムにオフセットを変更して確認できる。
        """
        from constants import RESULTS_FOLDER, BOXED_FOLDER

        if not self.image_folder or not self.coord_excel_path:
            messagebox.showinfo("情報",
                                "画像フォルダまたは座標ファイルが未設定のため、\n"
                                "位置プレビューは利用できません。\n\n"
                                "オフセット値を直接入力してください。",
                                parent=self.window)
            return

        boxed_folder = Path(self.image_folder) / RESULTS_FOLDER / BOXED_FOLDER
        if not boxed_folder.exists():
            messagebox.showinfo("情報",
                                "補正済み画像フォルダが見つかりません。\n"
                                "Step 1（OMR認識）を先に実行してください。\n\n"
                                "オフセット値を直接入力してください。",
                                parent=self.window)
            return

        image_files = sorted(boxed_folder.glob("*.jpg")) + sorted(boxed_folder.glob("*.png"))
        if not image_files:
            messagebox.showinfo("情報", "補正済み画像が見つかりません。",
                                parent=self.window)
            return

        try:
            from omr_engine import parse_excel_coordinates
            coordinates, _ = parse_excel_coordinates(
                self.coord_excel_path, self.skip_questions
            )
        except Exception as e:
            messagebox.showerror("エラー",
                                 f"座標データの読み込みに失敗しました:\n{e}",
                                 parent=self.window)
            return

        # 最初の問題（skip_questions + 1 が最初の採点対象問題）の座標を取得
        first_q_no = self.skip_questions + 1
        q_coords = [c for c in coordinates if c['question_no'] == first_q_no]
        if not q_coords:
            messagebox.showinfo("情報",
                                f"問題 {first_q_no} の座標が見つかりません。",
                                parent=self.window)
            return

        # 画像読み込み（日本語パス対応: np.fromfile + cv2.imdecode）
        img_path = str(image_files[0])
        img_array = np.fromfile(img_path, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            messagebox.showerror("エラー", "画像の読み込みに失敗しました。",
                                 parent=self.window)
            return

        # プレビューウィンドウを作成
        _PositionPreviewWindow(
            parent=self.window,
            image=img,
            question_coords=q_coords,
            offset_var=self.var_offset,
        )


class _PositionPreviewWindow:
    """マーク採点結果の描画位置プレビュー（内部クラス）

    1問目の画像を表示し、オフセットに応じた描画位置を矩形で示す。
    ◀▶ボタンまたはメインの offset spinbox で即座に反映する。
    """

    # プレビュー表示の最大サイズ
    PREVIEW_MAX_W = 1040
    PREVIEW_MAX_H = 650
    # プレビュー拡大倍率の上限（小さいマーク領域を見やすく拡大）
    PREVIEW_SCALE_CAP = 2.0
    # クロップ領域の横方向拡張比率（1.0=拡張なし、1.5=横幅1.5倍）
    PREVIEW_CROP_EXPAND = 1.5

    def __init__(self, parent, image, question_coords, offset_var):
        """
        Args:
            parent: 親ウィンドウ
            image: OpenCV BGR 画像 (フルサイズ)
            question_coords: 1問分の座標辞書リスト
            offset_var: tk.DoubleVar（オフセット、小数対応）
        """
        self.parent = parent
        self.full_image = image
        self.q_coords = question_coords
        self.offset_var = offset_var
        self.num_choices = len(question_coords)

        # 問題エリアのバウンディングボックスを算出（枠外も見せる広いマージン）
        xs = [c['x'] for c in question_coords]
        ys = [c['y'] for c in question_coords]
        ws = [c['width'] for c in question_coords]
        hs = [c['height'] for c in question_coords]

        cell_width = question_coords[0]['width']
        margin_x = int(cell_width * 4)  # 左右に4セル分の余白（枠外確認用）
        margin_y = 30
        self.crop_x1 = max(0, min(xs) - margin_x)
        self.crop_y1 = max(0, min(ys) - margin_y)
        self.crop_x2 = min(image.shape[1], max(x + w for x, w in zip(xs, ws)) + margin_x)
        self.crop_y2 = min(image.shape[0], max(y + h for y, h in zip(ys, hs)) + margin_y)

        # クロップ幅を横方向に拡張（オフセット変更時に左右の余裕を確保するため）
        crop_w = self.crop_x2 - self.crop_x1
        extra = int(crop_w * (self.PREVIEW_CROP_EXPAND - 1.0) / 2)
        self.crop_x1 = max(0, self.crop_x1 - extra)
        self.crop_x2 = min(image.shape[1], self.crop_x2 + extra)

        # ウィンドウ
        self.win = tk.Toplevel(parent)
        self.win.title("📐 描画位置プレビュー — 問題1")
        self.win.transient(parent)
        self.win.grab_set()
        self.win.configure(bg="#F5F7FA")

        self._build_ui()
        self._draw_preview()

        # offset_var の変更を監視
        self._trace_id = self.offset_var.trace_add("write", lambda *_: self._draw_preview())
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        BG = "#F5F7FA"
        FONT = (UI_FONT, get_ui_font_size(9))
        FONT_B = (UI_FONT, get_ui_font_size(9), "bold")
        FONT_S = (UI_FONT, get_ui_font_size(8))

        # コントロール行
        ctrl = tk.Frame(self.win, bg=BG, padx=8, pady=5)
        ctrl.pack(fill=tk.X)

        tk.Label(ctrl, text="オフセット:", font=FONT, bg=BG).pack(side=tk.LEFT)

        def _pv_step(delta):
            self.offset_var.set(round(self.offset_var.get() + delta, 1))

        tk.Button(ctrl, text="◀◀", font=FONT_S, width=3,
                  command=lambda: _pv_step(-1.0),
                  relief=tk.FLAT, bg="#E0E0E0", cursor="hand2").pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="◀", font=FONT_S, width=3,
                  command=lambda: _pv_step(-0.5),
                  relief=tk.FLAT, bg="#E0E0E0", cursor="hand2").pack(side=tk.LEFT)
        tk.Button(ctrl, text="◀.", font=FONT_S, width=3,
                  command=lambda: _pv_step(-0.1),
                  relief=tk.FLAT, bg="#F0F0F0", cursor="hand2").pack(side=tk.LEFT)

        self._lbl_offset = tk.Label(ctrl, text="0.0",
                                    font=(UI_FONT, get_ui_font_size(12), "bold"), bg=BG,
                                    width=5, anchor=tk.CENTER)
        self._lbl_offset.pack(side=tk.LEFT, padx=5)
        # var変更時にラベル更新
        def _pv_update_lbl(*_):
            self._lbl_offset.config(text=f"{self.offset_var.get():.1f}")
        self.offset_var.trace_add("write", _pv_update_lbl)
        _pv_update_lbl()  # 初期表示

        tk.Button(ctrl, text=".▶", font=FONT_S, width=3,
                  command=lambda: _pv_step(0.1),
                  relief=tk.FLAT, bg="#F0F0F0", cursor="hand2").pack(side=tk.LEFT)
        tk.Button(ctrl, text="▶", font=FONT_S, width=3,
                  command=lambda: _pv_step(0.5),
                  relief=tk.FLAT, bg="#E0E0E0", cursor="hand2").pack(side=tk.LEFT)
        tk.Button(ctrl, text="▶▶", font=FONT_S, width=3,
                  command=lambda: _pv_step(1.0),
                  relief=tk.FLAT, bg="#E0E0E0", cursor="hand2").pack(side=tk.LEFT, padx=2)

        tk.Button(ctrl, text="閉じる", font=FONT, width=8,
                  command=self._on_close,
                  relief=tk.FLAT, bg="#EEEEEE", cursor="hand2").pack(side=tk.RIGHT)

        # 説明
        tk.Label(ctrl, text="赤枠＝○× / 青枠＝得点・観点", font=FONT_S,
                 bg=BG, fg="#999").pack(side=tk.RIGHT, padx=10)

        # 画像表示
        self._canvas = tk.Canvas(self.win, bg="#333", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._photo_ref = None  # GC防止

    def _draw_preview(self):
        """現在のオフセットで描画位置を矢印付き矩形で示す（ピクセルベース、枠外対応）"""
        offset = float(self.offset_var.get())

        # 元画像からクロップ
        crop = self.full_image[self.crop_y1:self.crop_y2,
                               self.crop_x1:self.crop_x2].copy()

        # 各選択肢の矩形を薄いグレーで描画（参考用）
        for i, c in enumerate(self.q_coords):
            rx = c['x'] - self.crop_x1
            ry = c['y'] - self.crop_y1
            rw, rh = c['width'], c['height']
            cv2.rectangle(crop, (rx, ry), (rx + rw, ry + rh),
                          (200, 200, 200), 1)
            # 選択肢番号を小さく表示
            cv2.putText(crop, str(i + 1), (rx + 2, ry + rh - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)

        # ピクセルベースオフセット計算（image_renderer.py と同じロジック）
        base_coord = self.q_coords[self.num_choices - 2]  # デフォルト基準位置
        cell_width = self.q_coords[0]['width']
        pixel_offset = offset * cell_width

        # ○× 位置 — 赤枠（クランプなし、枠外OK）
        ox_x = int(base_coord['x'] + pixel_offset) - self.crop_x1
        ox_y = base_coord['y'] - self.crop_y1
        ox_w, ox_h = base_coord['width'], base_coord['height']
        cv2.rectangle(crop, (ox_x, ox_y), (ox_x + ox_w, ox_y + ox_h),
                      (0, 0, 255), 3)

        # 得点・観点位置（○×の次のセル幅分右）— 青枠
        sc_x = int(base_coord['x'] + pixel_offset + cell_width) - self.crop_x1
        sc_y = base_coord['y'] - self.crop_y1
        sc_w, sc_h = base_coord['width'], base_coord['height']
        cv2.rectangle(crop, (sc_x, sc_y), (sc_x + sc_w, sc_y + sc_h),
                      (255, 0, 0), 3)

        # サンプルテキストを描画（視覚化）
        try:
            pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(pil_crop)
            try:
                fnt = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 14)
            except Exception:
                fnt = ImageFont.load_default()

            # ○× サンプル
            draw.text((ox_x + 4, ox_y + 2), "○", font=fnt, fill=(255, 0, 0))
            # 得点・観点サンプル
            draw.text((sc_x + 2, sc_y + 2), "3①", font=fnt, fill=(0, 0, 0))

            crop = cv2.cvtColor(np.array(pil_crop), cv2.COLOR_RGB2BGR)
        except Exception:
            pass

        # スケーリングしてCanvas表示
        h, w = crop.shape[:2]
        scale = min(self.PREVIEW_MAX_W / w, self.PREVIEW_MAX_H / h, self.PREVIEW_SCALE_CAP)
        disp_w, disp_h = int(w * scale), int(h * scale)
        crop_resized = cv2.resize(crop, (disp_w, disp_h), interpolation=cv2.INTER_AREA if scale <= 1.0 else cv2.INTER_LINEAR)

        pil_img = Image.fromarray(cv2.cvtColor(crop_resized, cv2.COLOR_BGR2RGB))
        self._photo_ref = ImageTk.PhotoImage(pil_img)

        self._canvas.config(width=disp_w, height=disp_h)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo_ref)

        # ウィンドウサイズ調整（コントロール行+マージン用に十分な高さを確保）
        self.win.geometry(f"{disp_w + 16}x{disp_h + 90}")

    def _on_close(self):
        """閉じる"""
        self.offset_var.trace_remove("write", self._trace_id)
        self.win.grab_release()
        self.win.destroy()


# ========================================
# v4.0 起動モード選択ダイアログ
# ========================================

class StartupModeDialog:
    """アプリ起動時のモード選択ダイアログ

    5つのモードボタン（標準3種＋数学マーク2種）＋採点再開ボタンを表示し、
    ユーザーが選択したモードを返す。

    使い方:
        dialog = StartupModeDialog(root)
        mode = dialog.result           # MODE_MARK_ONLY etc. or None (閉じた場合)
        mark_format = dialog.mark_format  # MARK_FORMAT_STANDARD / MARK_FORMAT_MULTI_DIGIT
    """

    def __init__(self, root):
        self.root = root
        self.result = None
        self.mark_format = MARK_FORMAT_STANDARD
        self._session_path = None

        self._build_dialog()
        self.dialog.wait_window()

    def _build_dialog(self):
        """ダイアログUIを構築"""
        self.dialog = tk.Toplevel(self.root)
        from constants import APP_VERSION
        self.dialog.title(f"採点侍 v{APP_VERSION}")
        # transient(root) は使わない: root.withdraw() 中に呼ぶと
        # ダイアログも非表示になりフリーズするため
        self.dialog.grab_set()
        self.dialog.resizable(False, False)
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

        BG = "#F5F7FA"
        self.dialog.configure(bg=BG)

        # ヘッダー
        header = tk.Frame(self.dialog, bg=BG, padx=30, pady=20)
        header.pack(fill=tk.X)
        tk.Label(
            header, text="採点侍",
            font=(UI_FONT, get_ui_font_size(22), "bold"), fg="#1976D2", bg=BG,
        ).pack()
        tk.Label(
            header, text="採点モードを選択してください",
            font=(UI_FONT, get_ui_font_size(10)), fg="#546E7A", bg=BG,
        ).pack(pady=(5, 0))

        # ボタンエリア
        btn_area = tk.Frame(self.dialog, bg=BG, padx=40, pady=10)
        btn_area.pack(fill=tk.X)

        BTN_W = 32
        BTN_H = 3
        BTN_FONT = (UI_FONT, get_ui_font_size(11), "bold")
        DESC_FONT = (UI_FONT, get_ui_font_size(8))

        # マーク採点のみ
        self._make_mode_button(
            btn_area, "📝  マーク採点のみ",
            "座標ファイルを使ったOMR認識・マーク採点を実行します",
            "#A5D6A7", MODE_MARK_ONLY, BTN_W, BTN_H, BTN_FONT, DESC_FONT, BG,
        )

        # マーク＋記述
        self._make_mode_button(
            btn_area, "📝✏  マーク採点 ＋ 記述採点",
            "マーク採点に加えて、記述式問題の採点も行います",
            "#90CAF9", MODE_MARK_AND_DESCRIPTIVE, BTN_W, BTN_H, BTN_FONT, DESC_FONT, BG,
        )

        # 記述のみ
        self._make_mode_button(
            btn_area, "✏  記述採点のみ",
            "座標ファイル不要。答案画像から記述問題のみを採点します",
            "#B39DDB", MODE_DESCRIPTIVE_ONLY, BTN_W, BTN_H, BTN_FONT, DESC_FONT, BG,
        )

        # 数学マーク（複数桁）のみ
        self._make_mode_button(
            btn_area, "🔢  数学マーク採点のみ",
            "共通テスト数学式。複数のマーク行で1つの値(-24等)を完答採点します",
            "#FFCC80", MODE_MARK_ONLY, BTN_W, BTN_H, BTN_FONT, DESC_FONT, BG,
            mark_format=MARK_FORMAT_MULTI_DIGIT,
        )

        # 数学マーク＋記述
        self._make_mode_button(
            btn_area, "🔢✏  数学マーク採点 ＋ 記述採点",
            "数学マーク採点に加えて、記述式問題の採点も行います",
            "#FFAB91", MODE_MARK_AND_DESCRIPTIVE, BTN_W, BTN_H, BTN_FONT, DESC_FONT, BG,
            mark_format=MARK_FORMAT_MULTI_DIGIT,
        )

        # セパレータ
        tk.Frame(self.dialog, bg="#CFD8DC", height=1).pack(fill=tk.X, padx=40, pady=(15, 10))

        # 採点再開ボタン
        resume_frame = tk.Frame(self.dialog, bg=BG)
        resume_frame.pack(fill=tk.X, padx=40, pady=(0, 20))
        self._resume_btn = tk.Button(
            resume_frame, text="📂  採点再開（セッション復元）",
            command=self._on_resume,
            font=(UI_FONT, get_ui_font_size(9)), bg="#EEEEEE", fg="#546E7A",
            relief=tk.FLAT, cursor="hand2", height=2, width=BTN_W,
        )
        self._resume_btn.pack(fill=tk.X)

        # ダイアログを画面中央に配置
        self.dialog.update_idletasks()
        w = self.dialog.winfo_width()
        h = self.dialog.winfo_height()
        sw = self.dialog.winfo_screenwidth()
        sh = self.dialog.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.dialog.geometry(f"+{x}+{y}")

    def _make_mode_button(self, parent, text, desc, color, mode, w, h, font, desc_font, bg,
                          mark_format=MARK_FORMAT_STANDARD):
        """モードボタン＋説明テキストを作成"""
        frame = tk.Frame(parent, bg=bg)
        frame.pack(fill=tk.X, pady=4)
        tk.Button(
            frame, text=text, command=lambda: self._select(mode, mark_format),
            font=font, bg=color, relief=tk.FLAT, cursor="hand2",
            height=h, width=w, activebackground=color,
        ).pack(fill=tk.X)
        tk.Label(
            frame, text=desc, font=desc_font, fg="#78909C", bg=bg,
        ).pack(anchor=tk.W, padx=5)

    def _select(self, mode, mark_format=MARK_FORMAT_STANDARD):
        """モードを選択してダイアログを閉じる"""
        self.result = mode
        self.mark_format = mark_format
        self.dialog.grab_release()
        self.dialog.destroy()

    def _on_resume(self):
        """採点再開: セッションファイルを選択してモードを判定"""
        from tkinter import filedialog
        selected = filedialog.askopenfilename(
            parent=self.dialog,
            title="セッションファイルを選択",
            filetypes=[
                ("セッションファイル", "session_state.json"),
                ("JSONファイル", "*.json"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if not selected:
            return

        import json
        try:
            with open(selected, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Invalid format")
        except Exception:
            messagebox.showerror("エラー", "セッションファイルの読み込みに失敗しました。", parent=self.dialog)
            return

        # セッションからモードを復元
        app_mode = data.get("app_mode", None)
        if app_mode and app_mode in (MODE_MARK_ONLY, MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY):
            self.result = app_mode
        elif data.get("descriptive_enabled", False):
            self.result = MODE_MARK_AND_DESCRIPTIVE
        else:
            self.result = MODE_MARK_ONLY

        # マーク形式（複数桁モード）を復元。旧セッションはキーなし=標準
        saved_format = data.get("mark_format", MARK_FORMAT_STANDARD)
        self.mark_format = (saved_format if saved_format in (MARK_FORMAT_STANDARD, MARK_FORMAT_MULTI_DIGIT)
                            else MARK_FORMAT_STANDARD)

        self._session_path = selected
        self.dialog.grab_release()
        self.dialog.destroy()

    def _on_close(self):
        """ウィンドウを閉じた場合 — アプリ終了"""
        self.result = None
        self.dialog.grab_release()
        self.dialog.destroy()
