#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
採点侍 (SaitenSamurai) メインGUIモジュール

SaitenSamuraiGUI クラスを提供する。マークシート解析・採点・チェックの
統合GUIウィンドウを構築し、各処理パイプラインを制御する。

saitensamurai.py から分離されたモジュール。
"""

from __future__ import annotations

# ========================================
# インポート
# ========================================

# 標準ライブラリ
import logging
import sys
import json
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# サードパーティライブラリ
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from PIL import Image, ImageDraw, ImageFont

# 共通定数・ユーティリティ（constants.pyから）
from constants import (
    safe_print, extract_pdf_to_images, combine_images_to_pdf,
    HAS_PYMUPDF,
    APP_VERSION,
    MARK2_WIDTH, MARK2_HEIGHT,
    RESULTS_FOLDER, BOXED_FOLDER, CLEAN_FOLDER, RESULTS_DATA_FOLDER,
    SCORED_FOLDER, FINAL_REPORT_FOLDER,
    MARK_AREAS_FILE, ANSWER_KEY_FILE,
    STUDENT_SUMMARY_FILE, EXAM_SUMMARY_FILE,
    CTT_ANALYSIS_EXCEL_FILE, CTT_ANALYSIS_PDF_FILE, SCORED_PDF_FILE,
    R_EXPORT_FOLDER,
    READING_RESULTS_FOLDER_NAME, SESSION_STATE_FILE,
    get_rendering_settings, DEFAULT_RENDERING_SETTINGS,
    resource_path,
    MODE_MARK_ONLY, MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY,
    MARK_FORMAT_STANDARD, MARK_FORMAT_MULTI_DIGIT,
    OMR_MODE_THRESHOLD, OMR_MODE_KMEANS,
    atomic_json_save, load_json_safe,
    open_in_file_manager, get_ui_font_family, get_ui_font_size,
)

# 日本語UIフォント（Windows: Yu Gothic UI, Mac: Hiragino Sans）
UI_FONT = get_ui_font_family()

# 採点コアロジック（scoring_engine.pyから）
from scoring_engine import (
    number_to_circled, load_template, load_mark2_results, score_answers,
)

# 画像アライメント（採点モード非依存。image_alignment.pyから）
from image_alignment import (
    detect_corner_markers, compute_output_scale,
    apply_perspective_transform, imread_unicode,
)

# OMR認識エンジン（マーク採点専用。omr_engine.pyから）
from omr_engine import (
    parse_excel_coordinates, process_box_drawer, save_recognition_results,
    generate_template, process_folder,
)

# 画像描画・採点結果レンダリング（image_renderer.pyから）
from image_renderer import (
    process_scoring, draw_scoring_results, draw_total_score,
)

# サマリー生成（summary_generator.pyから）
from summary_generator import (
    process_summary_generation, generate_student_summary, generate_exam_summary,
    process_descriptive_only_summary,
)

# CTT分析（ctt_analyzer.pyから）
from ctt_analyzer import generate_ctt_analysis

# Checker機能（mark_checker.pyから）
from mark_checker import detect_errors_checker, apply_corrections_checker

# GUIサブウィンドウ（gui_components.pyから）
from gui_components import (
    MarkCheckerGUI,
    StudentAnswerSheetViewer,
    ThresholdCalibratorGUI,
    RenderingSettingsGUI,
)

# 注: descriptive_scorer, name_trimmer はメソッド内で遅延インポートされる


# ========================================
# ツールチップ ヘルパー
# ========================================

class _ToolTip:
    """軽量ツールチップ。ウィジェットにマウスオーバーで表示する。"""

    def __init__(self, widget: tk.Widget, text: str, *, delay: int = 400):
        self._widget = widget
        self.text = text
        self._delay = delay
        self._tipwindow: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def _schedule(self, _event: tk.Event | None = None):
        self._cancel()
        self._after_id = self._widget.after(self._delay, self._show)

    def _show(self):
        if self._tipwindow or not self.text:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#FFFDE7", foreground="#333333",
            relief=tk.SOLID, borderwidth=1,
            font=(UI_FONT, get_ui_font_size(9)), wraplength=320, padx=6, pady=4,
        )
        label.pack()
        self._tipwindow = tw

    def _hide(self, _event: tk.Event | None = None):
        self._cancel()
        if self._tipwindow:
            self._tipwindow.destroy()
            self._tipwindow = None

    def _cancel(self):
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None

    def _on_destroy(self, _event: tk.Event | None = None):
        self._hide()
        self._cancel()


# ========================================
# SaitenSamuraiGUIクラス（メイン統合GUI）
# ========================================

class SaitenSamuraiGUI:
    """採点侍 統合GUIクラス"""
    def __init__(self, root, mode=MODE_MARK_AND_DESCRIPTIVE, restore_session_path=None,
                 mark_format=MARK_FORMAT_STANDARD):
        self.root = root
        self.app_mode = mode  # v4.0: アプリケーション動作モード
        # v4.7: マーク形式 (app_modeに直交するフラグ。multi_digit=複数桁設問モード)
        self.mark_format = mark_format
        self._restore_session_path = restore_session_path  # 起動時復元用

        # モード別タイトル
        mode_labels = {
            MODE_MARK_ONLY: "マーク採点",
            MODE_MARK_AND_DESCRIPTIVE: "マーク＋記述採点",
            MODE_DESCRIPTIVE_ONLY: "記述採点",
        }
        mode_label = mode_labels.get(mode, "")
        if self.mark_format == MARK_FORMAT_MULTI_DIGIT:
            mode_label = f"数学{mode_label}（複数桁）"
        self.root.title(f"採点侍 v{APP_VERSION} — {mode_label}")
        self.root.geometry("1100x600")
        
        # ウィンドウアイコン設定
        try:
            icon_path = resource_path("resources/icon.ico")
            if Path(icon_path).exists():
                self.root.iconbitmap(icon_path)
        except Exception:
            pass  # アイコンが見つからない場合はデフォルトのまま
        
        self.image_folder_path = tk.StringVar()
        self.coord_excel_path = tk.StringVar()
        self.skip_questions = tk.StringVar(value="4")
        self.template_path = tk.StringVar()
        self.mark2_result_path = tk.StringVar()
        
        # OMR閾値
        self.color_threshold = tk.DoubleVar(value=0.1)
        self.area_threshold = tk.DoubleVar(value=0.4)
        
        # OMR認識モード (v4.5)
        self.omr_mode = tk.StringVar(value=OMR_MODE_KMEANS)
        
        self.last_boxed_folder = None
        self.last_scored_folder = None
        self.last_results_folder = None
        self._name_trimmer = None  # 氏名欄トリミング用（cleanup管理）
        self._student_id_ocr_trimmer = None  # 学籍番号OCR用（cleanup管理）

        # 記述採点オプション（モードによりデフォルト値を決定）
        self.descriptive_enabled = tk.BooleanVar(
            value=(mode in (MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY))
        )
        # 記述採点の結果を分析ファイル（CTT/R）に含むか
        # デフォルトON。マークのみモードではチェックボックス自体が非表示
        self.include_descriptive_in_analysis = tk.BooleanVar(value=True)
        
        # 採点結果描画の詳細設定（セッション保存/復元対象）
        self.rendering_settings = get_rendering_settings()
        
        self.create_widgets()

        # ウィンドウ閉じるハンドラ（処理中のデータ保護）
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def _on_window_close(self):
        """メインウィンドウ閉じる際のガード。

        処理中の場合は確認ダイアログを表示し、誤ってデータを失うのを防ぐ。
        閉じる前にセッション状態を保存する。
        """
        if self._processing:
            if not messagebox.askyesno(
                "確認",
                "処理が実行中です。\n中断してウィンドウを閉じますか？\n\n"
                "※ 処理中のデータが失われる可能性があります。",
            ):
                return  # キャンセル: 閉じない

        # セッション状態の保存を試行
        try:
            self._save_session_state()
        except Exception:
            pass  # 保存失敗は許容

        self.root.destroy()
        
    def create_widgets(self):
        """ウィジェットの作成（パステルカラー・シンプルデザイン）"""
        # カラーパレット定義
        BG_COLOR = "#F5F7FA"      # 全体の背景色（薄いグレー）
        SECTION_BG = "#FFFFFF"    # セクションの背景色（白）
        TEXT_COLOR = "#333333"    # 基本テキスト色
        HEADER_TEXT = "#546E7A"   # ヘッダーテキスト色
        
        # パステルボタン色 (より落ち着いたトーンに調整)
        BTN_GREEN = "#A5D6A7"     # 枠描画 (Green 200)
        BTN_BLUE = "#90CAF9"      # 採点 (Blue 200)
        BTN_ORANGE = "#FFCC80"    # マークチェック (Orange 200)
        BTN_AMBER = "#FFE082"     # サマリー (Amber 200)
        BTN_GRAY = "#EEEEEE"      # 参照・開くボタン
        
        FONT_NORMAL = (UI_FONT, get_ui_font_size(9))
        FONT_BOLD = (UI_FONT, get_ui_font_size(9), "bold")
        FONT_TITLE = (UI_FONT, get_ui_font_size(12), "bold")
        
        # ルートウィンドウの背景設定
        self.root.configure(bg=BG_COLOR)
        
        # メインコンテナ
        main_container = tk.Frame(self.root, padx=10, pady=10, bg=BG_COLOR)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # =============================================================================
        # 下部: ログエリア (先に配置して下部に固定)
        # =============================================================================
        log_frame = tk.LabelFrame(main_container, text="処理ログ", padx=5, pady=2, font=FONT_BOLD, bg=SECTION_BG, fg=HEADER_TEXT, relief=tk.FLAT, bd=1)
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(5, 0))
        
        # 高さ10行固定
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD, font=("Consolas", 9), bg="#FAFAFA", relief=tk.FLAT, bd=1, height=4)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # プログレスバー（処理中のみ表示、determinateモードで進捗率表示）
        self._progress_bar = ttk.Progressbar(log_frame, mode="determinate", maximum=100, length=200)
        # 中断ボタン（処理中のみ表示）
        self._cancel_frame = tk.Frame(log_frame, bg=SECTION_BG)
        self._btn_cancel = tk.Button(
            self._cancel_frame, text="⏹ 中断", font=FONT_BOLD,
            bg="#E74C3C", fg="black", activebackground="#C0392B",
            command=self._request_cancel, width=10,
        )
        self._btn_cancel.pack(side=tk.RIGHT, padx=4, pady=2)
        self._cancel_event = threading.Event()
        # 初期状態では非表示（pack しない）
        self._processing = False

        # =============================================================================
        # 上部: コントロールエリア
        # =============================================================================
        controls_frame = tk.Frame(main_container, bg=BG_COLOR)
        controls_frame.pack(side=tk.TOP, fill=tk.X)
        
        # タイトル行（タイトル＋復元ボタン）
        title_row = tk.Frame(controls_frame, bg=BG_COLOR)
        title_row.pack(fill=tk.X, pady=(0, 5))

        # モード別タイトルテキスト
        mode_titles = {
            MODE_MARK_ONLY: f"採点侍 v{APP_VERSION} — マーク採点",
            MODE_MARK_AND_DESCRIPTIVE: f"採点侍 v{APP_VERSION} — マーク＋記述採点",
            MODE_DESCRIPTIVE_ONLY: f"採点侍 v{APP_VERSION} — 記述採点",
        }
        if self.mark_format == MARK_FORMAT_MULTI_DIGIT:
            mode_titles = {
                MODE_MARK_ONLY: f"採点侍 v{APP_VERSION} — 数学マーク採点（複数桁）",
                MODE_MARK_AND_DESCRIPTIVE: f"採点侍 v{APP_VERSION} — 数学マーク＋記述採点（複数桁）",
            }
        title_text = mode_titles.get(self.app_mode, f"採点侍 v{APP_VERSION}")
        tk.Label(title_row, text=title_text, font=FONT_TITLE, fg="#1976D2", bg=BG_COLOR).pack(side=tk.LEFT)
        tk.Button(
            title_row, text="📂 前回の状態を復元",
            command=self._restore_session_interactive,
            font=(UI_FONT, get_ui_font_size(8)), bg="#E3F2FD", relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(10, 0))

        # ---------------------------------------------------------
        # 1. データソース & 設定 (横並び)
        # ---------------------------------------------------------
        top_section = tk.Frame(controls_frame, bg=BG_COLOR)
        top_section.pack(fill=tk.X, pady=(0, 10))
        
        # 左側: ファイル入力
        input_group = tk.LabelFrame(top_section, text="1. データソース", padx=10, pady=5, font=FONT_BOLD, bg=SECTION_BG, fg=HEADER_TEXT, relief=tk.FLAT)
        input_group.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        # 画像フォルダ
        row1 = tk.Frame(input_group, bg=SECTION_BG)
        row1.pack(fill=tk.X, pady=2)
        tk.Label(row1, text="画像フォルダ", width=10, anchor=tk.W, font=FONT_NORMAL, bg=SECTION_BG).pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self.image_folder_path, font=(UI_FONT, get_ui_font_size(8)), bg="#F9F9F9", relief=tk.FLAT, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._btn_select_folder = tk.Button(row1, text="フォルダ選択", command=self.select_folder, width=10, bg=BTN_GRAY, relief=tk.FLAT, font=FONT_NORMAL)
        self._btn_select_folder.pack(side=tk.LEFT)
        self._btn_select_pdf = tk.Button(row1, text="PDF選択", command=self.select_pdf, width=8, bg=BTN_GRAY, relief=tk.FLAT, font=FONT_NORMAL)
        self._btn_select_pdf.pack(side=tk.LEFT, padx=(2, 0))
        self._btn_page_number_check = tk.Button(row1, text="🔢 ページ番号確認", command=self.run_page_number_check, bg=BTN_GRAY, relief=tk.FLAT, font=FONT_NORMAL)
        self._btn_page_number_check.pack(side=tk.LEFT, padx=(2, 0))
        _ToolTip(
            self._btn_page_number_check,
            "同じページ番号の答案だけをまとめたつもりのフォルダに、\n"
            "取り違えが混ざっていないかを確認する単発ツールです。\n"
            "印刷されたページ番号の数字を1回だけ矩形選択すると、\n"
            "全画像の同じ位置をOCRして多数決と異なるものを警告表示します。",
        )

        # 座標ファイル（記述のみモードでは非表示）
        row2 = tk.Frame(input_group, bg=SECTION_BG)
        self._coord_row = row2  # モード制御用に保持
        if self.app_mode != MODE_DESCRIPTIVE_ONLY:
            row2.pack(fill=tk.X, pady=2)
        tk.Label(row2, text="座標ファイル", width=10, anchor=tk.W, font=FONT_NORMAL, bg=SECTION_BG).pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=self.coord_excel_path, font=(UI_FONT, get_ui_font_size(8)), bg="#F9F9F9", relief=tk.FLAT, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._btn_select_excel = tk.Button(row2, text="ファイル選択", command=self.select_excel, width=10, bg=BTN_GRAY, relief=tk.FLAT, font=FONT_NORMAL)
        self._btn_select_excel.pack(side=tk.LEFT)

        # 右側: オプション（記述のみモードでは簡略化）
        option_group = tk.LabelFrame(top_section, text="2. オプション", padx=10, pady=5, font=FONT_BOLD, bg=SECTION_BG, fg=HEADER_TEXT, relief=tk.FLAT)
        option_group.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        opt_row1 = tk.Frame(option_group, bg=SECTION_BG)
        opt_row1.pack(fill=tk.X)
        
        # スキップ（記述のみモードでは非表示）
        self._skip_label1 = tk.Label(opt_row1, text="Skip:", font=FONT_NORMAL, bg=SECTION_BG)
        self._skip_entry = tk.Entry(opt_row1, textvariable=self.skip_questions, width=3, justify=tk.CENTER, bg="#F9F9F9", relief=tk.FLAT)
        self._skip_label2 = tk.Label(opt_row1, text="問", font=FONT_NORMAL, bg=SECTION_BG)
        if self.app_mode != MODE_DESCRIPTIVE_ONLY:
            self._skip_label1.pack(side=tk.LEFT)
            self._skip_entry.pack(side=tk.LEFT, padx=2)
            self._skip_label2.pack(side=tk.LEFT, padx=(0, 10))
        # ツールチップ: Skip の意味を補足
        _skip_tip_text = (
            "座標定義の先頭にある ID 列（学年・クラス・出席番号など）の数です。\n"
            "採点対象の問題ではない列を除外するために使います。\n"
            "Mark2 テンプレートの標準値は 4 です。"
        )
        _ToolTip(self._skip_label1, _skip_tip_text)
        _ToolTip(self._skip_entry, _skip_tip_text)
        _ToolTip(self._skip_label2, _skip_tip_text)

        # 記述採点オプション
        # マークのみモード: OFF固定
        # 記述のみモード: ON固定
        # マーク＋記述モード: ON固定（起動時のモード選択で確定済み）
        # チェックボックスは非表示（起動画面で選択済みのため）
        self._chk_descriptive = tk.Checkbutton(
            opt_row1, text="記述問題も採点する",
            variable=self.descriptive_enabled, bg=SECTION_BG,
            font=(UI_FONT, get_ui_font_size(8)), anchor=tk.W, cursor="hand2",
            command=self._on_descriptive_toggle,
        )
        # チェックボックスは pack しない（値は init で設定済み）
        
        # 記述のみモードのモード表示ラベル
        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            tk.Label(opt_row1, text="📝 記述採点モード",
                     font=(UI_FONT, get_ui_font_size(9), "bold"), fg="#7B1FA2", bg=SECTION_BG).pack(side=tk.LEFT)
        
        # OMR認識モード選択 (v4.5: 記述のみモード以外で表示)
        # 表示ラベル ↔ 内部値のマッピング
        self._omr_label_to_value = {
            "（推奨）クラスタリング": OMR_MODE_KMEANS,
            "しきい値による識別（従来式）": OMR_MODE_THRESHOLD,
        }
        self._omr_value_to_label = {v: k for k, v in self._omr_label_to_value.items()}
        self._omr_display_var = tk.StringVar(
            value=self._omr_value_to_label.get(self.omr_mode.get(), "（推奨）クラスタリング"))

        omr_mode_row = tk.Frame(option_group, bg=SECTION_BG)
        self._omr_mode_row = omr_mode_row
        if self.app_mode != MODE_DESCRIPTIVE_ONLY:
            omr_mode_row.pack(fill=tk.X, pady=(5, 0))

        tk.Label(omr_mode_row, text="認識方式:", font=(UI_FONT, get_ui_font_size(8)), bg=SECTION_BG).pack(side=tk.LEFT)
        self._omr_mode_combo = ttk.Combobox(
            omr_mode_row, textvariable=self._omr_display_var, width=22,
            values=list(self._omr_label_to_value.keys()), state="readonly",
        )
        self._omr_mode_combo.pack(side=tk.LEFT, padx=(5, 0))
        self._omr_mode_combo.bind("<<ComboboxSelected>>", self._on_omr_mode_changed)

        # スライダー群（同じ行の右側に配置 — 閾値モード時のみ表示）
        self._omr_slider_row = tk.Frame(omr_mode_row, bg=SECTION_BG)
        # 初期表示: 閾値モード かつ 記述のみでない場合のみ表示
        if self.app_mode != MODE_DESCRIPTIVE_ONLY and self.omr_mode.get() == OMR_MODE_THRESHOLD:
            self._omr_slider_row.pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(self._omr_slider_row, text="色:", font=(UI_FONT, get_ui_font_size(8)), bg=SECTION_BG).pack(side=tk.LEFT)
        tk.Scale(self._omr_slider_row, variable=self.color_threshold, from_=0.03, to=0.35, resolution=0.005, orient=tk.HORIZONTAL, bg=SECTION_BG, relief=tk.FLAT, length=80).pack(side=tk.LEFT, padx=2)

        tk.Label(self._omr_slider_row, text="面積:", font=(UI_FONT, get_ui_font_size(8)), bg=SECTION_BG).pack(side=tk.LEFT, padx=(5, 0))
        tk.Scale(self._omr_slider_row, variable=self.area_threshold, from_=0.1, to=0.8, resolution=0.05, orient=tk.HORIZONTAL, bg=SECTION_BG, relief=tk.FLAT, length=80).pack(side=tk.LEFT, padx=2)

        tk.Button(self._omr_slider_row, text="\U0001f527 自動調整", command=self.open_threshold_calibrator,
                  width=8, bg="#CE93D8", relief=tk.FLAT, font=(UI_FONT, get_ui_font_size(8)),
                  cursor="hand2").pack(side=tk.LEFT, padx=(10, 0))

        # ---------------------------------------------------------
        # 2. アクションパイプライン (3カラム)
        # ---------------------------------------------------------
        pipeline_frame = tk.Frame(controls_frame, bg=BG_COLOR)
        pipeline_frame.pack(fill=tk.X)
        pipeline_frame.columnconfigure(0, weight=2, uniform="steps")   # Step1
        pipeline_frame.columnconfigure(1, weight=3, uniform="steps")   # Step2 (広め)
        pipeline_frame.columnconfigure(2, weight=2, uniform="steps")   # Step3
        
        # 共通スタイル
        def create_step_frame(parent, title, color_bar):
            f = tk.LabelFrame(parent, text=title, padx=10, pady=10, font=FONT_BOLD, bg=SECTION_BG, fg=HEADER_TEXT, relief=tk.FLAT)
            # 色付きバー（アクセント）
            tk.Frame(f, bg=color_bar, height=2).pack(fill=tk.X, pady=(0, 10))
            return f

        # Step 1: 採点準備
        step1 = create_step_frame(pipeline_frame, "Step 1: 採点準備", BTN_GREEN)
        step1.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._step1_frame = step1  # toggle用に保持
        
        # 認識実行 + 結果フォルダ（記述のみモードでは「画像準備」に変更）
        step1_run_row = tk.Frame(step1, bg=SECTION_BG)
        step1_run_row.pack(fill=tk.X, pady=(0, 5))

        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            self._btn_run_box = tk.Button(step1_run_row, text="▶ 画像準備",
                                          command=self._prepare_images_for_descriptive,
                                          bg="#B39DDB", font=FONT_BOLD, height=2,
                                          relief=tk.FLAT, cursor="hand2")
        else:
            self._btn_run_box = tk.Button(step1_run_row, text="▶ 認識実行",
                                          command=self.run_box_drawer,
                                          bg=BTN_GREEN, font=FONT_BOLD, height=2,
                                          relief=tk.FLAT, cursor="hand2")
        self._btn_run_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # 初期状態: フォルダ/座標ファイル未選択なので無効化
        self._btn_run_box.config(state=tk.DISABLED)
        self.open_boxed_btn = tk.Button(step1_run_row, text="📁", command=self.open_boxed_folder, bg=BTN_GRAY, relief=tk.FLAT, state=tk.DISABLED, width=3, font=(UI_FONT, get_ui_font_size(10)))
        self.open_boxed_btn.pack(side=tk.LEFT, padx=(3, 0), fill=tk.Y)

        # 正答データ（記述のみモードでは非表示）
        s_row1 = tk.Frame(step1, bg=SECTION_BG)
        self._answer_key_row = s_row1
        if self.app_mode != MODE_DESCRIPTIVE_ONLY:
            s_row1.pack(fill=tk.X, pady=2)
        tk.Label(s_row1, text="正答データ", width=10, anchor=tk.W, font=(UI_FONT, get_ui_font_size(8)), bg=SECTION_BG).pack(side=tk.LEFT)
        tk.Entry(s_row1, textvariable=self.template_path, font=(UI_FONT, get_ui_font_size(8)), bg="#F9F9F9", relief=tk.FLAT, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(s_row1, text="ファイル選択", command=self.select_template, width=10, bg=BTN_GRAY, relief=tk.FLAT, font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT)
        _btn_key_check = tk.Button(
            s_row1, text="📋", command=self.run_answer_key_check_gui,
            width=3, bg=BTN_GRAY, relief=tk.FLAT, font=(UI_FONT, get_ui_font_size(8)), cursor="hand2")
        _btn_key_check.pack(side=tk.LEFT, padx=(3, 0))
        _ToolTip(_btn_key_check,
                 "正答チェック — 登録内容を検証し、チェック報告と模範解答の\n"
                 "Markdownを正答データと同じフォルダに書き出します")

        # OMR結果（記述のみモードでは非表示）
        s_row2 = tk.Frame(step1, bg=SECTION_BG)
        self._omr_result_row = s_row2
        if self.app_mode != MODE_DESCRIPTIVE_ONLY:
            s_row2.pack(fill=tk.X, pady=2)
        tk.Label(s_row2, text="OMR結果", width=10, anchor=tk.W, font=(UI_FONT, get_ui_font_size(8)), bg=SECTION_BG).pack(side=tk.LEFT)
        tk.Entry(s_row2, textvariable=self.mark2_result_path, font=(UI_FONT, get_ui_font_size(8)), bg="#F9F9F9", relief=tk.FLAT, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(s_row2, text="ファイル選択", command=self.select_mark2_result, width=10, bg=BTN_GRAY, relief=tk.FLAT, font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT)

        # 記述問題設定（記述ON時のみ表示 — _on_descriptive_toggle で制御）
        self.desc_setup_btn = tk.Button(
            step1, text="⚙ 記述問題設定",
            command=self.setup_descriptive,
            bg="#CE93D8", font=FONT_BOLD, height=2, relief=tk.FLAT, cursor="hand2",
        )
        # 記述のみ/マーク＋記述モードでは初期表示
        if self.app_mode in (MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY):
            self.desc_setup_btn.pack(fill=tk.X, pady=(5, 0))

        # Step 2: 採点実行
        step2 = create_step_frame(pipeline_frame, "Step 2: 採点実行", BTN_BLUE)
        step2.grid(row=0, column=1, sticky="nsew", padx=5)
        self._step2_frame = step2  # toggle用に保持
        
        # --- 常時表示ボタン（記述のみモードではマークチェック非表示） ---
        BTN_STYLE = dict(font=FONT_BOLD, height=2, relief=tk.FLAT, cursor="hand2")

        self._btn_mark_check = tk.Button(step2, text="🔍 マークチェック", command=self.run_mark_checker, bg=BTN_ORANGE, **BTN_STYLE)
        if self.app_mode != MODE_DESCRIPTIVE_ONLY:
            self._btn_mark_check.pack(fill=tk.X, pady=(0, 3))

        # 記述採点ボタン（記述ON時のみ表示 — _on_descriptive_toggle で制御）
        self.desc_scoring_btn = tk.Button(
            step2, text="✏ 記述採点",
            command=self.run_descriptive_scoring,
            bg="#B39DDB", **BTN_STYLE,
        )
        # 記述系モードではデフォルト表示
        if self.app_mode in (MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY):
            self.desc_scoring_btn.pack(fill=tk.X, pady=3)

        # 記述ステータスパネル（記述ON時のみ表示 — _on_descriptive_toggle で制御）
        # 外枠: 左に紫のアクセントライン
        self._desc_status_frame = tk.Frame(step2, bg="#E1BEE7")
        _inner = tk.Frame(self._desc_status_frame, bg="#F3E5F5", padx=8, pady=4)
        _inner.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        # 左アクセントライン（2px 紫）
        tk.Frame(self._desc_status_frame, bg="#CE93D8", width=3).pack(side=tk.LEFT, fill=tk.Y)
        # テスト互換性のため非表示の Label を保持（.cget("text") 用）
        self._desc_status_label = tk.Label(self._desc_status_frame, text="")
        # 表示用: 固定高さの Text ウィジェット（安定したレイアウト）
        self._desc_status_text = tk.Text(
            _inner, font=(UI_FONT, get_ui_font_size(8)),
            bg="#F3E5F5", fg="#4A148C", wrap=tk.WORD,
            height=4, relief=tk.FLAT, bd=0, state=tk.DISABLED,
            highlightthickness=0, cursor="arrow",
        )
        self._desc_status_text.pack(fill=tk.BOTH, expand=True)

        # 記述系モードではステータスパネルもデフォルト表示
        if self.app_mode in (MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY):
            self._desc_status_frame.pack(fill=tk.X, pady=(3, 0))

        # --- 採点確認ボタン（α: 記述採点の確認機能、記述系モードのみ） ---
        self._btn_desc_review = tk.Button(
            step2, text="🔎 記述採点の確認",
            command=self._open_descriptive_review,
            bg="#E1BEE7", **BTN_STYLE,
        )
        if self.app_mode in (MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY):
            self._btn_desc_review.pack(fill=tk.X, pady=3)

        # --- 合計点位置設定（出力の直前）---
        self._btn_total_pos = tk.Button(step2, text="📐 合計点位置設定", command=self.setup_total_position, bg="#90CAF9", **BTN_STYLE)
        self._btn_total_pos.pack(fill=tk.X, pady=3)

        # --- 詳細設定リンク ---
        self._link_detailed_settings = tk.Label(
            step2, text="⚙ 詳細設定...",
            font=(UI_FONT, get_ui_font_size(8), "underline"), fg="#1976D2",
            bg=SECTION_BG, cursor="hand2", anchor=tk.E,
        )
        self._link_detailed_settings.pack(fill=tk.X, pady=(0, 2))
        self._link_detailed_settings.bind("<Button-1>", lambda e: self._open_rendering_settings())
        self._link_detailed_settings.bind("<Enter>", lambda e: self._link_detailed_settings.config(fg="#0D47A1"))
        self._link_detailed_settings.bind("<Leave>", lambda e: self._link_detailed_settings.config(fg="#1976D2"))

        # 採点済み答案を生成 + 結果フォルダ（横並び）
        step2_run_row = tk.Frame(step2, bg=SECTION_BG)
        step2_run_row.pack(fill=tk.X, pady=(3, 5))
        self._btn_run_scoring = tk.Button(step2_run_row, text="▶ 採点済み答案を生成", command=self.run_scoring, bg=BTN_BLUE, **BTN_STYLE)
        self._btn_run_scoring.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.open_scored_btn = tk.Button(step2_run_row, text="📁", command=self.open_scored_folder, bg=BTN_GRAY, relief=tk.FLAT, state=tk.DISABLED, width=3, font=(UI_FONT, get_ui_font_size(10)))
        self.open_scored_btn.pack(side=tk.LEFT, padx=(3, 0), fill=tk.Y)

        # Step 3: サマリー
        step3 = create_step_frame(pipeline_frame, "Step 3: 集計", BTN_AMBER)
        step3.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        
        # --- チェックボックス群（集計実行ボタンの上部） ---
        self.name_trim_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(
            step3, text="氏名画像を集計シートに表示する",
            variable=self.name_trim_enabled, bg=SECTION_BG,
            font=(UI_FONT, get_ui_font_size(8)), anchor=tk.W, cursor="hand2"
        ).pack(fill=tk.X, pady=(0, 3))

        # 学籍番号OCR（新機能のためデフォルトOFF、実験的機能）
        self.student_id_ocr_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(
            step3, text="学籍番号をOCRで読み取る（実験的機能・要確認）",
            variable=self.student_id_ocr_enabled, bg=SECTION_BG,
            font=(UI_FONT, get_ui_font_size(8)), anchor=tk.W, cursor="hand2"
        ).pack(fill=tk.X, pady=(0, 3))

        # 記述採点を分析に含むチェックボックス（記述ON時のみ表示）
        self._chk_include_desc_analysis = tk.Checkbutton(
            step3, text="記述採点の結果を分析ファイルに含む",
            variable=self.include_descriptive_in_analysis, bg=SECTION_BG,
            font=(UI_FONT, get_ui_font_size(8)), anchor=tk.W, cursor="hand2"
        )
        # 記述のみモードではON固定で表示、マーク＋記述では表示
        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            self.include_descriptive_in_analysis.set(True)
            self._chk_include_desc_analysis.config(state=tk.DISABLED)
            self._chk_include_desc_analysis.pack(fill=tk.X, pady=(0, 3))
        elif self.app_mode == MODE_MARK_AND_DESCRIPTIVE:
            self._chk_include_desc_analysis.pack(fill=tk.X, pady=(0, 3))
        # マークのみでは非表示（_on_descriptive_toggle で制御）
        
        # --- 集計実行 + 結果フォルダ（横並び） ---
        self._step3_run_row = tk.Frame(step3, bg=SECTION_BG)
        self._step3_run_row.pack(fill=tk.X, pady=5)
        self._btn_run_summary = tk.Button(self._step3_run_row, text="▶ 集計実行", command=self.run_summary_generation, bg=BTN_AMBER, font=FONT_BOLD, height=2, relief=tk.FLAT, cursor="hand2")
        self._btn_run_summary.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.open_results_btn = tk.Button(self._step3_run_row, text="📁", command=self.open_results_folder, bg=BTN_GRAY, relief=tk.FLAT, state=tk.DISABLED, width=3, font=(UI_FONT, get_ui_font_size(10)))
        self.open_results_btn.pack(side=tk.LEFT, padx=(3, 0), fill=tk.Y)

        # --- 複数ページ統合（既存の集計Excel同士を学籍番号で統合する単発ツール） ---
        self._btn_multi_page_merge = tk.Button(
            step3, text="🔗 複数ページ統合", command=self.run_multi_page_merge,
            bg=BTN_GRAY, relief=tk.FLAT, font=FONT_NORMAL,
        )
        self._btn_multi_page_merge.pack(fill=tk.X, pady=(5, 0))
        _ToolTip(
            self._btn_multi_page_merge,
            "1人の学生が複数ページ提出する場合、ページ番号ごとに\n"
            "別々に生成した集計Excel（学籍番号OCR確認済み）を、\n"
            "学籍番号をキーに1つに統合します。\n"
            "画像フォルダの選択状態とは無関係に使えます。",
        )

        # --- 初期化完了後の処理 ---
        # Step2/3 のボタンを初期状態で無効化（Step進行ガード）
        self._update_step_availability()

        # 起動時セッション復元（StartupModeDialogの「採点再開」から来た場合）
        if self._restore_session_path:
            self.root.after(100, lambda: self._auto_restore_from_path(self._restore_session_path))

    # ---------------------------------------------------------
    # Step 進行ガード
    # ---------------------------------------------------------

    def _update_step1_availability(self):
        """Step 1 実行ボタンの有効化/無効化を制御する。

        記述のみモード: 画像フォルダが設定されていれば有効化
        マーク系モード: 画像フォルダ＋座標ファイルが両方設定されていれば有効化
        """
        if not hasattr(self, '_btn_run_box'):
            return
        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            ready = bool(self.image_folder_path.get())
        else:
            ready = bool(self.image_folder_path.get()) and bool(self.coord_excel_path.get())
        self._btn_run_box.config(state=tk.NORMAL if ready else tk.DISABLED)

    def _update_step_availability(self):
        """ファイルシステムの状態に基づき Step1/2/3 ボタンの有効化を制御する。

        Step 1 実行ボタン: フォルダ＋座標ファイル設定済みで有効化
        Step 1 完了（boxed_folder 存在）→ Step 2 ボタン有効化
        Step 2 完了（scored_folder 存在）→ Step 3 ボタン有効化

        各 Step の完了時と、セッション復元後に呼ばれる。
        """
        # Step 1 実行ボタンの有効化判定
        self._update_step1_availability()

        # GUI ウィジェットが未初期化の場合はスキップ（テストスタブ等）
        if not hasattr(self, '_btn_mark_check'):
            return

        img_folder = self.image_folder_path.get()
        if not img_folder:
            # フォルダ未選択 → Step2/3 無効
            self._set_step2_enabled(False)
            self._set_step3_enabled(False)
            return

        base = Path(img_folder)
        boxed = base / RESULTS_FOLDER / BOXED_FOLDER
        scored = base / RESULTS_FOLDER / SCORED_FOLDER
        final = base / RESULTS_FOLDER / FINAL_REPORT_FOLDER

        # Step 1 完了判定: boxed_folder に画像があるか
        step1_done = boxed.exists() and any(
            f.suffix.lower() in ('.jpg', '.jpeg', '.png')
            for f in boxed.iterdir()
        ) if boxed.exists() else False
        self._set_step2_enabled(step1_done)

        # Step 2 完了判定: scored_folder に画像があるか
        step2_done = scored.exists() and any(
            f.suffix.lower() in ('.jpg', '.jpeg', '.png')
            for f in scored.iterdir()
        ) if scored.exists() else False
        # Step 3 は Step 1 完了だけで有効にする（採点なしで集計可能なケースあり）
        self._set_step3_enabled(step1_done)

        # フォルダ📁ボタンの状態更新
        if step1_done:
            self.last_boxed_folder = str(boxed)
            self.open_boxed_btn.config(state=tk.NORMAL)
        if step2_done:
            self.last_scored_folder = str(scored)
            self.open_scored_btn.config(state=tk.NORMAL)
        if final.exists():
            self.last_results_folder = str(final)
            self.open_results_btn.config(state=tk.NORMAL)

    def _set_step2_enabled(self, enabled: bool):
        """Step2 の操作ボタン群を有効化/無効化する"""
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in [
            self._btn_mark_check,
            self.desc_scoring_btn,
            self._btn_desc_review,
            self._btn_total_pos,
            self._btn_run_scoring,
        ]:
            try:
                btn.config(state=state)
            except Exception:
                pass
        # 詳細設定リンクは色で表現
        if hasattr(self, '_link_detailed_settings'):
            fg = "#1976D2" if enabled else "#B0BEC5"
            self._link_detailed_settings.config(fg=fg)

    def _set_step3_enabled(self, enabled: bool):
        """Step3 の操作ボタンを有効化/無効化する"""
        state = tk.NORMAL if enabled else tk.DISABLED
        try:
            self._btn_run_summary.config(state=state)
        except Exception:
            pass

    # ---------------------------------------------------------
    # エラーメッセージのユーザーフレンドリー変換
    # ---------------------------------------------------------

    @staticmethod
    def _friendly_error_message(e: Exception) -> str:
        """技術的な例外メッセージを初心者向けの日本語に変換する。

        対処法のヒントを添えて返す。元の例外情報はログに残す。
        """
        msg = str(e)
        etype = type(e).__name__

        if isinstance(e, FileNotFoundError):
            return f"ファイルが見つかりません。\n\n{msg}\n\nファイルを移動・削除していないか確認してください。"
        if isinstance(e, PermissionError):
            return (
                "ファイルにアクセスできません。\n\n"
                "他のプログラム（Excel等）でファイルを開いていないか確認してください。"
            )
        if isinstance(e, MemoryError):
            return (
                "メモリが不足しました。\n\n"
                "画像の枚数が多すぎる場合は、フォルダを分割して処理してください。"
            )
        if isinstance(e, (ValueError, KeyError, IndexError)):
            return (
                f"データの処理中にエラーが発生しました。\n\n"
                f"詳細: {msg}\n\n"
                f"入力ファイルの形式が正しいか確認してください。"
            )
        # デフォルト: 型名を省いた分かりやすい形
        return f"処理中にエラーが発生しました。\n\n詳細: {msg}"
    
    def select_folder(self):
        """画像フォルダを選択"""
        folder = filedialog.askdirectory(title="画像フォルダを選択")
        if folder:
            self.image_folder_path.set(folder)
            self.log_message(f"✓ 画像フォルダを選択: {folder}")
            self._try_auto_restore()
            if self.app_mode != MODE_DESCRIPTIVE_ONLY:
                self.auto_detect_template()
            self._update_step1_availability()
            self._update_step_availability()

    # ---------------------------------------------------------
    # 記述のみモード: 画像準備
    # ---------------------------------------------------------

    def _prepare_images_for_descriptive(self):
        """記述のみモード: 画像を 00_Processing にコピーして準備する"""
        if self._processing:
            return
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        img_folder = Path(self.image_folder_path.get())
        if not img_folder.exists():
            messagebox.showerror("エラー", "画像フォルダが存在しません")
            return

        # 画像ファイルの存在チェック
        image_files = sorted(
            [f for f in img_folder.iterdir()
             if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
        )
        if not image_files:
            messagebox.showerror("エラー", "画像フォルダに画像ファイル（JPG/PNG）が見つかりません")
            return

        self._set_processing_state(True)
        thread = threading.Thread(
            target=self._run_prepare_images_thread, args=(img_folder, image_files),
            daemon=True,
        )
        thread.start()

    def _run_prepare_images_thread(self, img_folder, image_files):
        """画像準備の実行（別スレッド）"""
        try:
            import shutil

            results_folder = img_folder / RESULTS_FOLDER
            boxed_folder = results_folder / BOXED_FOLDER
            data_folder = results_folder / RESULTS_DATA_FOLDER

            boxed_folder.mkdir(parents=True, exist_ok=True)
            data_folder.mkdir(parents=True, exist_ok=True)

            self.log_message(f"画像準備を開始します... ({len(image_files)}枚)")

            copied = 0
            for img_path in image_files:
                dst = boxed_folder / img_path.name
                if not dst.exists() or dst.stat().st_mtime < img_path.stat().st_mtime:
                    shutil.copy2(str(img_path), str(dst))
                copied += 1

            self.log_message(f"✓ 画像準備完了: {copied}枚を {BOXED_FOLDER}/ にコピー")
            self.last_boxed_folder = str(boxed_folder)
            self.root.after(0, lambda: self.open_boxed_btn.config(state=tk.NORMAL))
            self.root.after(0, self._save_session_state)
            self.root.after(0, self._update_descriptive_status)
            self.root.after(0, self._update_step_availability)

            self.root.after(0, lambda: messagebox.showinfo(
                "完了",
                f"画像準備が完了しました！\n\n"
                f"・画像数: {copied}枚\n\n"
                f"次のステップ:\n"
                f"「⚙ 記述問題設定」で採点領域を設定してください。"
            ))
        except Exception as e:
            self.log_message(f"画像準備エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            friendly = self._friendly_error_message(e)
            self.root.after(0, lambda: messagebox.showerror("エラー", friendly))
        finally:
            self.root.after(0, self._set_processing_state, False)
    
    def select_pdf(self):
        """PDFファイルを選択し、画像に展開する"""
        if not HAS_PYMUPDF:
            if getattr(sys, 'frozen', False):
                messagebox.showerror(
                    "エラー",
                    "この実行ファイルではPDF入力機能が利用できません。\n\n"
                    "PDFを画像に変換してからお使いください。\n"
                    "（Windowsの「PrintScreen」やPDF閲覧ソフトの\n"
                    "「画像として保存」機能をご利用ください）"
                )
            else:
                messagebox.showerror(
                    "エラー",
                    "PDF入力にはPyMuPDFが必要です。\n\n"
                    "pip install PyMuPDF\n\n"
                    "でインストールしてください。"
                )
            return
        
        pdf_files = filedialog.askopenfilenames(
            title="PDFファイルを選択（複数選択可）",
            filetypes=[("PDFファイル", "*.pdf"), ("すべてのファイル", "*.*")]
        )
        if not pdf_files:
            return

        pdf_files = list(pdf_files)
        if len(pdf_files) == 1:
            self.log_message(f"PDF展開中: {pdf_files[0]}")
        else:
            self.log_message(f"PDF展開中: {len(pdf_files)}ファイル")
        self._set_processing_state(True)
        thread = threading.Thread(
            target=self._run_pdf_extract_thread, args=(pdf_files,), daemon=True
        )
        thread.start()

    def _run_pdf_extract_thread(self, pdf_files):
        """別スレッドでPDF展開を実行（複数PDFは共通フォルダへ展開）

        画像ファイル名は {PDF名}_pNNN.png 形式のため、
        複数PDFを同一フォルダに展開しても衝突しない。
        """
        try:
            first = Path(pdf_files[0])
            if len(pdf_files) == 1:
                # 単一PDF: 従来どおり {PDF名}_images/ へ展開
                output_folder = extract_pdf_to_images(pdf_files[0])
            else:
                # 複数PDF: 1件目のPDFと同じ場所の共通フォルダへまとめて展開
                output_folder = first.parent / "pdf_import_images"
                for pdf_file in pdf_files:
                    extract_pdf_to_images(pdf_file, output_folder=output_folder)
                    self.log_message(f"  ✓ 展開: {Path(pdf_file).name}")
            self.root.after(0, lambda: self.image_folder_path.set(str(output_folder)))
            self.log_message(f"✓ PDF展開完了 ({len(pdf_files)}ファイル) → {output_folder}")
            self.root.after(0, self._try_auto_restore)
            self.root.after(0, self.auto_detect_template)
            self.root.after(0, self._update_step1_availability)
        except Exception as e:
            self.log_message(f"✗ PDF展開エラー: {e}")
            self.root.after(0, lambda: messagebox.showerror("PDF展開エラー", str(e)))
        finally:
            self.root.after(0, self._set_processing_state, False)
    
    def select_excel(self):
        """座標ファイルを選択"""
        file = filedialog.askopenfilename(title="座標ファイルを選択", filetypes=[("Excelファイル", "*.xlsx *.xls"), ("すべてのファイル", "*.*")])
        if file:
            self.coord_excel_path.set(file)
            self.log_message(f"✓ 座標ファイルを選択: {file}")
            self._update_step1_availability()
    
    def run_page_number_check(self):
        """ページ番号確認ツールを実行する（単発、集計処理とは独立）。

        画像フォルダ内の全画像から、教員が最初の1枚で選んだ矩形位置の
        印刷ページ番号をOCRし、多数決と異なるファイル（取り違えの疑い）を
        一覧表示する。射影補正前の生スキャン画像に対してもそのまま使える。
        """
        image_folder = self.image_folder_path.get()
        if not image_folder or not Path(image_folder).exists():
            messagebox.showerror("エラー", "先に画像フォルダを選択してください。")
            return
        from page_number_checker import check_page_numbers
        check_page_numbers(image_folder, parent=self.root)

    def run_multi_page_merge(self):
        """複数ページ統合ツールを実行する（単発、集計処理とは独立）。

        ページ番号ごとに別々に生成した集計Excel（記述のみモード、学籍番号OCR
        確認済み）を、教員が順番に指定すると、学籍番号をキーに1つに統合する。
        """
        from multi_page_merger import run_multi_page_merge_gui
        run_multi_page_merge_gui(parent=self.root)

    def select_template(self):
        """正答データファイルを選択"""
        file = filedialog.askopenfilename(title="正答データを選択", filetypes=[("Excelファイル", "*.xlsx *.xls"), ("すべてのファイル", "*.*")])
        if file:
            self.template_path.set(file)
            self.log_message(f"✓ 正答データを選択: {file}")
            self.run_answer_key_check_gui(auto=True)

    def run_answer_key_check_gui(self, auto=False):
        """正答チェックを実行し、要約をログに・詳細をMarkdownに書き出す。

        answer_keyと同じフォルダに <ファイル名>_check.md（検証結果・行割当・集計）を
        常に書き出し、エラーがなければ <ファイル名>_模範解答.md も書き出す。

        Args:
            auto: 正答データの選択/自動検出時の自動実行ならTrue
                  （未選択・正答未入力を騒がず要点だけログに出す）
        """
        template = self.template_path.get().strip()
        if not template:
            if not auto:
                messagebox.showerror("エラー", "正答データ（Answer Key）を選択してください")
            return
        try:
            from answer_key_checker import run_answer_key_check
            coord = self.coord_excel_path.get().strip() or None
            try:
                skip = int(self.skip_questions.get())
            except (ValueError, tk.TclError):
                skip = 0
            res, check_md, model_md = run_answer_key_check(
                template, mark_format=getattr(self, 'mark_format', MARK_FORMAT_STANDARD),
                coord_excel_path=coord, skip_questions=skip)
        except Exception as e:
            self.log_message(f"⚠ 正答チェックでエラー: {e}")
            return

        if res['ok']:
            stats = res['stats']
            self.log_message(
                f"📋 正答チェック: ✅ エラーなし（{stats['問題数']}問 / 満点{stats['満点']}点 / "
                f"最終使用行 解答番号{stats['最終使用行']}）")
        else:
            # 自動実行時、生成直後の空answer_key（正答未入力）は騒がない
            only_empty = (len(res['errors']) == 1 and '1問もありません' in res['errors'][0])
            if auto and only_empty:
                self.log_message("📋 正答チェック: 正答が未入力です（入力後に 📋 ボタンで確認できます）")
                return
            self.log_message(f"📋 正答チェック: ❌ エラー {len(res['errors'])}件")
            for err in res['errors'][:5]:
                self.log_message(f"   ❌ {err}")
            if len(res['errors']) > 5:
                self.log_message(f"   … 他{len(res['errors']) - 5}件はチェック報告を参照")
        for w in res['warnings']:
            self.log_message(f"   ⚠ {w}")
        self.log_message(f"   📄 チェック報告: {Path(check_md).name}")
        if model_md:
            self.log_message(f"   📄 模範解答: {Path(model_md).name}")
        if not auto and not res['ok']:
            messagebox.showwarning(
                "正答チェック",
                f"エラーが{len(res['errors'])}件あります。\n"
                "詳細はログとチェック報告（Markdown）を確認してください。")
    
    def select_mark2_result(self):
        """OMR読取結果ファイルを選択"""
        file = filedialog.askopenfilename(title="OMR読取結果を選択", filetypes=[("Excelファイル", "*.xlsx *.xls"), ("すべてのファイル", "*.*")])
        if file:
            self.mark2_result_path.set(file)
            self.log_message(f"✓ OMR読取結果を選択: {file}")
    
    def auto_detect_template(self):
        """テンプレートファイルを検出し、自動でセットする。

        画像フォルダ内の結果フォルダからAnswer Keyを検出し、
        見つかればGUIに自動設定する。
        """
        if not self.image_folder_path.get():
            return
        
        template_path = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER / ANSWER_KEY_FILE
        if template_path.exists():
            self.template_path.set(str(template_path))
            self.log_message(f"✓ 正答データを自動検出: {template_path.name}")
            self.run_answer_key_check_gui(auto=True)
    
    def _auto_detect_omr_result(self, results_folder):
        """Step1完了後、最新のOMR読取結果を自動検出してStep1にセット"""
        try:
            reading_folder = Path(results_folder) / RESULTS_DATA_FOLDER / READING_RESULTS_FOLDER_NAME
            if not reading_folder.exists():
                return
            
            # Mark2-Result-*.xlsx を検索し、最新のものを取得
            result_files = sorted(reading_folder.glob("Mark2-Result-*.xlsx"))
            if result_files:
                latest = result_files[-1]  # ファイル名にタイムスタンプが含まれるので最後が最新
                self.mark2_result_path.set(str(latest))
                self.log_message(f"✓ OMR結果を自動検出: {latest.name}")
        except Exception as e:
            self.log_message(f"⚠ OMR結果の自動検出に失敗: {e}")
    
    def open_boxed_folder(self):
        """枠描画結果フォルダを開く"""
        if self.last_boxed_folder and Path(self.last_boxed_folder).exists():
            open_in_file_manager(self.last_boxed_folder)

    def open_scored_folder(self):
        """採点結果フォルダを開く"""
        if self.last_scored_folder and Path(self.last_scored_folder).exists():
            open_in_file_manager(self.last_scored_folder)

    def open_results_folder(self):
        """集計結果フォルダ(_saiten_grading_results)を開く"""
        if self.last_results_folder and Path(self.last_results_folder).exists():
            open_in_file_manager(self.last_results_folder)
    
    def log_message(self, message, replace_last=False):
        """
        ログメッセージを表示（スレッドセーフ）。
        バックグラウンドスレッドから呼ばれた場合は root.after() で
        メインスレッドに委譲する。
        replace_last=Trueの場合、最後の行を上書きする（TQDM風）
        """
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.log_message, message, replace_last)
            return

        self.log_text.config(state=tk.NORMAL)
        
        if replace_last:
            # 最後の行（改行の直前）を削除
            # 行全体を削除して書き直す
            last_line_index = self.log_text.index("end-2l") # 最後の行の開始位置
            self.log_text.delete(last_line_index, "end-1c")
            self.log_text.insert(tk.END, message + "\n")
        else:
            self.log_text.insert(tk.END, message + "\n")
            
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        # update() はメインスレッドからのみ安全に呼べる
        self.root.update_idletasks()

    # ------------------------------------------------------------------
    # ロガー出力 → GUIログ転送ヘルパー
    # ------------------------------------------------------------------
    def _attach_gui_log_handler(self):
        """ロガー出力をGUIログウィジェットにリアルタイム転送するハンドラを追加し、
        コンソールハンドラを一時的に抑止する。

        Returns:
            (gui_handler, suppressed): 後で _detach_gui_log_handler に渡す
        """
        class _GUILogHandler(logging.Handler):
            """GUIの log_message() にリアルタイム転送するハンドラ"""
            def __init__(self, log_func):
                super().__init__()
                self.log_func = log_func
            def emit(self, record):
                try:
                    msg = self.format(record)
                    self.log_func(msg)
                except Exception:
                    pass

        gui_handler = _GUILogHandler(self.log_message)
        gui_handler.setLevel(logging.INFO)
        gui_handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger = logging.getLogger()
        # コンソール StreamHandler を一時的に無効化（ターミナルへの二重出力を防止）
        suppressed: list[tuple[logging.Handler, int]] = []
        for h in root_logger.handlers:
            if (isinstance(h, logging.StreamHandler)
                    and not isinstance(h, logging.FileHandler)):
                suppressed.append((h, h.level))
                h.setLevel(logging.CRITICAL + 1)  # 実質無効化

        root_logger.addHandler(gui_handler)
        return gui_handler, suppressed

    def _detach_gui_log_handler(self, gui_handler, suppressed):
        """_attach_gui_log_handler で追加したハンドラを除去し、
        コンソールハンドラを元のレベルに復元する。"""
        root_logger = logging.getLogger()
        root_logger.removeHandler(gui_handler)
        for h, orig_level in suppressed:
            h.setLevel(orig_level)

    def open_threshold_calibrator(self):
        """閾値キャリブレーション画面を開く"""
        if not self.image_folder_path.get() or not self.coord_excel_path.get():
            messagebox.showwarning("入力不足", "画像フォルダと座標ファイルを先に設定してください")
            return
        if not Path(self.image_folder_path.get()).exists():
            messagebox.showerror("エラー", "画像フォルダが存在しません")
            return
        if not Path(self.coord_excel_path.get()).exists():
            messagebox.showerror("エラー", "座標ファイルが存在しません")
            return

        try:
            skip = int(self.skip_questions.get())
        except ValueError:
            skip = 0

        self.log_message("閾値キャリブレーション画面を起動します...")
        ThresholdCalibratorGUI(
            parent_window=self.root,
            image_folder=self.image_folder_path.get(),
            coord_excel_path=self.coord_excel_path.get(),
            skip_questions=skip,
            color_threshold_var=self.color_threshold,
            area_threshold_var=self.area_threshold
        )

    # ---------------------------------------------------------
    # 採点結果描画の詳細設定
    # ---------------------------------------------------------

    def _open_rendering_settings(self):
        """詳細設定ウィンドウを開く"""
        RenderingSettingsGUI(
            parent_window=self.root,
            current_settings=self.rendering_settings,
            on_apply=self._apply_rendering_settings,
            image_folder=self.image_folder_path.get(),
            coord_excel_path=self.coord_excel_path.get(),
            template_path=self.template_path.get(),
            mark2_result_path=self.mark2_result_path.get(),
            skip_questions=self.skip_questions.get(),
            app_mode=self.app_mode,
        )

    def _apply_rendering_settings(self, new_settings):
        """設定ウィンドウからの適用コールバック"""
        self.rendering_settings = get_rendering_settings(new_settings)
        self.log_message("✓ 描画詳細設定を更新しました")

    # ---------------------------------------------------------
    # OMR認識モード切り替え (v4.5)
    # ---------------------------------------------------------

    def _on_omr_mode_changed(self, _event=None):
        """OMR認識モード ComboBox の選択が変わったときの処理。
        
        表示ラベルから内部値へ変換し、K-means モードでは閾値スライダーを
        非表示にし、閾値モードでは同一行の右側に表示する。
        """
        display = self._omr_display_var.get()
        internal = self._omr_label_to_value.get(display, OMR_MODE_KMEANS)
        self.omr_mode.set(internal)
        if internal == OMR_MODE_THRESHOLD:
            self._omr_slider_row.pack(side=tk.LEFT, padx=(10, 0))
        else:
            self._omr_slider_row.pack_forget()

    # ---------------------------------------------------------
    # 記述採点オプション関連メソッド
    # ---------------------------------------------------------

    def _on_descriptive_toggle(self):
        """記述採点チェックボックスの切り替え — ボタン群とステータスの表示/非表示

        記述ON時に表示するウィジェット:
          - Step1: desc_setup_btn（記述問題設定）
          - Step2: desc_scoring_btn（記述採点）→ ステータスパネル
        記述OFF時: 上記をすべて非表示にする。

        Step2 では pack 順序が重要なため、常時表示ボタンも含めて
        一度 forget してから正しい順序で再 pack する。
        """
        # MODE_DESCRIPTIVE_ONLY ではレイアウトが初期化時に確定しており、
        # toggle による再構成は不要（二重 pack 防止）
        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            return
        if self.descriptive_enabled.get():
            # --- Step1: 記述問題設定ボタンを表示 ---
            self.desc_setup_btn.pack(fill=tk.X, pady=(5, 0))

            # --- Step2 レイアウト再構成 ---
            # 順序: [マークチェック] → [記述採点] → [ステータス] →
            #       [採点確認] → [合計点位置] → [詳細設定リンク] →
            #       [採点済み答案を生成+フォルダ]
            step2_run_row = self._btn_run_scoring.master
            self._btn_total_pos.pack_forget()
            self._link_detailed_settings.pack_forget()
            step2_run_row.pack_forget()

            self.desc_scoring_btn.pack(fill=tk.X, pady=3)
            self._desc_status_frame.pack(fill=tk.X, pady=(3, 0))
            self._btn_desc_review.pack(fill=tk.X, pady=3)
            self._btn_total_pos.pack(fill=tk.X, pady=3)
            self._link_detailed_settings.pack(fill=tk.X, pady=(0, 2))
            step2_run_row.pack(fill=tk.X, pady=(3, 5))

            # 表示直後にステータスを最新状態に更新
            self._update_descriptive_status()

            # --- Step3: 記述採点を分析に含むチェックボックスを表示（ボタン上部） ---
            self._chk_include_desc_analysis.pack(fill=tk.X, pady=(0, 3), before=self._step3_run_row)
        else:
            # 記述OFFの場合は記述関連ウィジェットを非表示
            self.desc_setup_btn.pack_forget()
            self.desc_scoring_btn.pack_forget()
            self._desc_status_frame.pack_forget()
            self._btn_desc_review.pack_forget()
            self._chk_include_desc_analysis.pack_forget()

    def _set_desc_status(self, text):
        """記述ステータスのテキストを更新する（Label互換 + Text表示）"""
        # テスト互換: _desc_status_label.cget("text") が常に最新値を返す
        self._desc_status_label.config(text=text)
        # 表示用 Text ウィジェットを更新（スタブアプリでは存在しない場合あり）
        if hasattr(self, '_desc_status_text'):
            self._desc_status_text.config(state=tk.NORMAL)
            self._desc_status_text.delete("1.0", tk.END)
            self._desc_status_text.insert("1.0", text)
            self._desc_status_text.config(state=tk.DISABLED)

    # ---------------------------------------------------------
    # 記述のみモード: 採点済み答案生成
    # ---------------------------------------------------------

    def _run_scoring_descriptive_only(self):
        """記述のみモード: 記述採点のみで採点済み答案を生成"""
        results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        desc_config_path = results_data_folder / "descriptive_config.json"
        desc_scores_path = results_data_folder / "descriptive_scores.json"

        if not desc_config_path.exists():
            messagebox.showerror(
                "エラー",
                "記述問題の設定が見つかりません。\n"
                "先に「⚙ 記述問題設定」を実行してください。"
            )
            return
        if not desc_scores_path.exists():
            messagebox.showerror(
                "エラー",
                "記述採点結果が見つかりません。\n"
                "先に「✏ 記述採点」を実行してください。"
            )
            return

        # 採点完了チェック
        is_complete, unscored, total_img, detail = self._check_descriptive_completeness()
        if not is_complete and total_img > 0:
            detail_text = "\n".join(detail) if detail else ""
            if not messagebox.askyesno(
                "記述採点が未完了です",
                f"記述採点が完了していない生徒が {unscored}名 います。\n\n"
                f"{detail_text}\n\n"
                f"未採点の問題は 0点 として処理されます。\n"
                f"このまま続行しますか？",
            ):
                return

        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

        self.log_message("=" * 60)
        self.log_message("採点処理を開始します（記述のみモード）...")
        self.log_message("=" * 60)

        self._set_processing_state(True)
        # メインスレッドでStringVar値をキャプチャ（スレッドセーフ）
        params = {
            'image_folder': self.image_folder_path.get(),
        }
        thread = threading.Thread(
            target=self._run_descriptive_only_thread, args=(params,), daemon=True,
        )
        thread.start()

    def _run_descriptive_only_thread(self, params):
        """記述のみモード: 採点済み答案の生成スレッド"""
        try:
            from descriptive_scorer import (
                load_descriptive_config, load_descriptive_scores,
                generate_descriptive_only_sheets,
                load_total_display_config, TOTAL_DISPLAY_CONFIG_FILE,
            )

            results_folder = Path(params['image_folder']) / RESULTS_FOLDER
            results_data = results_folder / RESULTS_DATA_FOLDER
            boxed_folder = results_folder / BOXED_FOLDER
            output_folder = results_folder / SCORED_FOLDER

            config = load_descriptive_config(str(results_data / "descriptive_config.json"))
            scores_data = load_descriptive_scores(str(results_data / "descriptive_scores.json"))

            if not config or not scores_data:
                self.root.after(0, lambda: messagebox.showerror(
                    "エラー", "記述設定またはスコアの読み込みに失敗しました。"
                ))
                return

            # 合計点表示位置の読み込み
            try:
                tdc_path = str(results_data / TOTAL_DISPLAY_CONFIG_FILE)
                tdc = load_total_display_config(tdc_path)
                if tdc and "total_display_region" in tdc:
                    config["total_display_region"] = tdc["total_display_region"]
            except Exception:
                pass

            result = generate_descriptive_only_sheets(
                boxed_folder=str(boxed_folder),
                config=config,
                descriptive_scores=scores_data.get("scores", {}),
                output_folder=str(output_folder),
                log_callback=self.log_message,
                rendering_settings=dict(self.rendering_settings),
            )

            if result:
                self.last_scored_folder = str(output_folder)
                self.root.after(0, lambda: self.open_scored_btn.config(state=tk.NORMAL))
                self.root.after(0, self._save_session_state)
                self.root.after(0, self._update_step_availability)

                mode_label = "記述のみ"
                summary = (
                    f"採点処理が正常に完了しました！\n\n"
                    f"【処理結果】（{mode_label}）\n"
                    f"・処理対象: {result['total_count']}件\n"
                    f"・成功: {result['success_count']}件\n"
                    f"・エラー: {result['error_count']}件\n\n"
                    f"出力フォルダ: {output_folder}"
                )
                self.root.after(0, lambda: messagebox.showinfo("完了", summary))

        except Exception as e:
            self.log_message(f"採点処理エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror("エラー", f"採点処理中にエラーが発生しました:\n{self._friendly_error_message(e)}"))
        finally:
            self.root.after(0, self._set_processing_state, False)

    # ---------------------------------------------------------
    # α: 記述採点の確認機能
    # ---------------------------------------------------------

    def _open_descriptive_review(self):
        """記述採点の確認ウィンドウを開く"""
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        results_data = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = results_data / "descriptive_config.json"
        scores_path = results_data / "descriptive_scores.json"
        boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER

        if not config_path.exists():
            messagebox.showerror("エラー", "記述問題の設定が見つかりません。\n先に「⚙ 記述問題設定」を実行してください。")
            return
        if not scores_path.exists():
            messagebox.showinfo("情報", "採点データがまだありません。\n先に「✏ 記述採点」を実行してください。")
            return

        try:
            from descriptive_scorer import (
                load_descriptive_config, load_descriptive_scores,
                DescriptiveReviewGUI,
            )
            config = load_descriptive_config(str(config_path))
            scores_data = load_descriptive_scores(str(scores_path))

            if not config or not scores_data:
                messagebox.showerror("エラー", "設定またはスコアの読み込みに失敗しました。")
                return

            reviewer = DescriptiveReviewGUI(
                parent=self.root,
                config=config,
                scores=scores_data.get("scores", {}),
                boxed_folder=str(boxed_folder),
                scores_save_path=str(scores_path),
                original_image_folder=self.image_folder_path.get(),
            )
            if reviewer.modified:
                self.log_message("✓ 記述採点の確認・修正が完了しました")
                self._update_descriptive_status()
                self._save_session_state()
        except Exception as e:
            self.log_message(f"記述採点確認エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            messagebox.showerror("エラー", f"記述採点確認中にエラーが発生しました:\n{e}")

    def _update_descriptive_status(self):
        """記述ステータスパネルの内容を更新する"""
        if not self.descriptive_enabled.get():
            return

        img_folder = self.image_folder_path.get()
        if not img_folder:
            self._set_desc_status("📋 記述ステータス: フォルダ未選択")
            return

        results_data = Path(img_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = results_data / "descriptive_config.json"
        scores_path = results_data / "descriptive_scores.json"
        boxed_folder = Path(img_folder) / RESULTS_FOLDER / BOXED_FOLDER

        if not config_path.exists():
            self._set_desc_status("📋 記述ステータス: ⚠ 未設定\n  → 「⚙ 記述問題設定」を実行してください")
            return

        try:
            from descriptive_scorer import load_descriptive_config, load_descriptive_scores
            config = load_descriptive_config(str(config_path))
            if not config or not config.get("questions"):
                self._set_desc_status("📋 記述ステータス: ⚠ 設定が空です")
                return

            questions = config["questions"]
            total_max = sum(q.get("max_score", 0) for q in questions)
            q_count = len(questions)

            # 画像枚数を取得
            if boxed_folder.exists():
                image_files = sorted(
                    [f.name for f in boxed_folder.iterdir()
                     if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
                )
                total_images = len(image_files)
            else:
                image_files = []
                total_images = 0

            # 採点進捗を計算
            scores = {}
            if scores_path.exists():
                scores_data = load_descriptive_scores(str(scores_path))
                if scores_data and "scores" in scores_data:
                    scores = scores_data["scores"]

            lines = [f"📋 記述ステータス: {q_count}問 (満点: {total_max}点)"]

            if total_images == 0:
                lines.append("  画像: 未検出（Step1を先に実行）")
            else:
                # 各問題の進捗
                all_complete = True
                for q in questions:
                    qid = q["id"]
                    scored_count = sum(
                        1 for img in image_files
                        if img in scores and qid in scores[img]
                    )
                    if scored_count >= total_images:
                        status = f"✅ 完了 ({scored_count}枚)"
                    elif scored_count > 0:
                        status = f"⏳ {scored_count}/{total_images}枚"
                        all_complete = False
                    else:
                        status = "❌ 未採点"
                        all_complete = False
                    lines.append(f"  {qid} {q['name']}: {status}")

                if all_complete and total_images > 0:
                    lines.insert(1, f"  採点進捗: ✅ 全完了 ({total_images}枚)")
                elif scores:
                    scored_any = sum(1 for img in image_files if img in scores)
                    lines.insert(1, f"  採点進捗: ⏳ {scored_any}/{total_images}枚")
                else:
                    lines.insert(1, f"  採点進捗: ❌ 未開始 (対象: {total_images}枚)")

            self._set_desc_status("\n".join(lines))
        except Exception as e:
            self._set_desc_status(f"📋 記述ステータス: 読み込みエラー ({e})")

    def _check_descriptive_completeness(self) -> tuple:
        """記述採点の完了状態をチェックする。

        Returns:
            (is_complete: bool, unscored_count: int, total_images: int, detail_lines: list)
        """
        img_folder = self.image_folder_path.get()
        results_data = Path(img_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = results_data / "descriptive_config.json"
        scores_path = results_data / "descriptive_scores.json"
        boxed_folder = Path(img_folder) / RESULTS_FOLDER / BOXED_FOLDER

        from descriptive_scorer import load_descriptive_config, load_descriptive_scores
        config = load_descriptive_config(str(config_path))
        scores_data = load_descriptive_scores(str(scores_path))
        scores = scores_data.get("scores", {}) if scores_data else {}

        questions = config.get("questions", []) if config else []
        if not questions:
            return (False, 0, 0, ["記述問題が設定されていません"])

        image_files = []
        if boxed_folder.exists():
            image_files = sorted(
                [f.name for f in boxed_folder.iterdir()
                 if f.suffix.lower() in ('.jpg', '.jpeg', '.png')]
            )

        total_images = len(image_files)
        if total_images == 0:
            return (False, 0, 0, ["補正済み画像がありません"])

        # --- 全問題 × 全画像のマトリクスで採点漏れを検出 ---
        # unscored_images: いずれかの問題で未採点の画像の集合（set で重複排除）
        # detail: 問題ごとの未採点枚数を人間向けに整形したリスト
        unscored_images = set()
        detail = []
        for q in questions:
            qid = q["id"]
            # この問題について採点レコードが存在しない画像を収集
            missing = [img for img in image_files if img not in scores or qid not in scores.get(img, {})]
            if missing:
                # set に追加することで、複数問題で同一画像が欠落していても 1 回だけカウント
                unscored_images.update(missing)
                detail.append(f"  {qid}「{q['name']}」: {len(missing)}枚 未採点")

        # 戻り値: (全完了フラグ, 未採点画像数, 全画像数, 詳細メッセージ)
        return (len(unscored_images) == 0, len(unscored_images), total_images, detail)

    def _reset_descriptive_data(self):
        """記述問題の設定・採点結果と、学籍番号欄の位置設定をすべて削除して初期状態に戻す。

        同じテスト用データ(PDF/フォルダ)を使い回して設定をやり直す際、
        学籍番号欄の位置設定だけが残っていて英字マス指定・桁数確認の画面が
        再度出てこない、という混乱を避けるため、記述設定とあわせてここで削除する。

        削除対象:
            - descriptive_config.json（問題設定）
            - descriptive_scores.json（採点結果）
            - total_display_config.json（合計点表示位置設定）
            - student_id_area_config.json（学籍番号欄の位置設定）
        """
        img_folder = self.image_folder_path.get()
        if not img_folder:
            messagebox.showerror("エラー", "画像フォルダを選択してください。")
            return

        results_data = Path(img_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = results_data / "descriptive_config.json"
        scores_path = results_data / "descriptive_scores.json"

        from descriptive_scorer import TOTAL_DISPLAY_CONFIG_FILE
        total_pos_path = results_data / TOTAL_DISPLAY_CONFIG_FILE

        from id_area_config import ID_AREA_CONFIG_FILE
        id_area_path = results_data / ID_AREA_CONFIG_FILE

        # 削除対象ファイルの存在チェック
        existing = []
        if config_path.exists():
            existing.append(f"・記述問題設定（{config_path.name}）")
        if scores_path.exists():
            existing.append(f"・記述採点結果（{scores_path.name}）")
        if total_pos_path.exists():
            existing.append(f"・合計点位置設定（{total_pos_path.name}）")
        if id_area_path.exists():
            existing.append(f"・学籍番号欄の位置設定（{id_area_path.name}）")

        if not existing:
            messagebox.showinfo("初期化", "削除対象の設定ファイルが見つかりません。\nすでに初期状態です。")
            return

        # 確認ダイアログ — 既存の採点データが消えることを明示
        answer = messagebox.askokcancel(
            "⚠ 記述設定・学籍番号欄設定の初期化",
            "以下のファイルを削除し、初期状態に戻します。\n\n"
            + "\n".join(existing) + "\n\n"
            "この操作は取り消せません。\n"
            "進行中の記述採点データ・学籍番号欄の位置設定もすべて失われます。\n\n"
            "本当に初期化しますか？",
            icon="warning",
        )
        if not answer:
            return

        # バックアップを自動作成（復元可能にする）
        import shutil
        import datetime
        backup_suffix = datetime.datetime.now().strftime("_%Y%m%d_%H%M%S.bak")
        backed_up = []
        backup_failed = []
        for path in [config_path, scores_path, total_pos_path, id_area_path]:
            if path.exists():
                try:
                    bak_path = path.with_suffix(path.suffix + backup_suffix)
                    shutil.copy2(str(path), str(bak_path))
                    backed_up.append(bak_path.name)
                except Exception as e:
                    backup_failed.append(f"{path.name}: {e}")

        if backup_failed:
            self.log_message(f"✗ バックアップに失敗したため初期化を中止しました: {', '.join(backup_failed)}")
            messagebox.showerror(
                "エラー",
                "以下のファイルのバックアップに失敗したため、初期化を中止しました。\n"
                "データを失わないよう、削除は行っていません。\n\n"
                + "\n".join(backup_failed)
            )
            return

        if backed_up:
            self.log_message(f"ℹ バックアップを作成しました: {', '.join(backed_up)}")

        # ファイル削除
        deleted = []
        for path in [config_path, scores_path, total_pos_path, id_area_path]:
            if path.exists():
                try:
                    path.unlink()
                    deleted.append(path.name)
                except Exception as e:
                    self.log_message(f"削除エラー: {path.name} — {e}")
            # atomic_json_save が作成する .json.bak も削除
            # （load_json_safe がバックアップから復元してしまうため）
            bak_atomic = path.with_suffix(path.suffix + ".bak")
            if bak_atomic.exists():
                try:
                    bak_atomic.unlink()
                    deleted.append(bak_atomic.name)
                except Exception as e:
                    self.log_message(f"削除エラー: {bak_atomic.name} — {e}")

        self.log_message(f"✓ 記述設定・学籍番号欄設定を初期化しました（{', '.join(deleted)}）")
        self._update_descriptive_status()

    # ---------------------------------------------------------
    # セッション状態の保存・復元
    # ---------------------------------------------------------

    def _get_session_state_path(self):
        """現在の画像フォルダに対応する session_state.json のパスを返す"""
        img_folder = self.image_folder_path.get()
        if not img_folder:
            return None
        return Path(img_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER / SESSION_STATE_FILE

    def _save_session_state(self):
        """現在のGUI状態を session_state.json に保存する"""
        session_path = self._get_session_state_path()
        if not session_path:
            return
        img_folder = Path(self.image_folder_path.get())
        if not img_folder.exists():
            return

        # パスを画像フォルダからの相対パスに変換（可搬性のため）
        def _to_rel(abs_path_str):
            if not abs_path_str:
                return ""
            try:
                return str(Path(abs_path_str).relative_to(img_folder))
            except ValueError:
                return abs_path_str  # 別ドライブ等は絶対パスのまま

        import datetime
        state = {
            "version": 1,
            "app_mode": self.app_mode,
            "mark_format": getattr(self, 'mark_format', MARK_FORMAT_STANDARD),
            "image_folder": str(img_folder),
            "coord_excel": _to_rel(self.coord_excel_path.get()),
            "template": _to_rel(self.template_path.get()),
            "omr_result": _to_rel(self.mark2_result_path.get()),
            "skip_questions": self.skip_questions.get(),
            "color_threshold": self.color_threshold.get(),
            "area_threshold": self.area_threshold.get(),
            "descriptive_enabled": self.descriptive_enabled.get(),
            "rendering_settings": self.rendering_settings,
            "saved_at": datetime.datetime.now().isoformat(),
        }

        try:
            atomic_json_save(session_path, state)
        except Exception as e:
            self.log_message(f"⚠ セッション保存失敗: {e}")

    def _load_session_state(self, session_path):
        """session_state.json を読み込む（破損時は .bak からリカバリ）"""
        return load_json_safe(session_path, required_keys=["version"])

    def _resolve_path(self, base_folder, rel_or_abs):
        """相対 or 絶対パスを解決し、存在すれば Path を返す"""
        if not rel_or_abs:
            return None
        # まず相対パスとして試行
        candidate = base_folder / rel_or_abs
        if candidate.exists():
            return candidate
        # 絶対パスとして試行
        abs_path = Path(rel_or_abs)
        if abs_path.is_absolute() and abs_path.exists():
            return abs_path
        return None

    def _ask_repair_path(self, description, expected_name, filetypes):
        """ファイル選択ダイアログを表示してパスを修復する。

        Returns:
            選択されたパス文字列。キャンセル時は None。
        """
        selected = filedialog.askopenfilename(
            title=f"{description} を選択 — {expected_name}",
            filetypes=filetypes,
        )
        return selected if selected else None

    def _show_repair_dialog(self, broken_items):
        """壊れたパスの一覧修復ダイアログを表示する。

        1つのダイアログ内に壊れたパスを一覧表示し、各行に
        「参照...」ボタンを配置。ユーザーが修復したい項目だけ
        ファイル選択で再設定できる。未修復の項目はスキップされる。

        Args:
            broken_items: [(idx, key, desc, expected, ftypes, var), ...]

        Returns:
            True: ダイアログで「復元」が押された
            False: ダイアログで「中断」が押された or 閉じられた
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("パスの修復")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        result = {"accepted": False}

        # ヘッダー
        tk.Label(
            dialog,
            text=f"{len(broken_items)} 件のパスが見つかりません。\n"
                 "修復したい項目は「参照...」ボタンでファイルを選択してください。\n"
                 "未修復の項目はスキップされます。",
            font=(UI_FONT, get_ui_font_size(9)),
            justify=tk.LEFT, padx=15, pady=10,
        ).pack(fill=tk.X)

        # 一覧フレーム
        list_frame = tk.Frame(dialog, padx=15, pady=5)
        list_frame.pack(fill=tk.X)

        # 各壊れたパスのエントリと参照ボタンを作成
        path_vars = {}  # key -> StringVar (修復後のパス)
        for _, key, desc, expected, ftypes, var in broken_items:
            row = tk.Frame(list_frame)
            row.pack(fill=tk.X, pady=3)

            tk.Label(row, text=f"・{desc}", font=(UI_FONT, get_ui_font_size(9), "bold"),
                     anchor=tk.W, width=22).pack(side=tk.LEFT)

            path_var = tk.StringVar(dialog, value="(未設定)")
            path_vars[key] = (path_var, var, ftypes, desc, expected)

            entry = tk.Entry(row, textvariable=path_var, font=(UI_FONT, get_ui_font_size(8)),
                             bg="#F9F9F9", relief=tk.FLAT, state="readonly", width=40)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))

            def _browse(k=key):
                pv, _, ft, d, e = path_vars[k]
                selected = filedialog.askopenfilename(
                    parent=dialog,
                    title=f"{d} を選択 — {e}",
                    filetypes=ft,
                )
                if selected:
                    pv.set(selected)

            tk.Button(row, text="参照...", command=_browse,
                      font=(UI_FONT, get_ui_font_size(8)), bg="#EEEEEE",
                      relief=tk.FLAT, width=6, cursor="hand2").pack(side=tk.LEFT)

        # ボタン行
        btn_frame = tk.Frame(dialog, padx=15, pady=10)
        btn_frame.pack(fill=tk.X)

        def _on_accept():
            result["accepted"] = True
            dialog.destroy()

        def _on_cancel():
            result["accepted"] = False
            dialog.destroy()

        tk.Button(btn_frame, text="復元する", command=_on_accept,
                  bg="#A5D6A7", font=(UI_FONT, get_ui_font_size(9), "bold"),
                  relief=tk.FLAT, cursor="hand2", width=12).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(btn_frame, text="中断", command=_on_cancel,
                  bg="#EEEEEE", font=(UI_FONT, get_ui_font_size(9)),
                  relief=tk.FLAT, cursor="hand2", width=8).pack(side=tk.LEFT)

        # ダイアログを中央に配置
        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()

        if not result["accepted"]:
            return False

        # 修復結果を適用
        for key, (path_var, gui_var, _, _, _) in path_vars.items():
            val = path_var.get()
            if val and val != "(未設定)":
                gui_var.set(val)

        return True

    def _apply_session_state(self, state):
        """session_state を GUI に適用する。パスが無効な場合は修復を試みる。

        処理フロー:
            1. 全パスを事前スキャンし、解決できないものを一覧化
            2. 壊れたパスがあれば一覧修復ダイアログを表示
               （1つのウィンドウで全項目を確認・修復）
            3. ユーザーが「復元する」→ 修復済み項目を適用、未修復はスキップ
               ユーザーが「中断」→ 復元全体を中断

        Returns:
            True: 復元成功, False: 復元キャンセル
        """
        base_folder = Path(state.get("image_folder", ""))

        # マーク形式の不一致ガード: 標準セッションを数学モードで復元（またはその逆）
        # すると採点ルールが食い違い誤採点になるため、復元を中止する
        saved_format = state.get("mark_format", MARK_FORMAT_STANDARD)
        current_format = getattr(self, 'mark_format', MARK_FORMAT_STANDARD)
        if saved_format != current_format:
            fmt_names = {MARK_FORMAT_STANDARD: "標準マーク", MARK_FORMAT_MULTI_DIGIT: "数学マーク（複数桁）"}
            messagebox.showerror(
                "復元エラー",
                f"セッションのマーク形式（{fmt_names.get(saved_format, saved_format)}）が"
                f"現在のモード（{fmt_names.get(current_format, current_format)}）と一致しません。\n\n"
                "アプリを終了し、起動画面で対応するモードを選択してから復元してください。"
            )
            return False

        # 画像フォルダ自体の確認（PDF展開後のフォルダも含む）
        if not base_folder.exists():
            messagebox.showerror(
                "復元エラー",
                f"画像フォルダが見つかりません:\n{base_folder}\n\n"
                "フォルダを移動・削除していないか確認してください。"
            )
            return False

        self.image_folder_path.set(str(base_folder))

        # 各パスの定義
        path_items = [
            ("coord_excel", "座標ファイル", "coordinates.csv または mark_areas.xlsx",
             [("Excelファイル", "*.xlsx *.xls *.csv"), ("すべてのファイル", "*.*")],
             self.coord_excel_path),
            ("template", "正答データ (Answer Key)", ANSWER_KEY_FILE,
             [("Excelファイル", "*.xlsx *.xls"), ("すべてのファイル", "*.*")],
             self.template_path),
            ("omr_result", "OMR読取結果", "Mark2-Result-*.xlsx",
             [("Excelファイル", "*.xlsx *.xls"), ("すべてのファイル", "*.*")],
             self.mark2_result_path),
        ]

        # ---- 事前スキャン: 解決可能なパスは即適用、壊れたパスを収集 ----
        broken_items = []  # (index, key, desc, expected, ftypes, var)
        for idx, (key, desc, expected, ftypes, var) in enumerate(path_items):
            saved = state.get(key, "")
            if not saved:
                continue
            resolved = self._resolve_path(base_folder, saved)
            if resolved:
                var.set(str(resolved))
            else:
                broken_items.append((idx, key, desc, expected, ftypes, var))

        # ---- 壊れたパスがある場合: 一覧修復ダイアログを表示 ----
        if broken_items:
            if not self._show_repair_dialog(broken_items):
                return False

        # 数値・フラグの復元
        self.skip_questions.set(state.get("skip_questions", "4"))
        self.color_threshold.set(state.get("color_threshold", 0.1))
        self.area_threshold.set(state.get("area_threshold", 0.4))

        # descriptive_enabled は起動時の app_mode によって決まるため、
        # MODE_MARK_AND_DESCRIPTIVE のときのみセッション値を復元する。
        # MODE_MARK_ONLY でマーク＆記述セッションを読み込んだ際に
        # descriptive_enabled=True が適用されると _on_descriptive_toggle(True) で
        # 記述UI が強制表示・Step2 レイアウトが壊れ、マークチェックボタンが
        # 無効のままになるバグを防ぐ。
        # MODE_MARK_ONLY: False 固定（init で設定済み）
        # MODE_DESCRIPTIVE_ONLY: True 固定（init で設定済み）
        if self.app_mode == MODE_MARK_AND_DESCRIPTIVE:
            desc_on = state.get("descriptive_enabled", True)
            self.descriptive_enabled.set(desc_on)
            self._on_descriptive_toggle()

        # 描画詳細設定の復元
        saved_rs = state.get("rendering_settings")
        if saved_rs and isinstance(saved_rs, dict):
            self.rendering_settings = get_rendering_settings(saved_rs)

        # データソースラベルを最新状態に反映（Entry は textvariable で自動反映される）

        return True

    def _restore_session_interactive(self):
        """「前回の状態を復元」ボタンのハンドラ

        フロー:
          1. ファイル選択ダイアログで session_state.json を指定
          2. JSON 読み込み・バリデーション
          3. _apply_session_state でパス検証 → 壊れたパスの修復ダイアログ
          4. 成功時にステータスパネル更新
        """
        # Step 1: ユーザーに session_state.json を選択させる
        selected = filedialog.askopenfilename(
            title=f"セッションファイルを選択 — {SESSION_STATE_FILE}",
            filetypes=[
                ("セッションファイル", SESSION_STATE_FILE),
                ("JSONファイル", "*.json"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if not selected:
            return

        # Step 2: JSON の読み込みと基本的な構造チェック
        state = self._load_session_state(Path(selected))
        if not state:
            messagebox.showerror("エラー", "セッションファイルの読み込みに失敗しました。\n形式が正しくないか、破損しています。")
            return

        # Step 3: GUI 状態へ適用（パス修復ダイアログが表示される場合あり）
        self.log_message(f"セッション復元中: {selected}")
        if self._apply_session_state(state):
            # Step 4: 復元成功 → ログ出力 & 記述ステータス更新
            saved_at = state.get("saved_at", "不明")
            self.log_message(f"✓ セッション復元完了 (保存日時: {saved_at})")
            self._update_descriptive_status()
            self._update_step_availability()
        else:
            self.log_message("✗ セッション復元がキャンセルされました。")

    def _try_auto_restore(self):
        """画像フォルダ選択時に既存の session_state.json を検出して自動復元を提案

        画像フォルダが選択された直後に呼ばれ、同フォルダ内に
        前回のセッションファイルが存在すればユーザーに復元を提案する。
        復元をスキップした場合は何もせずに return する。
        """
        # Step 1: 現在の画像フォルダに session_state.json が存在するか確認
        session_path = self._get_session_state_path()
        if not session_path or not session_path.exists():
            return

        # Step 2: JSON の読み込み（破損ファイルの場合は静かにスキップ）
        state = self._load_session_state(session_path)
        if not state:
            return

        # Step 3: ユーザーに復元するか確認
        saved_at = state.get("saved_at", "不明")
        answer = messagebox.askyesno(
            "セッション復元",
            f"このフォルダには前回のセッション情報が見つかりました。\n\n"
            f"保存日時: {saved_at}\n\n"
            f"前回の設定を復元しますか？"
        )
        if answer:
            # Step 4: 適用（パス修復が必要な場合はダイアログが表示される）
            if self._apply_session_state(state):
                self.log_message(f"✓ セッション自動復元完了 (保存日時: {saved_at})")
                self._update_descriptive_status()
                self._update_step_availability()

    def _auto_restore_from_path(self, session_path):
        """指定されたセッションファイルからの自動復元（起動時復元用）"""
        state = self._load_session_state(Path(session_path))
        if not state:
            messagebox.showerror("エラー", "セッションファイルの読み込みに失敗しました。")
            return

        self.log_message(f"セッション復元中: {session_path}")
        if self._apply_session_state(state):
            saved_at = state.get("saved_at", "不明")
            self.log_message(f"✓ セッション復元完了 (保存日時: {saved_at})")
            self._update_descriptive_status()
            self._update_step_availability()
        else:
            self.log_message("✗ セッション復元がキャンセルされました。")

    def setup_total_position(self):
        """合計点表示位置の設定（マーク採点・記述採点共通）"""
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
        if not boxed_folder.exists():
            step1_name = "画像準備" if self.app_mode == MODE_DESCRIPTIVE_ONLY else "OMR認識"
            messagebox.showerror(
                "エラー",
                f"補正済み画像フォルダが存在しません。\n"
                f"Step 1（{step1_name}）を先に実行してください。"
            )
            return

        # 最初の画像を取得
        image_files = sorted(boxed_folder.glob("*.jpg")) + sorted(boxed_folder.glob("*.png"))
        if not image_files:
            messagebox.showerror("エラー", "補正済み画像が見つかりません")
            return

        # -- 記述のみモード: AnswerKeyなしで記述配点のみでプレビュー --
        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            try:
                results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
                desc_config_path = results_data_folder / "descriptive_config.json"
                aspect_max = {}
                total_max = 0

                if desc_config_path.exists():
                    from descriptive_scorer import load_descriptive_config
                    desc_config = load_descriptive_config(str(desc_config_path))
                    if desc_config:
                        for q in desc_config.get("questions", []):
                            asp = q.get("aspect", 1)
                            ms = q.get("max_score", 0)
                            aspect_max[asp] = aspect_max.get(asp, 0) + ms
                            total_max += ms

                if total_max == 0:
                    preview_text = "得点：? / ?"
                    recommended_w, recommended_h = 200, 50
                else:
                    line1 = f"得点：{total_max} / {total_max}"
                    sorted_aspects = sorted(aspect_max.keys())
                    parts = []
                    for asp in sorted_aspects:
                        circled = number_to_circled(asp)
                        mx = aspect_max[asp]
                        parts.append(f"観点{circled}：{mx}/{mx}")
                    line2 = "(" + " ".join(parts) + ")"
                    preview_text = line1 + "\n" + line2
                    try:
                        font14 = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 14)
                        font12 = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 12)
                    except Exception:
                        font14 = ImageFont.load_default()
                        font12 = font14
                    tmp_img = Image.new('RGB', (800, 200))
                    tmp_draw = ImageDraw.Draw(tmp_img)
                    bbox1 = tmp_draw.textbbox((0, 0), line1, font=font14)
                    bbox2 = tmp_draw.textbbox((0, 0), line2, font=font12)
                    text_w = max(bbox1[2] - bbox1[0], bbox2[2] - bbox2[0])
                    text_h = (bbox1[3] - bbox1[1]) + (bbox2[3] - bbox2[1]) + 4
                    recommended_w = text_w + 16
                    recommended_h = text_h + 12

                from descriptive_scorer import (
                    select_total_position, save_total_display_config,
                    TOTAL_DISPLAY_CONFIG_FILE
                )
                region = select_total_position(
                    str(image_files[0]), parent=self.root,
                    preview_text=preview_text,
                    initial_size=(recommended_w, recommended_h),
                )
                if region:
                    config_path = str(results_data_folder / TOTAL_DISPLAY_CONFIG_FILE)
                    save_total_display_config(config_path, list(region))
                    self.log_message(f"✓ 合計点表示位置を保存しました")
                else:
                    self.log_message("合計点位置設定がキャンセルされました。")
            except Exception as e:
                self.log_message(f"合計点位置設定エラー: {e}")
                import traceback
                self.log_message(traceback.format_exc())
                messagebox.showerror("エラー", f"合計点位置設定中にエラーが発生しました:\n{e}")
            return

        # -- マーク系モード: AnswerKey必須 --
        # AnswerKey必須チェック
        template_path = self.template_path.get()
        if not template_path or not Path(template_path).exists():
            messagebox.showerror(
                "エラー",
                "正答データ（Answer Key）が設定されていません。\n"
                "先に正答データのファイルを選択してください。"
            )
            return

        # AnswerKeyから満点ベースのプレビューテキストを生成
        try:
            template_dict = load_template(template_path, mark_format=self.mark_format)
            aspect_max = {}
            for q_no, q_info in template_dict.items():
                asp = q_info.get('観点', 1)
                score = q_info.get('配点', 0)
                aspect_max[asp] = aspect_max.get(asp, 0) + score
            total_max = sum(aspect_max.values())

            # 記述ON時は記述分の配点も合算
            if self.descriptive_enabled.get():
                results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
                desc_config_path = results_data_folder / "descriptive_config.json"
                if desc_config_path.exists():
                    try:
                        from descriptive_scorer import load_descriptive_config
                        desc_config = load_descriptive_config(str(desc_config_path))
                        if desc_config:
                            for q in desc_config.get("questions", []):
                                asp = q.get("aspect", 1)
                                ms = q.get("max_score", 0)
                                aspect_max[asp] = aspect_max.get(asp, 0) + ms
                                total_max += ms
                    except Exception:
                        pass

            # 満点ベースのプレビューテキスト
            line1 = f"得点：{total_max} / {total_max}"
            sorted_aspects = sorted(aspect_max.keys())
            parts = []
            for asp in sorted_aspects:
                circled = number_to_circled(asp)
                mx = aspect_max[asp]
                parts.append(f"観点{circled}：{mx}/{mx}")
            line2 = "(" + " ".join(parts) + ")"
            preview_text = line1 + "\n" + line2

            # プレビューテキストに合わせたボックス初期サイズを計算
            try:
                font14 = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 14)
                font12 = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 12)
            except Exception:
                font14 = ImageFont.load_default()
                font12 = font14
            tmp_img = Image.new('RGB', (800, 200))
            tmp_draw = ImageDraw.Draw(tmp_img)
            bbox1 = tmp_draw.textbbox((0, 0), line1, font=font14)
            bbox2 = tmp_draw.textbbox((0, 0), line2, font=font12)
            text_w = max(bbox1[2] - bbox1[0], bbox2[2] - bbox2[0])
            text_h = (bbox1[3] - bbox1[1]) + (bbox2[3] - bbox2[1]) + 4
            # パディング込みの推奨サイズ
            recommended_w = text_w + 16
            recommended_h = text_h + 12

        except Exception as e:
            self.log_message(f"正答データの読み込みに失敗しました: {e}")
            messagebox.showerror("エラー", f"正答データの読み込みに失敗しました:\n{e}")
            return

        try:
            from descriptive_scorer import (
                select_total_position, save_total_display_config,
                TOTAL_DISPLAY_CONFIG_FILE
            )
            region = select_total_position(
                str(image_files[0]), parent=self.root,
                preview_text=preview_text,
                initial_size=(recommended_w, recommended_h),
            )
            if region:
                results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
                config_path = str(results_data_folder / TOTAL_DISPLAY_CONFIG_FILE)
                save_total_display_config(config_path, list(region))
                self.log_message(f"✓ 合計点表示位置を保存しました: {TOTAL_DISPLAY_CONFIG_FILE}")
            else:
                self.log_message("合計点位置設定がキャンセルされました。")
        except Exception as e:
            self.log_message(f"合計点位置設定エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            messagebox.showerror("エラー", f"合計点位置設定中にエラーが発生しました:\n{e}")

    def setup_descriptive(self):
        """記述問題の領域設定

        既存設定がある場合は「設定を続行 / 初期化 / キャンセル」の
        3択ダイアログを表示する。初期化を選ぶと _reset_descriptive_data
        を呼び設定ファイルを削除後、メイン画面に戻る。
        """
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
        if not boxed_folder.exists():
            step1_name = "画像準備" if self.app_mode == MODE_DESCRIPTIVE_ONLY else "OMR認識"
            messagebox.showerror(
                "エラー",
                f"補正済み画像フォルダが存在しません。\n"
                f"Step 1（{step1_name}）を先に実行してください。"
            )
            return

        results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = str(results_data_folder / "descriptive_config.json")

        # --- 既存設定がある場合: 続行 / 初期化 / キャンセル ---
        if Path(config_path).exists():
            choice = self._ask_descriptive_setup_action()
            if choice == "reset":
                self._reset_descriptive_data()
                return
            elif choice == "cancel":
                return
            # choice == "continue" → 統合ウィンドウで既存設定を読み込んで続行

        try:
            from descriptive_scorer import setup_descriptive_regions_integrated
            config = setup_descriptive_regions_integrated(
                str(boxed_folder), config_path, parent=self.root
            )
            if config:
                self.log_message(f"✓ 記述問題設定完了: {len(config['questions'])}問")
                self._update_descriptive_status()
                self._save_session_state()
            else:
                self.log_message("記述問題設定がキャンセルされました。")
        except Exception as e:
            self.log_message(f"記述問題設定エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            messagebox.showerror("エラー", f"記述問題設定中にエラーが発生しました:\n{e}")

    def _ask_descriptive_setup_action(self):
        """記述問題設定ボタン押下時の3択ダイアログ。

        Returns:
            "continue": 設定を続行（問題を追加）
            "reset": 既存設定を初期化
            "cancel": 何もしない
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("記述問題設定")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        result = {"value": "cancel"}

        tk.Label(
            dialog,
            text="既に記述問題の設定が存在します。\nどの操作を行いますか？",
            font=(UI_FONT, get_ui_font_size(10)),
            justify=tk.LEFT, padx=20, pady=15,
        ).pack(fill=tk.X)

        btn_frame = tk.Frame(dialog, padx=20, pady=10)
        btn_frame.pack(fill=tk.X)

        def choose(val):
            result["value"] = val
            dialog.destroy()

        tk.Button(
            btn_frame, text="設定を続行（問題を追加）",
            command=lambda: choose("continue"),
            bg="#A5D6A7", font=(UI_FONT, get_ui_font_size(9), "bold"),
            relief=tk.FLAT, cursor="hand2", height=2,
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            btn_frame, text="🗑 既存設定を初期化",
            command=lambda: choose("reset"),
            bg="#FFCDD2", font=(UI_FONT, get_ui_font_size(9)),
            relief=tk.FLAT, cursor="hand2", height=2,
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            btn_frame, text="キャンセル",
            command=lambda: choose("cancel"),
            bg="#EEEEEE", font=(UI_FONT, get_ui_font_size(9)),
            relief=tk.FLAT, cursor="hand2",
        ).pack(fill=tk.X, pady=2)

        # ダイアログを中央に配置
        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()
        return result["value"]

    def run_descriptive_scoring(self):
        """記述採点GUIを起動"""
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
        clean_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / CLEAN_FOLDER
        results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = results_data_folder / "descriptive_config.json"
        scores_path = results_data_folder / "descriptive_scores.json"

        if not config_path.exists():
            messagebox.showerror(
                "エラー",
                "記述問題の設定が見つかりません。\n"
                "先に「記述設定」を実行してください。"
            )
            return

        if not boxed_folder.exists():
            messagebox.showerror(
                "エラー",
                "補正済み画像フォルダが存在しません。\n"
                "Step 1（OMR認識）を先に実行してください。"
            )
            return

        try:
            from descriptive_scorer import load_descriptive_config, DescriptiveScorerGUI
            config = load_descriptive_config(str(config_path))
            if not config:
                messagebox.showerror("エラー", "記述問題設定ファイルの読み込みに失敗しました。")
                return

            # 記述のみモードでは 00_Processing が元画像そのものなので高解像度パス不要
            # マーク系モードのみ original_image_folder を渡して高解像度切り出しを行う
            orig_folder = (
                self.image_folder_path.get()
                if self.app_mode != MODE_DESCRIPTIVE_ONLY
                else None
            )

            # クリーン画像フォルダ（枠描画なし）を優先使用
            # 存在しない場合はboxedフォルダにフォールバック
            image_folder_for_desc = str(clean_folder) if clean_folder.exists() else str(boxed_folder)

            scorer = DescriptiveScorerGUI(
                parent=self.root,
                config=config,
                image_folder=image_folder_for_desc,
                scores_save_path=str(scores_path),
                original_image_folder=orig_folder,
            )
            result = scorer.run()

            if result is not None:
                self.log_message(f"✓ 記述採点完了: {len(result)}枚")
                self._update_descriptive_status()
                self._save_session_state()
            else:
                self.log_message("記述採点がキャンセルされました。")
        except Exception as e:
            self.log_message(f"記述採点エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            messagebox.showerror("エラー", f"記述採点中にエラーが発生しました:\n{e}")

    def run_generate_return_sheets(self):
        """返却答案を生成（レガシーメソッド — ボタン廃止済みだがAPI互換のため残置）"""
        if self._processing:
            return
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return
        if not self.coord_excel_path.get():
            messagebox.showerror("エラー", "座標ファイルを選択してください")
            return
        if not self.template_path.get():
            messagebox.showerror("エラー", "正答データファイルを選択してください")
            return
        if not self.mark2_result_path.get():
            messagebox.showerror("エラー", "OMR読取結果ファイルを選択してください")
            return

        for path_var, name in [
            (self.image_folder_path, "画像フォルダ"),
            (self.template_path, "正答データファイル"),
            (self.mark2_result_path, "OMR読取結果ファイル"),
        ]:
            if not Path(path_var.get()).exists():
                messagebox.showerror("エラー", f"{name}が存在しません")
                return

        results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = results_data_folder / "descriptive_config.json"
        scores_path = results_data_folder / "descriptive_scores.json"

        if not config_path.exists():
            messagebox.showerror("エラー", "記述問題の設定が見つかりません。\n先に「記述設定」を実行してください。")
            return
        if not scores_path.exists():
            messagebox.showerror(
                "エラー",
                "記述採点結果が見つかりません。\n先に「記述採点」を実行してください。"
            )
            return

        if not messagebox.askyesno(
            "確認",
            "返却答案を生成しますか？\n\n"
            "マーク採点 + 記述採点を合成した画像を\n"
            "02_Graded_Detail/ に保存します。\n\n"
            "※ 既存の採点済み画像は上書きされます。"
        ):
            return

        self._set_processing_state(True)
        # メインスレッドでStringVar値をキャプチャ（スレッドセーフ）
        params = {
            'image_folder': self.image_folder_path.get(),
            'coord_excel': self.coord_excel_path.get(),
            'template_path': self.template_path.get(),
            'mark2_result_path': self.mark2_result_path.get(),
            'skip_questions': int(self.skip_questions.get()),
        }
        thread = threading.Thread(
            target=self._run_return_sheets_thread, args=(params,), daemon=True
        )
        thread.start()

    def _run_return_sheets_thread(self, params):
        """返却答案生成の実行（別スレッド）"""
        try:
            from descriptive_scorer import (
                load_descriptive_config, load_descriptive_scores,
                generate_return_sheets,
            )

            results_data_folder = Path(params['image_folder']) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
            config = load_descriptive_config(
                str(results_data_folder / "descriptive_config.json")
            )
            scores_data = load_descriptive_scores(
                str(results_data_folder / "descriptive_scores.json")
            )

            if not config or not scores_data:
                self.root.after(0, lambda: messagebox.showerror(
                    "エラー", "設定またはスコアの読み込みに失敗しました。"
                ))
                return

            scores = scores_data.get("scores", {})
            output_folder = Path(params['image_folder']) / RESULTS_FOLDER / SCORED_FOLDER

            result = generate_return_sheets(
                image_folder=params['image_folder'],
                config=config,
                descriptive_scores=scores,
                coord_excel_path=params['coord_excel'],
                template_path=params['template_path'],
                mark2_result_path=params['mark2_result_path'],
                skip_questions=params['skip_questions'],
                output_folder=str(output_folder),
                log_callback=self.log_message,
                mark_format=self.mark_format,
            )

            if result:
                self.last_scored_folder = str(output_folder)
                self.root.after(0, lambda: self.open_scored_btn.config(state=tk.NORMAL))

                self.root.after(0, lambda: messagebox.showinfo(
                    "完了",
                    f"返却答案の生成が完了しました！\n\n"
                    f"成功: {result['success_count']}件\n"
                    f"エラー: {result['error_count']}件\n\n"
                    f"出力先: {output_folder}"
                ))
        except Exception as e:
            self.log_message(f"返却答案生成エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror(
                "エラー", f"返却答案生成中にエラーが発生しました:\n{e}"
            ))

        finally:
            self.root.after(0, self._set_processing_state, False)

    # ---------------------------------------------------------
    # 既存メソッド
    # ---------------------------------------------------------

    def validate_inputs(self):
        """入力値の検証"""
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return False
        
        if not self.coord_excel_path.get():
            messagebox.showerror("エラー", "座標ファイルを選択してください")
            return False
        
        if not Path(self.image_folder_path.get()).exists():
            messagebox.showerror("エラー", "画像フォルダが存在しません")
            return False
        
        if not Path(self.coord_excel_path.get()).exists():
            messagebox.showerror("エラー", "座標ファイルが存在しません")
            return False
        
        try:
            skip = int(self.skip_questions.get())
            if skip < 0:
                raise ValueError("負の値は指定できません")
        except ValueError:
            messagebox.showerror("エラー", "スキップする問題数は0以上の整数で指定してください")
            return False
        
        return True

    # ---------------------------------------------------------
    # 処理中状態の管理
    # ---------------------------------------------------------

    def _set_processing_state(self, busy: bool):
        """処理中/待機中の状態を切り替える。

        busy=True  → プログレスバー表示 & 全操作ボタン無効化
        busy=False → プログレスバー非表示 & 全操作ボタン有効化

        フォルダ/Excel選択ボタンも無効化し、処理中のパス変更によるデータ不整合を防ぐ。
        """
        self._processing = busy
        action_buttons = [
            self._btn_run_box,
            self._btn_mark_check,
            self._btn_total_pos,
            self._btn_run_scoring,
            self._btn_run_summary,
            self.desc_setup_btn,
            self.desc_scoring_btn,
            self._btn_desc_review,
            self._chk_descriptive,
            # データソース選択ボタンも無効化（処理中パス変更防止）
            self._btn_select_folder,
            self._btn_select_pdf,
            self._btn_select_excel,
        ]
        if busy:
            self._cancel_event.clear()
            self._progress_bar["value"] = 0
            self._progress_bar.pack(fill=tk.X, pady=(4, 0))
            self._cancel_frame.pack(fill=tk.X, pady=(2, 0))
            self._btn_cancel.config(state=tk.NORMAL)
            for btn in action_buttons:
                btn.config(state=tk.DISABLED)
        else:
            self._progress_bar["value"] = 0
            self._progress_bar.pack_forget()
            self._cancel_frame.pack_forget()
            for btn in action_buttons:
                btn.config(state=tk.NORMAL)
            # Stepガードを再適用（未設定ボタンを無条件にNORMALに戻さない）
            self._update_step_availability()

    def _update_progress(self, current, total):
        """プログレスバーを更新（バックグラウンドスレッドから安全に呼び出し可能）。

        Args:
            current: 現在の処理済み件数
            total: 全件数
        """
        import threading as _threading
        if _threading.current_thread() is not _threading.main_thread():
            self.root.after(0, self._update_progress, current, total)
            return
        if total > 0:
            self._progress_bar["value"] = int(current / total * 100)

    def _request_cancel(self):
        """ユーザーが中断ボタンを押した時の処理。"""
        self._cancel_event.set()
        self._btn_cancel.config(state=tk.DISABLED)
        self.log_message("⏹ 中断を要求しました。現在の処理が完了次第停止します...")

    def _confirm_mark_format_coord_match(self, coord_path, skip_q):
        """モード(mark_format)と座標ファイルの選択肢数の整合を確認する。

        数学マーク（複数桁）モードは15マーク紙面（-, 0〜9, a〜d）を想定するため、
        10択の標準座標ファイルとの組合せ（およびその逆）は誤採点につながる。
        不一致が疑われる場合は警告し、ユーザーが続行を選んだ場合のみTrueを返す。
        判定不能（パース失敗等）の場合は黙ってTrue（既存のエラー処理に委ねる）。
        """
        try:
            from collections import Counter
            from omr_engine import parse_excel_coordinates
            coords, _ = parse_excel_coordinates(coord_path)
            per_q = {}
            for c in coords:
                per_q[c['question_no']] = per_q.get(c['question_no'], 0) + 1
            answer_counts = [n for q, n in per_q.items()
                             if isinstance(q, (int, float)) and q > skip_q]
            if not answer_counts:
                return True
            typical = Counter(answer_counts).most_common(1)[0][0]
            is_md = getattr(self, 'mark_format', MARK_FORMAT_STANDARD) == MARK_FORMAT_MULTI_DIGIT
            if is_md and typical <= 10:
                msg = (
                    f"数学マーク採点（複数桁）モードですが、選択した座標ファイルの設問は"
                    f"{typical}択（標準テンプレート相当）です。\n\n"
                    "複数桁モードは15マーク（-, 0〜9, a〜d）の紙面を想定しています。\n"
                    "座標ファイルまたは起動モードが違っていませんか？\n\n"
                    "このまま続行しますか？")
            elif (not is_md) and typical >= 11:
                msg = (
                    f"標準マーク採点モードですが、選択した座標ファイルの設問は"
                    f"{typical}マーク（複数桁テンプレート相当）です。\n\n"
                    "数学マーク採点（複数桁）モードで起動し直す必要はありませんか？\n\n"
                    "このまま続行しますか？")
            else:
                return True
            return messagebox.askyesno("モードと座標ファイルの確認", msg)
        except Exception:
            return True

    def run_box_drawer(self):
        """枠描画処理を実行"""
        if self._processing:
            return
        if not self.validate_inputs():
            return
        if not self._confirm_mark_format_coord_match(
                self.coord_excel_path.get(), int(self.skip_questions.get())):
            return
        
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        self.log_message("=" * 60)
        self.log_message("枠描画処理を開始します...")
        self.log_message("=" * 60)
        
        self._set_processing_state(True)
        # メインスレッドでStringVar値をキャプチャ（スレッドセーフ）
        params = {
            'image_folder': self.image_folder_path.get(),
            'coord_excel': self.coord_excel_path.get(),
            'skip_questions': int(self.skip_questions.get()),
            'color_threshold': self.color_threshold.get(),
            'area_threshold': self.area_threshold.get(),
            'omr_mode': self.omr_mode.get(),
            'mark_format': self.mark_format,
        }
        thread = threading.Thread(target=self._run_box_drawer_thread, args=(params,), daemon=True)
        thread.start()
    
    def _run_box_drawer_thread(self, params):
        """枠描画処理の実際の実行（別スレッド）"""
        gui_handler, suppressed = self._attach_gui_log_handler()
        try:
            result = process_folder(
                params['image_folder'],
                params['coord_excel'],
                skip_questions=params['skip_questions'],
                output_base_folder=None,
                debug=False,
                color_threshold=params['color_threshold'],
                area_threshold=params['area_threshold'],
                progress_callback=self._update_progress,
                cancel_event=self._cancel_event,
                omr_mode=params['omr_mode'],
                mark_format=params['mark_format'],
            )

            # 中断された場合
            if self._cancel_event.is_set():
                self.log_message("")
                self.log_message("=" * 60)
                self.log_message("⏹ 処理が中断されました")
                self.log_message("=" * 60)
                self.root.after(0, lambda: messagebox.showwarning("中断", "処理が中断されました。"))
                return

            self.log_message("")
            self.log_message("=" * 60)
            self.log_message("処理が正常に完了しました！")
            self.log_message("=" * 60)
            
            results_folder = Path(params['image_folder']) / RESULTS_FOLDER
            self.last_boxed_folder = str(results_folder / BOXED_FOLDER)
            
            self.root.after(0, lambda: self.open_boxed_btn.config(state=tk.NORMAL))
            
            # ユーザーが既にテンプレートパスを設定済みの場合は上書きしない
            user_template = self.template_path.get().strip()
            if not user_template:
                self.root.after(0, self.auto_detect_template)
            
            self.root.after(0, lambda: self._auto_detect_omr_result(results_folder))
            self.root.after(0, self._save_session_state)
            self.root.after(0, self._update_step_availability)

            # --- Answer Key 空検出 ---
            # ユーザーが既にテンプレートを指定している場合（再実行シナリオ等）は
            # そのファイルの中身を確認し、正答入力済みならガイドをスキップする
            need_answer_key_guide = False
            results_data_folder = Path(params['image_folder']) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
            try:
                # ユーザー指定のテンプレートがあればそちらを確認
                check_path = Path(user_template) if user_template else results_data_folder / ANSWER_KEY_FILE

                if check_path.exists():
                    import pandas as pd
                    df = pd.read_excel(check_path)

                    if len(df) == 0:
                        need_answer_key_guide = True
                    elif '正答' in df.columns and '配点' in df.columns:
                        answers = df['正答'].fillna('').astype(str).str.strip()
                        points = df['配点'].fillna('').astype(str).str.strip()
                        if (answers == '').all() and (points == '').all():
                            need_answer_key_guide = True
                else:
                    # テンプレートファイル自体が存在しない場合もガイド不要
                    # （auto_detect_template未実行の初回等）
                    need_answer_key_guide = False
            except Exception as e:
                self.log_message(f"Answer Key 確認処理中にエラー: {e}")

            # 完了報告とAnswer Keyガイドを1つのフローにまとめる
            if result:
                summary = f"""処理が正常に完了しました！

【処理結果】
・処理対象: {result['total_count']}件
・成功: {result['success_count']}件
・エラー: {result['error_count']}件
・実行時間: {result['elapsed_time']:.2f}秒

出力フォルダ: {results_folder}

【生成ファイル】
・マーク認識結果Excel (Mark2-Result-...)
・枠描画済み画像
・coordinates.csv"""
                error_files = result.get('error_files') or []
                if error_files:
                    shown = error_files[:20]
                    file_list = "\n".join(f"・{fn}" for fn in shown)
                    if len(error_files) > len(shown):
                        file_list += f"\n…他{len(error_files) - len(shown)}件"
                    summary += (
                        "\n\n【排除候補（四隅マーカー等が検出できず処理できなかったページ）】\n"
                        f"{file_list}\n"
                        "スキャン向き・折れ・切れなどを確認し、必要であれば元フォルダから\n"
                        "除外して再スキャン・再実行してください。"
                    )
            else:
                summary = "マーク認識・枠描画処理が正常に完了しました！"

            if need_answer_key_guide:
                # 完了情報を含んだガイドダイアログを1つだけ表示
                def _show_combined():
                    self._show_answer_key_guide_dialog(results_data_folder, completion_summary=summary)
                self.root.after(0, _show_combined)
            else:
                # ガイド不要（正答入力済みまたは再実行）→ 完了メッセージのみ
                self.root.after(0, lambda: messagebox.showinfo("完了", summary))
            
        except Exception as e:
            self.log_message("")
            self.log_message("=" * 60)
            self.log_message(f"エラーが発生しました: {e}")
            self.log_message("=" * 60)
            
            import traceback
            self.log_message("\n詳細なエラー情報:")
            self.log_message(traceback.format_exc())
            
            self.root.after(0, lambda: messagebox.showerror("エラー", self._friendly_error_message(e)))

        finally:
            self._detach_gui_log_handler(gui_handler, suppressed)
            self.root.after(0, self._set_processing_state, False)

    def _show_answer_key_guide_dialog(self, results_data_folder, completion_summary=None):
        """Answer Key 未入力時のガイドダイアログ（カスタム・高視認性）

        処理完了情報と Answer Key 入力案内を1つのダイアログにまとめて表示する。
        「後で入力する」を選んだ場合はテンプレートパスの自動設定を行わない
        （ユーザーが自分で管理するエキスパートフローとして扱う）。

        Args:
            results_data_folder: 01_Results フォルダのパス
            completion_summary: 処理完了サマリー文字列（Noneなら非表示）
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("📋 処理完了 — 正答・配点の入力が必要です")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.configure(bg="#FFFDE7")

        # 処理完了サマリー（緑の完了帯）
        if completion_summary:
            done_frame = tk.Frame(dialog, bg="#E8F5E9", padx=20, pady=10)
            done_frame.pack(fill=tk.X)
            tk.Label(
                done_frame, text="✅ " + completion_summary,
                font=(UI_FONT, get_ui_font_size(9)), fg="#2E7D32", bg="#E8F5E9",
                justify=tk.LEFT, wraplength=480,
            ).pack(anchor=tk.W)

        # ヘッダー（黄色の注意帯）
        header_frame = tk.Frame(dialog, bg="#FFF9C4", padx=20, pady=12)
        header_frame.pack(fill=tk.X)
        tk.Label(
            header_frame, text="⚠️ 正答・配点の入力が必要です",
            font=(UI_FONT, get_ui_font_size(14), "bold"), fg="#F57F17", bg="#FFF9C4",
        ).pack(anchor=tk.W)

        # 本文
        body_frame = tk.Frame(dialog, bg="#FFFDE7", padx=20, pady=15)
        body_frame.pack(fill=tk.X)

        msg_lines = [
            f"マーク認識が完了し、{ANSWER_KEY_FILE} が自動生成されました。",
            "",
            "次のステップとして、以下の作業を行ってください：",
        ]
        tk.Label(
            body_frame, text="\n".join(msg_lines),
            font=(UI_FONT, get_ui_font_size(10)), fg="#333333", bg="#FFFDE7",
            justify=tk.LEFT, wraplength=420,
        ).pack(anchor=tk.W)

        # ステップリスト（番号付き）
        steps_frame = tk.Frame(body_frame, bg="#FFF8E1", padx=15, pady=10,
                                relief=tk.SOLID, bd=1)
        steps_frame.pack(fill=tk.X, pady=(10, 5))

        steps = [
            f"① {ANSWER_KEY_FILE} を Excel で開く",
            "② 各問題の「正答」「配点」「観点」を入力",
            "③ 保存して Excel を閉じる",
            "④ 採点侍で次のステップに進む",
        ]
        for step in steps:
            tk.Label(
                steps_frame, text=step,
                font=(UI_FONT, get_ui_font_size(10)), fg="#333333", bg="#FFF8E1",
                anchor=tk.W,
            ).pack(anchor=tk.W, pady=1)

        # ボタンフレーム
        btn_frame = tk.Frame(dialog, bg="#FFFDE7", padx=20, pady=15)
        btn_frame.pack(fill=tk.X)

        def _open_folder():
            try:
                folder_path = str(Path(results_data_folder).resolve())
                open_in_file_manager(folder_path)
            except Exception as e:
                self.log_message(f"フォルダを開けませんでした: {e}")
            # フォルダを開く → テンプレートパスを自動設定
            self.auto_detect_template()
            dialog.destroy()

        def _close():
            # 「後で入力する」 → エキスパートユーザーと判断
            # テンプレートパスの自動設定は行わない
            dialog.destroy()

        tk.Button(
            btn_frame, text="📂 フォルダを開いて編集する",
            command=_open_folder,
            font=(UI_FONT, get_ui_font_size(11), "bold"), bg="#FFD54F", fg="#333333",
            activebackground="#FFC107", relief=tk.FLAT, cursor="hand2",
            padx=20, pady=8,
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(
            btn_frame, text="後で入力する",
            command=_close,
            font=(UI_FONT, get_ui_font_size(10)), bg="#EEEEEE", fg="#666666",
            relief=tk.FLAT, cursor="hand2",
            padx=15, pady=8,
        ).pack(side=tk.LEFT)

        # ダイアログを親ウィンドウの中央に配置
        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dialog.geometry(f"+{x}+{y}")
    
    def run_scoring(self):
        """採点処理を実行（モードに応じた処理分岐）"""
        if self._processing:
            return
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        # --- 記述のみモード ---
        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            return self._run_scoring_descriptive_only()

        # --- マーク系モード: 必須入力チェック ---
        if not self.coord_excel_path.get():
            messagebox.showerror("エラー", "座標ファイルを選択してください")
            return
        
        if not self.template_path.get():
            messagebox.showerror("エラー", "正答データファイルを選択してください")
            return
        
        if not self.mark2_result_path.get():
            messagebox.showerror("エラー", "OMR読取結果ファイルを選択してください")
            return
        
        if not Path(self.image_folder_path.get()).exists():
            messagebox.showerror("エラー", "画像フォルダが存在しません")
            return
        
        if not Path(self.template_path.get()).exists():
            messagebox.showerror("エラー", "正答データファイルが存在しません")
            return
        
        if not Path(self.mark2_result_path.get()).exists():
            messagebox.showerror("エラー", "OMR結果ファイルが存在しません")
            return

        if not self._confirm_mark_format_coord_match(
                self.coord_excel_path.get(), int(self.skip_questions.get())):
            return

        # ----- 記述モード時の事前チェック -----
        # 記述採点が有効な場合、以下の 3 段階でデータの存在と完了状態を確認する。
        # (1) descriptive_config.json が存在するか？
        # (2) descriptive_scores.json が存在するか？
        # (3) 全問題×全生徒の採点が完了しているか？
        # いずれにも引っかかればエラーまたは確認ダイアログを表示し、
        # 未採点分は 0 点として継続するかをユーザーが選択できる。
        use_descriptive = False
        if self.descriptive_enabled.get():
            results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
            desc_config_path = results_data_folder / "descriptive_config.json"
            desc_scores_path = results_data_folder / "descriptive_scores.json"

            if not desc_config_path.exists():
                messagebox.showerror(
                    "エラー",
                    "記述問題の設定が見つかりません。\n"
                    "先に「⚙ 記述問題設定」を実行してください。"
                )
                return
            if not desc_scores_path.exists():
                messagebox.showerror(
                    "エラー",
                    "記述採点結果が見つかりません。\n"
                    "先に「✏ 記述採点」を実行してください。"
                )
                return

            # 採点完了状態のチェック
            is_complete, unscored, total_img, detail = self._check_descriptive_completeness()
            if not is_complete and total_img > 0:
                detail_text = "\n".join(detail) if detail else ""
                if not messagebox.askyesno(
                    "記述採点が未完了です",
                    f"記述採点が完了していない生徒が {unscored}名 います。\n\n"
                    f"{detail_text}\n\n"
                    f"未採点の問題は 0点 として処理されます。\n"
                    f"このまま続行しますか？",
                ):
                    return

            use_descriptive = True
        
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

        self.log_message("=" * 60)
        if use_descriptive:
            self.log_message("採点処理を開始します（マーク＋記述統合モード）...")
        else:
            self.log_message("採点処理を開始します...")
        self.log_message("=" * 60)

        # answer_key編集後の採点実行に合わせて、チェック報告・模範解答mdを再生成する
        # (古い模範解答を配布する事故の防止。エラーがあればこの後の採点でも失敗する)
        self.run_answer_key_check_gui(auto=True)
        
        self._set_processing_state(True)
        # メインスレッドでStringVar値をキャプチャ（スレッドセーフ）
        scoring_params = {
            'image_folder': self.image_folder_path.get(),
            'coord_excel': self.coord_excel_path.get(),
            'template': self.template_path.get(),
            'omr_result': self.mark2_result_path.get(),
            'skip_questions': int(self.skip_questions.get()),
            'rendering_settings': dict(self.rendering_settings),
        }
        thread = threading.Thread(
            target=self._run_scoring_thread,
            args=(use_descriptive, scoring_params),
            daemon=True,
        )
        thread.start()
    
    def _run_scoring_thread(self, use_descriptive=False, scoring_params=None):
        """採点処理の実際の実行（別スレッド）

        daemon スレッドとして実行される。GUI の更新は root.after() 経由で
        メインスレッドに委譲する。

        Args:
            use_descriptive: True の場合、マーク＋記述統合モードで返却シートを生成。
                             False の場合、マーク採点のみ (process_scoring) を使用。
            scoring_params: メインスレッドでキャプチャしたパラメータ dict。
        """
        # パラメータ展開（スレッドセーフ: StringVarは参照しない）
        p = scoring_params or {}
        image_folder = p.get('image_folder', '')
        coord_excel = p.get('coord_excel', '')
        template = p.get('template', '')
        omr_result = p.get('omr_result', '')
        skip_q = p.get('skip_questions', 0)
        r_settings = p.get('rendering_settings', {})

        try:
            # ログに入力パラメータを出力（デバッグ・確認用）
            self.log_message(f"画像フォルダ: {image_folder}")
            self.log_message(f"座標ファイル: {coord_excel}")
            self.log_message(f"正答データ: {template}")
            self.log_message(f"OMR読取結果: {omr_result}")
            self.log_message(f"スキップ問題数: {skip_q}")
            if use_descriptive:
                self.log_message("モード: マーク＋記述統合")
            self.log_message("")

            results_folder = Path(image_folder) / RESULTS_FOLDER

            if use_descriptive:
                # --- 記述統合モード: generate_return_sheets を使用 ---
                # マーク採点結果に記述採点を加算した統合返却シートを生成する。
                # descriptive_scorer モジュールから設定とスコアを読み込み、
                # 合計点表示位置のカスタム設定があれば config に注入する。
                from descriptive_scorer import (
                    load_descriptive_config, load_descriptive_scores,
                    generate_return_sheets,
                )
                results_data_folder = results_folder / RESULTS_DATA_FOLDER
                config = load_descriptive_config(
                    str(results_data_folder / "descriptive_config.json")
                )
                scores_data = load_descriptive_scores(
                    str(results_data_folder / "descriptive_scores.json")
                )
                if not config or not scores_data:
                    self.root.after(0, lambda: messagebox.showerror(
                        "エラー", "記述設定またはスコアの読み込みに失敗しました。"
                    ))
                    return

                # 合計点表示位置の設定を読み込み、config に注入
                try:
                    from descriptive_scorer import load_total_display_config, TOTAL_DISPLAY_CONFIG_FILE
                    tdc_path = str(results_data_folder / TOTAL_DISPLAY_CONFIG_FILE)
                    tdc = load_total_display_config(tdc_path)
                    if tdc and "total_display_region" in tdc:
                        config["total_display_region"] = tdc["total_display_region"]
                        self.log_message("✓ 合計点表示位置: カスタム設定を使用")
                except Exception:
                    pass  # 設定ファイルなし → デフォルト位置で描画

                output_folder = results_folder / SCORED_FOLDER
                result = generate_return_sheets(
                    image_folder=image_folder,
                    config=config,
                    descriptive_scores=scores_data.get("scores", {}),
                    coord_excel_path=coord_excel,
                    template_path=template,
                    mark2_result_path=omr_result,
                    skip_questions=skip_q,
                    output_folder=str(output_folder),
                    log_callback=self.log_message,
                    rendering_settings=r_settings,
                    progress_callback=self._update_progress,
                    cancel_event=self._cancel_event,
                    mark_format=self.mark_format,
                )
            else:
                # --- マーク採点のみ ---
                result = process_scoring(
                    image_folder=image_folder,
                    coord_excel_path=coord_excel,
                    template_path=template,
                    mark2_result_path=omr_result,
                    skip_questions=skip_q,
                    output_base_folder=None,
                    log_callback=self.log_message,
                    rendering_settings=r_settings,
                    progress_callback=self._update_progress,
                    cancel_event=self._cancel_event,
                    mark_format=self.mark_format,
                )
            
            # 中断された場合
            if self._cancel_event.is_set():
                self.log_message("")
                self.log_message("=" * 60)
                self.log_message("⏹ 採点処理が中断されました")
                self.log_message("=" * 60)
                self.root.after(0, lambda: messagebox.showwarning("中断", "採点処理が中断されました。"))
                return

            self.log_message("")
            self.log_message("=" * 60)
            self.log_message("採点処理が正常に完了しました！")
            self.log_message("=" * 60)
            
            self.last_scored_folder = str(results_folder / SCORED_FOLDER)
            self.root.after(0, lambda: self.open_scored_btn.config(state=tk.NORMAL))
            self.root.after(0, self._save_session_state)
            self.root.after(0, self._update_step_availability)
            
            if result:
                mode_label = "マーク＋記述統合" if use_descriptive else "マーク採点"
                summary = (
                    f"採点処理が正常に完了しました！\n\n"
                    f"【処理結果】（{mode_label}）\n"
                    f"・処理対象: {result['total_count']}件\n"
                    f"・成功: {result['success_count']}件\n"
                    f"・エラー: {result['error_count']}件\n\n"
                    f"出力フォルダ: {results_folder}\n\n"
                    f"採点済み画像を確認してください。"
                )
            else:
                summary = "採点処理が正常に完了しました！"
            
            self.root.after(0, lambda: messagebox.showinfo("完了", summary))
            
        except Exception as e:
            self.log_message("")
            self.log_message("=" * 60)
            self.log_message(f"エラーが発生しました: {e}")
            self.log_message("=" * 60)
            
            import traceback
            self.log_message("\n詳細なエラー情報:")
            self.log_message(traceback.format_exc())
            
            self.root.after(0, lambda: messagebox.showerror("エラー", self._friendly_error_message(e)))

        finally:
            self.root.after(0, self._set_processing_state, False)
    
    def run_mark_checker(self):
        """マークチェック機能を起動"""
        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            messagebox.showinfo("情報", "記述のみモードではマークチェックは使用できません。")
            return
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return
        
        results_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER
        coordinates_csv = results_folder / RESULTS_DATA_FOLDER / "coordinates.csv"
        
        if not coordinates_csv.exists():
            messagebox.showerror("エラー", f"coordinates.csvが見つかりません。\n枠描画処理を先に実行してください。\n\n期待されるパス:\n{coordinates_csv}")
            return
        
        if not self.mark2_result_path.get():
            messagebox.showerror("エラー", "OMR読取結果ファイルを選択してください")
            return
            
        if not Path(self.mark2_result_path.get()).exists():
            messagebox.showerror("エラー", "OMR読取結果ファイルが存在しません")
            return
        
        # ログ出力用ウィンドウを表示（または既存のログを使用）
        self.log_message("=" * 60)
        self.log_message("マークチェックツールを起動します...")
        self.log_message("=" * 60)
        
        # 別スレッドで実行し、標準出力をキャプチャ
        thread = threading.Thread(target=self._run_mark_checker_thread, args=(str(self.mark2_result_path.get()), str(coordinates_csv)), daemon=True)
        thread.start()

    def _run_mark_checker_thread(self, xlsx_path, csv_path):
        """マークチェックツールの実行スレッド（ログキャプチャ付き）"""
        try:
            # Toplevelはメインスレッドで作る必要があるため、afterで呼び出す
            self.root.after(0, lambda: self._launch_checker_gui(xlsx_path, csv_path))
                
        except Exception as e:
            self.log_message(f"エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())

    def _launch_checker_gui(self, xlsx_path, csv_path):
        """MarkCheckerGUIを起動（メインスレッド）

        sys.stdout は try/finally で確実に復元する。
        ロガー出力も GUI ログに転送する。
        """
        import sys
        
        # 既存のstdoutを保存
        original_stdout = getattr(self, 'original_stdout', sys.stdout)
        if not hasattr(self, 'original_stdout'):
            self.original_stdout = sys.stdout

        # ロガー出力をGUIログに転送するハンドラを追加
        gui_handler, suppressed = self._attach_gui_log_handler()

        try:
            class LogRedirector:
                def __init__(self, log_func):
                    self.log_func = log_func
                
                def write(self, text):
                    if text.strip():
                        self.log_func(text.strip())
                
                def flush(self):
                    pass
            
            # リダイレクト設定
            sys.stdout = LogRedirector(self.log_message)
            
            # チェッカー起動
            template_path = self.template_path.get() if self.template_path.get() else None
            checker = MarkCheckerGUI(
                self.root,
                self.image_folder_path.get(),
                csv_path,
                xlsx_path,
                int(self.skip_questions.get()),
                template_path=template_path,
                mark_format=self.mark_format
            )
            # MarkCheckerGUIにstdout復帰用の参照を渡す
            checker._original_stdout_ref = original_stdout
            
        except Exception as e:
            self.log_message(f"起動エラー: {e}")
        finally:
            # ロガーハンドラを復元
            self._detach_gui_log_handler(gui_handler, suppressed)
            sys.stdout = original_stdout
    
    def run_summary_generation(self):
        """サマリー生成処理を実行"""
        if self._processing:
            return
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        # --- 記述のみモード ---
        if self.app_mode == MODE_DESCRIPTIVE_ONLY:
            self._run_summary_generation_descriptive_only()
            return
        
        if not self.coord_excel_path.get():
            messagebox.showerror("エラー", "座標ファイルを選択してください")
            return
        
        if not self.template_path.get():
            messagebox.showerror("エラー", "正答データファイルを選択してください")
            return
        
        if not self.mark2_result_path.get():
            messagebox.showerror("エラー", "OMR読取結果ファイルを選択してください")
            return
        
        if not Path(self.image_folder_path.get()).exists():
            messagebox.showerror("エラー", "画像フォルダが存在しません")
            return
        
        if not Path(self.template_path.get()).exists():
            messagebox.showerror("エラー", "正答データファイルが存在しません")
            return
        
        if not Path(self.mark2_result_path.get()).exists():
            messagebox.showerror("エラー", "OMR結果ファイルが存在しません")
            return
        
        if not messagebox.askyesno(
            "確認",
            "集計レポートを生成しますか？\n\n"
            "学生別サマリー、試験統計、分析ファイルなどが\n"
            "結果フォルダに出力されます。"
        ):
            return

        # answer_key編集後の再集計に合わせて、チェック報告・模範解答mdを再生成する
        self.run_answer_key_check_gui(auto=True)

        # --- 氏名欄トリミング（チェックボックスで制御） ---
        name_images = None
        self._name_trimmer = None
        
        if self.name_trim_enabled.get():
            # 00_Processing フォルダから補正済み画像を使用
            boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
            if not boxed_folder.exists():
                messagebox.showerror(
                    "エラー",
                    f"補正済み画像フォルダが存在しません:\n{boxed_folder}\n\n"
                    "Step 1（OMR認識）を先に実行してください。"
                )
                return
            
            try:
                from name_trimmer import NameTrimmer
                trimmer = NameTrimmer()
                name_images = trimmer.run(str(boxed_folder), parent=self.root,
                                          original_image_folder=self.image_folder_path.get())
                
                if name_images is None:
                    # キャンセルされた場合、続行するか確認
                    if not messagebox.askyesno(
                        "確認",
                        "氏名欄トリミングがキャンセルされました。\n"
                        "氏名欄画像なしでサマリー生成を続行しますか？"
                    ):
                        return
                else:
                    self._name_trimmer = trimmer  # cleanup用に保持
                    self.log_message(f"✓ 氏名欄トリミング完了: {len(name_images)}枚")
            except Exception as e:
                self.log_message(f"氏名欄トリミングエラー: {e}")
                if not messagebox.askyesno(
                    "エラー",
                    f"氏名欄トリミング中にエラーが発生しました:\n{e}\n\n"
                    "氏名欄画像なしでサマリー生成を続行しますか？"
                ):
                    return
                name_images = None

        # --- 学籍番号OCR（チェックボックスで制御・実験的機能） ---
        aborted, student_id_result, id_ocr_trimmer = self._run_student_id_ocr_flow(
            self.image_folder_path.get()
        )
        if aborted:
            return
        self._student_id_ocr_trimmer = id_ocr_trimmer

        # --- 記述ON時のデータ存在チェック（スレッド起動前にメインスレッドで確認） ---
        # 記述が有効だがデータがない場合→マーク採点のみで継続するか尋ねる。
        # データがあるが未完了の場合→未採点を 0 点扱いで継続するか尋ねる。
        # これらのダイアログはメインスレッドでのみ安全なため、スレッド起動前に実行する。
        if self.descriptive_enabled.get():
            results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
            config_path = results_data_folder / "descriptive_config.json"
            scores_path = results_data_folder / "descriptive_scores.json"
            if not config_path.exists() or not scores_path.exists():
                missing = []
                if not config_path.exists():
                    missing.append("・記述問題設定（descriptive_config.json）")
                if not scores_path.exists():
                    missing.append("・記述採点結果（descriptive_scores.json）")
                if not messagebox.askyesno(
                    "記述データが見つかりません",
                    "記述採点が有効ですが、以下のデータが見つかりません:\n\n"
                    + "\n".join(missing) + "\n\n"
                    "マーク採点のみで集計を続行しますか？\n"
                    "（いいえ → 先に記述問題設定・記述採点を実行してください）"
                ):
                    return
            else:
                # データは存在するが、採点完了しているかチェック
                is_complete, unscored, total_img, detail = self._check_descriptive_completeness()
                if not is_complete and total_img > 0:
                    detail_text = "\n".join(detail) if detail else ""
                    if not messagebox.askyesno(
                        "記述採点が未完了です",
                        f"記述採点が完了していない生徒が {unscored}名 います。\n\n"
                        f"{detail_text}\n\n"
                        f"未採点の問題は 0点 として集計されます。\n"
                        f"このまま続行しますか？",
                    ):
                        return

        self._set_processing_state(True)
        # メインスレッドでStringVar値をキャプチャ（スレッドセーフ）
        params = {
            'image_folder': self.image_folder_path.get(),
            'coord_excel': self.coord_excel_path.get(),
            'template_path': self.template_path.get(),
            'mark2_result_path': self.mark2_result_path.get(),
            'skip_questions': int(self.skip_questions.get()),
            'descriptive_enabled': self.descriptive_enabled.get(),
            'include_descriptive_in_analysis': self.include_descriptive_in_analysis.get(),
        }
        thread = threading.Thread(
            target=self._run_summary_generation_thread,
            args=(params, name_images, student_id_result),
            daemon=True
        )
        thread.start()

    def _run_student_id_ocr_flow(self, image_folder):
        """学籍番号OCR: 矩形選択→OCR→名簿読込(任意)→確認GUI。

        チェックボックスがOFFの場合は何もしない。normal/記述のみモード
        どちらからも呼べるよう、対象フォルダの存在チェックも含めて自己完結させる。

        Returns:
            (aborted, student_id_result, trimmer) のタプル。
            aborted=True の場合、呼び出し元は処理全体を中断する。
        """
        if not self.student_id_ocr_enabled.get():
            return False, None, None

        boxed_folder = Path(image_folder) / RESULTS_FOLDER / BOXED_FOLDER
        if not boxed_folder.exists():
            messagebox.showerror(
                "エラー",
                f"補正済み画像フォルダが存在しません:\n{boxed_folder}\n\n"
                "Step 1（OMR認識）を先に実行してください。"
            )
            return True, None, None

        try:
            from student_id_ocr import StudentIdOcrTrimmer
            from id_area_config import ID_AREA_CONFIG_FILE
            config_path = Path(image_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER / ID_AREA_CONFIG_FILE
            ocr_trimmer = StudentIdOcrTrimmer()
            ocr_results = ocr_trimmer.run(
                str(boxed_folder), parent=self.root,
                original_image_folder=image_folder,
                config_path=str(config_path),
                default_digit_count=int(self.skip_questions.get() or 8),
            )
            if ocr_results is None:
                if not messagebox.askyesno(
                    "確認",
                    "学籍番号OCRがキャンセルされました。\n"
                    "OCRなしでサマリー生成を続行しますか？"
                ):
                    return True, None, None
                return False, None, None

            self.log_message(f"✓ 学籍番号OCR完了: {len(ocr_results)}枚")

            roster = None
            roster_path = filedialog.askopenfilename(
                title="名簿Excelを選択（任意・キャンセルでスキップ）",
                filetypes=[("Excelファイル", "*.xlsx *.xls"), ("すべてのファイル", "*.*")],
            )
            if roster_path:
                try:
                    from roster_loader import load_roster
                    roster = load_roster(roster_path)
                    self.log_message(f"✓ 名簿読込: {len(roster)}件")
                except Exception as e:
                    self.log_message(f"名簿読込エラー: {e}")
                    messagebox.showwarning(
                        "名簿読込エラー",
                        f"名簿の読込に失敗しました:\n{e}\n\n名簿照合なしで続行します。"
                    )
                    roster = None

            from student_id_review_gui import StudentIdReviewGUI
            review = StudentIdReviewGUI(self.root, ocr_results, roster)
            student_id_result = review.run()
            self.log_message(f"✓ 学籍番号OCR確認完了: {len(student_id_result)}枚")
            return False, student_id_result, ocr_trimmer

        except Exception as e:
            self.log_message(f"学籍番号OCRエラー: {e}")
            if not messagebox.askyesno(
                "エラー",
                f"学籍番号OCR中にエラーが発生しました:\n{e}\n\n"
                "OCRなしでサマリー生成を続行しますか？"
            ):
                return True, None, None
            return False, None, None

    # ---------------------------------------------------------
    # 記述のみモード: サマリー生成
    # ---------------------------------------------------------

    def _run_summary_generation_descriptive_only(self):
        """記述のみモードのサマリー生成エントリポイント"""
        results_data = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        desc_config_path = results_data / "descriptive_config.json"
        desc_scores_path = results_data / "descriptive_scores.json"

        if not desc_config_path.exists() or not desc_scores_path.exists():
            missing = []
            if not desc_config_path.exists():
                missing.append("・記述問題設定（descriptive_config.json）")
            if not desc_scores_path.exists():
                missing.append("・記述採点結果（descriptive_scores.json）")
            messagebox.showerror(
                "エラー",
                "以下のデータが見つかりません:\n\n"
                + "\n".join(missing) + "\n\n"
                "先に「⚙ 記述問題設定」と「✏ 記述採点」を実行してください。"
            )
            return

        # 採点完了チェック
        is_complete, unscored, total_img, detail = self._check_descriptive_completeness()
        if not is_complete and total_img > 0:
            detail_text = "\n".join(detail) if detail else ""
            if not messagebox.askyesno(
                "記述採点が未完了です",
                f"記述採点が完了していない生徒が {unscored}名 います。\n\n"
                f"{detail_text}\n\n"
                f"未採点の問題は 0点 として集計されます。\n"
                f"このまま続行しますか？",
            ):
                return

        if not messagebox.askyesno(
            "確認",
            "集計レポートを生成しますか？\n\n"
            "学生別サマリー、試験統計などが\n"
            "結果フォルダに出力されます。"
        ):
            return

        # 氏名欄トリミング
        name_images = None
        self._name_trimmer = None
        if self.name_trim_enabled.get():
            boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
            if boxed_folder.exists():
                try:
                    from name_trimmer import NameTrimmer
                    trimmer = NameTrimmer()
                    name_images = trimmer.run(str(boxed_folder), parent=self.root)
                    if name_images is None:
                        if not messagebox.askyesno(
                            "確認",
                            "氏名欄トリミングがキャンセルされました。\n"
                            "氏名欄画像なしでサマリー生成を続行しますか？"
                        ):
                            return
                    else:
                        self._name_trimmer = trimmer
                        self.log_message(f"✓ 氏名欄トリミング完了: {len(name_images)}枚")
                except Exception as e:
                    self.log_message(f"氏名欄トリミングエラー: {e}")
                    if not messagebox.askyesno(
                        "エラー",
                        f"氏名欄トリミング中にエラーが発生しました:\n{e}\n\n"
                        "氏名欄画像なしでサマリー生成を続行しますか？"
                    ):
                        return
                    name_images = None

        # 学籍番号OCR（チェックボックスで制御・実験的機能）
        aborted, student_id_result, id_ocr_trimmer = self._run_student_id_ocr_flow(
            self.image_folder_path.get()
        )
        if aborted:
            return
        self._student_id_ocr_trimmer = id_ocr_trimmer

        self._set_processing_state(True)
        # メインスレッドでStringVar値をキャプチャ（スレッドセーフ）
        params = {
            'image_folder': self.image_folder_path.get(),
        }
        thread = threading.Thread(
            target=self._run_summary_descriptive_only_thread,
            args=(params, name_images, student_id_result),
            daemon=True,
        )
        thread.start()

    def _run_summary_descriptive_only_thread(self, params, name_images=None, student_id_result=None):
        """記述のみモード: サマリー生成スレッド"""
        try:
            self.log_message("")
            self.log_message("=" * 60)
            self.log_message("サマリー生成を開始します（記述のみモード）...")
            self.log_message("=" * 60)

            from descriptive_scorer import load_descriptive_config, load_descriptive_scores

            results_folder = Path(params['image_folder']) / RESULTS_FOLDER
            results_data = results_folder / RESULTS_DATA_FOLDER
            final_report = results_folder / FINAL_REPORT_FOLDER
            final_report.mkdir(exist_ok=True)

            desc_config = load_descriptive_config(str(results_data / "descriptive_config.json"))
            scores_data = load_descriptive_scores(str(results_data / "descriptive_scores.json"))
            desc_scores = scores_data.get("scores", {}) if scores_data else {}

            # ロガー出力をGUIログに転送するハンドラを一時的に追加
            gui_handler, suppressed = self._attach_gui_log_handler()
            try:
                result = process_descriptive_only_summary(
                    image_folder=params['image_folder'],
                    descriptive_config=desc_config,
                    descriptive_scores=desc_scores,
                    name_images=name_images,
                    student_id_result=student_id_result,
                    output_base_folder=None,
                )
            finally:
                self._detach_gui_log_handler(gui_handler, suppressed)

            if result and result.get("success"):
                self.last_results_folder = str(final_report)
                self.root.after(0, lambda: self.open_results_btn.config(state=tk.NORMAL))

                stats = result["stats"]
                summary = (
                    f"サマリー生成が正常に完了しました！\n\n"
                    f"【試験統計】（記述のみ）\n"
                    f"・受験者数: {stats['受験者数']}名\n"
                    f"・満点: {stats['満点']}点\n"
                    f"・平均点: {stats['平均点']:.2f}点\n"
                    f"・標準偏差: {stats['標準偏差']:.2f}\n"
                    f"・最高点: {stats['最高点']}点\n"
                    f"・最低点: {stats['最低点']}点\n\n"
                    f"出力フォルダ: {final_report}\n\n"
                    f"生成されたファイル:\n"
                    f"・{STUDENT_SUMMARY_FILE} (学生別得点)\n"
                    f"・{EXAM_SUMMARY_FILE} (試験統計)"
                )
                if result.get('ctt_excel_path'):
                    summary += f"\n・{CTT_ANALYSIS_EXCEL_FILE} (古典テスト理論分析Excel)"
                if result.get('ctt_pdf_path'):
                    summary += f"\n・{CTT_ANALYSIS_PDF_FILE} (古典テスト理論分析PDF)"
                if result.get('r_export_dir'):
                    summary += f"\n・{R_EXPORT_FOLDER}/ (R連携分析キット)"
                self.root.after(0, lambda: messagebox.showinfo("完了", summary))
            else:
                err = result.get("error", "不明なエラー") if result else "不明なエラー"
                self.root.after(0, lambda: messagebox.showerror("エラー", f"サマリー生成に失敗しました:\n{err}"))
        except Exception as e:
            self.log_message(f"サマリー生成エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror("エラー", f"サマリー生成エラー:\n{e}"))
        finally:
            if hasattr(self, '_name_trimmer') and self._name_trimmer:
                try:
                    self._name_trimmer.cleanup()
                except Exception:
                    pass
                self._name_trimmer = None
            if hasattr(self, '_student_id_ocr_trimmer') and self._student_id_ocr_trimmer:
                try:
                    self._student_id_ocr_trimmer.cleanup()
                except Exception:
                    pass
                self._student_id_ocr_trimmer = None
            self.root.after(0, self._set_processing_state, False)

    def _run_summary_generation_thread(self, params, name_images=None, student_id_result=None):
        """サマリー生成処理の実際の実行（別スレッド）"""
        try:
            self.log_message("")
            self.log_message("=" * 60)
            self.log_message("サマリー生成を開始します...")
            self.log_message("=" * 60)
            self.log_message(f"画像フォルダ: {params['image_folder']}")
            self.log_message(f"座標ファイル: {params['coord_excel']}")
            self.log_message(f"正答データ: {params['template_path']}")
            self.log_message(f"OMR読取結果: {params['mark2_result_path']}")
            self.log_message(f"スキップ問題数: {params['skip_questions']}")
            if name_images:
                self.log_message(f"氏名欄画像: {len(name_images)}枚")

            # 記述問題データの読み込み
            # 記述が有効でも、ファイルが見つからない場合は
            # マーク採点のみでサマリーを生成する（フォールバック動作）。
            desc_config = None
            desc_scores = None
            if params['descriptive_enabled']:
                try:
                    from descriptive_scorer import load_descriptive_config, load_descriptive_scores
                    results_data_folder = Path(params['image_folder']) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
                    config_path = results_data_folder / "descriptive_config.json"
                    scores_path = results_data_folder / "descriptive_scores.json"
                    if config_path.exists() and scores_path.exists():
                        desc_config = load_descriptive_config(str(config_path))
                        scores_data = load_descriptive_scores(str(scores_path))
                        if scores_data:
                            desc_scores = scores_data.get("scores", {})
                        if desc_config and desc_scores:
                            self.log_message(f"記述問題: {len(desc_config.get('questions', []))}問")
                except Exception as e:
                    self.log_message(f"記述問題データ読み込み警告: {e}")

            self.log_message("")

            # ロガー出力をGUIログに転送するハンドラを一時的に追加
            gui_handler, suppressed = self._attach_gui_log_handler()
            try:
                result = process_summary_generation(
                    image_folder=params['image_folder'],
                    coord_excel_path=params['coord_excel'],
                    template_path=params['template_path'],
                    mark2_result_path=params['mark2_result_path'],
                    skip_questions=params['skip_questions'],
                    output_base_folder=None,
                    name_images=name_images,
                    student_id_result=student_id_result,
                    descriptive_config=desc_config,
                    descriptive_scores=desc_scores,
                    include_descriptive_in_analysis=(
                        params['descriptive_enabled']
                        and params['include_descriptive_in_analysis']
                    ),
                    progress_callback=self._update_progress,
                    cancel_event=self._cancel_event,
                    mark_format=self.mark_format,
                )
            finally:
                self._detach_gui_log_handler(gui_handler, suppressed)

            # 中断された場合
            if self._cancel_event.is_set():
                self.log_message("")
                self.log_message("=" * 60)
                self.log_message("⏹ サマリー生成が中断されました")
                self.log_message("=" * 60)
                self.root.after(0, lambda: messagebox.showwarning("中断", "サマリー生成が中断されました。"))
                return

            if result and result['success']:
                self.log_message("")
                self.log_message("=" * 60)
                self.log_message("サマリー生成が正常に完了しました！")
                self.log_message("=" * 60)
                
                results_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER
                self.last_results_folder = str(results_folder / FINAL_REPORT_FOLDER)
                self.root.after(0, lambda: self.open_results_btn.config(state=tk.NORMAL))
                
                stats = result['stats']
                summary = f"""サマリー生成が正常に完了しました！

【試験統計】
・受験者数: {stats['受験者数']}名
・満点: {stats['満点']}点
・平均点: {stats['平均点']:.2f}点
・標準偏差: {stats['標準偏差']:.2f}
・最高点: {stats['最高点']}点
・最低点: {stats['最低点']}点

出力フォルダ: {results_folder}

生成されたファイル:
・{STUDENT_SUMMARY_FILE} (学生別得点)
・{EXAM_SUMMARY_FILE} (試験統計)"""
                
                if result.get('ctt_excel_path'):
                    summary += f"\n・{CTT_ANALYSIS_EXCEL_FILE} (古典テスト理論分析Excel)"
                if result.get('ctt_pdf_path'):
                    summary += f"\n・{CTT_ANALYSIS_PDF_FILE} (古典テスト理論分析PDF)"
                if result.get('scored_pdf_path'):
                    summary += f"\n・{SCORED_PDF_FILE} (採点済み統合PDF)"
                if result.get('r_export_dir'):
                    summary += f"\n・{R_EXPORT_FOLDER}/ (R連携分析キット)"
                
                self.root.after(0, lambda: messagebox.showinfo("完了", summary))
            else:
                error_msg = result.get('error', '不明なエラー') if result else '不明なエラー'
                self.log_message("")
                self.log_message("=" * 60)
                self.log_message(f"サマリー生成に失敗しました: {error_msg}")
                self.log_message("=" * 60)
                self.root.after(0, lambda: messagebox.showerror("エラー", f"サマリー生成に失敗しました:\n{error_msg}"))
            
        except Exception as e:
            self.log_message("")
            self.log_message("=" * 60)
            self.log_message(f"エラーが発生しました: {e}")
            self.log_message("=" * 60)
            
            import traceback
            self.log_message("\n詳細なエラー情報:")
            self.log_message(traceback.format_exc())
            
            self.root.after(0, lambda: messagebox.showerror("エラー", f"処理中にエラーが発生しました:\n{e}"))
        
        finally:
            # NameTrimmer の一時ファイルを削除
            if hasattr(self, '_name_trimmer') and self._name_trimmer:
                try:
                    self._name_trimmer.cleanup()
                except Exception:
                    pass
                self._name_trimmer = None
            if hasattr(self, '_student_id_ocr_trimmer') and self._student_id_ocr_trimmer:
                try:
                    self._student_id_ocr_trimmer.cleanup()
                except Exception:
                    pass
                self._student_id_ocr_trimmer = None
            self.root.after(0, self._set_processing_state, False)


# 後方互換エイリアス
Mark2GUI = SaitenSamuraiGUI
