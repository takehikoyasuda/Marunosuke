#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
マル之助 (Marunosuke) メインGUIモジュール

MarunosukeGUI クラスを提供する。記述式答案の準備・採点・集計を行う
統合GUIウィンドウを構築し、各処理パイプラインを制御する。
旧 SaitenSamuraiGUI / Mark2GUI 名は後方互換エイリアスとして提供する。
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

# 同じ Tcl/Tk セッションではヘッダー用縮小画像を共有する。画面を作り直すたびに
# PhotoImage を増やすと、macOS の Tk で画像資源が蓄積して不安定になるため。
_HEADER_ICON_CACHE = {}

# サードパーティライブラリ
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageTk


def _askyesno_japanese(title, message, **kwargs):
    """OSロケールに依存せず、確認ボタンを「はい／いいえ」で表示する。"""
    parent = kwargs.get("parent") or tk._default_root
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    result = {"value": False}
    tk.Label(dialog, text=message, justify=tk.LEFT, wraplength=460,
             padx=20, pady=16).pack(fill=tk.BOTH, expand=True)
    buttons = tk.Frame(dialog)
    buttons.pack(pady=(0, 14))
    tk.Button(buttons, text="はい", width=10,
              command=lambda: (result.update(value=True), dialog.destroy())).pack(side=tk.LEFT, padx=5)
    tk.Button(buttons, text="いいえ", width=10,
              command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.grab_set()
    dialog.wait_window()
    return result["value"]


def _get_header_icon(root, size=48):
    """高解像度ロゴから、滑らかで余白の少ないヘッダー画像を作る。"""
    cache_key = (root.tk, size)
    cached = _HEADER_ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached

    logo_path = Path(resource_path("resources/marunosuke-logo.png"))
    if not logo_path.exists():
        return None

    with Image.open(logo_path) as source:
        image = source.convert("RGB")
        white = Image.new("RGB", image.size, "white")
        difference = ImageChops.difference(image, white).convert("L")
        mask = difference.point(lambda value: 255 if value > 18 else 0)
        bbox = mask.getbbox()
        if bbox:
            left, top, right, bottom = bbox
            padding = max(8, int(max(right - left, bottom - top) * 0.04))
            image = image.crop((
                max(0, left - padding), max(0, top - padding),
                min(image.width, right + padding), min(image.height, bottom + padding),
            ))
        image.thumbnail((size, size), Image.Resampling.LANCZOS)

        tile = Image.new("RGB", (size, size), "white")
        tile.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
        photo = ImageTk.PhotoImage(tile, master=root)

    _HEADER_ICON_CACHE[cache_key] = photo
    return photo


# アプリ内の確認ダイアログは日本語ボタンを統一して使う。
messagebox.askyesno = _askyesno_japanese


class ColoredButton(tk.Frame):
    """MacのAquaテーマに左右されない、Frame/Labelベースのボタン。"""

    def __init__(self, parent, text="", command=None, bg="#1976D2", fg="white",
                 activebackground=None, disabledbackground="#ECEFF1", disabledforeground="#90A4AE",
                 font=None, state=tk.NORMAL, padx=8, pady=5, wraplength=0, **kwargs):
        kwargs.setdefault("cursor", "hand2")
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self._text = text
        self._command = command
        self._normal_bg = bg
        self._normal_fg = fg
        self._active_bg = activebackground or bg
        self._disabled_bg = disabledbackground
        self._disabled_fg = disabledforeground
        self._state = state
        self._hovered = False
        # wraplength(px)を指定すると、環境ごとのフォント実測幅の差（同じフォント
        # サイズでも文字の描画幅がディスプレイ・システム設定によって変わることが
        # ある）で固定幅ボタンから文字がはみ出す代わりに、自動で折り返す。
        # tk.Labelは既定でボタン枠を超えて文字を描画してしまう（横方向に
        # クリップされない）ため、幅が固定されたボタンでは必須の対策。
        self._label = tk.Label(self, text=text, bg=bg, fg=fg, font=font,
                               padx=padx, pady=pady, cursor="hand2",
                               wraplength=wraplength, justify=tk.CENTER)
        self._label.pack(fill=tk.BOTH, expand=True)
        # Label が全面を覆うため、ポインターイベントは Label だけで受け取る。
        # Frame と Label の両方に Enter/Leave を設定すると、境界をまたぐ際に
        # Leave/Enter が連続して発生し、macOS で再描画がちらつくことがある。
        self._label.bind("<Button-1>", self._on_click)
        self._label.bind("<Enter>", self._on_enter)
        self._label.bind("<Leave>", self._on_leave)
        self._apply_state()

    def _on_click(self, _event=None):
        if self._state != tk.DISABLED and self._command:
            self._command()

    def _on_enter(self, _event=None):
        # ホバー色が通常色と同じボタンでは何も再描画しない。
        # macOS の Tk は同じ背景色の再設定でも一瞬ちらつくことがある。
        if self._state != tk.DISABLED and self._active_bg != self._normal_bg:
            self._hovered = True
            self._label.config(bg=self._active_bg)
            # self.config(bg=...) は通常色 (_normal_bg) の変更として扱われる。
            # ホバー表示では基底クラスを直接更新し、通常色を保持する。
            tk.Frame.config(self, bg=self._active_bg)

    def _on_leave(self, _event=None):
        if self._hovered:
            self._hovered = False
            self._apply_state()

    def _apply_state(self):
        enabled = self._state != tk.DISABLED
        bg = self._normal_bg if enabled else self._disabled_bg
        fg = self._normal_fg if enabled else self._disabled_fg
        cursor = "hand2" if enabled else "arrow"
        # config() 経由にすると _apply_state() を再度呼んで再帰するため、
        # Tk の基底クラスへ直接設定する。
        tk.Frame.config(self, bg=bg, cursor=cursor)
        self._label.config(bg=bg, fg=fg, cursor=cursor)

    def config(self, cnf=None, **kwargs):
        for key in ("text", "command", "state", "activebackground", "bg", "fg"):
            if key in kwargs:
                value = kwargs.pop(key)
                if key == "text":
                    self._text = value
                    if hasattr(self, "_label"):
                        self._label.config(text=value)
                elif key == "command":
                    self._command = value
                elif key == "state":
                    self._state = value
                elif key == "activebackground":
                    self._active_bg = value
                elif key == "bg":
                    self._normal_bg = value
                elif key == "fg":
                    self._normal_fg = value
        result = super().config(cnf, **kwargs)
        if hasattr(self, "_label"):
            self._apply_state()
        return result

    configure = config

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "command":
            return self._command
        if key == "state":
            return self._state
        return super().cget(key)

    # tkinter.Misc.__getitem__ は基底クラスの cget への固定エイリアスなので、
    # サブクラスで cget を上書きした場合は明示的に張り直す必要がある。
    __getitem__ = cget

    def invoke(self):
        if self._state != tk.DISABLED and self._command:
            return self._command()


# 共通定数・ユーティリティ（constants.pyから）
from constants import (
    safe_print, extract_pdf_to_images, combine_images_to_pdf,
    HAS_PYMUPDF,
    APP_TITLE,
    RESULTS_FOLDER, BOXED_FOLDER, CLEAN_FOLDER, RESULTS_DATA_FOLDER,
    SCORED_FOLDER, FINAL_REPORT_FOLDER,
    ANSWER_KEY_FILE,
    STUDENT_SUMMARY_FILE, EXAM_SUMMARY_FILE,
    READING_RESULTS_FOLDER_NAME, SESSION_STATE_FILE,
    get_rendering_settings, DEFAULT_RENDERING_SETTINGS,
    resource_path,
    MODE_DESCRIPTIVE_ONLY,
    atomic_json_save, load_json_safe,
    get_app_temp_dir,
    open_in_file_manager, get_ui_font_family, get_ui_font_size,
    fit_window_to_content,
    number_to_circled,
)

# 日本語UIフォント（Windows: Yu Gothic UI, Mac: Hiragino Sans）
UI_FONT = get_ui_font_family()

# 画像アライメント（採点モード非依存。image_alignment.pyから）
from image_alignment import (
    detect_corner_markers, compute_output_scale,
    apply_perspective_transform, imread_unicode,
)

# サマリー生成（summary_generator.pyから）
from summary_generator import process_descriptive_only_summary

# GUIサブウィンドウ（gui_components.pyから）
from gui_components import RenderingSettingsGUI

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
# MarunosukeGUIクラス（メイン統合GUI）
# ========================================

class MarunosukeGUI:
    """マル之助のメイン統合GUIクラス。"""
    def __init__(self, root, restore_session_path=None):
        self.root = root
        self._restore_session_path = restore_session_path  # 起動時復元用

        self.root.title(APP_TITLE)
        self.root.geometry("900x600")
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(250, lambda: self.root.attributes("-topmost", False))
        self.root.after(300, self.root.focus_force)

        # ウィンドウアイコン設定（PhotoImage は参照を保持しないと破棄される）
        self._app_icon = None
        try:
            icon_png_path = resource_path("resources/marunosuke-icon.png")
            if Path(icon_png_path).exists():
                self._app_icon = tk.PhotoImage(file=icon_png_path)
                self.root.iconphoto(True, self._app_icon)

        except Exception:
            pass  # アイコンが見つからない場合はデフォルトのまま

        self.image_folder_path = tk.StringVar()
        self.total_pages = tk.StringVar(value="")
        self._pages_confirmed = False
        self.skip_questions = tk.StringVar(value="4")

        self.last_boxed_folder = None
        self.last_scored_folder = None
        self.last_results_folder = None
        self.last_combined_summary_folder = None
        self._name_trimmer = None  # 氏名欄トリミング用（cleanup管理）
        self._student_id_ocr_trimmer = None  # 学籍番号OCR用（cleanup管理）

        # 記述式のみモード固定のため常にON
        self.descriptive_enabled = tk.BooleanVar(value=True)
        # 採点結果描画の詳細設定（セッション保存/復元対象）
        self.rendering_settings = get_rendering_settings()

        self.create_widgets()
        self._fit_root_window()

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

    # 横方向はスクロールを付けていないため、採点ワークフローの各行に並ぶ
    # ボタン群が収まる幅（実測で最大約860px）を下回らないようにする。
    # 縦方向はcreate_widgets()で全体を縦スクロール可能にしたため、横ほど
    # 厳しくする必要はない。
    _MIN_ROOT_WIDTH = 880
    _MIN_ROOT_HEIGHT = 480

    def _fit_root_window(self):
        """初期ウィンドウサイズと最小サイズを、実コンテンツに基づいて設定する。

        create_widgets()で本文全体を縦スクロール可能なCanvasの中に入れたため、
        root自体のwinfo_reqwidth/reqheightはCanvasの既定値（コンテンツと無関係な
        小さい値）になってしまい使えない。実コンテンツを持つ self._content_host
        （main_container）を計測し、それを初期サイズの目安にする。
        最小サイズ(minsize)は初期サイズよりも小さい固定値にすることで、
        ウィンドウを縮めても縦はスクロールで、横はボタンが収まる幅を保ったまま
        操作できるようにする。
        """
        self.root.update_idletasks()
        content_w = self._content_host.winfo_reqwidth()
        content_h = self._content_host.winfo_reqheight()

        screen_w = max(1, self.root.winfo_screenwidth())
        screen_h = max(1, self.root.winfo_screenheight())
        margin_x = min(40, max(12, screen_w // 40))
        margin_y = min(60, max(12, screen_h // 30))
        max_w = max(1, screen_w - margin_x * 2)
        max_h = max(1, screen_h - margin_y * 2)

        # スクロールバー分の余白を少し確保する。
        default_w = min(max(self._MIN_ROOT_WIDTH, content_w + 20), max_w)
        default_h = min(max(self._MIN_ROOT_HEIGHT, content_h), max_h)

        self.root.geometry(f"{default_w}x{default_h}")
        self.root.minsize(min(self._MIN_ROOT_WIDTH, max_w), min(self._MIN_ROOT_HEIGHT, max_h))

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
        BTN_AMBER = "#FFE082"     # サマリー (Amber 200)
        BTN_GRAY = "#EEEEEE"      # 参照・開くボタン

        FONT_NORMAL = (UI_FONT, get_ui_font_size(9))
        FONT_BOLD = (UI_FONT, get_ui_font_size(9), "bold")
        FONT_TITLE = (UI_FONT, get_ui_font_size(12), "bold")

        # ルートウィンドウの背景設定
        self.root.configure(bg=BG_COLOR)

        # ウィンドウを縦に縮めても内容が完全に見えなくなることがないよう、
        # 全体を縦スクロール可能なCanvasの中に構築する（横方向は最小幅
        # (minsize)で確保するため、横スクロールは付けない）。
        outer_canvas = tk.Canvas(self.root, bg=BG_COLOR, highlightthickness=0)
        v_scrollbar = tk.Scrollbar(self.root, orient=tk.VERTICAL, command=outer_canvas.yview)
        outer_canvas.configure(yscrollcommand=v_scrollbar.set)
        outer_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._root_scrollbar = v_scrollbar

        scroll_host = tk.Frame(outer_canvas, bg=BG_COLOR)
        canvas_window = outer_canvas.create_window((0, 0), window=scroll_host, anchor="nw")

        def _on_scroll_host_configure(_event=None):
            outer_canvas.configure(scrollregion=outer_canvas.bbox("all"))
        scroll_host.bind("<Configure>", _on_scroll_host_configure)

        def _on_canvas_configure(event):
            # 内側フレームの幅をcanvas幅に追従させる（横方向は追従、縦方向のみ
            # スクロールで対応する）。
            outer_canvas.itemconfig(canvas_window, width=event.width)
        outer_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            outer_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        # bind_all()はアプリ全体（"all"バインドタグ）に対する登録であり、ウィジェット
        # のdestroy()では自動的に解除されない。マウスポインタがこのCanvas上に
        # ある間だけ有効化・退出時に解除することで、他のウィンドウのスクロールを
        # 妨げず、bind_allの登録が使い捨てのまま蓄積することも防ぐ。
        def _bind_mousewheel(_event=None):
            outer_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(_event=None):
            outer_canvas.unbind_all("<MouseWheel>")

        outer_canvas.bind("<Enter>", _bind_mousewheel)
        outer_canvas.bind("<Leave>", _unbind_mousewheel)

        # メインコンテナ
        main_container = tk.Frame(scroll_host, padx=10, pady=10, bg=BG_COLOR)
        main_container.pack(fill=tk.BOTH, expand=True)
        # Canvasでラップした後はroot自体のwinfo_reqwidth/reqheightがCanvasの
        # 既定値になってしまい使えないため、実際のコンテンツサイズの計測用に
        # 保持しておく（__init__側の初期ウィンドウサイズ計算で使う）。
        self._content_host = main_container

        # =============================================================================
        # 下部: 処理状況（詳細ログ本文は別ウィンドウで表示）
        # =============================================================================
        log_frame = tk.LabelFrame(main_container, text="処理状況", padx=5, pady=2, font=FONT_BOLD, bg=SECTION_BG, fg=HEADER_TEXT, relief=tk.FLAT, bd=1, height=42)
        log_frame.pack(side=tk.BOTTOM, fill=tk.X, expand=False, pady=(5, 0))
        log_frame.pack_propagate(False)
        # 詳細ログは別ウィンドウから取得するため、トップ画面には表示しない。
        log_frame.pack_forget()

        # 高さ10行固定
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD, font=("Consolas", 9), bg="#FAFAFA", relief=tk.FLAT, bd=1, height=4)
        # ログ本文は常設しない。log_message() の保存先として保持する。

        # 処理開始・終了時にレイアウト全体が上下へ動かないよう、進捗領域は
        # 最初から一定の高さを確保する。処理中は中身だけを表示する。
        self._processing_frame = tk.Frame(log_frame, bg=SECTION_BG, height=42)
        self._processing_frame.pack(fill=tk.X, pady=(4, 0))
        self._processing_frame.pack_propagate(False)
        self._progress_bar = ttk.Progressbar(
            self._processing_frame, mode="determinate", maximum=100, length=200,
        )
        self._cancel_frame = tk.Frame(self._processing_frame, bg=SECTION_BG)
        self._btn_cancel = tk.Button(
            self._cancel_frame, text="⏹ 中断", font=FONT_BOLD,
            bg="#E74C3C", fg="black", activebackground="#C0392B",
            command=self._request_cancel, width=10,
        )
        self._btn_cancel.pack(side=tk.RIGHT, padx=4, pady=2)
        self._cancel_event = threading.Event()
        # 初期状態では中身だけを非表示にし、確保済み領域の高さは変えない。
        self._processing = False

        # =============================================================================
        # 上部: コントロールエリア
        # =============================================================================
        controls_frame = tk.Frame(main_container, bg=BG_COLOR)
        controls_frame.pack(side=tk.TOP, fill=tk.X)

        # タイトル行（タイトル＋復元ボタン）
        title_row = tk.Frame(controls_frame, bg=BG_COLOR)
        title_row.pack(fill=tk.X, pady=(0, 5))

        # 青は操作色、赤はブランド色として使い分ける。アイコンはタイトル横に
        # 常時表示し、アプリの視覚的な識別点にする。
        self._header_icon = None
        try:
            if self._app_icon is not None:
                self._header_icon = _get_header_icon(self.root, size=48)
            if self._header_icon is not None:
                tk.Label(
                    title_row, image=self._header_icon, bg=BG_COLOR, bd=0,
                    highlightthickness=0,
                ).pack(side=tk.LEFT, padx=(0, 9), pady=1)
        except Exception:
            self._header_icon = None

        tk.Label(
            title_row, text=APP_TITLE, font=FONT_TITLE,
            fg="#C62828", bg=BG_COLOR,
        ).pack(side=tk.LEFT)
        tk.Button(
            title_row, text="📂 前回の状態を復元",
            command=self._restore_session_interactive,
            font=(UI_FONT, get_ui_font_size(8)), bg="#E3F2FD", relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(10, 0))

        # 進捗ガイド（横一列にして、画面の主役を作業ボタンに戻す）
        self._progress_guide_frame = tk.LabelFrame(
            controls_frame, text="進捗", padx=10, pady=5,
            font=FONT_BOLD, bg=SECTION_BG, fg=HEADER_TEXT, relief=tk.FLAT,
        )
        self._progress_guide_frame.pack(fill=tk.X, pady=(0, 8))
        self._progress_guide_frame.pack_forget()
        self._progress_guide_labels = {}
        progress_items = (
            ("source", "準備"), ("setup", "問題設定"),
            ("scoring", "採点"), ("review", "採点確認"), ("summary", "集計"),
        )
        progress_row = tk.Frame(self._progress_guide_frame, bg=SECTION_BG)
        progress_row.pack(fill=tk.X)
        for index, (key, title) in enumerate(progress_items):
            item = tk.Frame(progress_row, bg=SECTION_BG)
            item.pack(side=tk.LEFT, fill=tk.X, expand=True)
            marker = tk.Label(item, text="○", width=2, anchor=tk.E,
                              font=FONT_BOLD, bg=SECTION_BG, fg="#90A4AE")
            marker.pack(side=tk.LEFT)
            status = tk.Label(item, text=title, anchor=tk.W,
                              font=FONT_NORMAL, bg=SECTION_BG, fg="#78909C")
            status.pack(side=tk.LEFT, padx=(3, 0))
            self._progress_guide_labels[key] = (marker, status)
            if index < len(progress_items) - 1:
                tk.Label(progress_row, text="→", font=FONT_NORMAL,
                         bg=SECTION_BG, fg="#CFD8DC").pack(side=tk.LEFT, padx=2)

        next_row = tk.Frame(self._progress_guide_frame, bg="#FFF8E1")
        next_row.pack(fill=tk.X, pady=(5, 0))
        self._progress_next_label = tk.Label(
            next_row, text="次にすること：画像フォルダを選択してください",
            anchor=tk.W, font=FONT_BOLD, bg="#FFF8E1", fg="#795548", padx=7, pady=4,
        )
        self._progress_next_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._progress_next_button = ColoredButton(
            next_row, text="作業スペースを選択", command=self.select_folder,
            font=FONT_BOLD, bg="#FFCC80", relief=tk.FLAT, cursor="hand2", padx=8,
        )
        self._progress_next_button.pack(side=tk.RIGHT, padx=4, pady=3)

        # ---------------------------------------------------------
        # 1. データソース & 設定 (横並び)
        # ---------------------------------------------------------
        top_section = tk.Frame(controls_frame, bg=BG_COLOR)
        top_section.pack(fill=tk.X, pady=(0, 10))

        # 左側: ファイル入力
        input_group = tk.LabelFrame(
            top_section, text="案件設定", labelanchor="n", padx=10, pady=5,
            font=(UI_FONT, get_ui_font_size(13), "bold"), bg=SECTION_BG, fg=HEADER_TEXT,
            relief=tk.FLAT, bd=0,
        )
        input_group.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            input_group, text="作業スペースとページ数は、この案件で最初に1回だけ設定します。",
            bg=SECTION_BG, fg="#607D8B", font=(UI_FONT, get_ui_font_size(9)),
            justify=tk.CENTER,
        ).pack(fill=tk.X, pady=(0, 4))

        # 画像フォルダ
        row1 = tk.Frame(input_group, bg=SECTION_BG)
        row1.pack(fill=tk.X, pady=2)
        self._step_markers = {}
        self._step_markers[1] = tk.Label(row1, text="→", width=2, anchor=tk.CENTER, font=(UI_FONT, get_ui_font_size(22), "bold"), fg="#1565C0", bg=SECTION_BG)
        self._step_markers[1].pack(side=tk.LEFT)
        tk.Label(row1, text="1", width=2, anchor=tk.CENTER, font=(UI_FONT, get_ui_font_size(22), "bold"), fg="#1565C0", bg=SECTION_BG).pack(side=tk.LEFT, padx=(0, 8))
        self._btn_select_folder = ColoredButton(
            row1, text="作業スペース選択", command=self.select_folder,
            bg="#1976D2", fg="white",
            font=(UI_FONT, get_ui_font_size(11), "bold"),
            width=205, height=56, padx=16, pady=7,
        )
        self._btn_select_folder.pack_propagate(False)
        self._btn_select_folder.pack(side=tk.LEFT, padx=(0, 8))
        tk.Entry(
            row1, textvariable=self.image_folder_path,
            font=(UI_FONT, get_ui_font_size(8)),
            bg="#FFFFFF", readonlybackground="#FFFFFF", fg="#222222",
            relief=tk.SOLID, bd=1, highlightthickness=1,
            highlightbackground="#9E9E9E", highlightcolor="#1976D2",
            state="readonly",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3), ipady=2)

        page_row = tk.Frame(input_group, bg=SECTION_BG)
        page_row.pack(fill=tk.X, pady=(7, 2))
        self._step_markers[2] = tk.Label(page_row, text=" ", width=2, anchor=tk.CENTER, font=(UI_FONT, get_ui_font_size(22), "bold"), fg="#2E7D32", bg=SECTION_BG)
        self._step_markers[2].pack(side=tk.LEFT)
        tk.Label(page_row, text="2", width=2, anchor=tk.CENTER, font=(UI_FONT, get_ui_font_size(22), "bold"), fg="#1565C0", bg=SECTION_BG).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(page_row, text="答案のページ数", width=10, anchor=tk.W,
                 font=(UI_FONT, get_ui_font_size(11), "bold"), bg=SECTION_BG,
                 fg=HEADER_TEXT).pack(side=tk.LEFT)
        # tk.Spinbox はmacOS上で矢印を素早く連続クリックすると、二重入力扱いに
        # なり値が1つ飛ぶことがあるため使わない。数字入力欄と増減ボタンを分離し、
        # 単純な command 呼び出しだけで値を変える。
        self._page_entry = tk.Entry(
            page_row, textvariable=self.total_pages, width=5, justify=tk.CENTER,
            font=(UI_FONT, get_ui_font_size(11), "bold"),
        )
        self._page_entry.pack(side=tk.LEFT)
        page_stepper = tk.Frame(page_row, bg=SECTION_BG)
        page_stepper.pack(side=tk.LEFT, padx=(2, 8))
        tk.Button(
            page_stepper, text="▲", width=2, font=(UI_FONT, get_ui_font_size(6)),
            relief=tk.FLAT, bg="#ECEFF1", command=lambda: self._adjust_page_count(1),
        ).pack(side=tk.TOP)
        tk.Button(
            page_stepper, text="▼", width=2, font=(UI_FONT, get_ui_font_size(6)),
            relief=tk.FLAT, bg="#ECEFF1", command=lambda: self._adjust_page_count(-1),
        ).pack(side=tk.TOP)
        tk.Button(page_row, text="確定", command=self._confirm_page_count,
                  bg="#ECEFF1", fg="#37474F", relief=tk.FLAT,
                  font=(UI_FONT, get_ui_font_size(8), "bold"), padx=8, pady=3).pack(side=tk.LEFT)

        tk.Button(
            log_frame, text="処理ログを表示", command=self._show_log_window,
            font=(UI_FONT, get_ui_font_size(8)), bg="#ECEFF1", fg="#607D8B",
            relief=tk.FLAT, padx=6,
        ).pack(side=tk.RIGHT, padx=4, pady=2)

        # ---------------------------------------------------------
        # 2. アクションパイプライン（Step3〜5をひとつの枠にまとめ、
        #    どのページを対象にしているかを示すダッシュボードを先頭に置く）
        # ---------------------------------------------------------
        pipeline_frame = tk.LabelFrame(
            controls_frame, text="採点ワークフロー（各ページの作業）", labelanchor="n", padx=10, pady=8,
            font=(UI_FONT, get_ui_font_size(13), "bold"), bg=SECTION_BG, fg=HEADER_TEXT,
            relief=tk.FLAT, bd=0,
        )
        pipeline_frame.pack(fill=tk.X, pady=(10, 0))
        pipeline_frame.columnconfigure(0, weight=1)

        tk.Label(
            pipeline_frame,
            text=(
                "Step3〜5は1ページ分の作業です。ページ数分、繰り返します。\n"
                "次のページに進むときも、もう一度「答案ファイルを追加＆採点準備」から始めてください。"
            ),
            bg=SECTION_BG, fg="#607D8B", font=(UI_FONT, get_ui_font_size(9)),
            justify=tk.CENTER,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))

        # 複数ページ案件ダッシュボード（Step3〜5すべてが対象にする「今のページ」を
        # 切り替える場所なので、案件設定(Step1・2)側ではなくこの枠の先頭に置く）
        self._multi_page_dashboard = tk.Frame(pipeline_frame, bg="#E8EAF6", padx=8, pady=6)
        self._multi_page_dashboard.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        _mpd_row1 = tk.Frame(self._multi_page_dashboard, bg="#E8EAF6")
        _mpd_row1.pack(fill=tk.X)
        tk.Label(
            _mpd_row1, text="複数ページ答案",
            bg="#E8EAF6", fg="#283593", font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=(0, 8))
        self._btn_prev_exam_page = tk.Button(
            _mpd_row1, text="◀ 前ページ",
            command=lambda: self._navigate_exam_page(-1),
            bg="#C5CAE9", fg="#263238", relief=tk.FLAT, font=FONT_NORMAL,
            state=tk.DISABLED,
        )
        self._btn_prev_exam_page.pack(side=tk.LEFT, padx=2)
        self._btn_next_exam_page = tk.Button(
            _mpd_row1, text="次ページ ▶",
            command=lambda: self._navigate_exam_page(1),
            bg="#C5CAE9", fg="#263238", relief=tk.FLAT, font=FONT_NORMAL,
            state=tk.DISABLED,
        )
        self._btn_next_exam_page.pack(side=tk.LEFT, padx=2)
        self._multi_page_status_label = tk.Label(
            _mpd_row1,
            text="未設定 — PDFを選択して複数ページ答案の取込を開始",
            bg="#FFF3CD", fg="#5D4037", anchor=tk.W, justify=tk.LEFT,
            font=(UI_FONT, get_ui_font_size(8), 'bold'),
            # 状態によって文字数が伸びても、右側の「ページを管理」ボタンを
            # 押し出さないよう、一定幅で折り返す（はみ出す代わりに複数行になる）。
            wraplength=260,
        )
        self._multi_page_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self._btn_multi_page_merge = tk.Button(
            _mpd_row1, text="📚 ページを管理",
            command=self.run_multi_page_merge,
            bg="#C5CAE9", fg="#263238",
            activebackground="#9FA8DA", activeforeground="#263238",
            relief=tk.FLAT, font=FONT_BOLD,
        )
        self._btn_multi_page_merge.pack(side=tk.RIGHT)

        # 各ページの進捗を常時見えるコンパクトなチップ列として表示する
        # （それまでは「今見ているページ」の状態しか出ておらず、他ページが
        # どこまで進んでいるかはトップ画面から分からなかった）。
        self._page_progress_row = tk.Frame(self._multi_page_dashboard, bg="#E8EAF6")
        self._page_progress_row.pack(fill=tk.X, pady=(4, 0))

        # 共通スタイル
        def create_step_frame(parent, title, color_bar, number):
            f = tk.Frame(parent, padx=8, pady=5, bg=SECTION_BG,
                         relief=tk.FLAT, bd=0, highlightthickness=0)
            header = tk.Frame(f, bg=SECTION_BG)
            header.pack(fill=tk.X, pady=(0, 3))
            marker = tk.Label(header, text=" ", width=2, font=(UI_FONT, get_ui_font_size(22), "bold"), fg="#2E7D32", bg=SECTION_BG)
            marker.pack(side=tk.LEFT)
            f._step_marker = marker
            self._step_markers[number] = marker
            tk.Label(header, text=str(number), width=2, font=(UI_FONT, get_ui_font_size(22), "bold"), fg="#1565C0", bg=SECTION_BG).pack(side=tk.LEFT, padx=(0, 10))
            f._main_header = header
            # 色付きバー（アクセント）
            # 工程間は水平線を使わず、余白だけで区切る。
            return f

        # Step 1: 答案ファイル追加＆採点準備
        step1 = create_step_frame(pipeline_frame, "答案ファイル追加＆採点準備", BTN_GREEN, 3)
        step1.grid(row=2, column=0, sticky="ew", pady=0)
        self._step1_frame = step1  # toggle用に保持

        # 画像準備 + 結果フォルダ
        step1_run_row = step1._main_header

        self._btn_run_box = ColoredButton(step1_run_row, text="答案ファイルを追加\n＆ 採点準備",
                                      command=self._start_answer_prep,
                                      bg="#1976D2", fg="white",
                                      font=(UI_FONT, get_ui_font_size(11), "bold"), width=250, height=95, padx=20, pady=8,
                                      wraplength=225,
                                      relief=tk.FLAT, cursor="hand2")
        self._btn_run_box.pack_propagate(False)
        self._btn_run_box.pack(side=tk.LEFT, padx=(0, 3))
        # 初期状態: フォルダ未選択なので無効化
        self._btn_run_box.config(state=tk.DISABLED)
        # 📁はメインボタン（答案ファイルを追加＆採点準備）の出力を開くもの
        # なので、間を空けずメインボタンにくっつけて「同じグループ」だと
        # 分かるようにする。
        self.open_boxed_btn = tk.Button(step1_run_row, text="📁", command=self.open_boxed_folder, bg=BTN_GRAY, relief=tk.FLAT, state=tk.DISABLED, width=3, font=(UI_FONT, get_ui_font_size(10)))
        self.open_boxed_btn.pack(side=tk.LEFT, fill=tk.Y)

        # 初期設定（やり直し用の補助ボタン。頻度が低いので小さく、
        # 上のグループとは間隔を空けて別グループだと分かるようにする）
        self.desc_setup_btn = ColoredButton(
            step1_run_row, text="採点準備をやり直す",
            command=self._run_step1_setup_wizard,
            bg="#ECEFF1", fg="#455A64", font=(UI_FONT, get_ui_font_size(8), "bold"),
            width=165, height=42, padx=8, pady=4, wraplength=145,
            relief=tk.FLAT, cursor="hand2",
        )
        self.desc_setup_btn.pack_propagate(False)
        self.desc_setup_btn.pack(side=tk.LEFT, padx=(16, 0))

        # Step 2: 採点実行
        step2 = create_step_frame(pipeline_frame, "採点実行", BTN_BLUE, 4)
        step2.grid(row=3, column=0, sticky="ew", pady=0)
        self._step2_frame = step2  # toggle用に保持

        BTN_STYLE = dict(font=FONT_BOLD, height=2, relief=tk.FLAT, cursor="hand2")

        # 記述採点ボタン
        self.desc_scoring_btn = ColoredButton(
            step2._main_header, text="採点実行",
            command=self.run_descriptive_scoring,
            bg="#1976D2", fg="white", font=(UI_FONT, get_ui_font_size(11), "bold"), width=205, height=56, padx=16, pady=7,
        )
        self.desc_scoring_btn.pack_propagate(False)
        self.desc_scoring_btn.pack(side=tk.LEFT, pady=3)

        # 「合計点位置設定」「描画の詳細設定」はどちらも補助的な調整項目で、
        # 頻度も低いため個別の行にせず「⚙」メニューへまとめる。
        self._btn_step2_more = tk.Button(
            step2._main_header, text="⚙", width=2, relief=tk.FLAT, bg=SECTION_BG,
            fg="#78909C", font=(UI_FONT, get_ui_font_size(14), "bold"),
            command=self._show_step2_more_menu,
        )
        self._btn_step2_more.pack(side=tk.RIGHT, anchor="ne", padx=(4, 0))
        _ToolTip(self._btn_step2_more, "合計点位置設定・描画の詳細設定（補助的な項目）")

        # 記述ステータスパネル
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
            height=2, relief=tk.FLAT, bd=0, state=tk.DISABLED,
            highlightthickness=0, cursor="arrow",
        )
        self._desc_status_text.pack(fill=tk.BOTH, expand=True)
        # 採点状況の詳細は必要時の確認画面で扱い、トップには表示しない。
        self._desc_status_frame.pack_forget()

        # 採点済み答案画像・結果フォルダ・採点結果を確認は、「4」の番号の
        # 真下ではなく、メインボタン（採点実行）と同じ行のその右側に置く。
        step2_run_row = tk.Frame(step2._main_header, bg=SECTION_BG)
        step2_run_row.pack(side=tk.LEFT, padx=(16, 0))
        self._btn_run_scoring = ColoredButton(step2_run_row, text="▶ 採点済み答案画像", command=self.run_scoring, bg="#90CAF9", fg="#263238", font=FONT_NORMAL, pady=3)
        self._btn_run_scoring.pack(side=tk.LEFT)
        self.open_scored_btn = tk.Button(step2_run_row, text="📁", command=self.open_scored_folder, bg=BTN_GRAY, relief=tk.FLAT, state=tk.DISABLED, width=3, font=(UI_FONT, get_ui_font_size(10)))
        self.open_scored_btn.pack(side=tk.LEFT, padx=(3, 0), fill=tk.Y)
        self._btn_desc_review = ColoredButton(
            step2_run_row, text="🔎 採点確認",
            command=self._open_descriptive_review,
            bg="#B39DDB", fg="#263238", font=FONT_NORMAL, pady=3,
        )
        self._btn_desc_review.pack(side=tk.LEFT, padx=(3, 0))

        # Step 3: サマリー
        step3 = create_step_frame(pipeline_frame, "集計", BTN_AMBER, 5)
        step3.grid(row=4, column=0, sticky="ew", pady=0)

        self._btn_run_summary = ColoredButton(step3._main_header, text="集計", command=self.run_summary_generation, bg="#1976D2", fg="white", font=(UI_FONT, get_ui_font_size(11), "bold"), width=205, height=56, padx=16, pady=7)
        self._btn_run_summary.pack_propagate(False)
        self._btn_run_summary.pack(side=tk.LEFT, pady=3)

        # 結果フォルダ・「氏名画像を表示する」チェックは、「5」の番号の
        # 真下ではなく、メインボタン（集計）と同じ行のその右側に置く。
        self._step3_run_row = tk.Frame(step3._main_header, bg=SECTION_BG)
        self._step3_run_row.pack(side=tk.LEFT, padx=(16, 0))

        step3_controls_row = tk.Frame(self._step3_run_row, bg=SECTION_BG)
        step3_controls_row.pack(side=tk.TOP, fill=tk.X, anchor=tk.W)

        self.open_results_btn = tk.Button(step3_controls_row, text="📁", command=self.open_results_folder, bg=BTN_GRAY, relief=tk.FLAT, state=tk.DISABLED, width=3, font=(UI_FONT, get_ui_font_size(10)))
        self.open_results_btn.pack(side=tk.LEFT)

        # 学籍番号OCRを実施するかどうかは、初期設定（学籍番号欄指定）で
        # 一度だけ決める。ここでは切り替えない。
        self.name_trim_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(
            step3_controls_row, text="氏名画像を集計シートに表示する",
            variable=self.name_trim_enabled, bg=SECTION_BG,
            font=(UI_FONT, get_ui_font_size(9)), anchor=tk.W, cursor="hand2"
        ).pack(side=tk.LEFT, padx=(8, 0))

        # 採点済み答案画像（Step2「▶採点済み答案画像」）が既に生成されていれば、
        # 集計と同時にそれらを統合したPDFも作られることを案内する。
        tk.Label(
            self._step3_run_row,
            text="※ 採点済み答案画像がある場合、それらを統合したPDFも出力されます",
            bg=SECTION_BG, fg="#607D8B", font=(UI_FONT, get_ui_font_size(9)),
            anchor=tk.W, justify=tk.LEFT,
        ).pack(side=tk.TOP, fill=tk.X, anchor=tk.W, pady=(2, 0))

        # 学籍番号OCRの実施可否は初期設定側で決めるが、既存コードとの
        # 互換のため変数自体はここで初期化しておく（トップ画面には出さない）。
        self.student_id_ocr_enabled = tk.BooleanVar(value=False)

        # 全ページ集計（Step3〜5をページごとに繰り返した最後にだけ意味を持つ、
        # 案件全体のゴール。ページ単位の3・4・5とは性質が違うので、
        # 「採点ワークフロー」の枠の外に独立して置く。大きさで十分目立つので
        # 色は控えめ（アプリの他のアンバー系と揃える）にする。
        combined_border = tk.Frame(controls_frame, bg="#FFCC80", padx=2, pady=2)
        combined_border.pack(fill=tk.X, pady=(20, 0))
        combined_row = tk.Frame(combined_border, bg="#FFF8E1", padx=8, pady=8)
        combined_row.pack(fill=tk.X)
        self._btn_combined_summary = ColoredButton(
            combined_row, text="🏁 全ページがそろったら：全ページ集計",
            command=self._generate_or_explain_combined_summary,
            bg="#FFE082", fg="#4E342E",
            font=(UI_FONT, get_ui_font_size(13), "bold"), padx=20, pady=12,
        )
        self._btn_combined_summary.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.open_combined_summary_btn = tk.Button(
            combined_row, text="📁", command=self.open_combined_summary_folder,
            bg=BTN_GRAY, relief=tk.FLAT, state=tk.DISABLED, width=3,
            font=(UI_FONT, get_ui_font_size(10)),
        )
        self.open_combined_summary_btn.pack(side=tk.LEFT, padx=(6, 0), fill=tk.Y)
        _ToolTip(
            self._btn_combined_summary,
            "全ページのページ別集計が揃ったら、学籍番号をキーに\n"
            "得点・総合計・全ページ試験統計を1つのExcelへ統合します。",
        )

        # --- 初期化完了後の処理 ---
        # Step2/3 のボタンを初期状態で無効化（Step進行ガード）
        self._update_step_availability()

        # 起動時セッション復元（前回の状態を復元から来た場合）
        if self._restore_session_path:
            self.root.after(100, lambda: self._auto_restore_from_path(self._restore_session_path))

    # ---------------------------------------------------------
    # Step 進行ガード
    # ---------------------------------------------------------

    def _is_pages_confirmed(self):
        """このフォルダで「ページ数確定」相当の状態が既に成立しているか判定する。

        明示的に「確定」ボタンを押した場合（self._pages_confirmed）に加え、
        既に答案の取込・準備が進んでいるフォルダでは、アプリ再起動後や
        「📚 ページを管理」を直接使った場合でも自動的に確定済みとみなす。
        """
        if self._pages_confirmed:
            return True
        folder = self.image_folder_path.get()
        if not folder or not Path(folder).exists():
            return False
        try:
            from multi_page_merger import get_multi_page_project_status
            status = get_multi_page_project_status(folder)
            if status and status['pages']:
                return True
        except Exception:
            pass  # マニフェスト破損時は他の判定にフォールバック
        boxed = Path(folder) / RESULTS_FOLDER / BOXED_FOLDER
        return boxed.exists() and any(boxed.iterdir())

    def _update_step1_availability(self):
        """Step 1 実行ボタン（画像準備）の有効化/無効化を制御する。

        画像フォルダが設定されていれば有効化する。
        """
        if not hasattr(self, '_btn_run_box'):
            return
        folder = Path(self.image_folder_path.get()) if self.image_folder_path.get() else None
        ready = bool(folder and folder.exists() and self._is_pages_confirmed())
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
        if not hasattr(self, 'desc_scoring_btn'):
            return

        img_folder = self.image_folder_path.get()
        if not img_folder:
            # フォルダ未選択 → Step2/3 無効
            self._set_step2_enabled(False)
            self._set_step3_enabled(False)
            self._update_progress_guide()
            self._update_multi_page_dashboard()
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
        self._update_progress_guide()
        self._update_multi_page_dashboard()

    def _update_multi_page_dashboard(self):
        """トップ画面の複数ページ数・現在ページ・進捗を更新する。

        画像ファイルが直下にある案件は、複数ページ機能を使わない
        単純な画像案件として扱い（_start_answer_prep と同じ優先順位）、
        既存の複数ページマニフェストが無ければダッシュボード自体を隠す。
        """
        if not hasattr(self, '_multi_page_status_label'):
            return
        folder = self.image_folder_path.get()
        folder_path = Path(folder) if folder else None
        has_images = bool(folder_path and folder_path.exists() and any(
            f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')
            for f in folder_path.iterdir()
        ))
        has_pdfs = bool(folder_path and folder_path.exists() and any(
            f.is_file() and f.suffix.lower() == '.pdf' for f in folder_path.iterdir()
        ))
        if not folder:
            self._multi_page_dashboard.grid_remove()
            return
        try:
            from multi_page_merger import get_multi_page_project_status
            status = get_multi_page_project_status(folder)
        except Exception as exc:
            self._multi_page_dashboard.grid()
            self._multi_page_status_label.config(text=f"進捗を読み込めません: {exc}")
            self._build_page_progress_chips([], None)
            return
        show_dashboard = bool(status and status['pages']) or (not has_images and has_pdfs)
        if not show_dashboard:
            self._multi_page_dashboard.grid_remove()
            return
        self._multi_page_dashboard.grid()
        if not status:
            self._multi_page_status_label.config(
                text="単一ページ案件　｜　複数ページの場合は「ページを管理」"
            )
            self._btn_prev_exam_page.config(state=tk.DISABLED)
            self._btn_next_exam_page.config(state=tk.DISABLED)
            self._build_page_progress_chips([], None)
            return
        pages = status['pages']
        active = status.get('active_page')
        active_state = next((p['state'] for p in pages if p['page'] == active), None)
        state_text = f"　｜　{active_state}" if active_state else ""
        combined_done = Path(status['combined_summary_path']).is_file()
        combined_text = "　✅ 全ページ集計済み" if combined_done else ""
        self._multi_page_status_label.config(
            text=(f"作業ページ：{active or '未選択'} / {len(pages)}ページ"
                  + state_text + combined_text)
        )
        page_numbers = [item['page'] for item in pages]
        if active in page_numbers:
            index = page_numbers.index(active)
            self._btn_prev_exam_page.config(state=tk.NORMAL if index > 0 else tk.DISABLED)
            self._btn_next_exam_page.config(
                state=tk.NORMAL if index < len(page_numbers) - 1 else tk.DISABLED
            )
        else:
            state = tk.NORMAL if page_numbers else tk.DISABLED
            self._btn_prev_exam_page.config(state=tk.DISABLED)
            self._btn_next_exam_page.config(state=state)
        self._build_page_progress_chips(pages, active)

    # ページ状態文字列 → (背景色, アイコン) のスタイル対応。
    # '採点中 N/M' のような可変テキストは前方一致で個別処理する。
    _PAGE_STATE_STYLE = {
        '集計済み': ('#A5D6A7', '✅'),
        '採点完了': ('#C8E6C9', '☑'),
        '初期設定済み': ('#B3E5FC', '⚙'),
        '取込済み': ('#CFD8DC', '📥'),
        '未取込': ('#ECEFF1', '⬜'),
    }

    def _build_page_progress_chips(self, pages, active_page):
        """各ページの進捗を、常時見えるコンパクトなチップ列として描画する。

        トップ画面の状態表示は従来「今見ているページ」の状態しか出ておらず、
        他ページがどこまで進んでいるかはページを移動しないと分からなかった。
        ここでは全ページ分を1行に並べ、現在の作業ページには▶マークと太枠を
        付けて区別する。
        """
        if not hasattr(self, '_page_progress_row'):
            return
        for child in self._page_progress_row.winfo_children():
            child.destroy()
        if not pages:
            return
        for item in pages:
            state = item['state']
            if state.startswith('採点中'):
                bg, icon = '#FFE082', '▶'
                detail = state[len('採点中 '):]
            else:
                bg, icon = self._PAGE_STATE_STYLE.get(state, ('#ECEFF1', '?'))
                detail = ''
            is_active = (item['page'] == active_page)
            chip_text = f"{'▶' if is_active else ''}P{item['page']} {icon}{(' ' + detail) if detail else ''}"
            chip = tk.Label(
                self._page_progress_row, text=chip_text, bg=bg, fg='#263238',
                font=(UI_FONT, get_ui_font_size(8), 'bold' if is_active else 'normal'),
                relief=tk.SOLID if is_active else tk.FLAT,
                bd=2 if is_active else 1, padx=5, pady=1,
            )
            chip.pack(side=tk.LEFT, padx=2)
            _ToolTip(chip, f"ページ{item['page']}: {state}")

    def _on_multi_page_project_change(self):
        """答案取込画面を閉じた後、トップ画面の工程状態を再評価する。

        取込済みの答案があれば、追加画面を再度開かせずにそのまま
        採点準備へ継続する。
        """
        self._update_step_availability()
        self._update_progress_guide()
        self._update_multi_page_dashboard()
        self._try_continue_multi_page_prep()

    def _navigate_exam_page(self, offset):
        """現在ページの前後へワンクリックで切り替える。"""
        from multi_page_merger import get_multi_page_project_status
        status = get_multi_page_project_status(self.image_folder_path.get())
        if not status or not status['pages']:
            return
        pages = [item['page'] for item in status['pages']]
        active = status.get('active_page')
        if active in pages:
            target_index = pages.index(active) + offset
        else:
            target_index = 0
        if not 0 <= target_index < len(pages):
            return
        target = pages[target_index]
        self._go_to_exam_page(target)

    def _go_to_exam_page(self, page_number):
        """指定した試験ページを採点対象として開く。"""
        from multi_page_merger import activate_exam_page, get_multi_page_project_status
        status = get_multi_page_project_status(self.image_folder_path.get())
        if not status:
            return
        try:
            workspace = activate_exam_page(status['project_folder'], page_number)
        except Exception as exc:
            messagebox.showerror("ページ切替エラー", self._friendly_error_message(exc))
            return
        self._prepare_multi_page_exam_page(page_number, workspace)

    def _generate_or_explain_combined_summary(self):
        """全ページ統合Excelを生成し、未集計なら次の作業を案内する。"""
        folder = self.image_folder_path.get()
        if not folder:
            messagebox.showinfo(
                "全ページ集計",
                "先に複数ページ答案のPDFフォルダを選択してください。",
            )
            return
        from multi_page_merger import (
            generate_combined_multi_page_summary,
            get_multi_page_project_status,
        )
        status = get_multi_page_project_status(folder)
        if not status:
            messagebox.showinfo(
                "全ページ集計",
                "複数ページ答案が設定されていません。\n"
                "「ページを管理」から試験ページとPDFを追加してください。",
            )
            return
        result = generate_combined_multi_page_summary(status['project_folder'])
        if result.get('success'):
            output_path = Path(result['output_path'])
            self.last_combined_summary_folder = str(output_path.parent)
            self.open_combined_summary_btn.config(state=tk.NORMAL)
            messagebox.showinfo(
                "全ページ集計 完了",
                f"全ページの採点結果を統合しました。\n\n"
                f"ファイル: {output_path.name}\n"
                f"統合人数: {result['student_count']}名\n\n"
                f"保存先: {output_path.parent}",
            )
            open_in_file_manager(output_path.parent)
            self._update_multi_page_dashboard()
            return

        pending = result.get('pending_pages')
        if pending:
            pending_text = "、".join(f"ページ{page}" for page in pending)
            move = messagebox.askyesno(
                "全ページ集計はまだ作成できません",
                "次のページでStep 3の「確認して集計を実行」が必要です。\n\n"
                f"未集計: {pending_text}\n\n"
                f"最初の未集計ページ（ページ{pending[0]}）を開きますか？",
            )
            if move:
                self._go_to_exam_page(pending[0])
            return

        missing_student_id = result.get('missing_student_id_pages')
        if missing_student_id:
            pages_text = "、".join(f"ページ{page}" for page in missing_student_id)
            move = messagebox.askyesno(
                "全ページ集計はまだ作成できません",
                f"次のページの集計結果には、学籍番号OCRで確認済みの学籍番号が"
                f"含まれていません:\n\n{pages_text}\n\n"
                "該当ページで学籍番号OCRを有効にして集計をやり直す必要があります。\n"
                f"最初のページ（ページ{missing_student_id[0]}）を開きますか？",
            )
            if move:
                self._go_to_exam_page(missing_student_id[0])
            return

        messagebox.showerror(
            "全ページ集計エラー",
            f"統合Excelを作成できませんでした。\n\n{result.get('error', '不明なエラー')}",
        )

    def _update_progress_guide(self):
        """トップ画面の準備状況と次の操作を更新する。"""
        if not hasattr(self, "_progress_guide_labels"):
            return
        img_folder = self.image_folder_path.get()
        base = Path(img_folder) / RESULTS_FOLDER if img_folder else None
        data = base / RESULTS_DATA_FOLDER if base else None

        def has_images(path):
            return bool(path and path.exists() and any(
                p.suffix.lower() in (".jpg", ".jpeg", ".png") for p in path.iterdir()
            ))

        source = bool(img_folder and Path(img_folder).exists())
        setup = bool(data and (data / "descriptive_config.json").exists())
        boxed = has_images(base / BOXED_FOLDER) if base else False
        scored = has_images(base / SCORED_FOLDER) if base else False
        # 「採点実行」の完了は、採点済み答案の出力(SCORED_FOLDER)ではなく
        # 全問題×全画像の採点データ(descriptive_scores.json)が揃っているかで
        # 判定する。出力は採点完了後の別工程（▶ 採点済み答案画像）であり、
        # これを条件にすると採点自体は終わっているのにチェックが付かない。
        scoring_done = (
            self._check_descriptive_completeness(img_folder)[0]
            if (img_folder and setup and boxed) else False
        )
        reviewed = bool(data and (data / "descriptive_scores.json").exists())
        summary = bool(base and (base / FINAL_REPORT_FOLDER).exists())
        states = {
            "source": (source, "画像フォルダ選択済み" if source else "画像フォルダ未選択"),
            "setup": (setup, "採点領域設定済み" if setup else "初期設定が必要"),
            "scoring": (scored, "採点済み答案あり" if scored else ("採点可能" if setup and boxed else "画像準備が必要")),
            "review": (reviewed, "確認可能" if reviewed else "採点後に確認"),
            "summary": (summary, "集計結果あり" if summary else ("集計可能" if boxed else "画像準備後に実行")),
        }
        # 複数ページ案件では、Step3〜5のチェックは「今見ているページ」だけでなく
        # 全ページの完了状況で判定する。1ページ目だけ終えた時点で✓が付くと
        # 紛らわしいため。
        all_boxed, all_scored, all_summary = boxed, scoring_done, summary
        multi_status = None
        pending_page = None
        if img_folder:
            from multi_page_merger import get_multi_page_project_status
            multi_status = get_multi_page_project_status(img_folder)
            if multi_status and multi_status['pages']:
                all_boxed = all_scored = all_summary = True
                for page in multi_status['pages']:
                    page_base = Path(page['workspace']) / RESULTS_FOLDER
                    if not has_images(page_base / BOXED_FOLDER):
                        all_boxed = False
                    # page['state']（get_multi_page_project_status）は監査で除外
                    # された答案を採点対象から除いた上で完了判定している。
                    # _check_descriptive_completeness はboxed_folder内の画像を
                    # 単純に数えるため、除外済みの答案ファイルが残っていると
                    # 常に未完了と誤判定してしまう。ここでは前者を使う。
                    if page['state'] not in ('採点完了', '集計済み'):
                        all_scored = False
                    if not (page_base / FINAL_REPORT_FOLDER).exists():
                        all_summary = False
                        if pending_page is None:
                            pending_page = page['page']

        # 縦型の工程表示（完了はチェック、次の工程は矢印）
        marker_done = {
            1: source,
            2: self._is_pages_confirmed(),
            3: all_boxed,
            4: all_scored,
            5: all_summary,
        }
        next_step = next((step for step, done in marker_done.items() if not done), 5)
        for step, done in marker_done.items():
            marker = getattr(self, "_step_markers", {}).get(step)
            if marker is not None:
                marker.config(
                    text="✓" if done else ("→" if step == next_step else " "),
                    fg="#2E7D32" if done else ("#1565C0" if step == next_step else "#B0BEC5"),
                )
        for key, (done, text) in states.items():
            marker, label = self._progress_guide_labels[key]
            marker.config(text="✓" if done else "○", fg="#2E7D32" if done else "#90A4AE")
            label.config(fg="#2E7D32" if done else "#78909C")
        if not source:
            next_text, button_text, command, button_bg = "次にすること：画像フォルダを選択してください", "フォルダを選択", self.select_folder, "#FFCC80"
        elif not boxed:
            next_text, button_text, command, button_bg = "次にすること：答案ファイルを追加して採点準備をしてください", "答案ファイル追加＆採点準備", self._start_answer_prep, "#1976D2"
        elif not setup:
            next_text, button_text, command, button_bg = "次にすること：初期設定を実行してください", "初期設定", self._run_step1_setup_wizard, "#CE93D8"
        elif not reviewed:
            next_text, button_text, command, button_bg = "次にすること：採点を開始してください", "採点", self.run_descriptive_scoring, "#90CAF9"
        elif not summary:
            next_text, button_text, command, button_bg = "次にすること：採点結果を確認して集計してください", "集計", self.run_summary_generation, "#FFE082"
        elif multi_status and multi_status['pages'] and not all_summary:
            # 今のページは完了しているが、他のページがまだ集計未完了。
            next_text = f"次にすること：ページ{pending_page}の採点・集計を進めてください"
            button_text = f"ページ{pending_page}へ移動"
            command = lambda: self._go_to_exam_page(pending_page)
            button_bg = "#FFE082"
        else:
            next_text, button_text, command, button_bg = "次にすること：採点結果を確認・再集計できます", "採点確認", self._open_descriptive_review, "#E1BEE7"
        self._progress_next_label.config(text=next_text)
        self._progress_next_button.config(text=button_text, command=command, bg=button_bg)

    def _set_step2_enabled(self, enabled: bool):
        """Step2 の操作ボタン群を有効化/無効化する"""
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in [
            self.desc_scoring_btn,
            self._btn_desc_review,
            self._btn_run_scoring,
            self._btn_step2_more,
        ]:
            try:
                btn.config(state=state)
            except Exception:
                pass

    def _show_step2_more_menu(self):
        """「合計点位置設定」「描画の詳細設定」をまとめた補助メニューを表示する。

        どちらも頻度の低い調整項目なので、常設ボタンにせず「⋯」から呼び出す。
        """
        if str(self._btn_step2_more["state"]) == tk.DISABLED:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="📐 合計点位置設定", command=self.setup_total_position)
        menu.add_command(label="⚙ 描画の詳細設定", command=self._open_rendering_settings)
        x = self._btn_step2_more.winfo_rootx()
        y = self._btn_step2_more.winfo_rooty() + self._btn_step2_more.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

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
        """作業スペースだけを選択し、処理は開始しない。"""
        folder = filedialog.askdirectory(title="作業スペースを選択")
        if folder:
            self._set_processing_state(False)
            self._pages_confirmed = False
            self.image_folder_path.set(str(folder))
            self.log_message(f"✓ 作業スペースを選択: {folder}")
            self._try_auto_restore()
            self._update_step1_availability()
            self._update_step_availability()
            self._update_multi_page_dashboard()

    def _start_answer_prep(self):
        """Step3の入口: 答案ファイルを追加し、そのまま採点準備まで進める。

        画像案件はそのまま採点準備を実行する。PDF・複数ページ案件は、
        取込済みの答案があれば追加画面を開かずに直接採点準備へ進み、
        まだ何も取り込まれていなければ追加専用の画面を開く。
        """
        if self._processing:
            return
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "先に作業スペースを選択してください。")
            return
        if not self._is_pages_confirmed():
            messagebox.showerror("エラー", "先にページ数を入力して「確定」を押してください。")
            return

        img_folder = Path(self.image_folder_path.get())
        if not img_folder.exists():
            messagebox.showerror("エラー", "作業スペースが存在しません。")
            return

        has_images = any(
            f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')
            for f in img_folder.iterdir()
        )
        if has_images:
            self._prepare_images_for_descriptive(auto_start_setup=True)
            return

        has_pdfs = any(f.is_file() and f.suffix.lower() == '.pdf' for f in img_folder.iterdir())
        if not has_pdfs:
            messagebox.showerror("エラー", "作業スペースに対応する画像またはPDFが見つかりません。")
            return

        if not self._try_continue_multi_page_prep():
            self.run_multi_page_merge()

    def _try_continue_multi_page_prep(self):
        """取込済みの答案ページがあれば、追加画面を開かず直接採点準備へ進む。

        Returns:
            採点準備へ継続できた（＝呼び出し側は追加画面を開かなくてよい）場合True。
        """
        from multi_page_merger import activate_exam_page, get_multi_page_project_status
        status = get_multi_page_project_status(self.image_folder_path.get())
        if not status or not status['pages']:
            return False
        page_numbers = [item['page'] for item in status['pages']]
        active = status.get('active_page')
        target = active if active in page_numbers else page_numbers[0]
        target_status = next(item for item in status['pages'] if item['page'] == target)
        if target_status['state'] == '未取込':
            return False
        try:
            workspace = activate_exam_page(status['project_folder'], target)
        except Exception as exc:
            messagebox.showerror("ページ切替エラー", self._friendly_error_message(exc))
            return True
        self._prepare_multi_page_exam_page(target, workspace)
        return True

    def _adjust_page_count(self, delta):
        """▲▼ボタンでページ数を1刻みで増減する（1〜999に収める）。"""
        try:
            current = int(self.total_pages.get())
        except (TypeError, ValueError):
            current = 0
        self.total_pages.set(str(max(1, min(999, current + delta))))

    def _confirm_page_count(self):
        """ページ数を確定し、次の答案ファイル追加工程を有効にする。"""
        try:
            pages = int(self.total_pages.get())
            if pages < 1:
                raise ValueError
        except (TypeError, ValueError):
            self._pages_confirmed = False
            messagebox.showerror("ページ数", "1以上のページ数を入力してください。")
            self._update_progress_guide()
            return
        self._pages_confirmed = True
        self._update_step1_availability()
        self._update_progress_guide()

    def _start_setup_for_image_source(self, folder):
        """画像ソースを反映し、画像準備から初期設定まで連続実行する。"""
        self._set_processing_state(False)
        self._pages_confirmed = False
        self.image_folder_path.set(str(folder))
        self.log_message(f"✓ 画像フォルダを選択: {folder}")
        self._try_auto_restore()
        self._update_step1_availability()
        self._update_step_availability()
        source_folder = Path(folder)
        image_files = [
            path for path in source_folder.iterdir()
            if path.is_file() and path.suffix.lower()
            in ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')
        ]
        pdf_files = [
            path for path in source_folder.iterdir()
            if path.is_file() and path.suffix.lower() == '.pdf'
        ]
        if image_files:
            self._prepare_images_for_descriptive(auto_start_setup=True)
        elif pdf_files:
            self.log_message(
                f"✓ PDFのみのフォルダを選択: {len(pdf_files)}件。複数ページ答案の管理を開きます。"
            )
            self.root.after(0, self.run_multi_page_merge)
        else:
            messagebox.showerror(
                "エラー",
                "フォルダに対応する画像ファイルまたはPDFが見つかりません",
            )

    # ---------------------------------------------------------
    # 記述のみモード: 画像準備
    # ---------------------------------------------------------

    def _prepare_images_for_descriptive(self, auto_start_setup=False):
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
             if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')]
        )
        if not image_files:
            pdf_files = [
                path for path in img_folder.iterdir()
                if path.is_file() and path.suffix.lower() == '.pdf'
            ]
            if pdf_files:
                self.log_message(
                    f"PDFファイルを{len(pdf_files)}件検出しました。先に「答案ファイルを追加」を実行してください。"
                )
                manifest_path = (
                    Path(self.image_folder_path.get()) / RESULTS_FOLDER /
                    RESULTS_DATA_FOLDER / "multi_page_manifest.json"
                )
                if manifest_path.exists():
                    # 取込済みなら、答案追加の案内ではなく試験ページ選択へ進む。
                    self.run_multi_page_merge()
                    return
                messagebox.showinfo(
                    "答案ファイルの追加",
                    "PDF案件は、先に「答案ファイルを追加」から答案を取り込んでください。\n"
                    "取込完了後に「採点準備」を実行できます。",
                )
            else:
                messagebox.showerror(
                    "エラー",
                    "フォルダに対応する画像ファイルまたはPDFが見つかりません",
                )
            return

        self._set_processing_state(True)
        thread = threading.Thread(
            target=self._run_prepare_images_thread,
            args=(img_folder, image_files, auto_start_setup),
            daemon=True,
        )
        thread.start()

    def _run_prepare_images_thread(self, img_folder, image_files, auto_start_setup=False):
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

            if auto_start_setup:
                self.root.after(0, self._continue_setup_after_prepare)
            else:
                self.root.after(0, lambda: messagebox.showinfo(
                    "完了",
                    f"画像準備が完了しました！\n\n"
                    f"・画像数: {copied}枚"
                ))
        except Exception as e:
            self.log_message(f"画像準備エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            friendly = self._friendly_error_message(e)
            self.root.after(0, lambda: messagebox.showerror("エラー", friendly))
        finally:
            self.root.after(0, self._set_processing_state, False)

    def _continue_setup_after_prepare(self):
        """画像準備の完了後、そのまま初期設定ウィザードを開始する。"""
        self._set_processing_state(False)
        from multi_page_merger import shared_layout_was_applied
        if shared_layout_was_applied(self.image_folder_path.get()):
            results_data = (
                Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
            )
            self._wizard_step_roster()
            self._sync_student_id_ocr_enabled(results_data)
            self.log_message(
                "✓ 全ページ共通の学籍番号欄・氏名欄・解答欄設定を適用しました"
            )
            self._update_descriptive_status()
            self._save_session_state()
            self._update_step_availability()
            return
        self._run_step1_setup_wizard()
    
    def select_pdf(self):
        """PDFまたは画像ファイルを選択する。"""
        if not HAS_PYMUPDF:
            messagebox.showerror(
                "エラー",
                "PDF入力にはPyMuPDFが必要です。\n\n"
                "pip install PyMuPDF\n\n"
                "でインストールしてください。"
            )
            return
        
        pdf_files = filedialog.askopenfilenames(
            title="画像ファイルを選択（複数選択可）",
            filetypes=[
                ("PDF・画像", "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべてのファイル", "*.*"),
            ]
        )
        if not pdf_files:
            return

        pdf_files = list(pdf_files)
        non_pdf_files = [path for path in pdf_files if Path(path).suffix.lower() != ".pdf"]
        if non_pdf_files:
            # 画像はそのまま作業スペースの入力として扱う。複数の場所から
            # 選ばれた場合も、最初の画像の親を作業スペースにする。
            self._start_setup_for_image_source(Path(non_pdf_files[0]).parent)
            return
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
            self.log_message(f"✓ PDF展開完了 ({len(pdf_files)}ファイル) → {output_folder}")
            self.root.after(0, lambda: self._start_setup_for_image_source(output_folder))
        except Exception as e:
            self.log_message(f"✗ PDF展開エラー: {e}")
            self.root.after(0, lambda: messagebox.showerror("PDF展開エラー", str(e)))
        finally:
            self.root.after(0, self._set_processing_state, False)
    
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
        """複数ページ答案の試験ページ・取込バッチ管理画面を開く。"""
        image_folder = self.image_folder_path.get()
        if not image_folder or not Path(image_folder).exists():
            messagebox.showerror("エラー", "先に画像フォルダを選択してください。")
            return
        from multi_page_merger import (
            resolve_multi_page_project_folder,
            run_multi_page_import_gui,
        )
        project_folder = resolve_multi_page_project_folder(image_folder)
        try:
            total_pages = max(1, int(self.total_pages.get()))
        except (TypeError, ValueError):
            messagebox.showerror("ページ数", "答案のページ数を1以上の整数で入力してください。")
            return
        run_multi_page_import_gui(
            project_folder,
            parent=self.root,
            on_project_change=self._on_multi_page_project_change,
            total_pages=total_pages,
        )

    def _prepare_multi_page_exam_page(self, exam_page, workspace):
        """選択した試験ページを現在の作業対象にして採点準備を開始する。"""
        self._pages_confirmed = False
        self.image_folder_path.set(str(workspace))
        self.log_message(f"✓ 試験ページ {exam_page} を作業対象に設定: {workspace}")
        self._update_step1_availability()
        self._update_step_availability()
        workspace_path = Path(workspace)
        boxed = workspace_path / RESULTS_FOLDER / BOXED_FOLDER
        config = workspace_path / RESULTS_FOLDER / RESULTS_DATA_FOLDER / "descriptive_config.json"
        self._sync_student_id_ocr_enabled(workspace_path / RESULTS_FOLDER / RESULTS_DATA_FOLDER)
        if boxed.exists() and config.exists():
            self._update_descriptive_status()
            self._update_multi_page_dashboard()
        elif boxed.exists():
            self._run_step1_setup_wizard()
        else:
            self._prepare_images_for_descriptive(auto_start_setup=True)

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

    def open_combined_summary_folder(self):
        """全ページ集計の統合Excelが入ったフォルダを開く"""
        if self.last_combined_summary_folder and Path(self.last_combined_summary_folder).exists():
            open_in_file_manager(self.last_combined_summary_folder)
    
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

    def _show_log_window(self):
        """必要なときだけ詳細ログを別ウィンドウで表示する。"""
        window = tk.Toplevel(self.root)
        window.title("処理ログ")
        window.geometry("760x420")
        text = scrolledtext.ScrolledText(window, wrap=tk.WORD, font=("Consolas", 9),
                                         bg="#FAFAFA", relief=tk.FLAT)
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        text.insert("1.0", self.log_text.get("1.0", tk.END))
        text.config(state=tk.DISABLED)

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

    def _open_rendering_settings(self):
        """詳細設定ウィンドウを開く"""
        RenderingSettingsGUI(
            parent_window=self.root,
            current_settings=self.rendering_settings,
            on_apply=self._apply_rendering_settings,
            image_folder=self.image_folder_path.get(),
            skip_questions=self.skip_questions.get(),
            app_mode=MODE_DESCRIPTIVE_ONLY,
        )

    def _apply_rendering_settings(self, new_settings):
        """設定ウィンドウからの適用コールバック"""
        self.rendering_settings = get_rendering_settings(new_settings)
        self.log_message("✓ 描画詳細設定を更新しました")

    # ---------------------------------------------------------
    # OMR認識モード切り替え (v4.5)
    # ---------------------------------------------------------

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
                "記述問題の採点領域設定が見つかりません。\n"
                "先に「⚙ 初期設定」を実行してください。"
            )
            return
        if not desc_scores_path.exists():
            messagebox.showerror(
                "エラー",
                "採点結果が見つかりません。\n"
                "先に「✏ 採点を開始」を実行してください。"
            )
            return

        # 採点完了チェック
        is_complete, unscored, total_img, detail = self._check_descriptive_completeness()
        if not is_complete and total_img > 0:
            detail_text = "\n".join(detail) if detail else ""
            if not messagebox.askyesno(
                "採点が未完了です",
                f"採点が完了していない生徒が {unscored}名 います。\n\n"
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
                load_descriptive_annotations, DESCRIPTIVE_ANNOTATIONS_FILE,
            )

            results_folder = Path(params['image_folder']) / RESULTS_FOLDER
            results_data = results_folder / RESULTS_DATA_FOLDER
            boxed_folder = results_folder / BOXED_FOLDER
            output_folder = results_folder / SCORED_FOLDER

            config = load_descriptive_config(str(results_data / "descriptive_config.json"))
            scores_data = load_descriptive_scores(str(results_data / "descriptive_scores.json"))
            annotations = load_descriptive_annotations(
                str(results_data / DESCRIPTIVE_ANNOTATIONS_FILE)
            )

            if not config or not scores_data:
                self.root.after(0, lambda: messagebox.showerror(
                    "エラー", "初期設定またはスコアの読み込みに失敗しました。"
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
                annotations=annotations,
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
                    f"出力フォルダ（答案1枚ずつの画像）: {output_folder}\n\n"
                    f"※ 採点済み答案をまとめた1つのPDFは、この後「集計」を実行すると\n"
                    f"　 別フォルダ（03_Final_Report）に生成されます。"
                )
                self.root.after(0, lambda: messagebox.showinfo("完了", summary))

        except Exception as e:
            self.log_message(f"採点処理エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror("エラー", f"採点処理中にエラーが発生しました:\n{self._friendly_error_message(e)}"))
        finally:
            self.root.after(0, self._set_processing_state, False)

    def _current_exam_page(self, folder: str = None):
        """指定フォルダ（省略時は現在の画像フォルダ）が複数ページ案件の
        ページ別ワークスペースなら、その試験ページ番号を返す。単一ページ
        案件やワークスペース外なら None。

        採点実行・採点確認・学籍番号OCR確認など、ページ単位で開く別ウィンドウの
        タイトルに「試験ページ N」を表示し、複数ウィンドウが並んでいても
        今どのページの作業か分かるようにするために使う。
        """
        folder = folder or self.image_folder_path.get()
        if not folder:
            return None
        try:
            from multi_page_merger import get_exam_page_for_workspace
            return get_exam_page_for_workspace(folder)
        except Exception:
            return None

    # ---------------------------------------------------------
    # α: 記述採点の確認機能
    # ---------------------------------------------------------

    def _open_descriptive_review(self):
        """記述採点の確認ウィンドウを開く。

        複数ページ案件では、ウィンドウ内の前後ページボタンで閉じずに
        別の試験ページへ切り替えられるよう、ループして開き直す。
        """
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        while True:
            current_folder = self.image_folder_path.get()
            results_data = Path(current_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
            config_path = results_data / "descriptive_config.json"
            scores_path = results_data / "descriptive_scores.json"
            boxed_folder = Path(current_folder) / RESULTS_FOLDER / BOXED_FOLDER

            if not config_path.exists():
                messagebox.showerror("エラー", "採点領域の設定が見つかりません。\n先に「⚙ 初期設定」を実行してください。")
                return
            try:
                from descriptive_scorer import (
                    load_descriptive_config, load_descriptive_scores,
                    DescriptiveReviewGUI,
                )
                config = load_descriptive_config(str(config_path))
                # 採点開始前は得点ファイルがまだ存在しない。設定済みの答案領域を
                # レビューできるよう、空の得点データとして確認画面を開く。
                scores_data = (
                    load_descriptive_scores(str(scores_path))
                    if scores_path.exists()
                    else {"version": 1, "scores": {}}
                )

                if not config or scores_data is None:
                    messagebox.showerror("エラー", "設定またはスコアの読み込みに失敗しました。")
                    return

                reviewer = DescriptiveReviewGUI(
                    parent=self.root,
                    config=config,
                    scores=scores_data.get("scores", {}),
                    boxed_folder=str(boxed_folder),
                    scores_save_path=str(scores_path),
                    original_image_folder=current_folder,
                    exam_page=self._current_exam_page(current_folder),
                )
                if reviewer.modified:
                    self.log_message("✓ 採点結果の確認・修正が完了しました")
                    self._update_descriptive_status()
                    self._save_session_state()
                    # 複数ページ案件のトップ画面（ページ別進捗チップ・工程マーカー）に
                    # 反映されるよう更新する（呼び忘れると採点済みなのに反映されない）。
                    self._update_step_availability()
            except Exception as e:
                self.log_message(f"採点確認エラー: {e}")
                import traceback
                self.log_message(traceback.format_exc())
                messagebox.showerror("エラー", f"採点確認中にエラーが発生しました:\n{e}")
                return

            offset = reviewer.pending_page_switch
            if offset is None:
                return
            self._navigate_exam_page(offset)
            if self.image_folder_path.get() == current_folder:
                return  # 端のページで、これ以上移動できなかった

    def _update_descriptive_status(self):
        """記述ステータスパネルの内容を更新する"""
        if not self.descriptive_enabled.get():
            return

        img_folder = self.image_folder_path.get()
        if not img_folder:
            self._set_desc_status("📋 採点ステータス: フォルダ未選択")
            return

        results_data = Path(img_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = results_data / "descriptive_config.json"
        scores_path = results_data / "descriptive_scores.json"
        boxed_folder = Path(img_folder) / RESULTS_FOLDER / BOXED_FOLDER

        if not config_path.exists():
            self._set_desc_status("📋 採点ステータス: ⚠ 未設定\n  → 「⚙ 初期設定」を実行してください")
            return

        try:
            from descriptive_scorer import load_descriptive_config, load_descriptive_scores
            config = load_descriptive_config(str(config_path))
            if not config or not config.get("questions"):
                self._set_desc_status("📋 採点ステータス: ⚠ 設定が空です")
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

            lines = [f"📋 採点ステータス: {q_count}問 (満点: {total_max}点)"]

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
            self._set_desc_status(f"📋 採点ステータス: 読み込みエラー ({e})")

    def _check_descriptive_completeness(self, img_folder=None) -> tuple:
        """記述採点の完了状態をチェックする。

        Args:
            img_folder: チェック対象のワークスペースフォルダ。省略時は現在選択中の
                画像フォルダ(self.image_folder_path.get())を使う。複数ページ案件で
                他ページのワークスペースの完了状態を判定する際に指定する。

        Returns:
            (is_complete: bool, unscored_count: int, total_images: int, detail_lines: list)
        """
        if img_folder is None:
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
        """初期設定・採点結果と、学籍番号欄の位置設定をすべて削除して初期状態に戻す。

        同じテスト用データ(PDF/フォルダ)を使い回して設定をやり直す際、
        学籍番号欄の位置設定だけが残っていて英字マス指定・桁数確認の画面が
        再度出てこない、という混乱を避けるため、記述設定とあわせてここで削除する。

        削除対象:
            - descriptive_config.json（問題設定）
            - descriptive_scores.json（採点結果）
            - descriptive_annotations.json（採点メモ・注釈）
            - total_display_config.json（合計点表示位置設定）
            - student_id_area_config.json（学籍番号欄の位置設定）
            - roster_config.json（名簿）
            - name_area_config.json（氏名欄の位置設定）
        """
        img_folder = self.image_folder_path.get()
        if not img_folder:
            messagebox.showerror("エラー", "画像フォルダを選択してください。")
            return

        results_data = Path(img_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = results_data / "descriptive_config.json"
        scores_path = results_data / "descriptive_scores.json"
        annotations_path = results_data / "descriptive_annotations.json"

        from descriptive_scorer import TOTAL_DISPLAY_CONFIG_FILE
        total_pos_path = results_data / TOTAL_DISPLAY_CONFIG_FILE

        from id_area_config import ID_AREA_CONFIG_FILE
        id_area_path = results_data / ID_AREA_CONFIG_FILE

        from roster_config import ROSTER_CONFIG_FILE
        roster_path = results_data / ROSTER_CONFIG_FILE

        from name_area_config import NAME_AREA_CONFIG_FILE
        name_area_path = results_data / NAME_AREA_CONFIG_FILE

        # 削除対象ファイルの存在チェック
        existing = []
        if config_path.exists():
            existing.append(f"・採点領域の初期設定（{config_path.name}）")
        if scores_path.exists():
            existing.append(f"・採点結果（{scores_path.name}）")
        if annotations_path.exists():
            existing.append(f"・採点メモ・注釈（{annotations_path.name}）")
        if total_pos_path.exists():
            existing.append(f"・合計点位置設定（{total_pos_path.name}）")
        if id_area_path.exists():
            existing.append(f"・学籍番号欄の位置設定（{id_area_path.name}）")
        if roster_path.exists():
            existing.append(f"・名簿（{roster_path.name}）")
        if name_area_path.exists():
            existing.append(f"・氏名欄の位置設定（{name_area_path.name}）")

        if not existing:
            messagebox.showinfo("初期化", "削除対象の設定ファイルが見つかりません。\nすでに初期状態です。")
            return

        # 確認ダイアログ — 既存の採点データが消えることを明示
        answer = messagebox.askokcancel(
            "⚠ 初期設定と採点データの初期化",
            "以下のファイルを削除し、初期状態に戻します。\n\n"
            + "\n".join(existing) + "\n\n"
            "この操作は取り消せません。\n"
            "進行中の採点データ・学籍番号欄の位置設定もすべて失われます。\n\n"
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
        for path in [config_path, scores_path, annotations_path, total_pos_path, id_area_path, roster_path, name_area_path]:
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
        for path in [config_path, scores_path, annotations_path, total_pos_path, id_area_path, roster_path, name_area_path]:
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

        self.log_message(f"✓ 初期設定と採点データを初期化しました（{', '.join(deleted)}）")
        self._update_descriptive_status()
        self._update_step_availability()

    # ---------------------------------------------------------
    # セッション状態の保存・復元
    # ---------------------------------------------------------

    def _get_session_state_path(self):
        """現在の画像フォルダに対応する session_state.json のパスを返す"""
        img_folder = self.image_folder_path.get()
        if not img_folder:
            return None
        return Path(img_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER / SESSION_STATE_FILE

    def _get_last_session_pointer(self):
        # OSの一時領域は再起動・環境によって変わることがあるため、
        # ユーザー領域に固定して前回パスを保持する。
        return Path.home() / ".marunosuke_last_session.json"

    def _save_session_state(self):
        """現在のGUI状態を session_state.json に保存する"""
        session_path = self._get_session_state_path()
        if not session_path:
            return
        img_folder = Path(self.image_folder_path.get())
        if not img_folder.exists():
            return

        import datetime
        state = {
            "version": 1,
            "image_folder": str(img_folder),
            "skip_questions": self.skip_questions.get(),
            "rendering_settings": self.rendering_settings,
            "saved_at": datetime.datetime.now().isoformat(),
        }

        try:
            atomic_json_save(session_path, state)
            atomic_json_save(self._get_last_session_pointer(), {"path": str(session_path)})
        except Exception as e:
            self.log_message(f"⚠ セッション保存失敗: {e}")

    def _load_session_state(self, session_path):
        """session_state.json を読み込む（破損時は .bak からリカバリ）"""
        return load_json_safe(session_path, required_keys=["version"])

    def _apply_session_state(self, state):
        """session_state を GUI に適用する。

        Returns:
            True: 復元成功, False: 復元キャンセル
        """
        base_folder = Path(state.get("image_folder", ""))
        # 復元に成功したセッションを次回の自動復元候補として記憶する。
        session_path = base_folder / RESULTS_FOLDER / RESULTS_DATA_FOLDER / SESSION_STATE_FILE
        try:
            atomic_json_save(self._get_last_session_pointer(), {"path": str(session_path)})
        except Exception:
            pass

        # 画像フォルダ自体の確認（PDF展開後のフォルダも含む）
        if not base_folder.exists():
            messagebox.showerror(
                "復元エラー",
                f"画像フォルダが見つかりません:\n{base_folder}\n\n"
                "フォルダを移動・削除していないか確認してください。"
            )
            return False

        self._pages_confirmed = False
        self.image_folder_path.set(str(base_folder))

        # 数値・フラグの復元
        self.skip_questions.set(state.get("skip_questions", "4"))

        # 描画詳細設定の復元
        saved_rs = state.get("rendering_settings")
        if saved_rs and isinstance(saved_rs, dict):
            self.rendering_settings = get_rendering_settings(saved_rs)

        return True

    def _restore_session_interactive(self):
        """「前回の状態を復元」ボタンのハンドラ

        フロー:
          1. ファイル選択ダイアログで session_state.json を指定
          2. JSON 読み込み・バリデーション
          3. _apply_session_state でパス検証 → 壊れたパスの修復ダイアログ
          4. 成功時にステータスパネル更新
        """
        # 前回使用した画像フォルダが分かっていて、そこにセッションがあれば
        # ファイル選択を省略してそのまま復元する。
        remembered = self._get_session_state_path()
        if not remembered:
            pointer = self._get_last_session_pointer()
            pointer_state = load_json_safe(pointer)
            if isinstance(pointer_state, dict) and pointer_state.get("path"):
                remembered = Path(pointer_state["path"])
        if remembered and remembered.exists():
            selected = str(remembered)
        else:
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
        """合計点表示位置の設定"""
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
        if not boxed_folder.exists():
            messagebox.showerror(
                "エラー",
                f"補正済み画像フォルダが存在しません。\n"
                f"Step 1（画像準備）を先に実行してください。"
            )
            return

        # 最初の画像を取得
        image_files = sorted(boxed_folder.glob("*.jpg")) + sorted(boxed_folder.glob("*.png"))
        if not image_files:
            messagebox.showerror("エラー", "補正済み画像が見つかりません")
            return

        # AnswerKeyなしで記述配点のみでプレビュー
        try:
            results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
            desc_config_path = results_data_folder / "descriptive_config.json"
            total_max = 0

            if desc_config_path.exists():
                from descriptive_scorer import load_descriptive_config
                desc_config = load_descriptive_config(str(desc_config_path))
                if desc_config:
                    for q in desc_config.get("questions", []):
                        ms = q.get("max_score", 0)
                        total_max += ms

            if total_max == 0:
                preview_text = "得点：? / ?"
                recommended_w, recommended_h = 200, 50
            else:
                line1 = f"得点：{total_max} / {total_max}"
                preview_text = line1
                try:
                    font14 = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 14)
                    font12 = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 12)
                except Exception:
                    font14 = ImageFont.load_default()
                    font12 = font14
                tmp_img = Image.new('RGB', (800, 200))
                tmp_draw = ImageDraw.Draw(tmp_img)
                bbox1 = tmp_draw.textbbox((0, 0), line1, font=font14)
                text_w = bbox1[2] - bbox1[0]
                text_h = bbox1[3] - bbox1[1]
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

    def _run_step1_setup_wizard(self):
        """Step1「採点準備」の統合セットアップウィザード。

        名簿・ページ設定・氏名欄・学籍番号欄の4項目を順番にまとめて
        設定してから、最後に採点領域の初期設定(setup_descriptive)を呼ぶ。
        各項目は「既存ファイルがあれば自動スキップ」「キャンセル/スキップは
        次のステップへ進むだけ(全体を中断しない)」というルールで動く
        (解答欄指定=setup_descriptiveだけは実質必須のためスキップ不可)。
        """
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
        if not boxed_folder.exists():
            messagebox.showerror(
                "エラー",
                "補正済み画像フォルダが存在しません。\nStep 1（画像準備）を先に実行してください。"
            )
            return

        results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        results_data_folder.mkdir(parents=True, exist_ok=True)

        # 既存設定をどう扱うかは、名簿や各領域を設定する前に必ず決める。
        descriptive_config_path = results_data_folder / "descriptive_config.json"
        if descriptive_config_path.exists():
            choice = self._ask_descriptive_setup_action()
            if choice == "cancel":
                return
            if choice == "reset":
                self._reset_descriptive_data()
                # 初期化がキャンセル／失敗した場合は既存ファイルが残る。
                if descriptive_config_path.exists():
                    return

        self._wizard_step_roster()
        self._wizard_step_page_check()
        self._wizard_step_name_area(boxed_folder, results_data_folder)
        self._wizard_step_id_area(boxed_folder, results_data_folder)
        self.setup_descriptive(skip_existing_prompt=True)

    def _wizard_step_roster(self):
        """ウィザードStep: 名簿の読込(保存済みなら自動スキップ)。

        名簿はページに依存しない（試験全体で共通）ため、複数ページ案件では
        案件フォルダ直下の1箇所にまとめて保存し、ページごとに聞き直さない。
        """
        from roster_config import load_roster_config, save_roster_config
        from multi_page_merger import resolve_roster_config_path
        config_path = resolve_roster_config_path(self.image_folder_path.get())
        if load_roster_config(config_path) is not None:
            self.log_message("✓ 名簿は設定済みです — スキップします")
            return
        from roster_loader import select_roster_gui
        roster = select_roster_gui(parent=self.root)
        if roster:
            save_roster_config(config_path, roster)
            self.log_message(f"✓ 名簿を保存しました: {len(roster)}件")
        else:
            self.log_message("名簿入力: 該当なし（スキップ）")

    def _wizard_step_page_check(self):
        """ウィザードStep: ページ番号確認(値の保存は行わない、ツールを流用するだけ)"""
        if not messagebox.askyesno(
            "ページ設定",
            "別ページの答案が紛れていないかOCRで確認しますか？",
        ):
            self.log_message("ページ設定: 該当なし（スキップ）")
            return
        self.run_page_number_check()

    def _wizard_step_name_area(self, boxed_folder, results_data_folder):
        """ウィザードStep: 氏名欄の選択(保存済みなら自動スキップ)"""
        from name_area_config import NAME_AREA_CONFIG_FILE, load_name_area_config, save_name_area_config
        config_path = str(results_data_folder / NAME_AREA_CONFIG_FILE)
        if load_name_area_config(config_path) is not None:
            self.log_message("✓ 氏名欄は設定済みです — スキップします")
            return
        from name_trimmer import NameTrimmer, get_image_files
        image_files = get_image_files(str(boxed_folder))
        if not image_files:
            return
        trimmer = NameTrimmer()
        result = trimmer.run(str(boxed_folder), parent=self.root)
        trimmer.cleanup()
        if result is None:
            self.log_message("氏名欄選択: 該当なし（スキップ）")
            return
        with Image.open(image_files[0]) as img:
            img_w, img_h = img.size
        l, t, r, b = trimmer.last_trim_rect
        save_name_area_config(config_path, (l / img_w, t / img_h, r / img_w, b / img_h))
        self.log_message("✓ 氏名欄の位置を保存しました")

    def _wizard_step_id_area(self, boxed_folder, results_data_folder):
        """ウィザードStep: 学籍番号OCRの実施可否と、学籍番号欄の位置指定。

        学籍番号OCRを実施するかどうかは、このステップだけで決める
        （集計実行時には聞かない・トップ画面にも表示しない）。
        位置が既に保存済みならOCR実施として自動スキップする。
        """
        from id_area_config import ID_AREA_CONFIG_FILE, load_id_area_config
        config_path = str(results_data_folder / ID_AREA_CONFIG_FILE)
        if load_id_area_config(config_path) is not None:
            self.log_message("✓ 学籍番号欄は設定済みです — スキップします")
            self.student_id_ocr_enabled.set(True)
            return
        if not messagebox.askyesno(
            "学籍番号欄指定",
            "学籍番号をOCRで読み取りますか？（実験的機能・要確認）\n\n"
            "ここでは読み取り位置を1回選ぶだけで、実際の読み取りは\n"
            "集計実行時に行います。（後からでも設定できます）",
        ):
            self.log_message("学籍番号欄指定: 該当なし（スキップ）")
            self._warn_if_multi_page_needs_student_id()
            self.student_id_ocr_enabled.set(False)
            return
        from student_id_ocr import ensure_id_area_config
        config = ensure_id_area_config(
            str(boxed_folder), parent=self.root, config_path=config_path,
            default_digit_count=int(self.skip_questions.get() or 8),
        )
        if config:
            self.log_message("✓ 学籍番号欄の位置を保存しました")
            self.student_id_ocr_enabled.set(True)
        else:
            self.log_message("学籍番号欄指定: 該当なし（スキップ）")
            self._warn_if_multi_page_needs_student_id()
            self.student_id_ocr_enabled.set(False)

    def _sync_student_id_ocr_enabled(self, results_data_folder):
        """学籍番号欄が設定済みかどうかで、学籍番号OCRの実施可否を自動的に決める。"""
        from id_area_config import ID_AREA_CONFIG_FILE, load_id_area_config
        config_path = str(Path(results_data_folder) / ID_AREA_CONFIG_FILE)
        self.student_id_ocr_enabled.set(load_id_area_config(config_path) is not None)

    def _warn_if_multi_page_needs_student_id(self):
        """複数ページ案件で学籍番号OCRを使わない場合、全ページ集計が
        使えなくなることを警告する（選択自体は止めない）。"""
        from multi_page_merger import resolve_multi_page_project_folder
        workspace = self.image_folder_path.get()
        if not workspace:
            return
        project_folder = resolve_multi_page_project_folder(workspace)
        if project_folder == str(Path(workspace)):
            return  # 単一ページ案件
        messagebox.showwarning(
            "全ページ集計が使えなくなります",
            "学籍番号OCRを設定しないと、複数ページの答案を学籍番号で\n"
            "1人分にまとめる「全ページ集計」が使えなくなります。\n\n"
            "後から「採点準備をやり直す」で設定を追加できます。",
        )

    def setup_descriptive(self, skip_existing_prompt=False):
        """採点領域の初期設定

        既存設定がある場合は「設定を続行 / 初期化 / キャンセル」の
        3択ダイアログを表示する。初期化を選ぶと _reset_descriptive_data
        を呼び設定ファイルを削除後、メイン画面に戻る。
        """
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return

        boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
        if not boxed_folder.exists():
            messagebox.showerror(
                "エラー",
                f"補正済み画像フォルダが存在しません。\n"
                f"Step 1（画像準備）を先に実行してください。"
            )
            return

        results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
        config_path = str(results_data_folder / "descriptive_config.json")

        # --- 既存設定がある場合: 続行 / 初期化 / キャンセル ---
        if Path(config_path).exists() and not skip_existing_prompt:
            choice = self._ask_descriptive_setup_action()
            if choice == "reset":
                self._reset_descriptive_data()
                return
            elif choice == "cancel":
                return
            # choice == "continue" → 統合ウィンドウで既存設定を読み込んで続行

        try:
            from descriptive_scorer import setup_descriptive_regions_integrated
            from multi_page_merger import get_exam_page_for_workspace
            exam_page = get_exam_page_for_workspace(self.image_folder_path.get())
            config = setup_descriptive_regions_integrated(
                str(boxed_folder), config_path, parent=self.root, exam_page=exam_page
            )
            if config:
                self.log_message(f"✓ 初期設定完了: {len(config['questions'])}問")
                from multi_page_merger import publish_shared_layout_settings
                shared_files = publish_shared_layout_settings(self.image_folder_path.get())
                if shared_files:
                    self.log_message(
                        "✓ 学籍番号欄・氏名欄・解答欄の設定を全ページ共通として保存しました"
                    )
                self._update_descriptive_status()
                self._save_session_state()
                self._update_step_availability()
            else:
                self.log_message("初期設定がキャンセルされました。")
        except Exception as e:
            self.log_message(f"初期設定エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            messagebox.showerror("エラー", f"初期設定中にエラーが発生しました:\n{e}")

    def _ask_descriptive_setup_action(self):
        """初期設定開始時の3択ダイアログ。

        Returns:
            "continue": 設定を続行（問題を追加）
            "reset": 既存設定を初期化
            "cancel": 何もしない
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("初期設定")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        result = {"value": "cancel"}

        tk.Label(
            dialog,
            text="既に初期設定が存在します。\n最初に、どの操作を行うか選んでください。",
            font=(UI_FONT, get_ui_font_size(10)),
            justify=tk.LEFT, padx=20, pady=15,
        ).pack(fill=tk.X)

        btn_frame = tk.Frame(dialog, padx=20, pady=10)
        btn_frame.pack(fill=tk.X)

        def choose(val):
            result["value"] = val
            dialog.destroy()

        tk.Button(
            btn_frame, text="既存の設定を使って続ける",
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
                "記述問題の採点領域設定が見つかりません。\n"
                "先に「初期設定」を実行してください。"
            )
            return

        if not boxed_folder.exists():
            messagebox.showerror(
                "エラー",
                "補正済み画像フォルダが存在しません。\n"
                "Step 1（画像準備）を先に実行してください。"
            )
            return

        try:
            from descriptive_scorer import load_descriptive_config, DescriptiveScorerGUI
            config = load_descriptive_config(str(config_path))
            if not config:
                messagebox.showerror("エラー", "初期設定ファイルの読み込みに失敗しました。")
                return

            # 00_Processing が元画像そのものなので高解像度パス不要
            orig_folder = None

            # クリーン画像フォルダ（枠描画なし）を優先使用
            # 存在しない場合はboxedフォルダにフォールバック
            image_folder_for_desc = str(clean_folder) if clean_folder.exists() else str(boxed_folder)

            scorer = DescriptiveScorerGUI(
                parent=self.root,
                config=config,
                image_folder=image_folder_for_desc,
                scores_save_path=str(scores_path),
                original_image_folder=orig_folder,
                exam_page=self._current_exam_page(),
            )
            result = scorer.run()

            if result is not None:
                self.log_message(f"✓ 採点完了: {len(result)}枚")
                self._update_descriptive_status()
                self._save_session_state()
                # 複数ページ案件のトップ画面（ページ別進捗チップ・工程マーカー）に
                # 反映されるよう更新する（呼び忘れると採点済みなのに反映されない）。
                self._update_step_availability()
            else:
                self.log_message("採点がキャンセルされました。")
        except Exception as e:
            self.log_message(f"採点エラー: {e}")
            import traceback
            self.log_message(traceback.format_exc())
            messagebox.showerror("エラー", f"採点中にエラーが発生しました:\n{e}")

    def validate_inputs(self):
        """入力値の検証"""
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return False

        if not Path(self.image_folder_path.get()).exists():
            messagebox.showerror("エラー", "画像フォルダが存在しません")
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
            self._btn_step2_more,
            self._btn_run_scoring,
            self._btn_run_summary,
            self.desc_setup_btn,
            self.desc_scoring_btn,
            self._btn_desc_review,
            # データソース選択ボタンも無効化（処理中パス変更防止）
            self._btn_select_folder,
        ]
        if busy:
            self._cancel_event.clear()
            self._progress_bar["value"] = 0
            self._progress_bar.pack(fill=tk.X)
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

    def run_scoring(self):
        """採点処理を実行"""
        if self._processing:
            return
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return
        self._run_scoring_descriptive_only()
    
    def run_summary_generation(self):
        """サマリー生成処理を実行"""
        if self._processing:
            return
        if not self.image_folder_path.get():
            messagebox.showerror("エラー", "画像フォルダを選択してください")
            return
        self._run_summary_generation_descriptive_only()

    def _run_student_id_ocr_flow(self, image_folder, name_images=None):
        """学籍番号OCR: 矩形選択→OCR→名簿読込(任意)→確認GUI。

        チェックボックスがOFFの場合は何もしない。normal/記述のみモード
        どちらからも呼べるよう、対象フォルダの存在チェックも含めて自己完結させる。

        Args:
            name_images: 呼び出し元が既にトリミング済みの氏名欄画像
                {ファイル名: パス}（「氏名画像を集計シートに表示する」機能で
                生成されるものを流用する）。確認画面で学籍番号欄画像と並べて
                表示するために使う。Noneまたは対応ファイルが無ければ、
                従来通り学籍番号欄画像のみ表示する。

        Returns:
            (aborted, student_id_result, roster, trimmer) のタプル。
            roster は {学籍番号: 氏名} の dict（名簿の並び順を保持）で、
            名簿を使わなかった場合は None。
            aborted=True の場合、呼び出し元は処理全体を中断する。
        """
        if not self.student_id_ocr_enabled.get():
            return False, None, None, None

        boxed_folder = Path(image_folder) / RESULTS_FOLDER / BOXED_FOLDER
        if not boxed_folder.exists():
            messagebox.showerror(
                "エラー",
                f"補正済み画像フォルダが存在しません:\n{boxed_folder}\n\n"
                "Step 1（OMR認識）を先に実行してください。"
            )
            return True, None, None, None

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
                    return True, None, None, None
                return False, None, None, None

            self.log_message(f"✓ 学籍番号OCR完了: {len(ocr_results)}枚")

            # 氏名欄画像（呼び出し元で既にトリミング済みなら）を確認画面に渡し、
            # 学籍番号欄の画像と並べて見比べられるようにする。
            if name_images:
                matched = 0
                for fname in ocr_results:
                    path = name_images.get(fname)
                    if path:
                        ocr_results[fname]['name_thumbnail_path'] = path
                        matched += 1
                if matched:
                    self.log_message(f"✓ 氏名欄画像を確認画面に反映: {matched}枚")
                else:
                    self.log_message("ℹ 氏名欄画像とファイル名が一致しなかったため、確認画面には学籍番号欄画像のみ表示します")
            else:
                self.log_message("ℹ 氏名欄画像が無いため、確認画面には学籍番号欄画像のみ表示します")

            from roster_config import load_roster_config
            from multi_page_merger import resolve_roster_config_path
            roster_config_path = resolve_roster_config_path(image_folder)
            roster = load_roster_config(roster_config_path)
            if roster is not None:
                self.log_message(f"✓ 名簿読込（Step1で設定済み）: {len(roster)}件")
            else:
                from roster_loader import select_roster_gui
                roster = select_roster_gui(parent=self.root)
                if roster:
                    self.log_message(f"✓ 名簿読込: {len(roster)}件")

            from student_id_review_gui import StudentIdReviewGUI
            review = StudentIdReviewGUI(
                self.root, ocr_results, roster, exam_page=self._current_exam_page(image_folder),
            )
            student_id_result = review.run()
            self.log_message(f"✓ 学籍番号OCR確認完了: {len(student_id_result)}枚")
            return False, student_id_result, roster, ocr_trimmer

        except Exception as e:
            self.log_message(f"学籍番号OCRエラー: {e}")
            if not messagebox.askyesno(
                "エラー",
                f"学籍番号OCR中にエラーが発生しました:\n{e}\n\n"
                "OCRなしでサマリー生成を続行しますか？"
            ):
                return True, None, None, None
            return False, None, None, None

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
                missing.append("・採点領域の初期設定（descriptive_config.json）")
            if not desc_scores_path.exists():
                missing.append("・採点結果（descriptive_scores.json）")
            messagebox.showerror(
                "エラー",
                "以下のデータが見つかりません:\n\n"
                + "\n".join(missing) + "\n\n"
                "先に「⚙ 初期設定」と「✏ 採点を開始」を実行してください。"
            )
            return

        # 採点完了チェック
        is_complete, unscored, total_img, detail = self._check_descriptive_completeness()
        if not is_complete and total_img > 0:
            detail_text = "\n".join(detail) if detail else ""
            if not messagebox.askyesno(
                "採点が未完了です",
                f"採点が完了していない生徒が {unscored}名 います。\n\n"
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
                    from name_trimmer import NameTrimmer, get_image_files
                    from name_area_config import NAME_AREA_CONFIG_FILE, load_name_area_config, resolve_rect_for_image
                    name_area_config_path = results_data / NAME_AREA_CONFIG_FILE
                    preset_rect = None
                    rect_frac = load_name_area_config(str(name_area_config_path))
                    if rect_frac is not None:
                        image_files = get_image_files(str(boxed_folder))
                        if image_files:
                            with Image.open(image_files[0]) as img:
                                img_w, img_h = img.size
                            preset_rect = resolve_rect_for_image(rect_frac, img_w, img_h)
                    trimmer = NameTrimmer()
                    name_images = trimmer.run(str(boxed_folder), parent=self.root, preset_rect=preset_rect)
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
        aborted, student_id_result, roster, id_ocr_trimmer = self._run_student_id_ocr_flow(
            self.image_folder_path.get(), name_images=name_images,
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
            args=(params, name_images, student_id_result, roster),
            daemon=True,
        )
        thread.start()

    def _write_back_student_ids_to_manifest(self, image_folder, student_id_result):
        """学籍番号OCR確認結果を、複数ページ案件のAnswerPageへ反映する。

        ワークスペース内の画像ファイル名は image_id + 拡張子 なので、
        student_id_result のキー（ファイル名）から拡張子を除いた文字列が
        そのまま AnswerPage.image_id と一致する。単一ページ案件では何もしない。
        """
        if not student_id_result:
            return
        from multi_page_merger import (
            MULTI_PAGE_MANIFEST_FILE, audit_answer_pages, get_exam_page_for_workspace,
            load_multi_page_manifest, resolve_multi_page_project_folder,
            save_multi_page_manifest,
        )
        exam_page = get_exam_page_for_workspace(image_folder)
        if exam_page is None:
            return
        project_folder = resolve_multi_page_project_folder(image_folder)
        manifest_path = (
            Path(project_folder) / RESULTS_FOLDER / RESULTS_DATA_FOLDER / MULTI_PAGE_MANIFEST_FILE
        )
        if not manifest_path.is_file():
            return
        batches, audit = load_multi_page_manifest(str(manifest_path))
        by_stem = {Path(fname).stem: info for fname, info in student_id_result.items()}
        changed = False
        for batch in batches:
            for answer in batch.answer_pages:
                if answer.exam_page != exam_page:
                    continue
                info = by_stem.get(answer.image_id)
                if info and info.get('text'):
                    answer.student_id = info['text']
                    changed = True
        if not changed:
            return
        new_audit = audit_answer_pages(
            [a for b in batches for a in b.answer_pages], expected_pages=audit.exam_pages,
        )
        new_audit.shared_layout = audit.shared_layout
        new_audit.active_exam_page = audit.active_exam_page
        save_multi_page_manifest(batches, new_audit, str(manifest_path))

    def _run_summary_descriptive_only_thread(self, params, name_images=None, student_id_result=None, roster=None):
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
                    roster=roster,
                    output_base_folder=None,
                )
            finally:
                self._detach_gui_log_handler(gui_handler, suppressed)

            if result and result.get("success"):
                self.last_results_folder = str(final_report)
                self.root.after(0, lambda: self.open_results_btn.config(state=tk.NORMAL))

                from multi_page_merger import (
                    generate_combined_multi_page_summary,
                    resolve_multi_page_project_folder,
                )
                project_folder = resolve_multi_page_project_folder(params['image_folder'])
                self._write_back_student_ids_to_manifest(params['image_folder'], student_id_result)
                combined = generate_combined_multi_page_summary(project_folder)
                if combined.get('success'):
                    combined_note = (
                        f"\n\n【全ページ統合集計】\n"
                        f"・{Path(combined['output_path']).name}\n"
                        f"・統合人数: {combined['student_count']}名"
                    )
                    self.last_combined_summary_folder = str(Path(combined['output_path']).parent)
                    self.root.after(0, lambda: self.open_combined_summary_btn.config(state=tk.NORMAL))
                elif combined.get('pending_pages'):
                    pages = "、".join(str(page) for page in combined['pending_pages'])
                    combined_note = (
                        f"\n\n全ページ統合集計は、ページ {pages} の集計完了後に自動生成されます。"
                    )
                elif project_folder != params['image_folder']:
                    combined_note = f"\n\n全ページ統合集計を生成できませんでした:\n{combined.get('error', '不明なエラー')}"
                else:
                    combined_note = ""

                stats = result["stats"]
                generated_files = [
                    f"・{STUDENT_SUMMARY_FILE} (学生別得点)",
                    f"・{EXAM_SUMMARY_FILE} (試験統計)",
                ]
                if result.get("scored_pdf_path"):
                    generated_files.append(
                        f"・{Path(result['scored_pdf_path']).name} (採点済み答案の統合PDF)"
                    )
                elif result.get("scored_pdf_error"):
                    generated_files.append(
                        "・（採点済み答案の統合PDFは生成できませんでした — "
                        f"{result['scored_pdf_error']}）"
                    )
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
                    + "\n".join(generated_files)
                    + f"{combined_note}"
                )
                self.root.after(0, lambda: messagebox.showinfo("完了", summary))
                self.root.after(0, self._update_multi_page_dashboard)
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



# 旧名称を利用する外部コード・テスト向けの後方互換エイリアス。
SaitenSamuraiGUI = MarunosukeGUI
Mark2GUI = MarunosukeGUI
