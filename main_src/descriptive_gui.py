#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descriptive_gui.py — 記述問題採点 GUI モジュール

descriptive_scorer.py から分離された GUI クラス群。
"""

import json
import logging
import os
import shutil
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Callable

import cv2
import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageFont

from name_trimmer import select_region_on_image, get_image_files
from constants import (
    get_app_temp_dir, atomic_json_save, load_json_safe, open_in_default_viewer,
    get_ui_font_family, get_ui_font_size, fit_window_to_content,
)

# 日本語UIフォント（Windows: Yu Gothic UI, Mac: Hiragino Sans）
UI_FONT = get_ui_font_family()
from descriptive_scorer import (
    DESCRIPTIVE_CONFIG_FILE, DESCRIPTIVE_SCORES_FILE, DESCRIPTIVE_ANNOTATIONS_FILE,
    load_descriptive_config, save_descriptive_config,
    load_descriptive_scores, save_descriptive_scores,
    load_descriptive_annotations, save_descriptive_annotations,
    update_comment_history,
    save_total_display_config,
    _calculate_marker_default_region,
    trim_descriptive_regions,
)
from descriptive_renderer import (
    _get_font, DEFAULT_TOTAL_BOX_WIDTH, DEFAULT_TOTAL_BOX_HEIGHT,
)

logger = logging.getLogger(__name__)


# キーボード採点で対応する最大配点 (0-9)
MAX_KEYBOARD_SCORE = 9


# オーバーレイ色定義（_create_overlay_image と共有）
_OVERLAY_COLORS_RGB = [
    (255, 100, 100), (100, 100, 255), (100, 200, 100),
    (255, 200, 50), (200, 100, 255), (255, 150, 50), (50, 200, 200),
]


def is_grading_space_key(event, platform_name: Optional[str] = None) -> bool:
    """答案送りとして扱う、実際のスペースキーイベントか判定する。"""
    if event.keysym != "space":
        return False
    platform_name = platform_name or sys.platform
    if platform_name == "darwin":
        # macOS virtual key code: Space=49, JIS Eisu=102, JIS Kana=104。
        # Aqua Tk がJISキーを keysym/char とも space として通知しても区別できる。
        return getattr(event, "keycode", None) == 49
    return getattr(event, "char", "") == " "


def _ask_three_way_japanese(
    title: str,
    message: str,
    parent,
    yes_text: str = "はい",
    no_text: str = "いいえ",
    cancel_text: str = "キャンセル",
):
    """OSロケールに依存しない日本語3択ダイアログを表示する。"""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)
    result = {"value": None}

    body = tk.Frame(dialog, padx=20, pady=16)
    body.pack(fill=tk.BOTH, expand=True)
    tk.Label(
        body, text=message, justify=tk.LEFT, wraplength=460,
        font=(UI_FONT, get_ui_font_size(9)),
    ).pack(fill=tk.X, pady=(0, 14))

    def _choose(value):
        result["value"] = value
        dialog.destroy()

    buttons = tk.Frame(body)
    buttons.pack(fill=tk.X)
    tk.Button(
        buttons, text=yes_text, command=lambda: _choose(True),
        font=(UI_FONT, get_ui_font_size(9), "bold"),
        bg="#1976D2", fg="black", activeforeground="black", width=14,
    ).pack(fill=tk.X, pady=2)
    tk.Button(
        buttons, text=no_text, command=lambda: _choose(False),
        font=(UI_FONT, get_ui_font_size(9)),
        fg="black", activeforeground="black", width=14,
    ).pack(fill=tk.X, pady=2)
    tk.Button(
        buttons, text=cancel_text, command=lambda: _choose(None),
        font=(UI_FONT, get_ui_font_size(9)),
        fg="black", activeforeground="black", width=14,
    ).pack(fill=tk.X, pady=2)

    dialog.protocol("WM_DELETE_WINDOW", lambda: _choose(None))
    dialog.bind("<Escape>", lambda _event: _choose(None))
    fit_window_to_content(dialog, min_width=400, min_height=230)
    dialog.grab_set()
    dialog.wait_window()
    return result["value"]


# ============================================================
# 領域設定GUI
# ============================================================

def setup_descriptive_regions(
    image_folder: str,
    config_save_path: str,
    parent: Optional[tk.Tk] = None,
) -> Optional[dict]:
    """
    記述問題の領域設定を対話的に行う。

    select_region_on_image() を繰り返し呼び、各問題の
    領域と配点を設定する。問題数に上限はない。
    2問目以降は既に設定した領域を画像上にオーバーレイ表示する。

    Args:
        image_folder: 補正済み画像 (00_Processing) フォルダ
        config_save_path: descriptive_config.json の保存先パス
        parent: 親ウィンドウ

    Returns:
        config dict。キャンセル時は None。
    """
    image_files = get_image_files(image_folder)
    if not image_files:
        if parent:
            messagebox.showerror(
                "エラー",
                f"補正済み画像が見つかりません:\n{image_folder}\n\n"
                "Step 1 (OMR認識) を先に実行してください。",
                parent=parent,
            )
        return None

    first_image = image_files[0]

    # --- 既存設定の読み込み（2回目以降の再開対応）---
    existing_config = load_descriptive_config(config_save_path)
    if existing_config and existing_config.get("questions"):
        config = existing_config
        # total_display_region が無い場合は補完
        config.setdefault("total_display_region", None)
    else:
        config = {"version": 2, "questions": [], "total_display_region": None}

    question_count = len(config["questions"])

    while True:
        question_count += 1

        # 既存領域を描画した一時画像を作成（既存設定からの再開時も含む）
        display_image = first_image
        temp_overlay_path = None
        if config["questions"]:
            temp_overlay_path = _create_overlay_image(first_image, config["questions"])
            if temp_overlay_path:
                display_image = temp_overlay_path

        # --- 領域選択 ---
        region = select_region_on_image(
            display_image,
            parent=parent,
            title=f"問題 {question_count} — 領域をドラッグで選択してください",
            label_text=f"問題{question_count}",
            instruction_text=(
                f"問題 {question_count} の\n"
                "解答エリアを\n"
                "ドラッグで囲んで\n"
                "ください。\n\n"
                + (f"設定済み: {len(config['questions'])}問\n（色付き枠で表示中）" if config["questions"] else "")
            ),
        )

        # 一時ファイルを削除
        if temp_overlay_path:
            try:
                Path(temp_overlay_path).unlink(missing_ok=True)
            except Exception:
                pass

        if region is None:
            # キャンセル: 1問も設定していなければ全体キャンセル
            if not config["questions"]:
                return None
            break  # 既に1問以上ある → 領域選択をスキップして終了

        # --- 問題情報ダイアログ ---
        q_info = _ask_question_info(parent, question_count)
        if q_info is None:
            # ダイアログキャンセル → この問題を追加せず終了
            break

        config["questions"].append({
            "id": f"D{question_count}",
            "name": q_info["name"],
            "max_score": q_info["max_score"],
            "region": list(region),
            "rubric_memo": q_info.get("rubric_memo", ""),
        })

        # --- 次の問題を追加するか? ---
        add_more = _ask_add_more(parent, question_count, q_info["name"])

        if not add_more:
            break

    if not config["questions"]:
        return None

    # 合計点表示位置は Step2 の「合計点位置設定」ボタンで別途設定するため、
    # ここでは聞かない。

    # --- 保存 ---
    config["version"] = 2
    save_descriptive_config(config_save_path, config)
    return config


# --- 内部ヘルパー: 追加確認ダイアログ ---


def _ask_add_more(
    parent: Optional[tk.Tk],
    question_number: int,
    question_name: str,
) -> bool:
    """
    記述問題の追加確認を専用ボタンラベルで行うカスタムダイアログ。

    「問題を追加する」「終了する」ボタンを表示し、結果を bool で返す。
    """
    if parent is None:
        return False

    result = [False]

    dialog = tk.Toplevel(parent)
    dialog.title("問題の追加")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    frame = tk.Frame(dialog, padx=25, pady=20)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frame,
        text=f"問題{question_number}「{question_name}」を登録しました。",
        font=(UI_FONT, get_ui_font_size(10)),
        wraplength=320,
    ).pack(pady=(0, 15))

    btn_frame = tk.Frame(frame)
    btn_frame.pack(fill=tk.X)

    def _add():
        result[0] = True
        dialog.destroy()

    def _finish():
        result[0] = False
        dialog.destroy()

    tk.Button(
        btn_frame, text="＋ 問題を追加する", command=_add,
        font=(UI_FONT, get_ui_font_size(10), "bold"), bg="#81C784", fg="black",
        width=16, height=2, relief=tk.FLAT, cursor="hand2",
    ).pack(side=tk.LEFT, padx=(0, 8))

    tk.Button(
        btn_frame, text="終了する", command=_finish,
        font=(UI_FONT, get_ui_font_size(10)), bg="#E0E0E0", fg="black",
        width=16, height=2, relief=tk.FLAT, cursor="hand2",
    ).pack(side=tk.LEFT)

    dialog.protocol("WM_DELETE_WINDOW", _finish)

    # ダイアログを中央に配置
    dialog.update_idletasks()
    w = dialog.winfo_width()
    h = dialog.winfo_height()
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
    dialog.geometry(f"+{x}+{y}")

    parent.wait_window(dialog)
    return result[0]


# --- 内部ヘルパー: 既存領域オーバーレイ画像生成 ---


def _create_overlay_image(base_image_path: str, questions: list) -> Optional[str]:
    """
    既に設定済みの領域を色付き矩形で描画した一時画像を作成する。
    
    各問題ごとに異なる色で半透明矩形とラベルを描画する。
    
    Returns:
        一時画像ファイルのパス。失敗時は None。
    """
    OVERLAY_COLORS = [
        (255, 100, 100, 60),   # 赤
        (100, 100, 255, 60),   # 青
        (100, 200, 100, 60),   # 緑
        (255, 200, 50, 60),    # 黄
        (200, 100, 255, 60),   # 紫
        (255, 150, 50, 60),    # オレンジ
        (50, 200, 200, 60),    # シアン
    ]
    BORDER_COLORS = [
        (220, 50, 50),
        (50, 50, 220),
        (50, 160, 50),
        (200, 160, 0),
        (160, 50, 220),
        (220, 120, 0),
        (0, 160, 160),
    ]
    
    try:
        img = Image.open(base_image_path).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        font = _get_font(12)
        
        for i, q in enumerate(questions):
            region = q["region"]
            color = OVERLAY_COLORS[i % len(OVERLAY_COLORS)]
            border = BORDER_COLORS[i % len(BORDER_COLORS)]
            left, top, right, bottom = int(region[0]), int(region[1]), int(region[2]), int(region[3])
            
            # 半透明塗りつぶし
            draw.rectangle([left, top, right, bottom], fill=color, outline=border, width=2)
            
            # ラベル
            label = f"{q['id']}: {q['name']}"
            draw.text((left + 3, top + 2), label, font=font, fill=border + (255,))
        
        result = Image.alpha_composite(img, overlay).convert("RGB")
        
        # 一時ファイルに保存
        import tempfile
        _app_temp = get_app_temp_dir(str(Path(base_image_path).parent.parent.parent))
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="desc_overlay_", dir=_app_temp)
        import os
        os.close(fd)
        result.save(tmp_path, quality=95)
        img.close()
        result.close()
        return tmp_path
    except Exception as e:
        logger.error("オーバーレイ画像作成エラー: %s", e)
        return None


# --- 合計点表示位置のドラッグ選択 ---

# ============================================================
# 統合設定ウィンドウ（Phase 2A）
# ============================================================


class IntegratedDescriptiveSetup:
    """記述問題の領域と設問情報を1画面で設定する統合ウィンドウ。

    左: 答案画像Canvas（ドラッグで領域選択）
    右: 設問テーブル（Treeview + 直接編集）

    kaizen.md Phase 2A に対応。
    """

    # Canvas 表示サイズ制限（ビューポートサイズ。ズームで実際の描画内容はこれより大きくなりスクロールする）
    # 拡大縮小・移動ボタンを画像下部から右側の専用カラムに移したことで
    # 空いた縦方向のスペース分、高さの上限を広げている。
    _MAX_CANVAS_W = 620
    _MAX_CANVAS_H = 820

    # ズーム設定
    _MIN_ZOOM = 1.0
    _MAX_ZOOM = 8.0
    _ZOOM_STEP = 1.25

    def __init__(self, parent, image_folder: str, config_save_path: str, exam_page: Optional[int] = None):
        self.parent = parent
        self.image_folder = image_folder
        self.config_save_path = config_save_path
        self.exam_page = exam_page  # 複数ページ案件のみ設定される
        self.result_config = None  # 完了時に設定が入る

        # 画像ファイル取得
        self._image_files = get_image_files(image_folder)
        if not self._image_files:
            messagebox.showerror(
                "エラー",
                f"補正済み画像が見つかりません:\n{image_folder}\n\n"
                "Step 1 (OMR認識) を先に実行してください。",
                parent=parent,
            )
            return

        self._base_image_path = self._image_files[0]

        # 既存設定読み込み
        existing = load_descriptive_config(config_save_path)
        if existing and existing.get("questions"):
            self._questions = list(existing["questions"])
        else:
            self._questions = []

        # 画像読み込み・表示スケール計算
        # zoom=1.0の時に画像全体がビューポート(_MAX_CANVAS_W×_MAX_CANVAS_H)に収まる基準スケール。
        # ズームすると表示内容はビューポートより大きくなり、スクロールバー/ホイールで移動できる。
        self._orig_img = Image.open(self._base_image_path).convert("RGB")
        self._orig_w, self._orig_h = self._orig_img.size
        self._base_scale = min(
            self._MAX_CANVAS_W / self._orig_w, self._MAX_CANVAS_H / self._orig_h, 1.0,
        )
        self._zoom = 1.0
        self._viewport_w = max(1, int(self._orig_w * self._base_scale))
        self._viewport_h = max(1, int(self._orig_h * self._base_scale))

        # ウィンドウ構築
        self.win = tk.Toplevel(parent)
        title = "📝 問題の設定"
        if self.exam_page is not None:
            title += f"（試験ページ {self.exam_page}）"
        self.win.title(title)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.focus_set()
        self.win.configure(bg="#F5F7FA")

        self._photo_refs = []
        self._overlay_img = None  # 元画像解像度で合成済みのオーバーレイ画像(ズーム再描画で使い回す)
        self._rect_ids = {}  # question_id -> canvas rect id
        self._drag_state = {"active": False, "start_x": 0, "start_y": 0, "rect_id": None}

        self._build_gui()
        self._redraw_overlay()
        self._refresh_table()

        # 実際に必要なサイズをウィジェット構築後に計算して反映する。
        # 拡大縮小・移動ボタンを追加した分、事前計算の固定値では
        # ウィンドウが小さすぎてボタンが隠れることがあったため。
        self.win.update_idletasks()
        req_w = self.win.winfo_reqwidth()
        req_h = self.win.winfo_reqheight()
        self.win.geometry(f"{req_w}x{req_h}")
        self.win.minsize(req_w, req_h)

        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.win.wait_window()

    def _build_gui(self):
        BG = "#F5F7FA"
        if self.exam_page is not None:
            # 複数ページ案件では、今どのページの設定をしているかを
            # ポップアップに頼らず常設バナーで示す。
            page_banner = tk.Frame(self.win, bg="#E8EAF6", padx=10, pady=4)
            page_banner.pack(fill=tk.X)
            tk.Label(
                page_banner,
                text=f"📄 試験ページ {self.exam_page} の設定です",
                bg="#E8EAF6", fg="#283593",
                font=(UI_FONT, get_ui_font_size(9), "bold"),
            ).pack(anchor=tk.W)

        main = tk.Frame(self.win, bg=BG, padx=8, pady=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ===== 左: Canvas =====
        left = tk.Frame(main, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH)

        tk.Label(left, text="答案画像（ドラッグで領域を選択）",
                 font=(UI_FONT, get_ui_font_size(10), "bold"), bg=BG, fg="#333").pack(anchor=tk.W, pady=(0, 3))

        canvas_frame = tk.Frame(left, bg=BG)
        canvas_frame.pack()
        h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        v_scroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        self._canvas = tk.Canvas(
            canvas_frame, width=self._viewport_w, height=self._viewport_h,
            bg="white", highlightthickness=1, highlightbackground="#999",
            cursor="crosshair",
            xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set,
        )
        h_scroll.config(command=self._canvas.xview)
        v_scroll.config(command=self._canvas.yview)
        self._canvas.grid(row=0, column=0)
        v_scroll.grid(row=0, column=1, sticky='ns')
        h_scroll.grid(row=1, column=0, sticky='ew')

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

        tk.Label(left, text="💡 ドラッグで新しい記述領域を追加できます",
                 font=(UI_FONT, get_ui_font_size(8)), bg=BG, fg="#777").pack(anchor=tk.W, pady=(3, 0))

        # ===== 中央: 拡大縮小・移動（画像を縦に大きく見せるため画像右側の縦カラムに配置） =====
        controls = tk.Frame(main, bg=BG)
        controls.pack(side=tk.LEFT, fill=tk.Y, padx=10)

        zoom_box = tk.Frame(controls, bg=BG)
        zoom_box.pack(side=tk.TOP, pady=(0, 16))
        tk.Label(zoom_box, text="拡大縮小", font=(UI_FONT, get_ui_font_size(8)), bg=BG, fg="#555").pack()
        tk.Button(
            zoom_box, text="＋", width=4, command=lambda: self._zoom_by(self._ZOOM_STEP),
        ).pack(pady=(4, 2))
        self._zoom_label = tk.Label(zoom_box, text="100%", width=6, bg=BG)
        self._zoom_label.pack()
        tk.Button(
            zoom_box, text="－", width=4, command=lambda: self._zoom_by(1 / self._ZOOM_STEP),
        ).pack(pady=(2, 0))

        pan_box = tk.Frame(controls, bg=BG)
        pan_box.pack(side=tk.TOP)
        tk.Label(
            pan_box, text="移動\n（ホイールでも可\n／Shiftで左右）",
            font=(UI_FONT, get_ui_font_size(8)), bg=BG, fg="#555", justify=tk.CENTER,
        ).pack(pady=(0, 4))
        pan_grid = tk.Frame(pan_box, bg=BG)
        pan_grid.pack()
        tk.Button(pan_grid, text="▲", width=3, command=lambda: self._pan(dy_units=-2)).grid(row=0, column=1)
        tk.Button(pan_grid, text="◀", width=3, command=lambda: self._pan(dx_units=-2)).grid(row=1, column=0)
        tk.Button(pan_grid, text="▶", width=3, command=lambda: self._pan(dx_units=2)).grid(row=1, column=2)
        tk.Button(pan_grid, text="▼", width=3, command=lambda: self._pan(dy_units=2)).grid(row=2, column=1)

        # ===== 右: テーブル + 操作 =====
        right = tk.Frame(main, bg=BG, padx=(10))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(right, text="設問一覧",
                 font=(UI_FONT, get_ui_font_size(11), "bold"), bg=BG, fg="#333").pack(anchor=tk.W, pady=(0, 5))

        # Treeview（問題リスト）
        # 問題数は少ない想定なので、行の高さを広めに取り、配点入力時に
        # 数字が行からはみ出さないようにする。専用スタイル名にして、
        # 他画面のTreeviewへ影響しないようにする。
        style = ttk.Style(self.win)
        row_font = (UI_FONT, get_ui_font_size(11))
        style.configure("Descriptive.Treeview", rowheight=36, font=row_font)
        style.configure("Descriptive.Treeview.Heading", font=(UI_FONT, get_ui_font_size(10), "bold"))

        cols = ("id", "name", "score")
        self._tree = ttk.Treeview(right, columns=cols, show="headings", height=15,
                                  selectmode="browse", style="Descriptive.Treeview")
        self._tree.heading("id", text="#")
        self._tree.heading("name", text="問題名")
        self._tree.heading("score", text="配点（ダブルクリックで編集）")
        self._tree.column("id", width=36, anchor="center")
        self._tree.column("name", width=100)
        self._tree.column("score", width=150, anchor="center")

        tree_scroll = tk.Scrollbar(right, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=tree_scroll.set)

        self._tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # ダブルクリックでセル編集
        self._tree.bind("<Double-1>", self._on_tree_double_click)

        # 操作ボタン行
        btn_frame = tk.Frame(right, bg=BG)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        tk.Button(btn_frame, text="🗑 選択行を削除", command=self._delete_selected,
                  font=(UI_FONT, get_ui_font_size(9)), bg="#FFCDD2", relief=tk.FLAT,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(btn_frame, text="📋 採点基準メモ", command=self._edit_selected_rubric,
                  font=(UI_FONT, get_ui_font_size(9)), bg="#FFF3E0", relief=tk.FLAT,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(btn_frame, text="", bg=BG).pack(side=tk.LEFT, expand=True)  # spacer

        tk.Button(btn_frame, text="キャンセル", command=self._on_cancel,
                  font=(UI_FONT, get_ui_font_size(9)), bg="#E0E0E0", relief=tk.FLAT,
                  cursor="hand2").pack(side=tk.RIGHT, padx=(5, 0))

        tk.Button(btn_frame, text="✔ 設定を保存", command=self._on_save,
                  font=(UI_FONT, get_ui_font_size(10), "bold"), bg="#81C784", fg="black",
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.RIGHT)

        # ステータス
        self._status_label = tk.Label(right, text="", bg=BG, font=(UI_FONT, get_ui_font_size(9)), fg="#555")
        self._status_label.pack(anchor=tk.W, pady=(5, 0))
        self._update_status()

    # ─── ズーム・移動 ───

    def _total_scale(self) -> float:
        return self._base_scale * self._zoom

    def _zoom_by(self, factor: float):
        new_zoom = max(self._MIN_ZOOM, min(self._MAX_ZOOM, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        self._zoom = new_zoom
        self._render_canvas()

    def _pan(self, dx_units: int = 0, dy_units: int = 0):
        if dx_units:
            self._canvas.xview_scroll(dx_units, "units")
        if dy_units:
            self._canvas.yview_scroll(dy_units, "units")

    def _wheel_units(self, event) -> int:
        # Windows/Linuxではevent.deltaが120単位、macOSでは±1程度と環境依存のため、
        # 120で割った結果が0になる場合は符号だけで1単位動かす。
        units = int(-1 * (event.delta / 120))
        return units if units != 0 else (-1 if event.delta > 0 else 1)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(self._wheel_units(event), "units")

    def _on_shift_mousewheel(self, event):
        self._canvas.xview_scroll(self._wheel_units(event), "units")

    # ─── Canvas ドラッグ ───

    def _on_press(self, event):
        self._drag_state["active"] = True
        self._drag_state["start_x"] = self._canvas.canvasx(event.x)
        self._drag_state["start_y"] = self._canvas.canvasy(event.y)
        if self._drag_state.get("rect_id"):
            self._canvas.delete(self._drag_state["rect_id"])
        self._drag_state["rect_id"] = None

    def _on_drag(self, event):
        if not self._drag_state["active"]:
            return
        scale = self._total_scale()
        content_w = self._orig_w * scale
        content_h = self._orig_h * scale
        ex = max(0, min(content_w, self._canvas.canvasx(event.x)))
        ey = max(0, min(content_h, self._canvas.canvasy(event.y)))
        if self._drag_state["rect_id"]:
            self._canvas.coords(self._drag_state["rect_id"],
                                self._drag_state["start_x"], self._drag_state["start_y"], ex, ey)
        else:
            self._drag_state["rect_id"] = self._canvas.create_rectangle(
                self._drag_state["start_x"], self._drag_state["start_y"], ex, ey,
                outline="red", width=2, dash=(4, 2))

    def _on_release(self, event):
        if not self._drag_state["active"]:
            return
        self._drag_state["active"] = False

        scale = self._total_scale()
        content_w = self._orig_w * scale
        content_h = self._orig_h * scale
        ex = max(0, min(content_w, self._canvas.canvasx(event.x)))
        ey = max(0, min(content_h, self._canvas.canvasy(event.y)))
        sx, sy = self._drag_state["start_x"], self._drag_state["start_y"]

        # 最小サイズ判定
        if abs(ex - sx) < 10 or abs(ey - sy) < 10:
            if self._drag_state.get("rect_id"):
                self._canvas.delete(self._drag_state["rect_id"])
            return

        # 表示座標→元画像座標
        x1 = int(min(sx, ex) / scale)
        y1 = int(min(sy, ey) / scale)
        x2 = int(max(sx, ex) / scale)
        y2 = int(max(sy, ey) / scale)
        region = [x1, y1, x2, y2]

        # 問題ID生成（既存最大+1）
        next_num = self._next_question_number()
        qid = f"D{next_num}"
        q = {
            "id": qid,
            "name": f"問題{next_num}",
            "max_score": 0,
            "region": region,
            "rubric_memo": "",
        }
        self._questions.append(q)

        # 一時ドラッグ矩形を消して、正式オーバーレイ再描画
        if self._drag_state.get("rect_id"):
            self._canvas.delete(self._drag_state["rect_id"])

        self._redraw_overlay()
        self._refresh_table()
        self._update_status()

    def _next_question_number(self):
        """現在の問題リストから次の連続番号を算出する"""
        if not self._questions:
            return 1
        existing_nums = []
        for q in self._questions:
            try:
                n = int(q["id"].replace("D", ""))
                existing_nums.append(n)
            except (ValueError, KeyError):
                pass
        return max(existing_nums, default=0) + 1

    # ─── オーバーレイ描画 ───

    def _redraw_overlay(self):
        """設問領域を焼き込んだオーバーレイ画像(元解像度)を再構築し、Canvasに描画する。"""
        self._build_overlay_image()
        self._render_canvas()

    def _build_overlay_image(self):
        """ベース画像(元解像度)に色付き領域を合成し、self._overlay_imgに保持する。"""
        self._rect_ids.clear()

        img = self._orig_img.copy().convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = _get_font(14)

        # 答案画像の縁取り（画像の境界を明示）
        border_w = max(3, int(min(img.size) * 0.004))
        draw.rectangle(
            [0, 0, img.size[0] - 1, img.size[1] - 1],
            outline=(0, 0, 200, 200), width=border_w,
        )

        for i, q in enumerate(self._questions):
            region = q["region"]
            color_rgb = _OVERLAY_COLORS_RGB[i % len(_OVERLAY_COLORS_RGB)]
            fill_color = color_rgb + (60,)
            border_color = color_rgb
            left, top, right, bottom = int(region[0]), int(region[1]), int(region[2]), int(region[3])
            draw.rectangle([left, top, right, bottom], fill=fill_color,
                           outline=border_color, width=3)
            label = f"{q['id']}: {q['name']}"
            draw.text((left + 4, top + 3), label, font=font,
                      fill=border_color + (255,))

        self._overlay_img = Image.alpha_composite(img, overlay).convert("RGB")

    def _render_canvas(self):
        """現在のズーム倍率に合わせてself._overlay_imgをリサイズしてCanvasに描画する。"""
        scale = self._total_scale()
        disp_w = max(1, round(self._orig_w * scale))
        disp_h = max(1, round(self._orig_h * scale))
        display = self._overlay_img.resize((disp_w, disp_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(display)
        self._photo_refs.clear()
        self._photo_refs.append(photo)

        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=photo)
        self._canvas.configure(scrollregion=(0, 0, disp_w, disp_h))
        if hasattr(self, "_zoom_label"):
            self._zoom_label.config(text=f"{self._zoom * 100:.0f}%")

    # ─── テーブル操作 ───

    def _refresh_table(self):
        """Treeviewの内容を再構築"""
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._tree.tag_configure("score_missing", background="#FFCDD2", foreground="#B71C1C")
        for q in self._questions:
            score = q.get("max_score", 0)
            tags = ("score_missing",) if score < 1 else ()
            # 配点セルは、それだけ見ても入力できるマスだと分かるよう
            # 鉛筆アイコンを添える（実データはあくまで整数のまま保持）。
            score_display = f"{score}点 ✎"
            self._tree.insert("", tk.END, iid=q["id"],
                              values=(q["id"], q["name"], score_display), tags=tags)

    def _on_tree_double_click(self, event):
        """Treeview のセルをダブルクリックで編集"""
        item = self._tree.identify_row(event.y)
        col = self._tree.identify_column(event.x)
        if not item or not col:
            return

        col_idx = int(col.replace("#", "")) - 1
        col_keys = ["id", "name", "score"]
        if col_idx == 0:
            return  # ID列は編集不可

        # 該当セルのバウンディングボックス
        bbox = self._tree.bbox(item, col)
        if not bbox:
            return

        if col_idx == 2:
            # 配点セルの表示値は鉛筆アイコン付きなので、編集時は
            # 元の整数値を使う（アイコンごと編集欄に入らないように）。
            current_val = next(
                (q.get("max_score", 0) for q in self._questions if q["id"] == item), 0
            )
        else:
            current_val = self._tree.item(item, "values")[col_idx]

        # 一時Entryウィジェットでインライン編集
        entry = tk.Entry(self._tree, font=(UI_FONT, get_ui_font_size(11)))
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.insert(0, str(current_val))
        entry.select_range(0, tk.END)
        entry.focus_set()

        def _commit(event=None):
            new_val = entry.get().strip()
            entry.destroy()
            # 対応する問題データを更新
            for q in self._questions:
                if q["id"] == item:
                    if col_idx == 1:  # name
                        q["name"] = new_val or q["name"]
                    elif col_idx == 2:  # max_score
                        try:
                            q["max_score"] = max(1, int(new_val))
                        except ValueError:
                            pass
                    break
            self._refresh_table()
            self._redraw_overlay()

        entry.bind("<Return>", _commit)
        entry.bind("<FocusOut>", _commit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def _delete_selected(self):
        """選択行の問題を削除"""
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("選択なし", "削除する行を選択してください。", parent=self.win)
            return
        qid = sel[0]
        self._questions = [q for q in self._questions if q["id"] != qid]
        self._redraw_overlay()
        self._refresh_table()
        self._update_status()

    def _edit_selected_rubric(self):
        """選択中の設問の採点基準メモを編集する。"""
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("選択なし", "設問を選択してください。", parent=self.win)
            return
        q = next((item for item in self._questions if item["id"] == sel[0]), None)
        if q is None:
            return
        dialog = tk.Toplevel(self.win)
        dialog.title(f"{q['name']} — 採点基準メモ")
        dialog.transient(self.win)
        frame = tk.Frame(dialog, padx=15, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(frame, text="採点中に参照する教員用メモ（答案には印字されません）",
                 font=(UI_FONT, get_ui_font_size(9))).pack(anchor=tk.W, pady=(0, 6))
        memo = tk.Text(
            frame, width=55, height=8, wrap=tk.WORD,
            font=(UI_FONT, get_ui_font_size(9)),
            bg="#FFFFFF", fg="#222222", insertbackground="#222222",
            relief=tk.SOLID, bd=1, highlightthickness=1,
            highlightbackground="#9E9E9E", highlightcolor="#1976D2",
        )
        memo.pack(fill=tk.BOTH, expand=True)
        memo.insert("1.0", q.get("rubric_memo", ""))

        def _save():
            q["rubric_memo"] = memo.get("1.0", "end-1c")
            dialog.destroy()

        buttons = tk.Frame(frame)
        buttons.pack(pady=(10, 0))
        tk.Button(buttons, text="保存", command=_save, width=10, bg="#4CAF50",
                  font=(UI_FONT, get_ui_font_size(9), "bold")).pack(side=tk.LEFT, padx=4)
        tk.Button(buttons, text="キャンセル", command=dialog.destroy,
                  width=10).pack(side=tk.LEFT, padx=4)
        fit_window_to_content(dialog, min_width=520, min_height=280)
        dialog.grab_set()
        memo.focus_set()

    def _update_status(self):
        n = len(self._questions)
        total_score = sum(q.get("max_score", 0) for q in self._questions)
        missing = sum(1 for q in self._questions if q.get("max_score", 0) < 1)
        if missing:
            self._status_label.config(
                text=f"⚠ 配点未入力: {missing}問　|　登録済み: {n}問　|　合計配点: {total_score}点",
                fg="#C62828",
            )
        else:
            self._status_label.config(
                text=f"登録済み: {n} 問  |  合計配点: {total_score} 点", fg="#555",
            )

    # ─── 保存・キャンセル ───

    def _on_save(self):
        if not self._questions:
            messagebox.showwarning("問題未登録", "問題を1つ以上追加してください。", parent=self.win)
            return
        missing_scores = [q.get("name", q.get("id", "")) for q in self._questions
                          if q.get("max_score", 0) < 1]
        if missing_scores:
            messagebox.showwarning(
                "配点が未入力です",
                "次の問題の配点を入力してください。\n\n"
                + "\n".join(f"・{name}" for name in missing_scores)
                + "\n\n設問一覧の配点セルをダブルクリックして入力できます。",
                parent=self.win,
            )
            return

        config = {
            "version": 2,
            "questions": self._questions,
            "total_display_region": None,
        }
        # 既存設定から total_display_region を引き継ぐ
        existing = load_descriptive_config(self.config_save_path)
        if existing and existing.get("total_display_region"):
            config["total_display_region"] = existing["total_display_region"]

        save_descriptive_config(self.config_save_path, config)
        self.result_config = config
        self.win.grab_release()
        self.win.destroy()

    def _on_cancel(self):
        self.result_config = None
        self.win.grab_release()
        self.win.destroy()


def setup_descriptive_regions_integrated(
    image_folder: str,
    config_save_path: str,
    parent: Optional[tk.Tk] = None,
    exam_page: Optional[int] = None,
) -> Optional[dict]:
    """統合ウィンドウ版の記述問題設定（旧 setup_descriptive_regions のラッパー）。

    Phase 2A: 領域選択と設問情報設定を1画面で完結する。
    exam_page は複数ページ案件でのみ指定し、どのページの設定かを画面に示す。
    """
    setup = IntegratedDescriptiveSetup(parent, image_folder, config_save_path, exam_page=exam_page)
    return setup.result_config


def select_total_position(
    image_path: str,
    parent: Optional[tk.Tk] = None,
    preview_text: Optional[str] = None,
    initial_size: Optional[Tuple[int, int]] = None,
    use_marker_default: bool = True,
) -> Optional[Tuple[int, int, int, int]]:
    """
    合計点表示位置をドラッグ移動方式で指定するGUI。

    デフォルトサイズのボックスを表示し、ドラッグで移動できる。
    ボックスの端をドラッグしてリサイズも可能。

    use_marker_default=True の場合、下部マーカー間にデフォルト配置。
    False の場合、従来通り右下隅。

    Args:
        image_path: 背景に表示する画像パス
        parent: 親ウィンドウ
        preview_text: ボックス内に表示するプレビュー文字列
        initial_size: ボックスの初期サイズ (width, height)。元画像座標系。
        use_marker_default: True の場合、デフォルト位置を下部マーカー間に設定

    Returns:
        (left, top, right, bottom) の座標タプル。キャンセル時は None。
    """
    from name_trimmer import MAX_DISPLAY_WIDTH, MAX_DISPLAY_HEIGHT
    
    original_img = Image.open(image_path)
    orig_w, orig_h = original_img.size
    
    # 表示用リサイズ比率
    if orig_w >= orig_h:
        resize_ratio = orig_w / MAX_DISPLAY_WIDTH if orig_w > MAX_DISPLAY_WIDTH else 1.0
    else:
        resize_ratio = orig_h / MAX_DISPLAY_HEIGHT if orig_h > MAX_DISPLAY_HEIGHT else 1.0
    
    display_w = int(orig_w / resize_ratio)
    display_h = int(orig_h / resize_ratio)
    display_img = original_img.resize((display_w, display_h), Image.LANCZOS)
    original_img.close()
    
    result_rect = [None]
    
    owns_root = False
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        owns_root = True
    else:
        root = parent
    
    win = tk.Toplevel(root)
    win.title("合計点表示位置 — ボックスをドラッグで移動、端でリサイズ")
    win.resizable(True, True)
    
    main_frame = tk.Frame(win)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    canvas_frame = tk.Frame(main_frame)
    canvas_frame.pack(side=tk.LEFT, padx=5, pady=5)
    
    panel = tk.Frame(main_frame)
    panel.pack(side=tk.RIGHT, padx=10, pady=10, fill=tk.Y)
    
    canvas = tk.Canvas(canvas_frame, width=display_w, height=display_h,
                       bg="black", highlightthickness=0)
    tk_img = ImageTk.PhotoImage(display_img, master=win)
    canvas.create_image(0, 0, image=tk_img, anchor=tk.NW)
    canvas.pack()
    
    # ボックスの初期サイズ（表示座標系）
    if initial_size:
        default_w = int(initial_size[0] / resize_ratio)
        default_h = int(initial_size[1] / resize_ratio)
    else:
        default_w = int(DEFAULT_TOTAL_BOX_WIDTH / resize_ratio)
        default_h = int(DEFAULT_TOTAL_BOX_HEIGHT / resize_ratio)
    # 表示領域内に収まるよう制限
    default_w = min(default_w, display_w - 10)
    default_h = min(default_h, display_h - 10)

    if use_marker_default:
        # デフォルト: 下部マーカー間フル幅（元画像座標で計算し、表示座標に変換）
        orig_box_h = int(default_h * resize_ratio)
        marker_x, marker_y, marker_w, _ = _calculate_marker_default_region(
            orig_w, orig_h, orig_box_h
        )
        default_x = int(marker_x / resize_ratio)
        default_y = int(marker_y / resize_ratio)
        default_w = int(marker_w / resize_ratio)  # マーカー間フル幅
    else:
        # 従来のデフォルト: 右下付近
        default_x = display_w - default_w - 30
        default_y = display_h - default_h - 30

    # 表示領域内にクリップ
    default_x = max(0, min(default_x, display_w - default_w))
    default_y = max(0, min(default_y, display_h - default_h))
    
    # ボックスの状態
    box_state = {
        "x1": default_x, "y1": default_y,
        "x2": default_x + default_w, "y2": default_y + default_h,
        "drag_mode": None,  # None, "move", "resize_br", "resize_bl", "resize_tr", "resize_tl"
        "drag_start_x": 0, "drag_start_y": 0,
        "orig_x1": 0, "orig_y1": 0, "orig_x2": 0, "orig_y2": 0,
    }
    HANDLE_SIZE = 8
    
    def _draw_box():
        canvas.delete("totalbox")
        x1, y1, x2, y2 = box_state["x1"], box_state["y1"], box_state["x2"], box_state["y2"]
        
        # 半透明効果（背景薄水色の矩形）
        canvas.create_rectangle(x1, y1, x2, y2, fill="#AED6F1", stipple="gray25",
                                outline="#2196F3", width=2, tags="totalbox")
        
        # テキスト（プレビュー）— preview_text があれば実際の表示例を描画
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        display_label = preview_text if preview_text else "合計点エリア"
        # プレビューテキストを表示（width指定なし＝折り返し無し、\nで改行）
        canvas.create_text(
            cx, cy, text=display_label, fill="#1565C0",
            font=(UI_FONT, get_ui_font_size(9)), tags="totalbox",
        )
        
        # リサイズハンドル（四隅）
        for hx, hy in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
            canvas.create_rectangle(hx - HANDLE_SIZE, hy - HANDLE_SIZE,
                                    hx + HANDLE_SIZE, hy + HANDLE_SIZE,
                                    fill="#2196F3", outline="white", tags="totalbox")
        
        # サイズ表示を更新
        real_w = int((x2 - x1) * resize_ratio)
        real_h = int((y2 - y1) * resize_ratio)
        size_var.set(f"{real_w} x {real_h} px")
    
    def _hit_test(mx, my):
        """マウス座標がどこに当たるかを判定"""
        x1, y1, x2, y2 = box_state["x1"], box_state["y1"], box_state["x2"], box_state["y2"]
        
        # 四隅ハンドルの判定
        corners = [
            ("resize_tl", x1, y1),
            ("resize_tr", x2, y1),
            ("resize_bl", x1, y2),
            ("resize_br", x2, y2),
        ]
        for mode, cx, cy in corners:
            if abs(mx - cx) <= HANDLE_SIZE + 2 and abs(my - cy) <= HANDLE_SIZE + 2:
                return mode
        
        # ボックス内部 → 移動
        if x1 <= mx <= x2 and y1 <= my <= y2:
            return "move"
        
        return None
    
    def _on_press(event):
        mode = _hit_test(event.x, event.y)
        if mode:
            box_state["drag_mode"] = mode
            box_state["drag_start_x"] = event.x
            box_state["drag_start_y"] = event.y
            box_state["orig_x1"] = box_state["x1"]
            box_state["orig_y1"] = box_state["y1"]
            box_state["orig_x2"] = box_state["x2"]
            box_state["orig_y2"] = box_state["y2"]
    
    def _on_drag(event):
        mode = box_state["drag_mode"]
        if not mode:
            return
        
        dx = event.x - box_state["drag_start_x"]
        dy = event.y - box_state["drag_start_y"]
        ox1, oy1, ox2, oy2 = box_state["orig_x1"], box_state["orig_y1"], box_state["orig_x2"], box_state["orig_y2"]
        
        if mode == "move":
            w, h = ox2 - ox1, oy2 - oy1
            nx1 = max(0, min(display_w - w, ox1 + dx))
            ny1 = max(0, min(display_h - h, oy1 + dy))
            box_state["x1"] = nx1
            box_state["y1"] = ny1
            box_state["x2"] = nx1 + w
            box_state["y2"] = ny1 + h
        elif mode == "resize_br":
            box_state["x2"] = max(ox1 + 30, min(display_w, ox2 + dx))
            box_state["y2"] = max(oy1 + 20, min(display_h, oy2 + dy))
        elif mode == "resize_bl":
            box_state["x1"] = min(ox2 - 30, max(0, ox1 + dx))
            box_state["y2"] = max(oy1 + 20, min(display_h, oy2 + dy))
        elif mode == "resize_tr":
            box_state["x2"] = max(ox1 + 30, min(display_w, ox2 + dx))
            box_state["y1"] = min(oy2 - 20, max(0, oy1 + dy))
        elif mode == "resize_tl":
            box_state["x1"] = min(ox2 - 30, max(0, ox1 + dx))
            box_state["y1"] = min(oy2 - 20, max(0, oy1 + dy))
        
        _draw_box()
    
    def _on_release(event):
        box_state["drag_mode"] = None
    
    def _on_motion(event):
        """カーソル形状の変更"""
        mode = _hit_test(event.x, event.y)
        if mode == "move":
            canvas.config(cursor="fleur")
        elif mode in ("resize_tl", "resize_br"):
            canvas.config(cursor="size_nw_se")
        elif mode in ("resize_tr", "resize_bl"):
            canvas.config(cursor="size_ne_sw")
        else:
            canvas.config(cursor="")
    
    canvas.bind("<ButtonPress-1>", _on_press)
    canvas.bind("<B1-Motion>", _on_drag)
    canvas.bind("<ButtonRelease-1>", _on_release)
    canvas.bind("<Motion>", _on_motion)
    
    # --- 操作パネル ---
    tk.Label(panel, text="合計点表示位置", font=(UI_FONT, get_ui_font_size(12), "bold")).pack(pady=(0, 10))
    
    tk.Label(panel, text="操作方法", font=(UI_FONT, get_ui_font_size(10), "bold")).pack()
    tk.Label(panel, text=(
        "■ ボックス内をドラッグ\n  → 移動\n\n"
        "■ 四隅の□をドラッグ\n  → サイズ変更\n\n"
        "この枠の位置に\n合計点が表示されます。"
    ), font=(UI_FONT, get_ui_font_size(8)), justify=tk.LEFT, wraplength=180).pack(pady=(5, 15))
    
    tk.Label(panel, text="ボックスサイズ:", font=(UI_FONT, get_ui_font_size(9))).pack()
    size_var = tk.StringVar()
    tk.Label(panel, textvariable=size_var, font=(UI_FONT, get_ui_font_size(9), "bold"),
             fg="#1976D2").pack(pady=(0, 10))
    
    def _confirm():
        x1, y1, x2, y2 = box_state["x1"], box_state["y1"], box_state["x2"], box_state["y2"]
        result_rect[0] = (
            round(x1 * resize_ratio),
            round(y1 * resize_ratio),
            round(x2 * resize_ratio),
            round(y2 * resize_ratio),
        )
        win.destroy()
    
    def _cancel():
        result_rect[0] = None
        win.destroy()
    
    tk.Button(panel, text="✔ 決定", command=_confirm, width=15, height=2,
              bg="#4CAF50", fg="black", font=(UI_FONT, get_ui_font_size(11), "bold")).pack(pady=5)
    tk.Button(panel, text="✖ キャンセル", command=_cancel, width=15, height=2,
              font=(UI_FONT, get_ui_font_size(10))).pack(pady=5)
    
    win.protocol("WM_DELETE_WINDOW", _cancel)
    
    # 初期描画
    _draw_box()

    fit_window_to_content(win, min_width=display_w + 220, min_height=display_h + 20)
    win.grab_set()
    win.wait_window()
    
    if owns_root:
        root.destroy()
    
    return result_rect[0]


def _ask_question_info(
    parent: Optional[tk.Tk],
    question_number: int,
) -> Optional[dict]:
    """
    問題情報（名前・配点）を入力させるモーダルダイアログ。

    Returns:
        {"name": str, "max_score": int} or None (キャンセル)
    """
    result = [None]

    owns_root = False
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        owns_root = True
    else:
        root = parent

    dialog = tk.Toplevel(root)
    dialog.title(f"問題{question_number} の設定")
    dialog.resizable(True, True)
    dialog.transient(root)

    frame = tk.Frame(dialog, padx=20, pady=15)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frame,
        text=f"問題 {question_number} の情報を入力",
        font=(UI_FONT, get_ui_font_size(11), "bold"),
    ).pack(pady=(0, 15))

    # 問題名
    row1 = tk.Frame(frame)
    row1.pack(fill=tk.X, pady=3)
    tk.Label(row1, text="問題名:", width=8, anchor=tk.W, font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT)
    name_var = tk.StringVar(value=f"問題{question_number}")
    tk.Entry(row1, textvariable=name_var, font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT, fill=tk.X, expand=True)

    # 配点
    row2 = tk.Frame(frame, bg="#FFF3E0", padx=8, pady=8)
    row2.pack(fill=tk.X, pady=6)
    tk.Label(
        row2, text="必須・配点:", width=10, anchor=tk.W,
        bg="#FFF3E0", fg="#C62828", font=(UI_FONT, get_ui_font_size(9), "bold"),
    ).pack(side=tk.LEFT)
    max_score_var = tk.StringVar(value="")
    max_score_entry = tk.Entry(
        row2, textvariable=max_score_var, width=7,
        font=(UI_FONT, get_ui_font_size(11), "bold"),
        bg="#FFFDE7", highlightthickness=2,
        highlightbackground="#EF6C00", highlightcolor="#E65100",
    )
    max_score_entry.pack(side=tk.LEFT)
    tk.Label(row2, text="点", bg="#FFF3E0", font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT, padx=5)

    tk.Label(frame, text="採点基準メモ（教員用）:",
             font=(UI_FONT, get_ui_font_size(9))).pack(anchor=tk.W, pady=(8, 2))
    rubric_text = tk.Text(
        frame, width=45, height=4, wrap=tk.WORD,
        font=(UI_FONT, get_ui_font_size(9)),
        bg="#FFFFFF", fg="#222222", insertbackground="#222222",
        relief=tk.SOLID, bd=1, highlightthickness=1,
        highlightbackground="#9E9E9E", highlightcolor="#1976D2",
    )
    rubric_text.pack(fill=tk.X)

    # 注意書き
    tk.Label(
        frame,
        text="※ 配点が10点以上の場合、採点時に数値入力欄を使用します",
        font=(UI_FONT, get_ui_font_size(7)), fg="#999",
    ).pack(pady=(8, 0))

    def _ok():
        try:
            ms = int(max_score_var.get())
        except ValueError:
            messagebox.showwarning("配点が未入力です", "配点を1以上の整数で入力してください。", parent=dialog)
            max_score_entry.focus_set()
            return

        if ms < 1:
            messagebox.showwarning("入力エラー", "配点は1以上の整数で入力してください。", parent=dialog)
            max_score_entry.focus_set()
            return

        result[0] = {
            "name": name_var.get().strip() or f"問題{question_number}",
            "max_score": ms,
            "rubric_memo": rubric_text.get("1.0", "end-1c"),
        }
        dialog.destroy()

    def _cancel():
        result[0] = None
        dialog.destroy()

    btn_frame = tk.Frame(frame)
    btn_frame.pack(pady=(15, 0))
    tk.Button(
        btn_frame, text="OK", command=_ok, width=10,
        bg="#4CAF50", fg="black", font=(UI_FONT, get_ui_font_size(9), "bold"),
    ).pack(side=tk.LEFT, padx=5)
    tk.Button(
        btn_frame, text="キャンセル", command=_cancel, width=10,
        font=(UI_FONT, get_ui_font_size(9)),
    ).pack(side=tk.LEFT, padx=5)

    dialog.protocol("WM_DELETE_WINDOW", _cancel)
    fit_window_to_content(dialog, min_width=480, min_height=390)
    dialog.grab_set()
    dialog.focus_force()
    dialog.wait_window()

    if owns_root:
        root.destroy()

    return result[0]


# ============================================================
# 採点GUI: 問題選択画面
# ============================================================

class DescriptiveScorerGUI:
    """
    記述問題の採点を統括するGUIクラス。

    問題一覧画面を表示し、各問題の採点サブウィンドウを起動する。
    """

    def __init__(
        self,
        parent: tk.Tk,
        config: dict,
        image_folder: str,
        scores_save_path: str,
        original_image_folder: Optional[str] = None,
        exam_page: Optional[int] = None,
    ):
        self.parent = parent
        self.config = config
        self.image_folder = image_folder
        self.scores_save_path = scores_save_path
        self.original_image_folder = original_image_folder
        self.exam_page = exam_page  # 複数ページ案件のみ設定される

        # 既存スコアの読み込み
        existing = load_descriptive_scores(scores_save_path)
        if existing and "scores" in existing:
            self.scores: Dict[str, Dict[str, int]] = existing["scores"]
        else:
            self.scores = {}

        self.annotations_path = str(
            Path(scores_save_path).parent / DESCRIPTIVE_ANNOTATIONS_FILE
        )
        self.annotations = load_descriptive_annotations(self.annotations_path)

        self._temp_dir: Optional[str] = None
        self._trimmed: Optional[Dict[str, Dict[str, str]]] = None
        self._result: Optional[Dict] = None
        self._list_win: Optional[tk.Toplevel] = None

    def run(self) -> Optional[dict]:
        """
        採点を実行（モーダル）。

        Returns:
            {image_filename: {question_id: score, ...}, ...} or None
        """
        # 切り出し
        _app_temp = get_app_temp_dir(str(Path(self.image_folder).parent.parent))
        self._temp_dir = tempfile.mkdtemp(prefix="desc_scoring_", dir=_app_temp)
        try:
            self._trimmed = trim_descriptive_regions(
                self.image_folder, self.config, self._temp_dir,
                original_image_folder=self.original_image_folder,
            )
        except Exception as e:
            messagebox.showerror(
                "エラー", f"画像切り出しに失敗しました:\n{e}", parent=self.parent
            )
            self._cleanup()
            return None

        if not self._trimmed or all(len(v) == 0 for v in self._trimmed.values()):
            messagebox.showerror(
                "エラー", "切り出し画像が生成されませんでした。", parent=self.parent
            )
            self._cleanup()
            return None

        # 問題選択画面
        self._show_question_list()

        return self._result

    def _show_question_list(self):
        """問題一覧・採点進捗画面（モーダル）"""
        win = tk.Toplevel(self.parent)
        title = "採点"
        if self.exam_page is not None:
            title += f"（試験ページ {self.exam_page}）"
        win.title(title)
        win.resizable(True, True)
        win.transient(self.parent)
        self._list_win = win

        frame = tk.Frame(win, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.grid_columnconfigure(0, weight=1)
        # 中央の問題一覧だけを伸縮させ、ヘッダーと下部操作は常に表示する。
        frame.grid_rowconfigure(3, weight=1, minsize=100)

        tk.Label(
            frame, text="採点",
            font=(UI_FONT, get_ui_font_size(13), "bold"),
        ).grid(row=0, column=0, sticky="ew", pady=(0, 5))
        tk.Label(
            frame,
            text="採点する問題を選択してください。完了後「採点完了」を押してください。",
            font=(UI_FONT, get_ui_font_size(8)), fg="gray", wraplength=520,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # --- 採点モード選択 ---
        mode_frame = tk.Frame(frame, bg="#F3E5F5", padx=10, pady=6)
        mode_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        tk.Label(mode_frame, text="採点モード:", font=(UI_FONT, get_ui_font_size(9), "bold"),
                 bg="#F3E5F5").pack(side=tk.LEFT, padx=(0, 5))
        # 前回の採点モードを復元（config に保存済みなら）
        saved_mode = self.config.get("scoring_mode", "1枚ずつ")
        self._scoring_mode_var = tk.StringVar(value=saved_mode)
        mode_combo = ttk.Combobox(mode_frame, textvariable=self._scoring_mode_var,
                                  values=["1枚ずつ", "一覧（グリッド）"],
                                  state="readonly", width=16,
                                  font=(UI_FONT, get_ui_font_size(9)))
        mode_combo.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(mode_frame, text="※ モードを変えるには一度採点を中断してください",
                 font=(UI_FONT, get_ui_font_size(8)), fg="#7B1FA2", bg="#F3E5F5"
                 ).pack(side=tk.LEFT)

        # --- 問題リスト（スクロール対応） ---
        self._status_labels: Dict[str, tk.Label] = {}
        self._info_labels: Dict[str, tk.Label] = {}

        # Canvas + Scrollbar によるスクロール可能エリア
        scroll_container = tk.Frame(frame)
        scroll_container.grid(row=3, column=0, sticky="nsew")

        q_canvas = tk.Canvas(scroll_container, highlightthickness=0, bd=0)
        q_scrollbar = tk.Scrollbar(scroll_container, orient=tk.VERTICAL, command=q_canvas.yview)
        q_canvas.configure(yscrollcommand=q_scrollbar.set)

        q_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        q_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        questions_frame = tk.Frame(q_canvas)
        q_canvas_window = q_canvas.create_window((0, 0), window=questions_frame, anchor="nw")

        def _on_questions_configure(event):
            q_canvas.configure(scrollregion=q_canvas.bbox("all"))

        def _on_canvas_configure(event):
            q_canvas.itemconfig(q_canvas_window, width=event.width)

        questions_frame.bind("<Configure>", _on_questions_configure)
        q_canvas.bind("<Configure>", _on_canvas_configure)

        # マウスホイールでスクロール
        def _on_mousewheel(event):
            q_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        q_canvas.bind("<MouseWheel>", _on_mousewheel)
        questions_frame.bind("<MouseWheel>", _on_mousewheel)

        for q in self.config["questions"]:
            q_id = q["id"]
            q_row = tk.Frame(questions_frame, pady=4)
            q_row.pack(fill=tk.X)
            q_row.grid_columnconfigure(0, weight=1)

            info_text = f"{q['name']}  (配点:{q['max_score']}点)"
            info_label = tk.Label(
                q_row, text=info_text,
                font=(UI_FONT, get_ui_font_size(9)), anchor=tk.W,
            )
            info_label.grid(row=0, column=0, sticky="ew")
            self._info_labels[q_id] = info_label

            status = self._get_question_status(q_id)
            status_label = tk.Label(
                q_row, text=status,
                font=(UI_FONT, get_ui_font_size(8)),
                fg="green" if "完了" in status else "gray",
            )
            status_label.grid(row=0, column=1, padx=5, sticky="e")
            self._status_labels[q_id] = status_label

            tk.Button(
                q_row, text="採点",
                command=lambda qid=q_id: self._score_question(qid),
                width=5, font=(UI_FONT, get_ui_font_size(9)),
                bg="#90CAF9", relief=tk.FLAT, cursor="hand2",
            ).grid(row=0, column=2, padx=(0, 2))

            tk.Button(
                q_row, text="配点・設定",
                command=lambda qid=q_id: self._edit_question(qid),
                width=8, font=(UI_FONT, get_ui_font_size(8), "bold"),
                bg="#FFE082", relief=tk.FLAT, cursor="hand2",
            ).grid(row=0, column=3)

        # 子ウィジェットにもマウスホイールバインド（スクロール連動）
        def _bind_mousewheel_recursive(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel_recursive(child)

        _bind_mousewheel_recursive(questions_frame)

        # --- 下部ボタン ---
        btn_frame = tk.Frame(frame, pady=10)
        btn_frame.grid(row=4, column=0, sticky="ew")

        tk.Button(
            btn_frame, text="✔ 採点完了・保存",
            command=lambda: self._finish(win),
            bg="#4CAF50", fg="black",
            font=(UI_FONT, get_ui_font_size(10), "bold"),
            width=20, height=2, relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_frame, text="キャンセル",
            command=lambda: self._cancel(win),
            font=(UI_FONT, get_ui_font_size(9)), width=10,
        ).pack(side=tk.LEFT, padx=5)

        win.protocol("WM_DELETE_WINDOW", lambda: self._cancel(win))
        fit_window_to_content(win, min_width=600, min_height=520)
        win.grab_set()
        win.wait_window()

    def _get_question_status(self, question_id: str) -> str:
        """問題の採点状況テキスト"""
        trimmed_for_q = self._trimmed.get(question_id, {})
        total_images = len(trimmed_for_q)
        if total_images == 0:
            return "画像なし"

        scored_count = 0
        for img_name in trimmed_for_q:
            if img_name in self.scores and question_id in self.scores[img_name]:
                scored_count += 1

        held_count = sum(
            1 for img_name in trimmed_for_q
            if self.annotations.get("answers", {}).get(img_name, {})
            .get(question_id, {}).get("held", False)
        )
        held_suffix = f" / 保留:{held_count}" if held_count else ""

        if scored_count == 0:
            return f"未採点{held_suffix}"
        elif scored_count >= total_images:
            return f"完了 ({scored_count}枚){held_suffix}"
        else:
            return f"{scored_count}/{total_images}枚{held_suffix}"

    def _update_status_labels(self):
        """ステータスラベルを更新"""
        for q_id, label in self._status_labels.items():
            status = self._get_question_status(q_id)
            label.config(
                text=status,
                fg="green" if "完了" in status else "gray",
            )

    def _update_info_labels(self):
        """問題情報ラベルを更新"""
        for q in self.config["questions"]:
            q_id = q["id"]
            if q_id in self._info_labels:
                info_text = f"{q['name']}  (配点:{q['max_score']}点)"
                self._info_labels[q_id].config(text=info_text)

    def _edit_question(self, question_id: str):
        """問題の設定（名前・配点）を編集するダイアログ。

        配点を下げた場合、既存スコアが新配点を超えるものがあれば
        警告してキャップ（新配点にクリップ）するか確認する。
        """
        q_config = None
        for q in self.config["questions"]:
            if q["id"] == question_id:
                q_config = q
                break
        if q_config is None:
            return

        result = [None]
        dialog = tk.Toplevel(self._list_win)
        dialog.title(f"{q_config['name']} の設定変更")
        dialog.resizable(True, True)
        dialog.transient(self._list_win)

        frame = tk.Frame(dialog, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text=f"問題 {q_config['id']} の設定を変更",
            font=(UI_FONT, get_ui_font_size(11), "bold"),
        ).pack(pady=(0, 12))

        # 問題名
        row1 = tk.Frame(frame)
        row1.pack(fill=tk.X, pady=3)
        tk.Label(row1, text="問題名:", width=8, anchor=tk.W, font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT)
        name_var = tk.StringVar(value=q_config["name"])
        tk.Entry(row1, textvariable=name_var, font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 配点
        row2 = tk.Frame(frame, bg="#FFF3E0", padx=8, pady=8)
        row2.pack(fill=tk.X, pady=6)
        tk.Label(
            row2, text="必須・配点:", width=10, anchor=tk.W,
            bg="#FFF3E0", fg="#C62828", font=(UI_FONT, get_ui_font_size(9), "bold"),
        ).pack(side=tk.LEFT)
        max_score_var = tk.StringVar(value=str(q_config["max_score"]))
        max_score_entry = tk.Entry(
            row2, textvariable=max_score_var, width=7,
            font=(UI_FONT, get_ui_font_size(11), "bold"), bg="#FFFDE7",
            highlightthickness=2, highlightbackground="#EF6C00", highlightcolor="#E65100",
        )
        max_score_entry.pack(side=tk.LEFT)
        tk.Label(
            row2, text=f"点  (現在: {q_config['max_score']}点)",
            bg="#FFF3E0", font=(UI_FONT, get_ui_font_size(8)), fg="#555",
        ).pack(side=tk.LEFT, padx=5)

        tk.Label(frame, text="採点基準メモ（教員用）:",
                 font=(UI_FONT, get_ui_font_size(9))).pack(anchor=tk.W, pady=(8, 2))
        rubric_text = tk.Text(
            frame, width=48, height=5, wrap=tk.WORD,
            font=(UI_FONT, get_ui_font_size(9)),
            bg="#FFFFFF", fg="#222222", insertbackground="#222222",
            relief=tk.SOLID, bd=1, highlightthickness=1,
            highlightbackground="#9E9E9E", highlightcolor="#1976D2",
        )
        rubric_text.pack(fill=tk.X)
        rubric_text.insert("1.0", q_config.get("rubric_memo", ""))

        tk.Label(frame, text="解答例画像（採点中に参照）:",
                 font=(UI_FONT, get_ui_font_size(9))).pack(anchor=tk.W, pady=(8, 2))
        example_path_var = tk.StringVar(value=q_config.get("answer_example_path", ""))
        example_label = tk.Label(
            frame, text=(Path(example_path_var.get()).name if example_path_var.get() else "未登録"),
            fg="#666", anchor=tk.W,
        )
        example_label.pack(fill=tk.X)
        example_buttons = tk.Frame(frame)
        example_buttons.pack(anchor=tk.W, pady=(2, 0))

        def _choose_example():
            selected = filedialog.askopenfilename(
                parent=dialog, title="解答例画像を選択",
                filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.gif"), ("すべて", "*.*")],
            )
            if selected:
                try:
                    example_dir = Path(self.scores_save_path).parent / "answer_examples"
                    example_dir.mkdir(parents=True, exist_ok=True)
                    stored = example_dir / f"{question_id}{Path(selected).suffix.lower()}"
                    shutil.copy2(selected, stored)
                    q_config["answer_example_path"] = str(stored)
                    example_path_var.set(str(stored))
                    example_label.config(text=stored.name)
                except OSError as exc:
                    messagebox.showerror("解答例画像", f"画像を保存できませんでした:\n{exc}", parent=dialog)

        def _clear_example():
            q_config.pop("answer_example_path", None)
            example_path_var.set("")
            example_label.config(text="未登録")

        tk.Button(example_buttons, text="画像を登録", command=_choose_example,
                  font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT)
        tk.Button(example_buttons, text="削除", command=_clear_example,
                  font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT, padx=(4, 0))

        # 採点リセットボタン
        tk.Label(frame, text="─" * 30, fg="#ccc").pack(pady=(10, 5))
        tk.Button(
            frame, text="🔄 この問題の採点をリセット",
            command=lambda: self._reset_question_scores(question_id, dialog),
            font=(UI_FONT, get_ui_font_size(9)), bg="#FFCDD2",
            relief=tk.FLAT, cursor="hand2",
        ).pack(fill=tk.X, pady=2)

        def _ok():
            try:
                new_max = int(max_score_var.get())
            except ValueError:
                messagebox.showwarning("入力エラー", "配点は1以上の整数で入力してください。", parent=dialog)
                return
            if new_max < 1:
                messagebox.showwarning("入力エラー", "配点は1以上の整数で入力してください。", parent=dialog)
                return

            old_max = q_config["max_score"]

            # 配点が下がった場合: 超過スコアの確認
            if new_max < old_max:
                over_count = 0
                for img_name in self.scores:
                    sc = self.scores[img_name].get(question_id)
                    if sc is not None and sc > new_max:
                        over_count += 1
                if over_count > 0:
                    if not messagebox.askyesno(
                        "確認",
                        f"配点を {old_max} → {new_max} に下げると、\n"
                        f"{over_count}件の採点が新配点を超えています。\n\n"
                        f"超過分を {new_max} 点にキャップしますか？",
                        parent=dialog,
                    ):
                        return
                    # スコアをキャップ
                    for img_name in self.scores:
                        sc = self.scores[img_name].get(question_id)
                        if sc is not None and sc > new_max:
                            self.scores[img_name][question_id] = new_max

            # 設定を更新
            q_config["name"] = name_var.get().strip() or q_config["name"]
            q_config["max_score"] = new_max
            q_config.pop("aspect", None)
            q_config["rubric_memo"] = rubric_text.get("1.0", "end-1c")

            # config を保存
            self.config["version"] = 2
            save_descriptive_config(
                str(Path(self.scores_save_path).parent / DESCRIPTIVE_CONFIG_FILE),
                self.config,
            )
            # scores も保存（キャップした場合）
            save_descriptive_scores(
                self.scores_save_path,
                {"version": 1, "scores": self.scores},
            )

            # use_entry 判定が変わる可能性があるので再構築は不要
            # （次回 _score_question 時に自動判定される）
            result[0] = True
            dialog.destroy()

        # ボタン
        btn_frame = tk.Frame(frame)
        btn_frame.pack(pady=(10, 0))
        tk.Button(
            btn_frame, text="OK", command=_ok, width=10,
            bg="#4CAF50", fg="black", font=(UI_FONT, get_ui_font_size(9), "bold"),
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame, text="キャンセル", command=dialog.destroy, width=10,
            font=(UI_FONT, get_ui_font_size(9)),
        ).pack(side=tk.LEFT, padx=5)

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        fit_window_to_content(dialog, min_width=480, min_height=430)
        dialog.grab_set()
        dialog.focus_force()
        dialog.wait_window()

        if result[0]:
            self._update_info_labels()
            self._update_status_labels()

    def _reset_question_scores(self, question_id: str, parent_dialog=None):
        """指定問題の全採点データをリセットする。"""
        q_config = None
        for q in self.config["questions"]:
            if q["id"] == question_id:
                q_config = q
                break
        if q_config is None:
            return

        # リセット対象件数をカウント
        count = 0
        for img_name in self.scores:
            if question_id in self.scores[img_name]:
                count += 1

        if count == 0:
            messagebox.showinfo(
                "情報",
                f"{q_config['name']} の採点データはありません。",
                parent=parent_dialog or self._list_win,
            )
            return

        if not messagebox.askyesno(
            "採点リセット確認",
            f"{q_config['name']} の採点データ（{count}件）を\n"
            f"すべてリセットしますか？\n\n"
            f"この操作は取り消せません。",
            parent=parent_dialog or self._list_win,
        ):
            return

        # スコアを削除
        for img_name in list(self.scores.keys()):
            if question_id in self.scores[img_name]:
                del self.scores[img_name][question_id]
            # 空になった画像エントリを削除
            if not self.scores[img_name]:
                del self.scores[img_name]

        # 保存
        save_descriptive_scores(
            self.scores_save_path,
            {"version": 1, "scores": self.scores},
        )

        messagebox.showinfo(
            "完了",
            f"{q_config['name']} の採点データ（{count}件）をリセットしました。",
            parent=parent_dialog or self._list_win,
        )
        self._update_status_labels()

    def _score_question(self, question_id: str):
        """1つの問題の採点サブウィンドウを開く"""
        trimmed_for_q = self._trimmed.get(question_id, {})
        if not trimmed_for_q:
            messagebox.showwarning(
                "警告", "この問題の切り出し画像がありません。",
                parent=self._list_win,
            )
            return

        q_config = None
        for q in self.config["questions"]:
            if q["id"] == question_id:
                q_config = q
                break
        if q_config is None:
            return

        # 採点モードを config に保存（次回復元用）
        current_mode = self._scoring_mode_var.get()
        self.config["scoring_mode"] = current_mode
        try:
            from descriptive_scorer import save_descriptive_config
            config_path = str(Path(self.scores_save_path).parent / "descriptive_config.json")
            save_descriptive_config(config_path, self.config)
        except Exception:
            pass

        scorer = _SingleQuestionScorer(
            parent=self._list_win,
            question_config=q_config,
            image_paths=trimmed_for_q,
            existing_scores=self.scores,
            initial_mode=current_mode,
            image_folder=self.image_folder,
            original_image_folder=self.original_image_folder,
            rubric_save_callback=self._save_rubric_config,
            annotations=self.annotations,
            annotations_save_callback=self._save_annotations,
            exam_page=self.exam_page,
        )
        updated = scorer.run()

        if updated is not None:
            # スコアをマージ
            for img_name, q_scores in updated.items():
                if img_name not in self.scores:
                    self.scores[img_name] = {}
                self.scores[img_name].update(q_scores)

            # 中間保存（作業中ロスト防止）
            save_descriptive_scores(
                self.scores_save_path,
                {"version": 1, "scores": self.scores},
            )

        self._update_status_labels()

    def _save_rubric_config(self):
        """採点中に編集された採点基準メモを設定ファイルへ保存する。"""
        self.config["version"] = 2
        save_descriptive_config(
            str(Path(self.scores_save_path).parent / DESCRIPTIVE_CONFIG_FILE),
            self.config,
        )

    def _save_annotations(self):
        """採点中の回答注釈をアトミックに保存する。"""
        save_descriptive_annotations(self.annotations_path, self.annotations)

    def _finish(self, win: tk.Toplevel):
        """採点完了・保存"""
        save_descriptive_scores(
            self.scores_save_path,
            {"version": 1, "scores": self.scores},
        )
        self._result = self.scores
        win.destroy()
        self._cleanup()

    def _cancel(self, win: tk.Toplevel):
        """キャンセル（中間保存はする）"""
        has_any = any(bool(v) for v in self.scores.values()) if self.scores else False
        if has_any:
            if not messagebox.askyesno(
                "確認",
                "採点を中断しますか？\n（ここまでの結果は自動保存済みです）",
                parent=win,
            ):
                return
        self._result = None
        win.destroy()
        self._cleanup()

    def _cleanup(self):
        """一時ファイル削除"""
        if self._temp_dir and Path(self._temp_dir).exists():
            try:
                shutil.rmtree(self._temp_dir)
            except Exception:
                pass
            self._temp_dir = None


# ============================================================
# 採点GUI: 1問分の採点サブウィンドウ
# ============================================================

class _SingleQuestionScorer:
    """
    1つの記述問題を全生徒について採点するサブウィンドウ。

    saitenGiri2021.py の siwakeApp() を参考に、
    キーボード入力 (0-9) で得点を入力し、自動で次の画像に進む。

    配点が10点以上の場合: 数値入力欄 + Enterキー方式に切り替え。
    """

    def __init__(
        self,
        parent: tk.Toplevel,
        question_config: dict,
        image_paths: Dict[str, str],
        existing_scores: dict,
        initial_mode: str = "1枚ずつ",
        image_folder: Optional[str] = None,
        original_image_folder: Optional[str] = None,
        rubric_save_callback: Optional[Callable[[], None]] = None,
        annotations: Optional[dict] = None,
        annotations_save_callback: Optional[Callable[[], None]] = None,
        exam_page: Optional[int] = None,
    ):
        self.parent = parent
        self.q_config = question_config
        self.q_id = question_config["id"]
        self.max_score = question_config["max_score"]
        self.exam_page = exam_page  # 複数ページ案件のみ設定される
        self.use_entry = self.max_score > MAX_KEYBOARD_SCORE
        self.image_paths = image_paths
        self.existing_scores = existing_scores
        self.initial_mode = "1枚ずつ" if "1枚" in initial_mode else "一覧"
        self.image_folder = image_folder  # 補正済み画像フォルダ (00_Processing)
        # 元画像フォルダ（マーク描画なしの純粋スキャン画像）
        self.original_image_folder = original_image_folder
        self.rubric_save_callback = rubric_save_callback
        self._rubric_save_after_id: Optional[str] = None
        self.annotations = annotations if annotations is not None else {
            "version": 1, "answers": {}, "comment_history": {},
        }
        self.annotations_save_callback = annotations_save_callback
        self._annotation_save_after_id: Optional[str] = None
        self._annotation_loaded_filename: Optional[str] = None

        self.filenames = sorted(image_paths.keys())
        self.current_idx = 0

        # この問題のローカル採点結果
        self.local_scores: Dict[str, int] = {}
        for fn in self.filenames:
            if fn in existing_scores and self.q_id in existing_scores[fn]:
                self.local_scores[fn] = existing_scores[fn][self.q_id]

        self._result: Optional[dict] = None
        self._tk_images: Dict[str, ImageTk.PhotoImage] = {}
        self._tk_images_order: list = []  # LRU順序管理
        self._MAX_IMG_CACHE = 10  # PhotoImage保持上限
        self._win: Optional[tk.Toplevel] = None

    def run(self) -> Optional[dict]:
        """採点ウィンドウを表示（モーダル）。"""
        if not self.filenames:
            return None

        win = tk.Toplevel(self.parent)
        title = f"採点: {self.q_config['name']} (配点:{self.max_score}点)"
        if self.exam_page is not None:
            title += f"（試験ページ {self.exam_page}）"
        win.title(title)
        # 画面サイズに合わせたウィンドウサイズ（切れ防止）
        screen_h = win.winfo_screenheight()
        win_h = min(700, screen_h - 100)
        win.geometry(f"1000x{win_h}")
        win.resizable(True, True)
        win.transient(self.parent)
        self._win = win

        # --- サムネイルサイズ（スライダーで連続調整） ---
        self._grid_thumb_size = 160  # 初期値
        self._zoom_after_id: Optional[str] = None  # デバウンス用

        # --- モード設定（選択されたモードで固定、採点中の切替は不可） ---
        self._mode_var = tk.StringVar(value=self.initial_mode)

        # --- ズームコントロール（一覧モード時のみ表示） ---
        self._zoom_bar = tk.Frame(win, bg="#37474F", padx=10, pady=4)

        self._zoom_frame = tk.Frame(self._zoom_bar, bg="#37474F")
        self._zoom_frame.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        tk.Label(self._zoom_frame, text="🔍 サイズ:",
                 font=(UI_FONT, get_ui_font_size(9)), bg="#37474F", fg="white"
                 ).pack(side=tk.LEFT)

        self._zoom_slider = tk.Scale(
            self._zoom_frame, from_=80, to=800, orient=tk.HORIZONTAL,
            length=200, bg="#37474F", fg="#FFD54F", troughcolor="#546E7A",
            highlightthickness=0, sliderlength=20,
            command=self._on_zoom_slider_change,
        )
        self._zoom_slider.set(160)
        self._zoom_slider.pack(side=tk.LEFT, padx=5)

        self._zoom_label_var = tk.StringVar(value="160px")
        tk.Label(self._zoom_frame, textvariable=self._zoom_label_var,
                 font=(UI_FONT, get_ui_font_size(9), "bold"), bg="#37474F", fg="#FFD54F",
                 width=8, anchor=tk.CENTER).pack(side=tk.LEFT, padx=2)

        # 一覧モードならズームバーを表示
        if self.initial_mode == "一覧":
            self._zoom_bar.pack(fill=tk.X)

        # --- コンテナ（モード別パネルの親） ---
        self._container = tk.Frame(win)
        self._container.pack(fill=tk.BOTH, expand=True)

        # ===== 1枚ずつパネル =====
        self._single_frame = tk.Frame(self._container)
        if self.initial_mode == "1枚ずつ":
            self._single_frame.pack(fill=tk.BOTH, expand=True)

        # --- 上部バー: 進捗・得点・〇×ボタン・ヘルプリンク ---
        top_bar = tk.Frame(self._single_frame, bg="#37474F", padx=6, pady=4)
        top_bar.pack(fill=tk.X)

        # 進捗（大きく目立つ表示）
        self.progress_var = tk.StringVar()
        tk.Label(
            top_bar, textvariable=self.progress_var,
            font=(UI_FONT, get_ui_font_size(14), "bold"), bg="#37474F", fg="#FFD54F",
        ).pack(side=tk.LEFT, padx=(0, 12))

        # ファイル名
        self.filename_var = tk.StringVar()
        tk.Label(
            top_bar, textvariable=self.filename_var,
            font=(UI_FONT, get_ui_font_size(8)), bg="#37474F", fg="#B0BEC5",
        ).pack(side=tk.LEFT, padx=(0, 10))

        # 得点表示
        tk.Label(top_bar, text="得点:", font=(UI_FONT, get_ui_font_size(9)),
                 bg="#37474F", fg="#FFD54F").pack(side=tk.LEFT)
        self.score_var = tk.StringVar(value="—")
        tk.Label(
            top_bar, textvariable=self.score_var,
            font=(UI_FONT, get_ui_font_size(16), "bold"), bg="#37474F", fg="#FFD54F",
        ).pack(side=tk.LEFT, padx=(2, 10))

        # 数値入力欄（配点>9の場合のみ表示）
        if self.use_entry:
            self.score_entry = tk.Entry(top_bar, width=4, font=(UI_FONT, get_ui_font_size(12)),
                                        justify=tk.CENTER)
            self.score_entry.pack(side=tk.LEFT, padx=(0, 3))
            tk.Button(
                top_bar, text="確定", command=self._submit_entry_score,
                font=(UI_FONT, get_ui_font_size(8)), bg="#90CAF9", relief=tk.FLAT,
            ).pack(side=tk.LEFT, padx=(0, 8))
            self.score_entry.bind("<Return>", lambda e: self._submit_entry_score())

        # 〇/× ボタン (コンパクト版)
        self._btn_maru = tk.Button(
            top_bar, text=f"〇 正解({self.max_score}点)",
            command=self._on_maru,
            bg="#E3F2FD", fg="#1565C0",
            font=(UI_FONT, get_ui_font_size(9), "bold"),
            relief=tk.RAISED, cursor="hand2",
            activebackground="#BBDEFB", padx=6, pady=1,
        )
        self._btn_maru.pack(side=tk.LEFT, padx=2)

        self._btn_batsu = tk.Button(
            top_bar, text="× 不正解(0点)",
            command=self._on_batsu,
            bg="#FFEBEE", fg="#C62828",
            font=(UI_FONT, get_ui_font_size(9), "bold"),
            relief=tk.RAISED, cursor="hand2",
            activebackground="#FFCDD2", padx=6, pady=1,
        )
        self._btn_batsu.pack(side=tk.LEFT, padx=2)

        self._btn_hold = tk.Button(
            top_bar, text="⏸ 保留して次へ",
            command=self._on_hold,
            bg="#FFF3E0", fg="#AD1457",
            font=(UI_FONT, get_ui_font_size(9), "bold"),
            relief=tk.RAISED, cursor="hand2",
            activebackground="#FFE0B2", padx=6, pady=1,
        )
        self._btn_hold.pack(side=tk.LEFT, padx=2)

        # 右端（採点完了・キャンセル）
        tk.Button(
            top_bar, text="キャンセル",
            command=self._cancel,
            font=(UI_FONT, get_ui_font_size(8)), bg="#37474F", fg="#B0BEC5",
            relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.RIGHT, padx=2)

        tk.Button(
            top_bar, text="✔ 採点完了",
            command=self._finish,
            bg="#4CAF50", fg="black",
            font=(UI_FONT, get_ui_font_size(9), "bold"),
            relief=tk.FLAT, cursor="hand2", padx=8,
        ).pack(side=tk.RIGHT, padx=2)

        # --- 中間バー: ズーム・フィルタ・ヘルプ・元画像リンク ---
        mid_bar = tk.Frame(self._single_frame, bg="#ECEFF1", padx=6, pady=2)
        mid_bar.pack(fill=tk.X)

        # 画像ズーム操作（100%は自動フィット）
        self._single_zoom_factor = 100  # % (100 = auto-fit)
        self._single_zoom_after_id: Optional[str] = None

        tk.Label(mid_bar, text="🔍", font=(UI_FONT, get_ui_font_size(9)),
                 bg="#ECEFF1").pack(side=tk.LEFT)
        tk.Button(mid_bar, text="－ 縮小", command=lambda: self._change_single_zoom(1 / 1.25),
                  font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT, padx=2)
        tk.Button(mid_bar, text="＋ 拡大", command=lambda: self._change_single_zoom(1.25),
                  font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT, padx=2)
        tk.Button(mid_bar, text="自動フィット", command=self._fit_single_image,
                  font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT, padx=2)
        self._single_zoom_label = tk.Label(
            mid_bar, text="自動フィット",
            font=(UI_FONT, get_ui_font_size(8)), fg="#555", bg="#ECEFF1",
        )
        self._single_zoom_label.pack(side=tk.LEFT, padx=(0, 8))

        # フィルタ
        tk.Label(mid_bar, text="表示:", bg="#ECEFF1",
                 font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT)
        self._single_filter_var = tk.StringVar(value="全件")
        self._single_filter_combo = ttk.Combobox(
            mid_bar, textvariable=self._single_filter_var,
            values=("全件", "未採点", "保留"), state="readonly", width=7,
            font=(UI_FONT, get_ui_font_size(8)),
        )
        self._single_filter_combo.pack(side=tk.LEFT, padx=(2, 5))
        self._single_filter_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._on_filter_change()
        )

        # 未採点カウント
        self._unscored_var = tk.StringVar()
        tk.Label(
            mid_bar, textvariable=self._unscored_var,
            font=(UI_FONT, get_ui_font_size(8)), fg="#E65100", bg="#ECEFF1",
        ).pack(side=tk.LEFT, padx=(0, 10))

        # 有効得点チェックボックス（配点<=9のときのみ）
        if not self.use_entry:
            tk.Label(mid_bar, text="|", fg="#ccc", bg="#ECEFF1",
                     font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT, padx=3)
            tk.Label(mid_bar, text="入力可能:",
                     font=(UI_FONT, get_ui_font_size(8)), bg="#ECEFF1").pack(side=tk.LEFT)

            self.score_checks: Dict[int, tk.BooleanVar] = {}
            for i in range(min(10, self.max_score + 1)):
                var = tk.BooleanVar(value=True)
                self.score_checks[i] = var
                cb = tk.Checkbutton(
                    mid_bar, text=str(i), variable=var,
                    font=(UI_FONT, get_ui_font_size(8)), bg="#ECEFF1",
                )
                cb.pack(side=tk.LEFT, padx=1)

        # 右端リンク
        help_link = tk.Label(
            mid_bar, text="❓操作方法",
            font=(UI_FONT, get_ui_font_size(8), "underline"), fg="#1976D2",
            bg="#ECEFF1", cursor="hand2",
        )
        help_link.pack(side=tk.RIGHT, padx=5)
        help_link.bind("<Button-1>", lambda e: self._show_help_window())

        # 元画像を開くリンク
        open_link = tk.Label(
            mid_bar, text="📷元画像を開く",
            font=(UI_FONT, get_ui_font_size(8), "underline"), fg="#1976D2",
            bg="#ECEFF1", cursor="hand2",
        )
        open_link.pack(side=tk.RIGHT, padx=5)
        open_link.bind("<Button-1>", lambda e: self._open_current_original())

        # --- メイン: 画像キャンバス（横長で広く表示） ---
        canvas_frame = tk.Frame(self._single_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # 答案を見ながら随時追記できる、設問共通の採点基準メモ。
        # 右パネルは小さい画面でも下端の注釈まで到達できるよう、独立して
        # 縦スクロールさせる。内容フレームを直接 pack すると、上段の内容が
        # 下段のメモ／コメントを画面外へ押し出してしまう。
        rubric_shell = tk.Frame(
            canvas_frame, bg="#FFF8E1",
            highlightthickness=1, highlightbackground="#D6B656",
        )
        rubric_shell.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        rubric_canvas = tk.Canvas(
            rubric_shell, width=300, bg="#FFF8E1", highlightthickness=0,
        )
        rubric_scrollbar = tk.Scrollbar(
            rubric_shell, orient=tk.VERTICAL, command=rubric_canvas.yview,
        )
        rubric_canvas.configure(yscrollcommand=rubric_scrollbar.set)
        rubric_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        rubric_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rubric_panel = tk.Frame(rubric_canvas, bg="#FFF8E1", padx=6, pady=5)
        rubric_window = rubric_canvas.create_window(
            (0, 0), window=rubric_panel, anchor=tk.NW,
        )

        def _resize_rubric_panel(event):
            rubric_canvas.itemconfigure(rubric_window, width=event.width)

        rubric_canvas.bind("<Configure>", _resize_rubric_panel)
        rubric_panel.bind(
            "<Configure>",
            lambda _event: rubric_canvas.configure(scrollregion=rubric_canvas.bbox("all")),
        )
        rubric_canvas.bind(
            "<MouseWheel>",
            lambda event: rubric_canvas.yview_scroll(
                int(-1 * (event.delta / 120)), "units"
            ),
        )

        rubric_header = tk.Frame(rubric_panel, bg="#FFF8E1")
        rubric_header.pack(fill=tk.X)
        tk.Label(
            rubric_header, text="📋 採点基準メモ",
            bg="#FFF8E1", fg="#5D4037",
            font=(UI_FONT, get_ui_font_size(9), "bold"),
        ).pack(side=tk.LEFT)
        tk.Button(
            rubric_header, text="採点に戻る（Esc）",
            command=self._focus_scoring_canvas,
            bg="#E3F2FD", fg="#1565C0", relief=tk.FLAT, cursor="hand2",
            font=(UI_FONT, get_ui_font_size(7), "bold"),
        ).pack(side=tk.RIGHT)
        tk.Label(
            rubric_panel,
            text="設問内で共有・自動保存（答案クリックで採点へ）",
            bg="#FFF8E1", fg="#795548", justify=tk.LEFT,
            font=(UI_FONT, get_ui_font_size(7)),
        ).pack(anchor=tk.W, pady=(2, 3))
        self._rubric_text = tk.Text(
            rubric_panel, width=28, height=4, wrap=tk.WORD,
            font=(UI_FONT, get_ui_font_size(8)),
            bg="#FFFFFF", fg="#222222", insertbackground="#222222",
            relief=tk.SOLID, bd=1, highlightthickness=1,
            highlightbackground="#BCAAA4", highlightcolor="#1976D2",
        )
        self._rubric_text.pack(fill=tk.X)
        self._rubric_text.insert("1.0", self.q_config.get("rubric_memo", ""))
        self._rubric_text.bind("<KeyRelease>", self._schedule_rubric_save)
        self._rubric_text.bind("<FocusOut>", lambda _e: self._save_rubric_now())
        self._rubric_status = tk.Label(
            rubric_panel, text="", bg="#FFF8E1", fg="#2E7D32",
            font=(UI_FONT, get_ui_font_size(7)), anchor=tk.E,
        )
        self._rubric_status.pack(fill=tk.X, pady=(3, 0))

        example_row = tk.Frame(rubric_panel, bg="#FFF8E1")
        example_row.pack(fill=tk.X, pady=(2, 0))
        tk.Label(example_row, text="解答例", bg="#FFF8E1", fg="#795548",
                 font=(UI_FONT, get_ui_font_size(8), "bold")).pack(anchor=tk.W)
        preview_frame = tk.Frame(example_row, bg="#FFFDF5", width=270, height=90,
                                 relief=tk.SOLID, bd=1)
        preview_frame.pack(fill=tk.X, pady=(2, 2))
        preview_frame.pack_propagate(False)
        self._example_image_label = tk.Label(
            preview_frame, text="未登録", bg="#FFFDF5", fg="#795548",
            font=(UI_FONT, get_ui_font_size(8)), anchor=tk.CENTER,
        )
        self._example_image_label.pack(fill=tk.BOTH, expand=True)
        example_buttons = tk.Frame(example_row, bg="#FFF8E1")
        example_buttons.pack(fill=tk.X)
        tk.Button(example_buttons, text="ファイルから登録", command=self._choose_answer_example,
                  font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT)
        tk.Button(example_buttons, text="答案から切り抜く", command=self._crop_answer_example,
                  font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT, padx=(3, 0))
        tk.Button(example_buttons, text="削除", command=self._clear_answer_example,
                  font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT, padx=(3, 0))
        self._refresh_answer_example_preview()

        tk.Frame(rubric_panel, height=1, bg="#BCAAA4").pack(fill=tk.X, pady=4)
        tk.Label(
            rubric_panel, text="🗒 この回答の注釈",
            bg="#FFF8E1", fg="#5D4037",
            font=(UI_FONT, get_ui_font_size(9), "bold"),
        ).pack(anchor=tk.W)

        tk.Label(rubric_panel, text="教員用メモ（答案には印字しません）",
                 bg="#FFF8E1", fg="#5D4037",
                 font=(UI_FONT, get_ui_font_size(7))).pack(anchor=tk.W, pady=(2, 1))
        self._answer_memo_text = tk.Text(
            rubric_panel, width=28, height=3, wrap=tk.WORD,
            font=(UI_FONT, get_ui_font_size(7)), bg="#FFFFFF", fg="#222222",
            insertbackground="#222222", relief=tk.SOLID, bd=1,
            highlightthickness=1, highlightbackground="#9E9E9E",
            highlightcolor="#1976D2",
        )
        self._answer_memo_text.pack(fill=tk.X)
        memo_history_row = tk.Frame(rubric_panel, bg="#FFF8E1")
        memo_history_row.pack(fill=tk.X, pady=(2, 0))
        self._memo_history_var = tk.StringVar()
        self._memo_history_combo = ttk.Combobox(
            memo_history_row, textvariable=self._memo_history_var,
            values=self.annotations.get("memo_history", {}).get(self.q_id, []),
            state="readonly", width=20,
        )
        self._memo_history_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._memo_history_combo.bind("<<ComboboxSelected>>", self._select_memo_history)
        tk.Button(memo_history_row, text="挿入", command=self._insert_memo_history,
                  font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT, padx=(3, 0))
        tk.Button(memo_history_row, text="削除", command=self._delete_memo_history,
                  font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT, padx=(2, 0))

        tk.Label(rubric_panel, text="生徒へのコメント",
                 bg="#FFF8E1", fg="#5D4037",
                 font=(UI_FONT, get_ui_font_size(7))).pack(anchor=tk.W, pady=(3, 1))
        self._answer_comment_text = tk.Text(
            rubric_panel, width=28, height=3, wrap=tk.WORD,
            font=(UI_FONT, get_ui_font_size(7)), bg="#FFFFFF", fg="#222222",
            insertbackground="#222222", relief=tk.SOLID, bd=1,
            highlightthickness=1, highlightbackground="#9E9E9E",
            highlightcolor="#1976D2",
        )
        self._answer_comment_text.pack(fill=tk.X)
        comment_history_row = tk.Frame(rubric_panel, bg="#FFF8E1")
        comment_history_row.pack(fill=tk.X, pady=(2, 0))
        self._comment_history_var = tk.StringVar()
        self._comment_history_combo = ttk.Combobox(
            comment_history_row, textvariable=self._comment_history_var,
            values=self.annotations.get("comment_history", {}).get(self.q_id, []),
            state="readonly", width=20,
        )
        self._comment_history_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._comment_history_combo.bind("<<ComboboxSelected>>", self._select_comment_history)
        tk.Button(comment_history_row, text="挿入", command=self._insert_comment_history,
                  font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT, padx=(3, 0))
        tk.Button(comment_history_row, text="削除", command=self._delete_comment_history,
                  font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT, padx=(2, 0))

        self._answer_held_var = tk.BooleanVar(value=False)
        hold_row = tk.Frame(rubric_panel, bg="#FFF8E1")
        hold_row.pack(fill=tk.X, pady=(3, 1))
        self._held_status_label = tk.Label(
            hold_row, text="", bg="#FFF8E1", fg="#AD1457",
            font=(UI_FONT, get_ui_font_size(9), "bold"),
        )
        self._held_status_label.pack(side=tk.LEFT)
        tk.Button(
            hold_row, text="保留解除", command=self._clear_hold,
            font=(UI_FONT, get_ui_font_size(7)),
        ).pack(side=tk.RIGHT)

        self._annotation_status = tk.Label(
            rubric_panel, text="", bg="#FFF8E1", fg="#2E7D32",
            font=(UI_FONT, get_ui_font_size(7)), anchor=tk.E,
        )
        self._annotation_status.pack(fill=tk.X, pady=(2, 0))

        for widget in (self._answer_memo_text, self._answer_comment_text):
            widget.bind("<KeyRelease>", self._schedule_annotation_save)
        self._answer_memo_text.bind("<FocusOut>", lambda _e: self._commit_current_annotation(add_memo_history=True))
        self._answer_comment_text.bind(
            "<FocusOut>", lambda _e: self._commit_current_annotation(add_comment_history=True)
        )

        def _scroll_rubric(event):
            rubric_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def _bind_rubric_scroll(widget):
            # Text と Combobox はそれぞれ固有のスクロール／選択操作を優先する。
            if not isinstance(widget, (tk.Text, ttk.Combobox)):
                widget.bind("<MouseWheel>", _scroll_rubric, add="+")
            for child in widget.winfo_children():
                _bind_rubric_scroll(child)

        _bind_rubric_scroll(rubric_panel)

        self.canvas = tk.Canvas(
            canvas_frame, bg="white",
            highlightthickness=1, highlightbackground="#ccc",
            takefocus=1,
        )
        self._canvas_xscroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL,
                                             command=self.canvas.xview)
        self._canvas_yscroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL,
                                             command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self._canvas_xscroll.set,
                              yscrollcommand=self._canvas_yscroll.set)
        self._canvas_yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_single_canvas_resize, add="+")
        self.canvas.bind("<ButtonPress-1>", self._start_single_pan, add="+")
        self.canvas.bind("<B1-Motion>", self._drag_single_pan, add="+")
        self.canvas.bind("<ButtonRelease-1>", self._end_single_pan, add="+")
        self.canvas.bind("<Double-Button-1>", self._show_magnifier, add="+")
        # マウスホイールでスクロール（1枚ずつモード）
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
                         if self._mode_var.get() == "1枚ずつ" and self._single_zoom_factor > 100
                         else None)
        self.canvas.bind("<Button-1>", self._focus_scoring_canvas, add="+")

        # フィルタ済みインデックスリスト（初期は全件）
        self._filtered_indices: List[int] = list(range(len(self.filenames)))

        # キーバインド
        win.bind("<Key>", self._on_key)
        win.bind("<Left>", self._prev)
        win.bind("<Right>", self._next)
        win.bind("<Tab>", self._jump_to_unscored)
        win.bind("<Escape>", self._focus_scoring_canvas)

        # ===== 一覧 (グリッド) パネル =====
        self._grid_frame = tk.Frame(self._container, bg="#F5F7FA")
        # 初期状態では pack しない (モード切替時に表示)

        self._grid_cols = max(1, 900 // (self._grid_thumb_size + 14))
        self._grid_thumb_cache: Dict[str, ImageTk.PhotoImage] = {}
        self._grid_active_score: Optional[int] = None  # 連続クリック用

        self._build_grid_panel()

        # 初期表示 — 選択されたモードに応じて
        if self.initial_mode == "一覧":
            self._grid_frame.pack(fill=tk.BOTH, expand=True)
            win.after(50, self._refresh_grid)
        else:
            win.after(50, self._show_current)

        # Textウィジェットへ初期フォーカスが移ると数字キー採点が効かないため、
        # 起動直後は必ず答案キャンバスをフォーカスする。
        win.after_idle(self.canvas.focus_force)
        win.after(250, self.canvas.focus_force)

        win.protocol("WM_DELETE_WINDOW", self._cancel)
        win.grab_set()
        win.focus_force()
        win.wait_window()

        return self._result

    # ─── ヘルプウィンドウ ───

    def _show_help_window(self):
        """操作方法を小さいウィンドウで表示"""
        hw = tk.Toplevel(self._win)
        hw.title("操作方法")
        hw.resizable(True, True)
        hw.transient(self._win)

        frame = tk.Frame(hw, padx=15, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="キーボード操作", font=(UI_FONT, get_ui_font_size(11), "bold")).pack(anchor=tk.W, pady=(0, 5))

        if self.use_entry:
            lines = [
                ("数値入力", "得点入力欄に数値を入力"),
                ("Enter", "確定して次へ"),
                ("m", "〇 正解（満点を付与）"),
                ("b", "× 不正解（0点を付与）"),
                ("← →", "前後の画像に移動"),
                ("Tab", "次の未採点へジャンプ"),
                ("Del", "得点をクリア"),
                ("Esc", "メモ編集を終えて採点に戻る"),
            ]
        else:
            lines = [
                (f"0〜{min(9, self.max_score)}", "得点入力（自動で次へ）"),
                ("m", "〇 正解（満点を付与）"),
                ("b", "× 不正解（0点を付与）"),
                ("← →", "前後の画像に移動"),
                ("Tab", "次の未採点へジャンプ"),
                ("Space", "スキップ"),
                ("Del", "得点をクリア"),
                ("Esc", "メモ編集を終えて採点に戻る"),
            ]

        for key, desc in lines:
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=key, font=(UI_FONT, get_ui_font_size(9), "bold"),
                     fg="#1976D2", width=10, anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(row, text=desc, font=(UI_FONT, get_ui_font_size(9)),
                     fg="#333", anchor=tk.W).pack(side=tk.LEFT)

        tk.Button(
            frame, text="閉じる", command=hw.destroy,
            font=(UI_FONT, get_ui_font_size(9)), padx=10,
        ).pack(pady=(10, 0))

        fit_window_to_content(hw, min_width=320, min_height=280)

    def _schedule_rubric_save(self, _event=None):
        """採点基準メモを入力停止後に保存する。"""
        if self._rubric_save_after_id and self._win:
            self._win.after_cancel(self._rubric_save_after_id)
        self._rubric_status.config(text="入力中…")
        self._rubric_save_after_id = self._win.after(400, self._save_rubric_now)

    def _save_rubric_now(self):
        """編集内容を問題設定へ反映して即時保存する。"""
        if not hasattr(self, "_rubric_text"):
            return
        if self._rubric_save_after_id and self._win:
            try:
                self._win.after_cancel(self._rubric_save_after_id)
            except tk.TclError:
                pass
        self._rubric_save_after_id = None
        self.q_config["rubric_memo"] = self._rubric_text.get("1.0", "end-1c")
        if self.rubric_save_callback:
            self.rubric_save_callback()
        if hasattr(self, "_rubric_status"):
            self._rubric_status.config(text="保存済み")

    def _refresh_answer_example_preview(self):
        path = self.q_config.get("answer_example_path", "")
        if not path or not Path(path).is_file():
            self._example_image_label.config(image="", text="未登録")
            self._example_image_label.image = None
            return
        try:
            image = Image.open(path).convert("RGB")
            # プレビュー枠の内寸いっぱいに拡大表示する。解答例の視認性を優先し、
            # 枠に合わせてリサイズする（元画像ファイルは変更しない）。
            image.thumbnail((276, 84), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self._example_image_label.config(image=photo, text="")
            self._example_image_label.image = photo
        except Exception:
            self._example_image_label.config(image="", text="画像を読み込めません")

    def _choose_answer_example(self):
        selected = filedialog.askopenfilename(
            parent=self._win, title="解答例画像を選択",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.gif"), ("すべて", "*.*")],
        )
        if not selected:
            return
        try:
            example_dir = Path(self.annotations_save_callback.__self__.scores_save_path).parent / "answer_examples" if hasattr(self.annotations_save_callback, "__self__") else Path(selected).parent
            example_dir.mkdir(parents=True, exist_ok=True)
            stored = example_dir / f"{self.q_id}{Path(selected).suffix.lower()}"
            shutil.copy2(selected, stored)
            self.q_config["answer_example_path"] = str(stored)
            if self.rubric_save_callback:
                self.rubric_save_callback()
            self._refresh_answer_example_preview()
        except OSError as exc:
            messagebox.showerror("解答例画像", f"画像を保存できませんでした:\n{exc}", parent=self._win)

    def _clear_answer_example(self):
        self.q_config.pop("answer_example_path", None)
        if self.rubric_save_callback:
            self.rubric_save_callback()
        self._refresh_answer_example_preview()

    def _crop_answer_example(self):
        if not self.filenames:
            return
        filename = self.filenames[self.current_idx]
        source = self.image_paths.get(filename)
        if not source or not Path(source).is_file():
            messagebox.showwarning("解答例画像", "現在の答案画像が見つかりません。", parent=self._win)
            return
        try:
            image = Image.open(source).convert("RGB")
        except Exception as exc:
            messagebox.showerror("解答例画像", f"答案画像を開けませんでした:\n{exc}", parent=self._win)
            return
        dialog = tk.Toplevel(self._win)
        dialog.title("答案から解答例を切り抜く")
        dialog.transient(self._win)
        max_w, max_h = 900, 650
        scale = min(1.0, max_w / image.width, max_h / image.height)
        display = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
        photo = ImageTk.PhotoImage(display)
        canvas = tk.Canvas(dialog, width=display.width, height=display.height, cursor="crosshair")
        canvas.pack(padx=8, pady=8)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo
        state = {"start": None, "rect": None}

        def press(event):
            state["start"] = (event.x, event.y)
            if state["rect"]:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#1976D2", width=2)

        def drag(event):
            if state["start"] and state["rect"]:
                canvas.coords(state["rect"], state["start"][0], state["start"][1], event.x, event.y)

        canvas.bind("<Button-1>", press)
        canvas.bind("<B1-Motion>", drag)

        def save_crop():
            if not state["start"]:
                return
            x1, y1 = state["start"]
            x2, y2 = canvas.coords(state["rect"])[2:]
            left, right = sorted((max(0, x1), min(display.width, x2)))
            top, bottom = sorted((max(0, y1), min(display.height, y2)))
            if right - left < 3 or bottom - top < 3:
                return
            crop = image.crop((int(left / scale), int(top / scale), int(right / scale), int(bottom / scale)))
            example_dir = Path(self.annotations_save_callback.__self__.scores_save_path).parent / "answer_examples"
            example_dir.mkdir(parents=True, exist_ok=True)
            stored = example_dir / f"{self.q_id}.png"
            crop.save(stored, "PNG")
            self.q_config["answer_example_path"] = str(stored)
            if self.rubric_save_callback:
                self.rubric_save_callback()
            self._refresh_answer_example_preview()
            dialog.destroy()

        tk.Button(dialog, text="この範囲を登録", command=save_crop).pack(pady=(0, 8))
        dialog.grab_set()

    def _show_answer_example(self):
        """互換用: 現在は同じ画面のプレビューを更新する。"""
        path = self.q_config.get("answer_example_path", "")
        if not path or not Path(path).is_file():
            messagebox.showinfo("解答例画像", "この設問には解答例画像が登録されていません。",
                                parent=self._win)
            return
        try:
            image = Image.open(path).convert("RGB")
            image.thumbnail((900, 700), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
        except Exception as exc:
            messagebox.showerror("解答例画像", f"画像を表示できませんでした:\n{exc}", parent=self._win)
            return
        dialog = tk.Toplevel(self._win)
        dialog.title(f"{self.q_config['name']} — 解答例")
        dialog.transient(self._win)
        label = tk.Label(dialog, image=photo, bg="white")
        label.image = photo
        label.pack(padx=8, pady=8)
        tk.Button(dialog, text="閉じる", command=dialog.destroy).pack(pady=(0, 8))
        dialog.grab_set()

    def _schedule_annotation_save(self, _event=None):
        """回答注釈を入力停止後に自動保存する。"""
        if self._annotation_save_after_id and self._win:
            self._win.after_cancel(self._annotation_save_after_id)
        self._annotation_status.config(text="入力中…")
        self._annotation_save_after_id = self._win.after(
            400, self._commit_current_annotation
        )

    def _focus_scoring_canvas(self, _event=None):
        """注釈編集を保存し、数字キー採点を受け付ける状態へ戻す。"""
        self._commit_current_annotation(add_comment_history=True)
        self.canvas.focus_force()
        return "break"

    def _current_annotation(self, filename: str, create: bool = True) -> dict:
        answers = self.annotations.setdefault("answers", {})
        if not create:
            return answers.get(filename, {}).get(self.q_id, {})
        question_map = answers.setdefault(filename, {})
        return question_map.setdefault(self.q_id, {
            "memo": "", "comment": "", "held": False,
        })

    def _commit_current_annotation(self, add_comment_history: bool = False,
                                   add_memo_history: bool = False):
        """画面上の回答注釈をモデルへ反映し保存する。"""
        filename = self._annotation_loaded_filename
        if not filename or not hasattr(self, "_answer_memo_text"):
            return
        if self._annotation_save_after_id and self._win:
            try:
                self._win.after_cancel(self._annotation_save_after_id)
            except tk.TclError:
                pass
        self._annotation_save_after_id = None
        annotation = self._current_annotation(filename)
        annotation["memo"] = self._answer_memo_text.get("1.0", "end-1c")
        annotation["comment"] = self._answer_comment_text.get("1.0", "end-1c").strip()
        annotation["held"] = bool(self._answer_held_var.get())
        # 旧データの tags は読み込み互換のため保持するが、新規編集は行わない。

        if add_memo_history and annotation["memo"].strip():
            histories = self.annotations.setdefault("memo_history", {})
            history = update_comment_history(histories.get(self.q_id, []), annotation["memo"])
            histories[self.q_id] = history
            self._memo_history_combo.configure(values=history)

        if add_comment_history and annotation["comment"]:
            histories = self.annotations.setdefault("comment_history", {})
            comment = annotation["comment"]
            history = update_comment_history(histories.get(self.q_id, []), comment)
            histories[self.q_id] = history
            self._comment_history_combo.configure(values=history)

        if self.annotations_save_callback:
            self.annotations_save_callback()
        self._annotation_status.config(text="保存済み")

    def _load_annotation_for(self, filename: str):
        """答案切替時に回答注釈をエディタへ読み込む。"""
        if self._annotation_loaded_filename == filename:
            return
        self._commit_current_annotation(add_comment_history=True)
        annotation = self._current_annotation(filename, create=False)
        self._answer_memo_text.delete("1.0", tk.END)
        self._answer_memo_text.insert("1.0", annotation.get("memo", ""))
        self._answer_comment_text.delete("1.0", tk.END)
        self._answer_comment_text.insert("1.0", annotation.get("comment", ""))
        self._answer_held_var.set(bool(annotation.get("held", False)))
        self._update_held_status()
        self._memo_history_var.set("")
        self._comment_history_var.set("")
        self._annotation_loaded_filename = filename
        self._annotation_status.config(text="")

    def _select_comment_history(self, _event=None):
        """選択した履歴を挿入対象として保持する。"""
        return "break"

    def _insert_comment_history(self):
        """選択した履歴で、1回答1件のコメント欄を置き換える。"""
        comment = self._comment_history_var.get()
        if not comment:
            return
        self._answer_comment_text.delete("1.0", tk.END)
        self._answer_comment_text.insert("1.0", comment)
        self._schedule_annotation_save()

    def _delete_comment_history(self):
        comment = self._comment_history_var.get()
        if not comment:
            return
        histories = self.annotations.setdefault("comment_history", {})
        history = [item for item in histories.get(self.q_id, []) if item != comment]
        if history:
            histories[self.q_id] = history
        else:
            histories.pop(self.q_id, None)
        self._comment_history_var.set("")
        self._comment_history_combo.configure(values=history)
        if self.annotations_save_callback:
            self.annotations_save_callback()

    def _select_memo_history(self, _event=None):
        """選択した履歴を挿入対象として保持する。"""
        return "break"

    def _insert_memo_history(self):
        memo = self._memo_history_var.get()
        if not memo:
            return
        index = self._answer_memo_text.index(tk.INSERT)
        current = self._answer_memo_text.get("1.0", "end-1c")
        prefix = "\n" if current and not current.endswith("\n") else ""
        self._answer_memo_text.insert(index, prefix + memo)
        self._schedule_annotation_save()

    def _delete_memo_history(self):
        memo = self._memo_history_var.get()
        if not memo:
            return
        histories = self.annotations.setdefault("memo_history", {})
        history = [item for item in histories.get(self.q_id, []) if item != memo]
        if history:
            histories[self.q_id] = history
        else:
            histories.pop(self.q_id, None)
        self._memo_history_var.set("")
        self._memo_history_combo.configure(values=history)
        if self.annotations_save_callback:
            self.annotations_save_callback()

    def _update_held_status(self):
        if hasattr(self, "_held_status_label"):
            self._held_status_label.config(
                text="⏸ 保留中" if self._answer_held_var.get() else ""
            )

    def _on_hold(self):
        """現在の答案を保留にして、得点を付けず次の答案へ進む。"""
        if not self.filenames:
            return
        self._answer_held_var.set(True)
        self._update_held_status()
        self._commit_current_annotation()
        self._update_filter_list()
        self.canvas.focus_set()
        self._next_auto()

    def _clear_hold(self):
        old_index = self.current_idx
        self._answer_held_var.set(False)
        self._update_held_status()
        self._commit_current_annotation()
        self._update_filter_list()
        self.canvas.focus_set()
        if self._get_single_filter_mode() == "保留":
            if not self._filtered_indices:
                self._on_filter_change()
                return
            self.current_idx = next(
                (idx for idx in self._filtered_indices if idx > old_index),
                self._filtered_indices[0],
            )
            self._show_current()

    def _open_current_original(self):
        """現在表示中の画像の元画像をビューアで開く"""
        if not self.filenames:
            return
        fn = self.filenames[self.current_idx]
        self._open_original_image(fn)

    def _edit_rubric_dialog(self):
        """一覧モードから採点基準メモを編集する。"""
        dialog = tk.Toplevel(self._win)
        dialog.title(f"{self.q_config['name']} — 採点基準メモ")
        dialog.transient(self._win)
        frame = tk.Frame(dialog, padx=15, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)
        memo = tk.Text(
            frame, width=55, height=10, wrap=tk.WORD,
            font=(UI_FONT, get_ui_font_size(9)), bg="#FFFFFF", fg="#222222",
            insertbackground="#222222", relief=tk.SOLID, bd=1,
            highlightthickness=1, highlightbackground="#9E9E9E",
            highlightcolor="#1976D2",
        )
        memo.pack(fill=tk.BOTH, expand=True)
        memo.insert("1.0", self.q_config.get("rubric_memo", ""))

        def _save():
            value = memo.get("1.0", "end-1c")
            self.q_config["rubric_memo"] = value
            if hasattr(self, "_rubric_text"):
                self._rubric_text.delete("1.0", tk.END)
                self._rubric_text.insert("1.0", value)
            if self.rubric_save_callback:
                self.rubric_save_callback()
            dialog.destroy()

        buttons = tk.Frame(frame)
        buttons.pack(pady=(10, 0))
        tk.Button(buttons, text="保存", command=_save, width=10,
                  bg="#4CAF50").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons, text="キャンセル", command=dialog.destroy,
                  width=10).pack(side=tk.LEFT, padx=4)
        fit_window_to_content(dialog, min_width=520, min_height=320)
        dialog.grab_set()
        memo.focus_set()

    # ─── グリッドパネル構築 ───

    def _build_grid_panel(self):
        """一覧モードのUI部品を構築する"""
        BG = "#F5F7FA"
        gf = self._grid_frame

        # 上部: ソート + 進捗
        top_bar = tk.Frame(gf, bg=BG)
        top_bar.pack(fill=tk.X, padx=8, pady=(8, 3))

        tk.Label(top_bar, text="並び順:", font=(UI_FONT, get_ui_font_size(9)), bg=BG).pack(side=tk.LEFT)
        self._grid_sort_var = tk.StringVar(value="ファイル名順")
        sort_combo = ttk.Combobox(top_bar, textvariable=self._grid_sort_var,
                                  values=["ファイル名順", "得点 昇順", "得点 降順",
                                          "画像の白さ（白い順）"],
                                  state="readonly", width=18)
        sort_combo.pack(side=tk.LEFT, padx=(3, 10))
        sort_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_grid())

        self._grid_progress_var = tk.StringVar()
        tk.Label(top_bar, textvariable=self._grid_progress_var,
                 font=(UI_FONT, get_ui_font_size(9), "bold"), bg=BG, fg="#555").pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(top_bar, text="", bg=BG).pack(side=tk.LEFT, expand=True)  # spacer

        tk.Button(top_bar, text="📋 採点基準メモ", command=self._edit_rubric_dialog,
                  bg="#FFF3E0", font=(UI_FONT, get_ui_font_size(8)),
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.RIGHT, padx=(0, 6))

        tk.Button(top_bar, text="✔ この問題の採点完了", command=self._finish,
                  bg="#4CAF50", fg="black", font=(UI_FONT, get_ui_font_size(9), "bold"),
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.RIGHT)

        # スクロール領域
        scroll_frame = tk.Frame(gf, bg=BG)
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=8)

        self._grid_canvas = tk.Canvas(scroll_frame, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(scroll_frame, orient=tk.VERTICAL, command=self._grid_canvas.yview)
        self._grid_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._grid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_inner = tk.Frame(self._grid_canvas, bg=BG)
        self._grid_canvas_window = self._grid_canvas.create_window(
            (0, 0), window=self._grid_inner, anchor="nw")

        self._grid_inner.bind("<Configure>",
                              lambda e: self._grid_canvas.configure(scrollregion=self._grid_canvas.bbox("all")))
        self._grid_canvas.bind("<Configure>", self._on_grid_canvas_resize)
        self._grid_canvas.bind("<Enter>",
                               lambda e: self._grid_canvas.bind_all("<MouseWheel>", self._on_grid_mousewheel))
        self._grid_canvas.bind("<Leave>",
                               lambda e: self._grid_canvas.unbind_all("<MouseWheel>"))

        # 下部: 得点ボタン行（連続クリック用）
        score_bar = tk.Frame(gf, bg="#ECEFF1", padx=8, pady=8)
        score_bar.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Label(score_bar, text="得点ボタン（クリック後、サムネイルをクリックで得点付与）:",
                 font=(UI_FONT, get_ui_font_size(9)), bg="#ECEFF1", fg="#555").pack(side=tk.LEFT, padx=(0, 8))

        # 得点ボタンはtk.Buttonではなくtk.Labelで自作する。macOSのAquaテーマでは
        # tk.Buttonのbg/relief変更がネイティブ描画に反映されず、選択状態が
        # 見た目上まったく変化しないため（tk.Frame/tk.Labelは汎用Tk描画のため
        # bg変更が正しく反映される。_refresh_gridのカード背景色切替と同じ理由）。
        self._grid_score_buttons: Dict[int, tk.Label] = {}
        for i in range(min(self.max_score + 1, 11)):
            btn = tk.Label(score_bar, text=str(i), width=3, font=(UI_FONT, get_ui_font_size(10), "bold"),
                           bg="#E3F2FD", relief=tk.RAISED, bd=1, cursor="hand2")
            btn.pack(side=tk.LEFT, padx=2)
            btn.bind("<Button-1>", lambda e, s=i: self._on_grid_score_btn(s))
            self._grid_score_buttons[i] = btn

        # 配点 > 10 の場合はEntry
        if self.max_score > 10:
            tk.Label(score_bar, text="得点:", font=(UI_FONT, get_ui_font_size(9)),
                     bg="#ECEFF1").pack(side=tk.LEFT, padx=(10, 3))
            self._grid_score_entry = tk.Entry(score_bar, width=5, font=(UI_FONT, get_ui_font_size(10)),
                                              justify=tk.CENTER)
            self._grid_score_entry.pack(side=tk.LEFT)
            tk.Button(score_bar, text="選択", font=(UI_FONT, get_ui_font_size(9)), bg="#90CAF9",
                      relief=tk.FLAT, command=self._on_grid_score_entry_select).pack(side=tk.LEFT, padx=3)

        # 答案プレビューボタン（同上の理由でtk.Labelを使用）
        self._grid_preview_btn = tk.Label(
            score_bar, text="📷 答案を表示",
            font=(UI_FONT, get_ui_font_size(9), "bold"),
            bg="#E3F2FD", relief=tk.RAISED, bd=1, cursor="hand2", padx=4, pady=2,
        )
        self._grid_preview_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._grid_preview_btn.bind("<Button-1>", lambda e: self._on_grid_preview_btn())

        # クリアボタン
        tk.Button(score_bar, text="選択解除", font=(UI_FONT, get_ui_font_size(8)),
                  bg="#E0E0E0", relief=tk.FLAT, cursor="hand2",
                  command=self._grid_clear_active).pack(side=tk.RIGHT, padx=(4, 0))

        self._grid_active_label = tk.Label(score_bar, text="",
                                           font=(UI_FONT, get_ui_font_size(9), "bold"),
                                           bg="#ECEFF1", fg="#E65100")
        self._grid_active_label.pack(side=tk.RIGHT, padx=(0, 10))

    def _on_grid_canvas_resize(self, event):
        """Canvas幅にinner Frameを合わせ、列数を再計算"""
        self._grid_canvas.itemconfig(self._grid_canvas_window, width=event.width)
        # 列数を再計算
        new_cols = max(1, event.width // (self._grid_thumb_size + 14))
        if new_cols != self._grid_cols:
            self._grid_cols = new_cols
            # デバウンスしてリフレッシュ
            if hasattr(self, '_resize_after_id') and self._resize_after_id:
                self._win.after_cancel(self._resize_after_id)
            self._resize_after_id = self._win.after(100, self._refresh_grid)

    def _on_grid_mousewheel(self, event):
        """マウスホイールでスクロール"""
        if self._mode_var.get() == "一覧":
            self._grid_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _ensure_scroll_binding(self):
        """マウスが既にCanvas内にある場合、スクロールバインドを有効にする。

        グリッド描画完了後に呼び出す。マウスがウィンドウ外から入った場合は
        <Enter> イベントで自動バインドされるが、描画開始前にカーソルが
        既にCanvas内にあると <Enter> が発火しないため、ここで補完する。
        """
        try:
            mx = self._win.winfo_pointerx()
            my = self._win.winfo_pointery()
            cx = self._grid_canvas.winfo_rootx()
            cy = self._grid_canvas.winfo_rooty()
            cw = self._grid_canvas.winfo_width()
            ch = self._grid_canvas.winfo_height()
            if cx <= mx <= cx + cw and cy <= my <= cy + ch:
                self._grid_canvas.bind_all("<MouseWheel>", self._on_grid_mousewheel)
        except Exception:
            pass

    # ─── グリッド得点操作 ───

    def _on_grid_score_btn(self, score: int):
        """得点ボタン押下 → アクティブ得点設定"""
        self._grid_active_score = score
        self._grid_preview_mode = False
        self._grid_active_label.config(text=f"アクティブ: {score}点")
        self._grid_preview_btn.config(bg="#E3F2FD", relief=tk.RAISED)
        # ボタン強調
        for s, btn in self._grid_score_buttons.items():
            if s == score:
                btn.config(bg="#FF8A65", relief=tk.SUNKEN)
            else:
                btn.config(bg="#E3F2FD", relief=tk.RAISED)

    def _on_grid_score_entry_select(self):
        """Entry入力からアクティブ得点を設定"""
        if not hasattr(self, '_grid_score_entry'):
            return
        text = self._grid_score_entry.get().strip()
        try:
            score = int(text)
            if 0 <= score <= self.max_score:
                self._grid_active_score = score
                self._grid_preview_mode = False
                self._grid_active_label.config(text=f"アクティブ: {score}点")
                self._grid_preview_btn.config(bg="#E3F2FD", relief=tk.RAISED)
                # ボタン強調をクリア
                for btn in self._grid_score_buttons.values():
                    btn.config(bg="#E3F2FD", relief=tk.RAISED)
        except ValueError:
            pass

    def _on_grid_preview_btn(self):
        """答案プレビューモードの切替"""
        self._grid_preview_mode = not getattr(self, '_grid_preview_mode', False)
        if self._grid_preview_mode:
            # プレビューモードON → 得点選択を解除
            self._grid_active_score = None
            self._grid_active_label.config(text="プレビュー: クリックで答案を表示")
            for btn in self._grid_score_buttons.values():
                btn.config(bg="#E3F2FD", relief=tk.RAISED)
            self._grid_preview_btn.config(bg="#FF8A65", relief=tk.SUNKEN)
        else:
            self._grid_preview_mode = False
            self._grid_active_label.config(text="")
            self._grid_preview_btn.config(bg="#E3F2FD", relief=tk.RAISED)

    def _grid_clear_active(self):
        """アクティブ得点を解除する"""
        self._grid_active_score = None
        self._grid_preview_mode = False
        self._grid_active_label.config(text="")
        self._grid_preview_btn.config(bg="#E3F2FD", relief=tk.RAISED)
        for btn in self._grid_score_buttons.values():
            btn.config(bg="#E3F2FD", relief=tk.RAISED)

    def _on_grid_card_click(self, fn: str, event=None):
        """サムネイルカードクリック時の処理

        プレビューモード時は答案全体を表示。
        得点選択時はスコアを付与。
        """
        # プレビューモード → 元画像を表示
        if getattr(self, '_grid_preview_mode', False):
            self._open_original_image(fn)
            return
        if self._grid_active_score is not None:
            self.local_scores[fn] = self._grid_active_score
            self._update_single_card(fn)
        else:
            # アクティブ得点がなければ何もしない
            pass

    def _open_original_image(self, fn: str):
        """純粋な元画像をOSのデフォルトビューアで開く

        original_image_folder（マーク描画なし）があればそちらを優先。
        なければ image_folder（00_Processing）にフォールバック。
        """
        # 優先: 純粋なスキャン原本
        for folder in [self.original_image_folder, self.image_folder]:
            if not folder:
                continue
            img_path = Path(folder) / fn
            if img_path.exists():
                try:
                    open_in_default_viewer(img_path)
                except Exception:
                    pass
                return

    # ─── グリッド表示更新 ───

    @staticmethod
    def _score_to_card_style(score, max_score):
        """スコアからカード背景色・マーク記号・色を返す"""
        if score is None:
            return "#F5F5F5", "─", "#999"
        if score >= max_score:
            return "#E3F2FD", "○", "#1565C0"
        if score == 0:
            return "#FFEBEE", "×", "#C62828"
        return "#FFF3E0", "△", "#E65100"

    def _refresh_grid(self):
        """グリッドの内容を再描画"""
        for widget in self._grid_inner.winfo_children():
            widget.destroy()
        self._grid_card_refs: Dict[str, dict] = {}

        BG = "#F5F7FA"

        # ソート
        sort_key = self._grid_sort_var.get()
        filenames = list(self.filenames)
        if sort_key == "得点 昇順":
            filenames.sort(key=lambda f: (self.local_scores.get(f) is None,
                                          self.local_scores.get(f, 0)))
        elif sort_key == "得点 降順":
            filenames.sort(key=lambda f: (self.local_scores.get(f) is None,
                                          -(self.local_scores.get(f, 0))))
        elif sort_key == "画像の白さ（白い順）":
            filenames.sort(key=lambda f: -self._compute_whiteness(f))

        # 列数を現在のキャンバス幅から動的に決定
        canvas_w = self._grid_canvas.winfo_width()
        if canvas_w <= 1:
            canvas_w = 900
        cols = max(1, canvas_w // (self._grid_thumb_size + 14))
        self._grid_cols = cols

        # 進捗更新
        self._update_grid_progress()

        # カード配置
        cols = self._grid_cols
        thumb_size = self._grid_thumb_size

        for i, fn in enumerate(filenames):
            row, col = divmod(i, cols)

            score = self.local_scores.get(fn)
            card_bg, mark_text, mark_fg = self._score_to_card_style(score, self.max_score)

            card = tk.Frame(self._grid_inner, bg=card_bg, bd=1, relief=tk.RAISED,
                            padx=3, pady=3, cursor="hand2")
            card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            card.bind("<Button-1>", lambda e, f=fn: self._on_grid_card_click(f, e))

            # サムネイル表示
            thumb_label = tk.Label(card, bg=card_bg)
            thumb_label.pack()
            thumb_label.bind("<Button-1>", lambda e, f=fn: self._on_grid_card_click(f, e))

            self._load_grid_thumb(fn, thumb_label, thumb_size)

            # スコア行
            score_frame = tk.Frame(card, bg=card_bg)
            score_frame.pack(fill=tk.X)
            score_frame.bind("<Button-1>", lambda e, f=fn: self._on_grid_card_click(f, e))

            mark_label = tk.Label(score_frame, text=mark_text,
                                  font=(UI_FONT, get_ui_font_size(12), "bold"),
                                  fg=mark_fg, bg=card_bg)
            mark_label.pack(side=tk.LEFT)

            score_text = f"{score}点" if score is not None else "未採点"
            score_label = tk.Label(score_frame, text=score_text,
                                   font=(UI_FONT, get_ui_font_size(8)),
                                   fg="#555", bg=card_bg)
            score_label.pack(side=tk.LEFT, padx=3)

            # ファイル名ラベル
            short_fn = fn[:20] + "…" if len(fn) > 20 else fn
            fn_label = tk.Label(card, text=short_fn, font=(UI_FONT, get_ui_font_size(7)),
                                fg="#777", bg=card_bg, wraplength=thumb_size)
            fn_label.pack()

            # 差分更新用にウィジェット参照を保持
            self._grid_card_refs[fn] = {
                "card": card, "thumb": thumb_label,
                "score_frame": score_frame, "mark": mark_label,
                "score": score_label, "fn_label": fn_label,
            }

        # 列 weight 設定
        for c in range(cols):
            self._grid_inner.columnconfigure(c, weight=1)

        # マウスが既にCanvas内にいればスクロールを有効化
        self._win.after_idle(self._ensure_scroll_binding)

    def _update_grid_progress(self):
        """進捗ラベルだけ更新する"""
        scored = len(self.local_scores)
        total = len(self.filenames)
        unscored = total - scored
        prog_text = f"採点済み: {scored}/{total}"
        if unscored > 0:
            prog_text += f"  (未採点: {unscored})"
        self._grid_progress_var.set(prog_text)

    def _update_single_card(self, fn: str):
        """1枚のカードだけスコア表示を差分更新する（全体再描画を回避）"""
        refs = self._grid_card_refs.get(fn)
        if refs is None:
            # カード参照がない場合はフォールバック
            self._refresh_grid()
            return

        score = self.local_scores.get(fn)
        card_bg, mark_text, mark_fg = self._score_to_card_style(score, self.max_score)

        # 背景色を一括変更
        for key in ("card", "thumb", "score_frame", "fn_label"):
            refs[key].config(bg=card_bg)

        # マーク記号
        refs["mark"].config(text=mark_text, fg=mark_fg, bg=card_bg)

        # スコアテキスト
        score_text = f"{score}点" if score is not None else "未採点"
        refs["score"].config(text=score_text, bg=card_bg)

        # 進捗更新
        self._update_grid_progress()

    def _load_grid_thumb(self, fn: str, label: tk.Label, size: int):
        """サムネイルを読み込んでラベルに表示"""
        if fn in self._grid_thumb_cache:
            label.config(image=self._grid_thumb_cache[fn])
            return

        img_path = self.image_paths.get(fn)
        if not img_path:
            return

        try:
            pil_img = Image.open(img_path)
            # 幅を size に合わせてリサイズ（高さは比率維持）
            target_w = size
            scale = target_w / max(pil_img.width, 1)
            target_h = max(1, int(pil_img.height * scale))
            # 高さが極端に大きい場合は上限制限
            max_h = size * 3
            if target_h > max_h:
                scale = max_h / max(pil_img.height, 1)
                target_w = max(1, int(pil_img.width * scale))
                target_h = max_h
            pil_img = pil_img.resize((target_w, target_h), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img, master=self._win)
            self._grid_thumb_cache[fn] = tk_img
            label.config(image=tk_img)
            pil_img.close()

            # キャッシュ上限
            if len(self._grid_thumb_cache) > 500:
                keys = list(self._grid_thumb_cache.keys())
                for k in keys[:250]:
                    del self._grid_thumb_cache[k]
        except Exception:
            pass

    # ─── モード切替 ───

    def _on_mode_change(self, event=None):
        """表示モード変更時"""
        mode = self._mode_var.get()
        if mode == "1枚ずつ":
            self._grid_frame.pack_forget()
            self._zoom_bar.pack_forget()
            self._single_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            self._show_current()
        else:
            self._single_frame.pack_forget()
            self._zoom_bar.pack(fill=tk.X)
            self._grid_frame.pack(fill=tk.BOTH, expand=True)
            self._refresh_grid()

    # ─── ズーム操作（スライダー） ───

    def _on_zoom_slider_change(self, value):
        """スライダー変更時にサムネイルサイズを更新（デバウンス付き）"""
        new_size = int(float(value))
        self._grid_thumb_size = new_size
        self._zoom_label_var.set(f"{new_size}px")
        # 列数を再計算
        canvas_w = self._grid_canvas.winfo_width()
        if canvas_w <= 1:
            canvas_w = 900
        self._grid_cols = max(1, canvas_w // (new_size + 14))
        # デバウンスしてリフレッシュ
        self._grid_thumb_cache.clear()
        if self._zoom_after_id:
            self._win.after_cancel(self._zoom_after_id)
        self._zoom_after_id = self._win.after(150, self._refresh_grid)

    def _compute_whiteness(self, fn: str) -> float:
        """画像の白さ（平均輝度）を計算してキャッシュ"""
        if not hasattr(self, '_whiteness_cache'):
            self._whiteness_cache: Dict[str, float] = {}
        if fn in self._whiteness_cache:
            return self._whiteness_cache[fn]
        img_path = self.image_paths.get(fn)
        if not img_path:
            return 0.0
        try:
            pil_img = Image.open(img_path).convert("L")
            pil_img.thumbnail((100, 100), Image.LANCZOS)
            arr = np.array(pil_img, dtype=np.float64)
            brightness = float(np.mean(arr))
            pil_img.close()
            self._whiteness_cache[fn] = brightness
            return brightness
        except Exception:
            return 0.0

    def _on_single_zoom_change(self, value):
        """1枚ずつモードのズームスライダー変更"""
        self._single_zoom_factor = int(float(value))
        label_text = f"{self._single_zoom_factor}%"
        if self._single_zoom_factor == 100:
            label_text += " (自動フィット)"
        self._single_zoom_label.config(text=label_text)
        # デバウンスして再描画
        if self._single_zoom_after_id:
            self._win.after_cancel(self._single_zoom_after_id)
        self._single_zoom_after_id = self._win.after(100, self._show_current)

    def _change_single_zoom(self, factor: float):
        current = self._single_zoom_factor if self._single_zoom_factor != 100 else 100
        self._single_zoom_factor = max(25, min(400, int(round(current * factor))))
        self._single_zoom_label.config(text=f"{self._single_zoom_factor}%")
        self._show_current()

    def _fit_single_image(self):
        self._single_zoom_factor = 100
        self._single_zoom_label.config(text="自動フィット")
        self._show_current()

    def _on_single_canvas_resize(self, _event=None):
        # ウィンドウサイズ変更時は自動フィットを常に再計算する。
        if self._single_zoom_factor == 100 and self._win:
            if self._single_zoom_after_id:
                self._win.after_cancel(self._single_zoom_after_id)
            self._single_zoom_after_id = self._win.after(80, self._show_current)

    def _start_single_pan(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _drag_single_pan(self, event):
        if self._single_zoom_factor > 100:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _end_single_pan(self, _event):
        pass

    def _show_magnifier(self, event):
        """ダブルクリック位置に、その部分だけを拡大した虫眼鏡枠を表示する。"""
        image = getattr(self, "_display_pil_image", None)
        item = getattr(self, "_single_image_item", None)
        if image is None or item is None:
            return "break"
        if self.canvas.find_withtag("magnifier"):
            self.canvas.delete("magnifier")
            return "break"
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        left, top, right, bottom = self.canvas.bbox(item)
        ix = int((x - left) * image.width / max(right - left, 1))
        iy = int((y - top) * image.height / max(bottom - top, 1))
        radius = 70
        crop = image.crop((max(0, ix - radius), max(0, iy - radius),
                           min(image.width, ix + radius), min(image.height, iy + radius)))
        crop = crop.resize((220, 220), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(crop, master=self._win)
        self._magnifier_photo = photo
        self.canvas.create_rectangle(x - 112, y - 112, x + 112, y + 112,
                                     outline="#1976D2", width=3, fill="white",
                                     tags="magnifier")
        self.canvas.create_image(x, y, image=photo, anchor=tk.CENTER, tags="magnifier")
        return "break"

    def _show_current(self):
        """現在の画像を表示"""
        if not self.filenames:
            return

        fn = self.filenames[self.current_idx]
        img_path = self.image_paths.get(fn)

        if hasattr(self, "_answer_memo_text"):
            self._load_annotation_for(fn)

        self.progress_var.set(f"{self.current_idx + 1} / {len(self.filenames)}")
        self.filename_var.set(fn)

        # 未採点カウント更新
        unscored = sum(1 for f in self.filenames if f not in self.local_scores)
        if hasattr(self, '_unscored_var'):
            if unscored > 0:
                filter_mode = self._get_single_filter_mode()
                filt_text = f" ({filter_mode}表示中)" if filter_mode != "全件" else ""
                self._unscored_var.set(f"未採点: {unscored}件{filt_text}")
            else:
                self._unscored_var.set("✅ 全件採点済み")

        # 得点表示更新
        if fn in self.local_scores:
            self.score_var.set(str(self.local_scores[fn]))
        else:
            self.score_var.set("—")

        # 数値入力欄があれば更新
        if self.use_entry and hasattr(self, 'score_entry'):
            self.score_entry.delete(0, tk.END)
            if fn in self.local_scores:
                self.score_entry.insert(0, str(self.local_scores[fn]))
            self.score_entry.focus_set()

        # 画像表示
        if img_path is None:
            self.canvas.delete("all")
            self.canvas.create_text(200, 200, text="画像なし", fill="gray")
            return

        try:
            self.canvas.update_idletasks()
            canvas_w = max(self.canvas.winfo_width(), 300)
            canvas_h = max(self.canvas.winfo_height(), 300)

            pil_img = Image.open(img_path)

            # 画像サイズ安全チェック (100Mpx 以上はメモリ不足のリスク)
            _MAX_SAFE_PIXELS = 100_000_000
            if pil_img.width * pil_img.height > _MAX_SAFE_PIXELS:
                pil_img.close()
                self.canvas.delete("all")
                self.canvas.create_text(200, 200,
                    text=f"画像が大きすぎます\n({pil_img.width}x{pil_img.height})",
                    fill="red")
                return

            # キャンバスに収まるようリサイズ（最大3倍まで拡大可）
            ratio_w = canvas_w / pil_img.width
            ratio_h = canvas_h / pil_img.height
            base_ratio = min(ratio_w, ratio_h, 3.0)

            # ズームスライダーの倍率を適用
            zoom_pct = getattr(self, '_single_zoom_factor', 100)
            ratio = base_ratio * (zoom_pct / 100.0)

            new_w = max(1, int(pil_img.width * ratio))
            new_h = max(1, int(pil_img.height * ratio))
            # 表示サイズ上限 (4000px) — 超高解像度画像の安全弁
            _MAX_DISPLAY_PX = 4000
            if max(new_w, new_h) > _MAX_DISPLAY_PX:
                ratio = _MAX_DISPLAY_PX / max(pil_img.width, pil_img.height)
                new_w = max(1, int(pil_img.width * ratio))
                new_h = max(1, int(pil_img.height * ratio))
            pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)

            self._display_pil_image = pil_img.copy()
            tk_img = ImageTk.PhotoImage(pil_img, master=self._win)
            # LRU キャッシュ: 古い画像を解放してメモリ消費を抑制
            # ズーム変更時はキャッシュを無効化するためキーにズーム%を含める
            cache_key = f"{fn}_{zoom_pct}"
            if fn in self._tk_images:
                self._tk_images_order.remove(fn)
            self._tk_images[fn] = tk_img
            self._tk_images_order.append(fn)
            while len(self._tk_images_order) > self._MAX_IMG_CACHE:
                oldest = self._tk_images_order.pop(0)
                del self._tk_images[oldest]

            self.canvas.delete("all")
            # ズーム拡大時はスクロール領域を設定
            if new_w > canvas_w or new_h > canvas_h:
                self.canvas.configure(scrollregion=(0, 0, new_w, new_h))
                self._single_image_item = self.canvas.create_image(
                    new_w // 2, new_h // 2,
                    image=tk_img, anchor=tk.CENTER,
                )
            else:
                self.canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))
                self._single_image_item = self.canvas.create_image(
                    canvas_w // 2, canvas_h // 2,
                    image=tk_img, anchor=tk.CENTER,
                )
            pil_img.close()
        except Exception as e:
            self.canvas.delete("all")
            self.canvas.create_text(
                200, 200, text=f"画像表示エラー:\n{e}", fill="red",
            )

    def _on_key(self, event):
        """キー入力処理"""
        if not self.filenames:
            return

        # メモや得点入力欄への文字入力を採点ショートカットとして扱わない。
        if isinstance(event.widget, (tk.Entry, tk.Text, ttk.Entry, tk.Listbox)):
            return

        key = event.keysym

        # p / P: 元画像をビューアで開く
        # m / b はモード問わず常に有効
        if key == "m":
            self._on_maru()
            return "break"
        elif key == "b":
            self._on_batsu()
            return "break"

        # 数値入力モードでは Entry にフォーカスがあるため、
        # Entry へのキー入力はここでは処理しない
        if self.use_entry:
            return

        if key in [str(i) for i in range(10)]:
            score = int(key)
            if score > self.max_score:
                return
            if score in self.score_checks and not self.score_checks[score].get():
                return

            fn = self.filenames[self.current_idx]
            self._assign_score(fn, score)

        # macOSのJIS「英数」「かな」はspace相当として通知される場合があるため、
        # 物理キーコードを含めて通常のスペースキーだけを受け付ける。
        elif is_grading_space_key(event):
            self._next_auto()

        elif key in ("Delete", "BackSpace"):
            fn = self.filenames[self.current_idx]
            if fn in self.local_scores:
                del self.local_scores[fn]
                self.score_var.set("—")
                self._update_filter_list()

    # ─── 〇 / × ボタン・背景フィードバック ───

    def _on_maru(self):
        """〇ボタン（満点を付与）"""
        if not self.filenames:
            return
        fn = self.filenames[self.current_idx]
        self._assign_score(fn, self.max_score)

    def _on_batsu(self):
        """×ボタン（0点を付与）"""
        if not self.filenames:
            return
        fn = self.filenames[self.current_idx]
        self._assign_score(fn, 0)

    def _assign_score(self, fn: str, score: int):
        """スコアを設定し、背景色フィードバックを表示して次へ進む。"""
        self.local_scores[fn] = score
        self.score_var.set(str(score))
        self._flash_background(score)
        self._update_filter_list()
        # 少し待ってから自動で次へ
        self._win.after(200, self._next_auto)

    def _flash_background(self, score: int):
        """得点に応じた背景色を一時的にCanvasに表示する。

        満点→薄青、0点→薄赤、中間点→薄橙。400ms後に白に戻す。
        """
        if score >= self.max_score:
            bg_color = "#E3F2FD"  # 薄青
        elif score == 0:
            bg_color = "#FFEBEE"  # 薄赤
        else:
            bg_color = "#FFF3E0"  # 薄橙
        self.canvas.config(bg=bg_color)
        self._win.after(400, lambda: self.canvas.config(bg="white"))

    # ─── フィルタ ───

    def _on_filter_change(self):
        """1枚ずつ採点の表示フィルタ変更時。"""
        self._commit_current_annotation(add_comment_history=True)
        self._update_filter_list()
        filter_mode = self._get_single_filter_mode()
        if filter_mode != "全件" and not self._filtered_indices:
            self.canvas.delete("all")
            self.canvas.configure(scrollregion=(0, 0, 600, 400))
            if filter_mode == "保留":
                message = "保留中の答案はありません"
                progress = f"全 {len(self.filenames)} 枚 / 保留 0 枚"
            else:
                message = "✅ すべての答案に得点が登録されています"
                progress = f"全 {len(self.filenames)} 枚 採点済み"
            self.canvas.create_text(
                300, 180, text=message,
                font=(UI_FONT, get_ui_font_size(13), "bold"), fill="#388E3C",
            )
            self.progress_var.set(progress)
            self.score_var.set("—")
            return
        # フィルタ後のリストで先頭を表示
        if self._filtered_indices:
            self.current_idx = self._filtered_indices[0]
        self._show_current()

    def _update_filter_list(self):
        """フィルタ済みインデックスリストを更新する。"""
        filter_mode = self._get_single_filter_mode()
        if filter_mode == "未採点":
            self._filtered_indices = [
                i for i, fn in enumerate(self.filenames)
                if fn not in self.local_scores
            ]
        elif filter_mode == "保留":
            answers = self.annotations.get("answers", {})
            self._filtered_indices = [
                i for i, fn in enumerate(self.filenames)
                if answers.get(fn, {}).get(self.q_id, {}).get("held", False)
            ]
        else:
            self._filtered_indices = list(range(len(self.filenames)))

    def _get_single_filter_mode(self) -> str:
        """現在の1枚ずつ採点フィルタを返す（旧テスト用変数にも対応）。"""
        if hasattr(self, "_single_filter_var"):
            mode = self._single_filter_var.get()
            if mode in ("全件", "未採点", "保留"):
                return mode
        if hasattr(self, "_filter_unscored_var") and self._filter_unscored_var.get():
            return "未採点"
        return "全件"

    def _submit_entry_score(self):
        """数値入力欄からの得点確定（配点>9の場合用）"""
        if not hasattr(self, 'score_entry'):
            return

        text = self.score_entry.get().strip()
        if not text:
            self._next_auto()
            return

        try:
            score = int(text)
        except ValueError:
            messagebox.showwarning(
                "入力エラー", "整数で入力してください。", parent=self._win,
            )
            return

        if score < 0 or score > self.max_score:
            messagebox.showwarning(
                "入力エラー", f"0〜{self.max_score} の範囲で入力してください。",
                parent=self._win,
            )
            return

        fn = self.filenames[self.current_idx]
        self._assign_score(fn, score)

    def _next_auto(self, event=None):
        """自動で次へ（フィルタ考慮）。全件採点済みなら完了ダイアログを表示。"""
        next_idx = self._find_next_filtered(self.current_idx)
        if next_idx is not None:
            self.current_idx = next_idx
            self._show_current()
        else:
            # 保留レビューの末尾では採点完了ダイアログを出さない。
            if self._get_single_filter_mode() == "保留":
                return
            # 次がない → 全件採点済みか確認
            unscored = sum(1 for f in self.filenames if f not in self.local_scores)
            if unscored == 0:
                self._show_all_scored_dialog()

    def _next(self, event=None):
        """次の画像（フィルタ考慮）"""
        next_idx = self._find_next_filtered(self.current_idx)
        if next_idx is not None:
            self.current_idx = next_idx
            self._show_current()

    def _prev(self, event=None):
        """前の画像（フィルタ考慮）"""
        prev_idx = self._find_prev_filtered(self.current_idx)
        if prev_idx is not None:
            self.current_idx = prev_idx
            self._show_current()

    def _find_next_filtered(self, current: int) -> Optional[int]:
        """フィルタリスト内で current より後の次インデックスを返す。"""
        for idx in self._filtered_indices:
            if idx > current:
                return idx
        return None

    def _find_prev_filtered(self, current: int) -> Optional[int]:
        """フィルタリスト内で current より前のインデックスを返す。"""
        for idx in reversed(self._filtered_indices):
            if idx < current:
                return idx
        return None

    def _jump_to_unscored(self, event=None):
        """次の未採点画像にジャンプする（Tab キー）。

        現在位置より後ろを優先的に探索し、見つからなければ先頭から探す。
        全て採点済みの場合は何もしない。
        """
        n = len(self.filenames)
        # 現在位置+1 から順に探索（ラップアラウンド）
        for offset in range(1, n + 1):
            idx = (self.current_idx + offset) % n
            if self.filenames[idx] not in self.local_scores:
                self.current_idx = idx
                self._show_current()
                return
        # 全採点済み → 何もしない
        return "break"

    def _show_all_scored_dialog(self):
        """全答案の採点が完了した際のカスタムダイアログ"""
        dlg = tk.Toplevel(self._win)
        dlg.title("採点完了")
        dlg.resizable(True, True)
        dlg.transient(self._win)

        body = tk.Frame(dlg, padx=20, pady=15)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text=f"✅ {len(self.filenames)} 枚すべての採点が完了しました",
            font=(UI_FONT, get_ui_font_size(11), "bold"), fg="#2E7D32",
        ).pack(pady=(0, 15))

        btn_frame = tk.Frame(body)
        btn_frame.pack()

        def _go_back():
            dlg.destroy()
            self._result = {}
            for fn, score in self.local_scores.items():
                self._result[fn] = {self.q_id: score}
            self._win.destroy()

        def _continue():
            dlg.destroy()

        tk.Button(
            btn_frame, text="問題選択に戻る",
            command=_go_back,
            font=(UI_FONT, get_ui_font_size(10), "bold"),
            bg="#4CAF50", fg="black", relief=tk.FLAT,
            cursor="hand2", padx=12, pady=4,
        ).pack(side=tk.LEFT, padx=8)

        tk.Button(
            btn_frame, text="採点を続ける",
            command=_continue,
            font=(UI_FONT, get_ui_font_size(10)),
            bg="#E0E0E0", relief=tk.FLAT,
            cursor="hand2", padx=12, pady=4,
        ).pack(side=tk.LEFT, padx=8)

        fit_window_to_content(dlg, min_width=360, min_height=150)
        dlg.grab_set()
        dlg.focus_force()
        dlg.wait_window()

    def _cleanup_bindings(self):
        """ウィンドウ破棄前にグローバルバインドを解除する"""
        try:
            self._grid_canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _finish(self):
        """この問題の採点完了"""
        self._save_rubric_now()
        self._commit_current_annotation(add_comment_history=True)
        scored = len(self.local_scores)
        total = len(self.filenames)

        if scored < total:
            if not messagebox.askyesno(
                "確認",
                f"未採点の答案が {total - scored} 件あります。\n"
                "このまま完了しますか？\n（未採点は0点として扱われます）",
                parent=self._win,
            ):
                return

        self._result = {}
        for fn, score in self.local_scores.items():
            self._result[fn] = {self.q_id: score}

        self._cleanup_bindings()
        self._win.destroy()

    def _cancel(self):
        """キャンセル — 入力済みのデータがある場合は保存するか確認する。"""
        self._save_rubric_now()
        self._commit_current_annotation(add_comment_history=True)
        if self.local_scores:
            answer = _ask_three_way_japanese(
                "採点の中断",
                "ここまでの採点結果を保存しますか？",
                parent=self._win,
                yes_text="保存して戻る",
                no_text="保存せず破棄",
                cancel_text="採点を続ける",
            )
            if answer is None:
                # キャンセル → 採点続行
                return
            if answer:
                # はい → 保存して戻る（_finish と同じ処理）
                self._result = {}
                for fn, score in self.local_scores.items():
                    self._result[fn] = {self.q_id: score}
                self._cleanup_bindings()
                self._win.destroy()
                return
            # いいえ → 破棄
        self._result = None
        self._cleanup_bindings()
        self._win.destroy()


# ============================================================
#   α: 記述採点の確認・修正 GUI
# ============================================================

def filter_descriptive_review_answers(
    image_files: List[str],
    scores: dict,
    annotations: dict,
    question_id: str,
    max_score: int,
    filter_value: str,
) -> List[Tuple[str, Optional[int]]]:
    """確認画面の状態フィルタを適用する（GUIに依存しない純粋関数）。"""
    filtered: List[Tuple[str, Optional[int]]] = []
    answers = annotations.get("answers", {})
    for filename in image_files:
        score = scores.get(filename, {}).get(question_id)
        annotation = answers.get(filename, {}).get(question_id, {})
        include = (
            filter_value == "全て"
            or (filter_value == "未採点" and score is None)
            or (filter_value == "採点済み" and score is not None)
            or (filter_value == "保留" and bool(annotation.get("held", False)))
            or (filter_value == "コメントあり" and bool(str(annotation.get("comment", "")).strip()))
            or (filter_value == "○ 満点" and score is not None and score >= max_score)
            or (filter_value == "× 0点" and score is not None and score == 0)
            or (filter_value == "△ 中間点" and score is not None and 0 < score < max_score)
        )
        if not include:
            try:
                include = score is not None and score == int(filter_value)
            except (TypeError, ValueError):
                include = False
        if include:
            filtered.append((filename, score))
    return filtered

class DescriptiveReviewGUI:
    """記述採点結果を一覧・確認・修正するための GUI。

    左ペイン: 設問一覧（リストボックス）
    右ペイン: 選択された設問の全生徒回答画像をグリッド表示。
              各画像にはファイル名と現在のスコアが表示され、
              クリックでスコアを変更できる。

    Args:
        parent: 親ウィンドウ
        config: descriptive_config dict
        scores: {filename: {question_id: score}}
        boxed_folder: 00_Processing フォルダパス
        scores_save_path: descriptive_scores.json 保存パス
        original_image_folder: 元画像フォルダ（高解像度参照用）
    """

    THUMB_SIZE_DEFAULT = 200
    GRID_COLS = 4

    def __init__(
        self,
        parent: tk.Tk,
        config: dict,
        scores: dict,
        boxed_folder: str,
        scores_save_path: str,
        original_image_folder: Optional[str] = None,
        exam_page: Optional[int] = None,
    ):
        self.parent = parent
        self.config = config
        self.scores = {k: dict(v) for k, v in scores.items()}  # deep copy
        self.boxed_folder = Path(boxed_folder)
        self.scores_save_path = scores_save_path
        self.exam_page = exam_page  # 複数ページ案件のみ設定される
        self.annotations_path = str(Path(scores_save_path).parent / DESCRIPTIVE_ANNOTATIONS_FILE)
        self.annotations = load_descriptive_annotations(self.annotations_path)
        try:
            from roster_config import ROSTER_CONFIG_FILE, load_roster_config
            self.roster = load_roster_config(str(Path(scores_save_path).parent / ROSTER_CONFIG_FILE)) or {}
        except Exception:
            self.roster = {}
        self.original_image_folder = original_image_folder
        self.questions = config.get("questions", [])
        self.modified = False
        self.pending_page_switch: Optional[int] = None
        self._thumb_cache: dict = {}
        self._photo_refs: list = []
        self._thumb_size = self.THUMB_SIZE_DEFAULT  # スライダーで変更可能
        self._grid_cols = self.GRID_COLS
        self._zoom_after_id: Optional[str] = None
        self._whiteness_cache: Dict[str, float] = {}

        # 画像ファイル一覧
        self._image_files = sorted([
            f.name for f in self.boxed_folder.iterdir()
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif')
        ])

        self._build_gui()
        self.win.grab_set()
        self.win.wait_window()

    # ----------------------------------------------------------
    # GUI 構築
    # ----------------------------------------------------------

    def _build_gui(self):
        self.win = tk.Toplevel(self.parent)
        title = "🔎 採点の確認・修正"
        if self.exam_page is not None:
            title += f"（試験ページ {self.exam_page}）"
        self.win.title(title)
        self.win.geometry("1100x700")
        self.win.configure(bg="#F5F7FA")
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        # --- 左ペイン: 設問リスト ---
        left = tk.Frame(self.win, bg="#F5F7FA", width=220)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0), pady=8)
        left.pack_propagate(False)

        tk.Label(left, text="設問一覧", font=("", 12, "bold"), bg="#F5F7FA").pack(pady=(0, 5))

        self._q_listbox = tk.Listbox(left, font=("", 11), activestyle="none")
        self._q_listbox.pack(fill=tk.BOTH, expand=True)
        for q in self.questions:
            self._q_listbox.insert(tk.END, f"{q['name']}  (配点: {q['max_score']})")
        self._q_listbox.bind("<<ListboxSelect>>", self._on_question_selected)

        # フィルタ
        filter_frame = tk.Frame(left, bg="#F5F7FA")
        filter_frame.pack(fill=tk.X, pady=(5, 0))
        tk.Label(filter_frame, text="フィルタ:", bg="#F5F7FA", font=("", 9)).pack(side=tk.LEFT)
        self._filter_var = tk.StringVar(value="全て")
        self._filter_combo = ttk.Combobox(
            filter_frame, textvariable=self._filter_var,
            values=["全て"], state="readonly", width=10,
        )
        self._filter_combo.pack(side=tk.LEFT, padx=3)
        self._filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_grid())

        display_frame = tk.Frame(left, bg="#F5F7FA")
        display_frame.pack(fill=tk.X, pady=(3, 0))
        tk.Label(display_frame, text="表示:", bg="#F5F7FA", font=("", 9)).pack(side=tk.LEFT)
        self._display_mode_var = tk.StringVar(value="画像一覧")
        display_combo = ttk.Combobox(
            display_frame, textvariable=self._display_mode_var,
            values=["画像一覧", "テキスト一覧"], state="readonly", width=14,
        )
        display_combo.pack(side=tk.LEFT, padx=3)
        display_combo.bind("<<ComboboxSelected>>", lambda e: self._on_display_mode_changed())

        # 並び順
        sort_frame = tk.Frame(left, bg="#F5F7FA")
        sort_frame.pack(fill=tk.X, pady=(3, 0))
        tk.Label(sort_frame, text="並び順:", bg="#F5F7FA", font=("", 9)).pack(side=tk.LEFT)
        self._sort_var = tk.StringVar(value="ファイル名順")
        self._sort_combo = ttk.Combobox(
            sort_frame, textvariable=self._sort_var,
            values=["ファイル名順", "得点 昇順", "得点 降順",
                    "画像の白さ（白い順）"],
            state="readonly", width=18,
        )
        self._sort_combo.pack(side=tk.LEFT, padx=3)
        self._sort_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_grid())

        # 統計ラベル
        self._stats_label = tk.Label(left, text="", bg="#F5F7FA", font=("", 9), fg="#555", justify=tk.LEFT)
        self._stats_label.pack(fill=tk.X, pady=(5, 0))

        # 保存ボタン
        tk.Button(
            left, text="💾 変更を保存", command=self._save,
            bg="#81C784", fg="black", font=("", 11, "bold"),
            relief=tk.FLAT, cursor="hand2",
        ).pack(fill=tk.X, pady=(8, 0))

        # --- 右ペイン: 画像グリッド ---
        right = tk.Frame(self.win, bg="#F5F7FA")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8)

        # ズームスライダー
        zoom_bar = tk.Frame(right, bg="#37474F", padx=10, pady=4)
        self._review_zoom_bar = zoom_bar
        zoom_bar.pack(fill=tk.X)

        tk.Label(zoom_bar, text="🔍 サイズ:",
                 font=(UI_FONT, get_ui_font_size(9)), bg="#37474F", fg="white"
                 ).pack(side=tk.LEFT)
        tk.Button(zoom_bar, text="－ 縮小", command=lambda: self._change_review_zoom(0.8),
                  font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT, padx=4)
        tk.Button(zoom_bar, text="＋ 拡大", command=lambda: self._change_review_zoom(1.25),
                  font=(UI_FONT, get_ui_font_size(8))).pack(side=tk.LEFT, padx=4)

        self._review_zoom_label = tk.StringVar(value=f"{self._thumb_size}px")
        tk.Label(zoom_bar, textvariable=self._review_zoom_label,
                 font=(UI_FONT, get_ui_font_size(9), "bold"), bg="#37474F", fg="#FFD54F",
                 width=8, anchor=tk.CENTER).pack(side=tk.LEFT, padx=2)

        # 複数ページ案件のみ、ページを閉じずに前後の試験ページへ切り替えられる
        # ボタンを表示する（単一ページ案件では原本フォルダにポインタファイルが
        # 無いため get_exam_page_for_workspace が None を返し、表示されない）。
        if self.original_image_folder:
            from multi_page_merger import get_exam_page_for_workspace
            if get_exam_page_for_workspace(self.original_image_folder) is not None:
                tk.Button(
                    zoom_bar, text="次ページ ▶", command=lambda: self._switch_page(1),
                    font=(UI_FONT, get_ui_font_size(8)),
                ).pack(side=tk.RIGHT, padx=(4, 0))
                tk.Button(
                    zoom_bar, text="◀ 前ページ", command=lambda: self._switch_page(-1),
                    font=(UI_FONT, get_ui_font_size(8)),
                ).pack(side=tk.RIGHT)

        # スクロール可能キャンバス
        self._canvas = tk.Canvas(right, bg="#FFFFFF", highlightthickness=0)
        self._scrollbar = tk.Scrollbar(right, orient=tk.VERTICAL, command=self._canvas.yview)
        # テキスト一覧は全列の可読幅を維持し、横方向に収まらない場合は
        # 明示的な案内と常設スクロールバーで続きがあることを伝える。
        self._horizontal_nav = tk.Frame(right, bg="#FFF3E0")
        tk.Label(
            self._horizontal_nav,
            text="↔ 左右に項目があります。下のバーを横へ動かしてください",
            bg="#FFF3E0", fg="#BF360C",
            font=(UI_FONT, get_ui_font_size(8), "bold"), anchor=tk.W,
        ).pack(fill=tk.X, padx=6, pady=(3, 1))
        self._h_scrollbar = tk.Scrollbar(
            self._horizontal_nav, orient=tk.HORIZONTAL, command=self._canvas.xview,
        )
        self._h_scrollbar.pack(fill=tk.X, padx=4, pady=(0, 3))
        self._grid_frame = tk.Frame(self._canvas, bg="#FFFFFF")

        self._grid_frame.bind("<Configure>",
                              lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_frame, anchor="nw")
        self._canvas.configure(
            yscrollcommand=self._scrollbar.set,
            xscrollcommand=self._h_scrollbar.set,
        )

        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # マウスホイールスクロール
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))
        self._canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

        # キャンバスのリサイズ追従
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # 初期選択
        if self.questions:
            self._q_listbox.selection_set(0)
            self._on_question_selected(None)

    def _on_display_mode_changed(self):
        if self._display_mode_var.get() == "画像一覧":
            self._review_zoom_bar.pack(fill=tk.X, before=self._canvas)
            self._horizontal_nav.pack_forget()
        else:
            self._review_zoom_bar.pack_forget()
            self._horizontal_nav.pack(side=tk.BOTTOM, fill=tk.X, before=self._canvas)
        self._refresh_grid()

    def _change_review_zoom(self, factor: float):
        self._thumb_size = max(100, min(800, int(round(self._thumb_size * factor))))
        self._review_zoom_label.set(f"{self._thumb_size}px")
        self._thumb_cache.clear()
        self._photo_refs.clear()
        self._grid_cols = max(1, self._canvas.winfo_width() // (self._thumb_size + 14))
        self._refresh_grid()

    # ----------------------------------------------------------
    # イベントハンドラ
    # ----------------------------------------------------------

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_shift_mousewheel(self, event):
        """Shift＋ホイールでテキスト一覧を横スクロールする。"""
        if self._display_mode_var.get() == "テキスト一覧":
            self._canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

    def _on_canvas_resize(self, event):
        if self._display_mode_var.get() == "テキスト一覧":
            # 表の全列が読める幅を維持し、超過分は横スクロールさせる。
            content_width = max(event.width, self._grid_frame.winfo_reqwidth())
            self._canvas.itemconfig(self._canvas_window, width=content_width)
        else:
            self._canvas.itemconfig(self._canvas_window, width=event.width)
        # 列数を再計算
        new_cols = max(1, event.width // (self._thumb_size + 14))
        if new_cols != self._grid_cols:
            self._grid_cols = new_cols
            if hasattr(self, '_resize_after_id') and self._resize_after_id:
                self.win.after_cancel(self._resize_after_id)
            self._resize_after_id = self.win.after(100, self._refresh_grid)

    def _on_review_zoom_change(self, value):
        """サイズスライダー変更時"""
        new_size = int(float(value))
        self._thumb_size = new_size
        self._review_zoom_label.set(f"{new_size}px")
        # 列数を再計算
        canvas_w = self._canvas.winfo_width()
        if canvas_w <= 1:
            canvas_w = 800
        self._grid_cols = max(1, canvas_w // (new_size + 14))
        # キャッシュクリアしてデバウンスリフレッシュ
        self._thumb_cache.clear()
        self._photo_refs.clear()
        if self._zoom_after_id:
            self.win.after_cancel(self._zoom_after_id)
        self._zoom_after_id = self.win.after(150, self._refresh_grid)

    def _compute_review_whiteness(self, fname: str, qid: str) -> float:
        """画像の白さ（領域の平均輝度）を計算してキャッシュ"""
        cache_key = (fname, qid)
        if cache_key in self._whiteness_cache:
            return self._whiteness_cache[cache_key]
        img_path = self.boxed_folder / fname
        if not img_path.exists():
            return 0.0
        try:
            q = next((q_ for q_ in self.questions if q_["id"] == qid), None)
            if not q or "region" not in q:
                return 0.0
            img_array = np.fromfile(str(img_path), dtype=np.uint8)
            image = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
            if image is None:
                return 0.0
            h, w = image.shape[:2]
            region = q["region"]
            x1 = max(0, min(int(region[0]), w))
            y1 = max(0, min(int(region[1]), h))
            x2 = max(0, min(int(region[2]), w))
            y2 = max(0, min(int(region[3]), h))
            cropped = image[y1:y2, x1:x2]
            if cropped.size == 0:
                return 0.0
            brightness = float(np.mean(cropped))
            self._whiteness_cache[cache_key] = brightness
            return brightness
        except Exception:
            return 0.0

    def _on_question_selected(self, event):
        sel = self._q_listbox.curselection()
        if not sel:
            return
        self._current_q_idx = sel[0]
        q = self.questions[self._current_q_idx]
        # フィルタ更新: セマンティックフィルタ + 数値フィルタ
        vals = [
            "全て", "未採点", "採点済み", "保留", "○ 満点", "× 0点",
            "△ 中間点", "コメントあり",
        ] + [str(s) for s in range(q["max_score"] + 1)]
        self._filter_combo.config(values=vals)
        self._filter_var.set("全て")
        self._refresh_grid()

    def _refresh_grid(self):
        """選択された設問に対応する全生徒回答画像をグリッド表示"""
        # 既存ウィジェットを破棄
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._photo_refs.clear()

        if not hasattr(self, '_current_q_idx'):
            return

        q = self.questions[self._current_q_idx]
        qid = q["id"]
        max_score = q["max_score"]
        filter_val = self._filter_var.get()

        # 集計とフィルタリング
        scored_count = 0
        total_score_sum = 0.0
        for fname in self._image_files:
            sc = self.scores.get(fname, {}).get(qid)
            if sc is not None:
                scored_count += 1
                total_score_sum += sc
        filtered = filter_descriptive_review_answers(
            self._image_files, self.scores, self.annotations, qid, max_score, filter_val,
        )

        # ソート
        sort_mode = self._sort_var.get() if hasattr(self, '_sort_var') else "ファイル名順"
        if sort_mode == "得点 昇順":
            filtered.sort(key=lambda x: (x[1] if x[1] is not None else -1, x[0]))
        elif sort_mode == "得点 降順":
            filtered.sort(key=lambda x: (-(x[1]) if x[1] is not None else 1, x[0]))
        elif sort_mode == "画像の白さ（白い順）":
            filtered.sort(key=lambda x: -self._compute_review_whiteness(x[0], qid))

        # 統計更新
        avg = total_score_sum / scored_count if scored_count > 0 else 0
        self._stats_label.config(
            text=f"採点済: {scored_count}/{len(self._image_files)}\n"
                 f"平均: {avg:.2f} / {max_score}\n"
                 f"表示: {filter_val} {len(filtered)} / 全{len(self._image_files)}件"
        )

        # 列数を現在のキャンバス幅から動的に決定
        canvas_w = self._canvas.winfo_width()
        if canvas_w <= 1:
            canvas_w = 800
        cols = max(1, canvas_w // (self._thumb_size + 14))
        self._grid_cols = cols

        if self._display_mode_var.get() == "テキスト一覧":
            self._render_text_table(filtered, qid, max_score)
            return

        # グリッド生成
        for idx, (fname, sc) in enumerate(filtered):
            row, col = divmod(idx, cols)
            
            # カード背景色の決定
            if sc is None:
                card_bg = "#F5F5F5"   # 未採点: 灰
            elif sc >= max_score:
                card_bg = "#E3F2FD"   # 満点: 薄い青
            elif sc == 0:
                card_bg = "#FFEBEE"   # 0点: 薄い赤
            else:
                card_bg = "#FFF3E0"   # 中間点: 薄いオレンジ
            
            cell = tk.Frame(self._grid_frame, bg=card_bg, bd=1, relief=tk.SOLID,
                            padx=3, pady=3)
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

            annotation = self.annotations.get("answers", {}).get(fname, {}).get(qid, {})
            memo_preview = self._annotation_preview(annotation.get("memo", ""))
            comment_preview = self._annotation_preview(annotation.get("comment", ""))

            if self._display_mode_var.get() == "テキスト一覧":
                cell.grid_configure(sticky="ew")
                tk.Label(cell, text=fname, bg=card_bg, anchor=tk.W,
                         font=(UI_FONT, get_ui_font_size(9), "bold")).pack(fill=tk.X)
            else:
                # サムネイル画像
                thumb = self._get_thumb(fname, qid)
                if thumb:
                    self._photo_refs.append(thumb)
                    img_label = tk.Label(cell, image=thumb, bg=card_bg, cursor="hand2")
                    img_label.pack()
                    img_label.bind("<Button-1>", lambda e, f=fname, q_=qid, ms=max_score: self._edit_score(f, q_, ms))
                else:
                    tk.Label(cell, text="(画像なし)", bg=card_bg, fg="#999").pack()

            # ファイル名（省略表示）
            display_name = fname[:20] + "…" if len(fname) > 20 else fname
            tk.Label(cell, text=display_name, bg=card_bg, font=("", 8), fg="#555").pack()

            # スコア表示
            if sc is not None:
                sc_color = "#4CAF50" if sc == max_score else ("#F44336" if sc == 0 else "#333")
                sc_text = f"{sc} / {max_score}"
            else:
                sc_color = "#999"
                sc_text = "未採点"
            score_lbl = tk.Label(cell, text=sc_text, bg=card_bg, font=("", 10, "bold"), fg=sc_color)
            score_lbl.pack()
            score_lbl.bind("<Button-1>", lambda e, f=fname, q_=qid, ms=max_score: self._edit_score(f, q_, ms))

            annotation = self.annotations.get("answers", {}).get(fname, {}).get(qid, {})
            badges = []
            if annotation.get("held"):
                badges.append("⏸ 保留")
            if annotation.get("memo"):
                badges.append("📝 メモ")
            if annotation.get("comment"):
                badges.append("💬 コメント")
            tk.Label(cell, text="  ".join(badges) or "注釈なし", bg=card_bg,
                     fg="#AD1457" if annotation.get("held") else "#777",
                     font=(UI_FONT, get_ui_font_size(8))).pack()
            # サムネイルよりカードが横に広がる場合の余白を活用し、注釈が
            # 細い段落にならないよう従来の約2倍まで一行に表示する。
            annotation_wraplength = max(320, self._thumb_size * 2)
            tk.Label(cell, text=f"メモ: {memo_preview or '—'}", bg=card_bg,
                     fg="#5D4037", anchor=tk.W, justify=tk.LEFT,
                     wraplength=annotation_wraplength).pack(fill=tk.X)
            tk.Label(cell, text=f"コメント: {comment_preview or '—'}", bg=card_bg,
                     fg="#37474F", anchor=tk.W, justify=tk.LEFT,
                     wraplength=annotation_wraplength).pack(fill=tk.X)
            tk.Button(cell, text="採点画面へ",
                      command=lambda q_=qid: self._open_scoring_screen(q_),
                      font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT, pady=(2, 0))
            tk.Button(cell, text="注釈を編集",
                      command=lambda f=fname, q_=qid: self._edit_annotation(f, q_),
                      font=(UI_FONT, get_ui_font_size(7))).pack(side=tk.LEFT, padx=(3, 0), pady=(2, 0))
            cell.bind("<Double-Button-1>",
                      lambda e, f=fname, q_=qid, ms=max_score: self._edit_score(f, q_, ms))

            # 元画像を開くリンク
            open_lbl = tk.Label(cell, text="📷開く", bg=card_bg, fg="#1976D2",
                                font=(UI_FONT, get_ui_font_size(8), "underline"), cursor="hand2")
            open_lbl.pack()
            open_lbl.bind("<Button-1>", lambda e, f=fname: self._open_original_image(f))

        # グリッド列の伸縮設定
        for c in range(cols):
            self._grid_frame.columnconfigure(c, weight=1)

    @staticmethod
    def _annotation_preview(value: str, limit: int = 80) -> str:
        """一覧用に改行を整え、長文を先頭だけ表示する。"""
        text = str(value or "").replace("\n", " / ").strip()
        return text if len(text) <= limit else text[:limit] + "…"

    def _render_text_table(self, filtered, qid: str, max_score: int):
        """答案1件を1行に表示する表形式の一覧を描画する。"""
        columns = ["氏名", "学籍番号", "ファイル名", "得点", "状態", "保留", "教員用メモ", "生徒コメント", "操作"]
        # 最大化時には全列を一望でき、小さい画面では横スクロールできる幅にする。
        # 長いファイル名・メモ・コメントは列を広げず、セル内で折り返す。
        widths = [10, 10, 18, 6, 7, 4, 16, 16, 8]
        for col, (name, width) in enumerate(zip(columns, widths)):
            tk.Label(self._grid_frame, text=name, bg="#455A64", fg="white",
                     font=(UI_FONT, get_ui_font_size(8), "bold"), width=width,
                     anchor=tk.W, padx=3, pady=3, bd=1, relief=tk.SOLID,
                     highlightthickness=0).grid(row=0, column=col, sticky="nsew")

        for row, (fname, score) in enumerate(filtered, start=1):
            annotation = self.annotations.get("answers", {}).get(fname, {}).get(qid, {})
            student_id, student_name = self._identity_for_filename(fname)
            bg = "#FFF8E1" if row % 2 else "#FFFFFF"
            values = [
                student_name, student_id, fname,
                f"{score} / {max_score}" if score is not None else "未採点",
                "採点済み" if score is not None else "未採点",
                "保留" if annotation.get("held") else "",
                self._annotation_preview(annotation.get("memo", ""), 18) or "—",
                self._annotation_preview(annotation.get("comment", ""), 18) or "—",
            ]
            for col, (value, width) in enumerate(zip(values, widths[:-1])):
                label = tk.Label(self._grid_frame, text=value, bg=bg,
                                 anchor=tk.W, justify=tk.LEFT, width=width,
                                 height=1, padx=3, pady=2, bd=1,
                                 relief=tk.SOLID, highlightthickness=0)
                label.grid(row=row, column=col, sticky="nsew")
                label.bind("<Double-Button-1>",
                           lambda e, q_=qid: self._open_scoring_screen(q_))
            actions = tk.Frame(
                self._grid_frame, bg=bg, bd=1, relief=tk.SOLID,
                highlightthickness=0,
            )
            actions.grid(row=row, column=len(columns) - 1, sticky="nsew")
            tk.Button(actions, text="採点", command=lambda q_=qid: self._open_scoring_screen(q_),
                      font=(UI_FONT, get_ui_font_size(6))).pack(side=tk.LEFT, padx=(1, 0), pady=1)
            tk.Button(actions, text="注釈", command=lambda f=fname, q_=qid: self._edit_annotation(f, q_),
                      font=(UI_FONT, get_ui_font_size(6))).pack(side=tk.LEFT, padx=1, pady=1)

        for col in range(len(columns)):
            self._grid_frame.columnconfigure(col, weight=1 if col in (0, 4, 5) else 0)

        # 強制縮小で左端列が消えないよう、表の要求幅をキャンバス内ウィンドウへ反映する。
        self._grid_frame.update_idletasks()
        content_width = max(self._canvas.winfo_width(), self._grid_frame.winfo_reqwidth())
        self._canvas.itemconfig(self._canvas_window, width=content_width)
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._canvas.xview_moveto(0)

    def _identity_for_filename(self, fname: str):
        """ファイル名から名簿情報を取得できる場合だけ氏名・番号を補う。"""
        stem = Path(fname).stem
        for student_id, name in self.roster.items():
            if str(student_id) == stem or str(student_id) in stem:
                return str(student_id), str(name)
        return "未取得", "未取得"

    def _get_thumb(self, fname: str, qid: str):
        """指定ファイル・設問の切り出しサムネイルを取得"""
        cache_key = (fname, qid)
        if cache_key in self._thumb_cache:
            return self._thumb_cache[cache_key]

        img_path = self.boxed_folder / fname
        if not img_path.exists():
            return None

        try:
            q = next((q_ for q_ in self.questions if q_["id"] == qid), None)
            if not q or "region" not in q:
                return None

            # Unicode パス対応 (cv2.imread は非 ASCII パスで失敗する)
            img_array = np.fromfile(str(img_path), dtype=np.uint8)
            image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if image is None:
                return None

            h, w = image.shape[:2]

            # region 座標は IntegratedDescriptiveSetup で 00_Processing の
            # 実画像サイズに対して定義されているため、そのまま使用する。
            # 旧コードでは 595×842 基準のスケーリングを行っていたが、
            # 記述のみモードでは画像が原寸大であるためスケーリング不要。
            region = q["region"]
            x1 = max(0, min(int(region[0]), w))
            y1 = max(0, min(int(region[1]), h))
            x2 = max(0, min(int(region[2]), w))
            y2 = max(0, min(int(region[3]), h))

            cropped = image[y1:y2, x1:x2]
            if cropped.size == 0:
                return None

            pil_img = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
            # 幅を _thumb_size に合わせてリサイズ（高さは比率維持）
            target_w = self._thumb_size
            scale = target_w / max(pil_img.width, 1)
            target_h = max(1, int(pil_img.height * scale))
            # 高さが極端に大きい場合は上限制限
            max_h = self._thumb_size * 3
            if target_h > max_h:
                scale = max_h / max(pil_img.height, 1)
                target_w = max(1, int(pil_img.width * scale))
                target_h = max_h
            pil_img = pil_img.resize((target_w, target_h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(pil_img)
            # サムネイルキャッシュ上限管理 (メモリ消費抑制)
            _MAX_THUMB_CACHE = 500
            if len(self._thumb_cache) >= _MAX_THUMB_CACHE:
                # 古いエントリを半分削除
                keys = list(self._thumb_cache.keys())
                for k in keys[:len(keys) // 2]:
                    del self._thumb_cache[k]
            self._thumb_cache[cache_key] = photo
            return photo
        except Exception:
            return None

    def _open_original_image(self, fname: str):
        """純粋な元画像をOSのデフォルトビューアで開く

        original_image_folder（マーク描画なし）があればそちらを優先。
        なければ boxed_folder（00_Processing）にフォールバック。
        """
        for folder in [self.original_image_folder, str(self.boxed_folder)]:
            if not folder:
                continue
            img_path = Path(folder) / fname
            if img_path.exists():
                try:
                    open_in_default_viewer(img_path)
                except Exception:
                    pass
                return

    def _edit_score(self, fname: str, qid: str, max_score: int):
        """スコア修正ダイアログを表示"""
        current = self.scores.get(fname, {}).get(qid)
        current_str = str(current) if current is not None else "未採点"

        dialog = tk.Toplevel(self.win)
        dialog.title(f"スコア修正: {fname}")
        dialog.transient(self.win)
        dialog.grab_set()
        dialog.configure(bg="#F5F7FA")

        tk.Label(dialog, text=f"ファイル: {fname}", bg="#F5F7FA", font=("", 10)).pack(pady=(10, 2))
        tk.Label(dialog, text=f"現在のスコア: {current_str}", bg="#F5F7FA", font=("", 10)).pack(pady=2)
        tk.Label(dialog, text=f"配点: 0 ～ {max_score}", bg="#F5F7FA", font=("", 10)).pack(pady=2)

        def set_score(val):
            if fname not in self.scores:
                self.scores[fname] = {}
            self.scores[fname][qid] = val
            self.modified = True
            dialog.destroy()
            self._refresh_grid()

        if max_score <= 10:
            # 配点が低い場合: ボタン群で選択
            btn_frame = tk.Frame(dialog, bg="#F5F7FA")
            btn_frame.pack(pady=10)

            for s in range(max_score + 1):
                bg = "#81C784" if s == current else "#E0E0E0"
                tk.Button(
                    btn_frame, text=str(s), width=4, font=("", 12, "bold"),
                    bg=bg, relief=tk.RAISED, cursor="hand2",
                    command=lambda v=s: set_score(v),
                ).pack(side=tk.LEFT, padx=2)
        else:
            # 配点が11点以上: 数値入力欄で入力
            entry_frame = tk.Frame(dialog, bg="#F5F7FA")
            entry_frame.pack(pady=10)
            tk.Label(entry_frame, text="得点:", bg="#F5F7FA", font=("", 10)).pack(side=tk.LEFT)
            entry = tk.Entry(entry_frame, width=6, font=("", 14), justify=tk.CENTER)
            entry.pack(side=tk.LEFT, padx=5)
            if current is not None:
                entry.insert(0, str(current))
            entry.focus_set()

            def _submit_entry():
                try:
                    val = int(entry.get().strip())
                    if 0 <= val <= max_score:
                        set_score(val)
                    else:
                        from tkinter import messagebox
                        messagebox.showwarning("範囲外", f"0 ～ {max_score} の範囲で入力してください。", parent=dialog)
                except ValueError:
                    from tkinter import messagebox
                    messagebox.showwarning("入力エラー", "整数を入力してください。", parent=dialog)

            entry.bind("<Return>", lambda e: _submit_entry())
            tk.Button(entry_frame, text="確定", command=_submit_entry,
                      bg="#81C784", fg="black", font=("", 10, "bold"),
                      relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=5)

        tk.Button(dialog, text="キャンセル", command=dialog.destroy,
                  bg="#BDBDBD", relief=tk.FLAT).pack(pady=5)

        min_h = 200 if max_score <= 10 else 220
        fit_window_to_content(dialog, min_width=350, min_height=min_h)
        dialog.wait_window()

    def _edit_annotation(self, fname: str, qid: str):
        annotation = self.annotations.setdefault("answers", {}).setdefault(fname, {}).setdefault(
            qid, {"memo": "", "comment": "", "held": False})
        dialog = tk.Toplevel(self.win)
        dialog.title(f"注釈編集: {fname}")
        dialog.transient(self.win)
        frame = tk.Frame(dialog, padx=12, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(frame, text="教員用メモ").pack(anchor=tk.W)
        memo = tk.Text(frame, width=45, height=4)
        memo.pack(fill=tk.X)
        memo.insert("1.0", annotation.get("memo", ""))
        tk.Label(frame, text="生徒へのコメント").pack(anchor=tk.W, pady=(6, 0))
        comment = tk.Text(frame, width=45, height=3)
        comment.pack(fill=tk.X)
        comment.insert("1.0", annotation.get("comment", ""))
        held = tk.BooleanVar(value=bool(annotation.get("held", False)))
        tk.Checkbutton(frame, text="保留", variable=held).pack(anchor=tk.W)

        def save():
            annotation["memo"] = memo.get("1.0", "end-1c")
            annotation["comment"] = comment.get("1.0", "end-1c").strip()
            annotation["held"] = held.get()
            self.modified = True
            dialog.destroy()
            self._refresh_grid()

        tk.Button(frame, text="保存", command=save, bg="#81C784").pack(side=tk.LEFT, pady=8)
        tk.Button(frame, text="キャンセル", command=dialog.destroy).pack(side=tk.LEFT, padx=5, pady=8)
        fit_window_to_content(dialog, min_width=420, min_height=300)
        dialog.grab_set()

    def _open_scoring_screen(self, qid: str):
        """一覧から選択中の設問の通常採点画面へ移動する。"""
        q_config = next((q for q in self.questions if q["id"] == qid), None)
        if not q_config:
            return
        image_paths = {fname: str(self.boxed_folder / fname) for fname in self._image_files}
        scorer = _SingleQuestionScorer(
            parent=self.win, question_config=q_config, image_paths=image_paths,
            existing_scores=self.scores, initial_mode="1枚ずつ",
            image_folder=str(self.boxed_folder), annotations=self.annotations,
            annotations_save_callback=lambda: save_descriptive_annotations(
                self.annotations_path, self.annotations),
            exam_page=self.exam_page,
        )
        result = scorer.run()
        if result is not None:
            for fname, scores in result.items():
                self.scores.setdefault(fname, {}).update(scores)
            self.modified = True
            self._refresh_grid()

    def _save(self):
        """変更を保存。成功時 True、失敗時 False を返す。"""
        if not self.modified:
            messagebox.showinfo("情報", "変更はありません。", parent=self.win)
            return True

        try:
            save_data = {"version": 1, "scores": self.scores}
            atomic_json_save(self.scores_save_path, save_data)
            save_descriptive_annotations(self.annotations_path, self.annotations)
            self.modified = False
            messagebox.showinfo("保存完了", "採点結果を保存しました。", parent=self.win)
            return True
        except Exception as e:
            messagebox.showerror("保存エラー", f"保存に失敗しました:\n{e}", parent=self.win)
            return False

    def _confirm_pending_changes(self) -> bool:
        """未保存の変更があれば保存するか確認する。続行してよければTrue。"""
        if not self.modified:
            return True
        answer = _ask_three_way_japanese(
            "確認",
            "変更が保存されていません。\n保存してから閉じますか？",
            parent=self.win,
            yes_text="保存して閉じる",
            no_text="保存せず閉じる",
            cancel_text="確認画面に戻る",
        )
        if answer is None:
            # キャンセル → 何もしない
            return False
        if answer:
            # 「はい」→ 保存試行、失敗なら続行しない
            return self._save()
        return True

    def _on_close(self):
        """ウィンドウを閉じる（保存失敗時は閉じない）"""
        if not self._confirm_pending_changes():
            return
        # スクロールバインドの解除（残留するとTclError）
        try:
            self._canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.win.destroy()

    def _switch_page(self, offset: int):
        """未保存の変更を確認してから、前後の試験ページへ切り替える。"""
        if not self._confirm_pending_changes():
            return
        try:
            self._canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.pending_page_switch = offset
        self.win.destroy()
