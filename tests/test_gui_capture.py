"""
test_gui_capture.py — tkinter GUI ウィンドウ *全体* キャプチャテスト

Win32 PrintWindow API を使い、タイトルバー・枠を含むウィンドウ全体を
PNG で保存する。ImageGrab.grab とは異なり、ウィンドウが背面にあっても正確。

tests/gui_captures/ に出力し、gui_captures_index.html で一覧表示する。

※ CI / ヘッドレス環境では skip される。
"""

from __future__ import annotations

import ctypes
import json
import os
import sys

if sys.platform == "win32":
    import ctypes.wintypes as wintypes
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Optional
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from PIL import Image, ImageGrab, ImageTk

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from conftest import get_shared_tk_root
from constants import (
    MODE_MARK_ONLY,
    MODE_MARK_AND_DESCRIPTIVE,
    MODE_DESCRIPTIVE_ONLY,
    DEFAULT_RENDERING_SETTINGS,
    get_rendering_settings,
)


# ============================================================
# キャプチャ出力ディレクトリ
# ============================================================

CAPTURE_DIR = Path(__file__).parent / "gui_captures"
CAPTURE_DIR.mkdir(exist_ok=True)


# ============================================================
# ディスプレイ判定
# ============================================================

def _can_capture() -> bool:
    """ディスプレイが存在するか"""
    try:
        root = get_shared_tk_root()
        root.update_idletasks()
        return True
    except tk.TclError:
        return False


pytestmark = [
    pytest.mark.visual,
    pytest.mark.gui_heavy,
    pytest.mark.legacy_mock,
    pytest.mark.skipif(
        not _can_capture(),
        reason="ディスプレイなし (ヘッドレス環境)",
    ),
]


# ============================================================
# Win32 PrintWindow ベース キャプチャ
# ============================================================

if sys.platform == "win32":
    class BITMAPINFOHEADER(ctypes.Structure):
        """Win32 BITMAPINFOHEADER 構造体"""
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]


def _get_hwnd(widget: tk.Wm) -> Optional[int]:
    """tkinter ウィジェットから Win32 HWND を取得 (外枠含む)"""
    try:
        frame_id = widget.wm_frame()
        if frame_id and frame_id != "0x0":
            return int(frame_id, 16)
    except Exception:
        pass
    try:
        return widget.winfo_id()
    except Exception:
        return None


def _capture_with_printwindow(widget: tk.Wm, path: Path) -> bool:
    """Win32 PrintWindow API でウィンドウ全体 (タイトルバー含む) をキャプチャ"""
    try:
        hwnd = _get_hwnd(widget)
        if not hwnd:
            return False

        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width < 10 or height < 10:
            return False

        wDC = ctypes.windll.user32.GetWindowDC(hwnd)
        if not wDC:
            return False

        try:
            dcObj = ctypes.windll.gdi32.CreateCompatibleDC(wDC)
            bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(wDC, width, height)
            old = ctypes.windll.gdi32.SelectObject(dcObj, bmp)

            # PW_RENDERFULLCONTENT = 2
            ok = ctypes.windll.user32.PrintWindow(hwnd, dcObj, 2)

            if ok:
                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = width
                bmi.biHeight = -height       # top-down
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                bmi.biCompression = 0        # BI_RGB

                buf = ctypes.create_string_buffer(width * height * 4)
                ctypes.windll.gdi32.GetDIBits(
                    dcObj, bmp, 0, height, buf, ctypes.byref(bmi), 0,
                )
                img = Image.frombuffer(
                    "RGBA", (width, height), buf, "raw", "BGRA", 0, 1,
                )
                img = img.convert("RGB")
                img.save(str(path))

            ctypes.windll.gdi32.SelectObject(dcObj, old)
            ctypes.windll.gdi32.DeleteObject(bmp)
            ctypes.windll.gdi32.DeleteDC(dcObj)
        finally:
            ctypes.windll.user32.ReleaseDC(hwnd, wDC)

        return bool(ok)
    except Exception as e:
        print(f"[PrintWindow failed] {e}")
        return False


def _capture_with_imagegrab(widget: tk.Wm, path: Path) -> bool:
    """フォールバック: winfo_x/y (外枠座標) で ImageGrab"""
    try:
        outer_x = widget.winfo_x()
        outer_y = widget.winfo_y()
        client_x = widget.winfo_rootx()
        client_y = widget.winfo_rooty()
        client_w = widget.winfo_width()
        client_h = widget.winfo_height()

        border = client_x - outer_x
        title_h = client_y - outer_y

        x1, y1 = outer_x, outer_y
        x2 = client_x + client_w + border
        y2 = client_y + client_h + border

        if (x2 - x1) < 10 or (y2 - y1) < 10:
            return False

        img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
        img.save(str(path))
        return True
    except Exception as e:
        print(f"[ImageGrab fallback failed] {e}")
        return False


def _capture_window(widget: tk.Wm, filename: str,
                    delay_ms: int = 600) -> Optional[Path]:
    """ウィンドウ全体 (タイトルバー + 枠 + クライアント) をキャプチャ

    1) Win32 PrintWindow を試行 (最も正確)
    2) 失敗時 ImageGrab (外枠座標補正付き)
    """
    widget.update_idletasks()
    widget.update()
    widget.lift()
    widget.update_idletasks()
    widget.update()
    time.sleep(delay_ms / 1000.0)
    widget.update()

    path = CAPTURE_DIR / f"{filename}.png"

    if sys.platform == "win32":
        if _capture_with_printwindow(widget, path):
            return path

    if _capture_with_imagegrab(widget, path):
        return path

    return None


# ============================================================
# ユーティリティ
# ============================================================

def _make_test_image(w: int, h: int, color=(200, 200, 200)):
    """テスト用 BGR numpy 画像"""
    return np.full((h, w, 3), color, dtype=np.uint8)


def _save_test_image(folder: Path, name: str, w: int, h: int):
    """テスト画像を jpeg で保存"""
    img = _make_test_image(w, h)
    path = folder / name
    _, buf = cv2.imencode(".jpg", img)
    buf.tofile(str(path))
    return path


# ============================================================
# 1. StartupModeDialog
# ============================================================


class TestStartupModeDialogCapture:

    def test_capture_startup_dialog(self):
        """モード選択ダイアログをタイトルバー込みでキャプチャ"""
        from gui_components import StartupModeDialog

        root = get_shared_tk_root()

        dialog = StartupModeDialog.__new__(StartupModeDialog)
        dialog.root = root
        dialog.result = None
        dialog._session_path = None
        dialog._build_dialog()

        dialog.dialog.update_idletasks()
        dialog.dialog.update()

        p = _capture_window(dialog.dialog, "01_startup_mode_dialog")
        dialog.dialog.destroy()
        assert p is None or p.exists()


# ============================================================
# 2. SaitenSamuraiGUI (3 モード)
# ============================================================


class TestMainGUICapture:

    @pytest.mark.parametrize("mode,name", [
        (MODE_MARK_ONLY, "02a_main_mark_only"),
        (MODE_MARK_AND_DESCRIPTIVE, "02b_main_mark_descriptive"),
        (MODE_DESCRIPTIVE_ONLY, "02c_main_descriptive_only"),
    ])
    def test_capture_main_gui_modes(self, mode, name):
        """各モードのメイン GUI をキャプチャ"""
        from main_gui import SaitenSamuraiGUI

        win = tk.Toplevel(get_shared_tk_root())
        win.withdraw()
        try:
            gui = SaitenSamuraiGUI(win, mode=mode)
            win.deiconify()
            win.geometry("1100x600+80+80")
            win.update_idletasks()
            win.update()

            _capture_window(win, name)
        finally:
            win.destroy()

        p = CAPTURE_DIR / f"{name}.png"
        assert (not _can_capture()) or p.exists()


# ============================================================
# 3. RenderingSettingsGUI
# ============================================================


class TestRenderingSettingsCapture:

    def _build_rendering_gui(self, show_mark, show_desc, suffix=""):
        """RenderingSettingsGUI を指定セクション表示で構築しキャプチャ"""
        from gui_components import RenderingSettingsGUI

        root = get_shared_tk_root()
        settings = DEFAULT_RENDERING_SETTINGS.copy()

        gui = RenderingSettingsGUI.__new__(RenderingSettingsGUI)
        gui.parent = root
        gui.on_apply = lambda s: None
        gui.image_folder = ""
        gui.coord_excel_path = ""
        gui.template_path = ""
        gui.mark2_result_path = ""
        gui.skip_questions = 4
        gui.original_settings = get_rendering_settings(settings)
        gui._defaults = DEFAULT_RENDERING_SETTINGS.copy()
        gui._show_mark_section = show_mark
        gui._show_desc_section = show_desc

        h = 520 if (show_mark and show_desc) else 320
        gui.window = tk.Toplevel(root)
        gui.window.title("⚙ 採点結果描画 詳細設定")
        gui.window.geometry(f"480x{h}+100+100")
        gui.window.resizable(False, False)
        gui.window.configure(bg="#F5F7FA")

        gui._create_vars()
        gui._create_widgets()
        gui.window.protocol("WM_DELETE_WINDOW", gui.window.destroy)

        gui.window.update_idletasks()
        gui.window.update()

        fname = f"03_rendering_settings{suffix}"
        _capture_window(gui.window, fname)
        gui.window.destroy()

    def test_capture_rendering_settings(self):
        """両セクション表示 (マーク+記述)"""
        self._build_rendering_gui(True, True)

    def test_capture_rendering_settings_mark_only(self):
        """マーク採点のみモード"""
        self._build_rendering_gui(True, False, "_mark_only")

    def test_capture_rendering_settings_desc_only(self):
        """記述採点のみモード"""
        self._build_rendering_gui(False, True, "_desc_only")


# ============================================================
# 4. _ask_question_info ダイアログ (実コード使用)
# ============================================================


class TestQuestionInfoDialogCapture:

    def test_capture_ask_question_info(self):
        """記述問題情報入力ダイアログ — 実コードの UI を再現"""
        root = get_shared_tk_root()

        # 実際の _ask_question_info と同一構造を再現
        dialog = tk.Toplevel(root)
        dialog.title("記述1 の設定")
        dialog.geometry("350x280+150+150")
        dialog.resizable(False, False)
        dialog.configure(bg="#F5F7FA")

        frame = tk.Frame(dialog, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="記述問題 1 の情報を入力",
                 font=("Yu Gothic UI", 11, "bold")).pack(pady=(0, 15))

        # 問題名
        row1 = tk.Frame(frame); row1.pack(fill=tk.X, pady=3)
        tk.Label(row1, text="問題名:", width=8, anchor=tk.W,
                 font=("Yu Gothic UI", 9)).pack(side=tk.LEFT)
        e1 = tk.Entry(row1, font=("Yu Gothic UI", 9))
        e1.pack(side=tk.LEFT, fill=tk.X, expand=True)
        e1.insert(0, "記述1")

        # 配点
        row2 = tk.Frame(frame); row2.pack(fill=tk.X, pady=3)
        tk.Label(row2, text="配点:", width=8, anchor=tk.W,
                 font=("Yu Gothic UI", 9)).pack(side=tk.LEFT)
        e2 = tk.Entry(row2, width=5, font=("Yu Gothic UI", 9))
        e2.pack(side=tk.LEFT)
        e2.insert(0, "5")
        tk.Label(row2, text="点",
                 font=("Yu Gothic UI", 8), fg="gray").pack(side=tk.LEFT, padx=5)

        # 観点
        row3 = tk.Frame(frame); row3.pack(fill=tk.X, pady=3)
        tk.Label(row3, text="観点:", width=8, anchor=tk.W,
                 font=("Yu Gothic UI", 9)).pack(side=tk.LEFT)
        e3 = tk.Entry(row3, width=5, font=("Yu Gothic UI", 9))
        e3.pack(side=tk.LEFT)
        e3.insert(0, "1")
        tk.Label(row3, text="(1以上の整数)",
                 font=("Yu Gothic UI", 8), fg="gray").pack(side=tk.LEFT, padx=5)

        # 注意書き
        tk.Label(frame,
                 text="※ 配点が10点以上の場合、採点時に数値入力欄を使用します",
                 font=("Yu Gothic UI", 7), fg="#999").pack(pady=(8, 0))

        # ボタン
        bf = tk.Frame(frame); bf.pack(pady=(15, 0))
        tk.Button(bf, text="OK", width=10, bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 9, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(bf, text="キャンセル", width=10,
                  font=("Yu Gothic UI", 9)).pack(side=tk.LEFT, padx=5)

        dialog.update_idletasks(); dialog.update()
        _capture_window(dialog, "04_ask_question_info")
        dialog.destroy()


# ============================================================
# 5. _ask_add_more ダイアログ
# ============================================================


class TestAddMoreDialogCapture:

    def test_capture_ask_add_more(self):
        root = get_shared_tk_root()

        dialog = tk.Toplevel(root)
        dialog.title("記述問題の追加")
        dialog.resizable(False, False)
        dialog.configure(bg="#F5F7FA")

        frame = tk.Frame(dialog, padx=25, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame,
                 text='記述1「記述1」を登録しました。',
                 font=("Yu Gothic UI", 10), wraplength=320).pack(pady=(0, 15))

        bf = tk.Frame(frame); bf.pack(fill=tk.X)

        tk.Button(bf, text="＋ 問題を追加する",
                  font=("Yu Gothic UI", 10, "bold"), bg="#81C784", fg="black",
                  width=16, height=2, relief=tk.FLAT, cursor="hand2",
                  ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(bf, text="終了する",
                  font=("Yu Gothic UI", 10), bg="#E0E0E0", fg="black",
                  width=16, height=2, relief=tk.FLAT, cursor="hand2",
                  ).pack(side=tk.LEFT)

        # 画面中央配置
        dialog.update_idletasks()
        w = dialog.winfo_width(); h = dialog.winfo_height()
        dialog.geometry(f"+{(dialog.winfo_screenwidth()-w)//2}+{(dialog.winfo_screenheight()-h)//2}")

        dialog.update_idletasks(); dialog.update()
        _capture_window(dialog, "05_ask_add_more")
        dialog.destroy()


# ============================================================
# 6. _SingleQuestionScorer — ボタンモード (配点 ≤ 9)
# ============================================================


class TestSingleQuestionScorerCapture:

    def test_capture_scorer_button_mode(self):
        """ボタンモード (_show_current 付き) 採点画面"""
        root = get_shared_tk_root()

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            for i in range(5):
                _save_test_image(td, f"student_{i:03d}.jpg", 300, 400)

            image_paths = {f"student_{i:03d}.jpg": str(td / f"student_{i:03d}.jpg")
                           for i in range(5)}

            q_config = {"id": "q1", "name": "記述1", "max_score": 5,
                        "aspect": 1, "region": [50, 50, 250, 350]}

            from descriptive_scorer import _SingleQuestionScorer

            scorer = _SingleQuestionScorer.__new__(_SingleQuestionScorer)
            scorer.parent = root
            scorer.q_config = q_config
            scorer.q_id = "q1"
            scorer.max_score = 5
            scorer.use_entry = False
            scorer.image_paths = image_paths
            scorer.existing_scores = {}
            scorer.filenames = sorted(image_paths.keys())
            scorer.current_idx = 0
            scorer.local_scores = {}
            scorer._result = None
            scorer._tk_images = {}
            scorer._tk_images_order = []
            scorer._MAX_IMG_CACHE = 10
            scorer._win = None

            win = tk.Toplevel(root)
            win.title(f"採点: {q_config['name']} (配点:{scorer.max_score}点)")
            win.geometry("1000x700+80+80")
            win.resizable(True, True)
            scorer._win = win

            # ── container ──
            container = tk.Frame(win)
            container.pack(fill=tk.BOTH, expand=True)

            single_frame = tk.Frame(container)
            single_frame.pack(fill=tk.BOTH, expand=True)

            # ── top_bar (ダークヘッダー) ──
            top_bar = tk.Frame(single_frame, bg="#37474F", padx=6, pady=4)
            top_bar.pack(fill=tk.X)

            scorer.progress_var = tk.StringVar(value="1 / 5")
            tk.Label(top_bar, textvariable=scorer.progress_var,
                     font=("Yu Gothic UI", 14, "bold"),
                     bg="#37474F", fg="#FFD54F").pack(side=tk.LEFT, padx=(0, 12))

            scorer.filename_var = tk.StringVar(value="student_000.jpg")
            tk.Label(top_bar, textvariable=scorer.filename_var,
                     font=("Yu Gothic UI", 8),
                     bg="#37474F", fg="#B0BEC5").pack(side=tk.LEFT, padx=(0, 10))

            tk.Label(top_bar, text="得点:",
                     font=("Yu Gothic UI", 9),
                     bg="#37474F", fg="#FFD54F").pack(side=tk.LEFT)

            scorer.score_var = tk.StringVar(value="—")
            tk.Label(top_bar, textvariable=scorer.score_var,
                     font=("Yu Gothic UI", 16, "bold"),
                     bg="#37474F", fg="#FFD54F").pack(side=tk.LEFT, padx=(2, 10))

            # ○ ボタン
            tk.Button(top_bar, text=f"〇 正解({scorer.max_score}点)",
                      bg="#E3F2FD", fg="#1565C0",
                      font=("Yu Gothic UI", 9, "bold"),
                      relief=tk.RAISED, cursor="hand2",
                      activebackground="#BBDEFB",
                      padx=6, pady=1).pack(side=tk.LEFT, padx=2)

            # × ボタン
            tk.Button(top_bar, text="× 不正解(0点)",
                      bg="#FFEBEE", fg="#C62828",
                      font=("Yu Gothic UI", 9, "bold"),
                      relief=tk.RAISED, cursor="hand2",
                      activebackground="#FFCDD2",
                      padx=6, pady=1).pack(side=tk.LEFT, padx=2)

            # 右寄せ: キャンセル → 完了
            tk.Button(top_bar, text="キャンセル",
                      font=("Yu Gothic UI", 8),
                      bg="#37474F", fg="#B0BEC5",
                      relief=tk.FLAT, cursor="hand2").pack(side=tk.RIGHT, padx=2)
            tk.Button(top_bar, text="✔ 採点完了",
                      bg="#4CAF50", fg="white",
                      font=("Yu Gothic UI", 9, "bold"),
                      relief=tk.FLAT, cursor="hand2",
                      padx=8).pack(side=tk.RIGHT, padx=2)

            # ── mid_bar ──
            mid_bar = tk.Frame(single_frame, bg="#ECEFF1", padx=6, pady=2)
            mid_bar.pack(fill=tk.X)

            tk.Label(mid_bar, text="🔍",
                     font=("Yu Gothic UI", 9), bg="#ECEFF1").pack(side=tk.LEFT)
            zoom_slider = tk.Scale(mid_bar, from_=25, to=300,
                                   orient=tk.HORIZONTAL, length=120,
                                   sliderlength=14, bg="#ECEFF1",
                                   highlightthickness=0, showvalue=False)
            zoom_slider.set(100)
            zoom_slider.pack(side=tk.LEFT, padx=(0, 2))
            tk.Label(mid_bar, text="100%",
                     font=("Yu Gothic UI", 8), fg="#555",
                     bg="#ECEFF1").pack(side=tk.LEFT, padx=(0, 8))

            scorer._filter_unscored_var = tk.BooleanVar(value=False)
            tk.Checkbutton(mid_bar, text="未採点のみ",
                           variable=scorer._filter_unscored_var,
                           font=("Yu Gothic UI", 8),
                           bg="#ECEFF1").pack(side=tk.LEFT, padx=(0, 5))

            scorer._unscored_var = tk.StringVar(value="未採点: 5件")
            tk.Label(mid_bar, textvariable=scorer._unscored_var,
                     font=("Yu Gothic UI", 8), fg="#E65100",
                     bg="#ECEFF1").pack(side=tk.LEFT, padx=(0, 10))

            # 入力可能チェックボックス
            tk.Label(mid_bar, text="|", fg="#ccc", bg="#ECEFF1",
                     font=("Yu Gothic UI", 9)).pack(side=tk.LEFT, padx=(0, 3))
            tk.Label(mid_bar, text="入力可能:",
                     font=("Yu Gothic UI", 8), bg="#ECEFF1").pack(side=tk.LEFT)
            scorer.score_checks = {}
            for i in range(6):
                var = tk.BooleanVar(value=True)
                scorer.score_checks[i] = var
                tk.Checkbutton(mid_bar, text=str(i), variable=var,
                               font=("Yu Gothic UI", 8),
                               bg="#ECEFF1").pack(side=tk.LEFT, padx=1)

            # 右寄せリンク
            tk.Label(mid_bar, text="📷元画像を開く",
                     font=("Yu Gothic UI", 8, "underline"),
                     fg="#1976D2", bg="#ECEFF1",
                     cursor="hand2").pack(side=tk.RIGHT, padx=5)
            tk.Label(mid_bar, text="❓操作方法",
                     font=("Yu Gothic UI", 8, "underline"),
                     fg="#1976D2", bg="#ECEFF1",
                     cursor="hand2").pack(side=tk.RIGHT, padx=5)

            # ── Canvas エリア ──
            canvas_frame = tk.Frame(single_frame)
            canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
            tk.Scrollbar(canvas_frame, orient=tk.VERTICAL).pack(side=tk.RIGHT, fill=tk.Y)
            tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL).pack(side=tk.BOTTOM, fill=tk.X)
            scorer.canvas = tk.Canvas(canvas_frame, bg="white",
                                       highlightthickness=1,
                                       highlightbackground="#ccc")
            scorer.canvas.pack(fill=tk.BOTH, expand=True)

            win.update_idletasks(); win.update()

            # 画像表示
            scorer._show_current()
            win.update_idletasks(); win.update()

            _capture_window(win, "06_single_question_scorer")
            win.destroy()


# ============================================================
# 7. _SingleQuestionScorer — Entry モード (配点 > 9)
# ============================================================


class TestEntryScorerCapture:

    def test_capture_scorer_entry_mode(self):
        """Entry モード (配点 20) — 水平トップバー採点画面"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("採点: 記述問題1 (配点:20点)")
        win.geometry("1000x700+80+80")
        win.resizable(True, True)

        container = tk.Frame(win)
        container.pack(fill=tk.BOTH, expand=True)

        single_frame = tk.Frame(container)
        single_frame.pack(fill=tk.BOTH, expand=True)

        # ── top_bar (ダークヘッダー) ──
        top_bar = tk.Frame(single_frame, bg="#37474F", padx=6, pady=4)
        top_bar.pack(fill=tk.X)

        tk.Label(top_bar, text="5 / 30",
                 font=("Yu Gothic UI", 14, "bold"),
                 bg="#37474F", fg="#FFD54F").pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(top_bar, text="student_005.jpg",
                 font=("Yu Gothic UI", 8),
                 bg="#37474F", fg="#B0BEC5").pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(top_bar, text="得点:",
                 font=("Yu Gothic UI", 9),
                 bg="#37474F", fg="#FFD54F").pack(side=tk.LEFT)

        tk.Label(top_bar, text="15",
                 font=("Yu Gothic UI", 16, "bold"),
                 bg="#37474F", fg="#FFD54F").pack(side=tk.LEFT, padx=(2, 10))

        # 数値入力欄 (配点 > 9)
        entry = tk.Entry(top_bar, width=4,
                         font=("Yu Gothic UI", 12), justify=tk.CENTER)
        entry.pack(side=tk.LEFT, padx=(0, 3))
        entry.insert(0, "15")
        tk.Button(top_bar, text="確定",
                  font=("Yu Gothic UI", 8),
                  bg="#90CAF9", relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 8))

        # ○ ボタン
        tk.Button(top_bar, text="〇 正解(20点)",
                  bg="#E3F2FD", fg="#1565C0",
                  font=("Yu Gothic UI", 9, "bold"),
                  relief=tk.RAISED, cursor="hand2",
                  activebackground="#BBDEFB",
                  padx=6, pady=1).pack(side=tk.LEFT, padx=2)

        # × ボタン
        tk.Button(top_bar, text="× 不正解(0点)",
                  bg="#FFEBEE", fg="#C62828",
                  font=("Yu Gothic UI", 9, "bold"),
                  relief=tk.RAISED, cursor="hand2",
                  activebackground="#FFCDD2",
                  padx=6, pady=1).pack(side=tk.LEFT, padx=2)

        # 右寄せ: キャンセル → 完了
        tk.Button(top_bar, text="キャンセル",
                  font=("Yu Gothic UI", 8),
                  bg="#37474F", fg="#B0BEC5",
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.RIGHT, padx=2)
        tk.Button(top_bar, text="✔ 採点完了",
                  bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 9, "bold"),
                  relief=tk.FLAT, cursor="hand2",
                  padx=8).pack(side=tk.RIGHT, padx=2)

        # ── mid_bar ──
        mid_bar = tk.Frame(single_frame, bg="#ECEFF1", padx=6, pady=2)
        mid_bar.pack(fill=tk.X)

        tk.Label(mid_bar, text="🔍",
                 font=("Yu Gothic UI", 9), bg="#ECEFF1").pack(side=tk.LEFT)
        zoom_slider = tk.Scale(mid_bar, from_=25, to=300,
                               orient=tk.HORIZONTAL, length=120,
                               sliderlength=14, bg="#ECEFF1",
                               highlightthickness=0, showvalue=False)
        zoom_slider.set(100)
        zoom_slider.pack(side=tk.LEFT, padx=(0, 2))
        tk.Label(mid_bar, text="100%",
                 font=("Yu Gothic UI", 8), fg="#555",
                 bg="#ECEFF1").pack(side=tk.LEFT, padx=(0, 8))

        filter_var = tk.BooleanVar(value=False)
        tk.Checkbutton(mid_bar, text="未採点のみ",
                       variable=filter_var,
                       font=("Yu Gothic UI", 8),
                       bg="#ECEFF1").pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(mid_bar, text="未採点: 25件",
                 font=("Yu Gothic UI", 8), fg="#E65100",
                 bg="#ECEFF1").pack(side=tk.LEFT, padx=(0, 10))

        # 右寄せリンク
        tk.Label(mid_bar, text="📷元画像を開く",
                 font=("Yu Gothic UI", 8, "underline"),
                 fg="#1976D2", bg="#ECEFF1",
                 cursor="hand2").pack(side=tk.RIGHT, padx=5)
        tk.Label(mid_bar, text="❓操作方法",
                 font=("Yu Gothic UI", 8, "underline"),
                 fg="#1976D2", bg="#ECEFF1",
                 cursor="hand2").pack(side=tk.RIGHT, padx=5)

        # ── Canvas エリア ──
        canvas_frame = tk.Frame(single_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        tk.Scrollbar(canvas_frame, orient=tk.VERTICAL).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL).pack(side=tk.BOTTOM, fill=tk.X)
        canvas = tk.Canvas(canvas_frame, bg="white",
                           highlightthickness=1,
                           highlightbackground="#ccc")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_text(300, 300, text="(記述回答画像)",
                           fill="#aaa", font=("Yu Gothic UI", 14))

        win.update_idletasks(); win.update()
        _capture_window(win, "07_entry_mode_scorer")
        win.destroy()


# ============================================================
# 8. _edit_score — ボタンモード (配点 ≤ 10)
# ============================================================


class TestEditScoreDialogCapture:

    def test_capture_edit_score_buttons(self):
        """配点 ≤ 10 のボタン式スコア修正"""
        root = get_shared_tk_root()

        dialog = tk.Toplevel(root)
        dialog.title("スコア修正: student_001.jpg")
        dialog.geometry("350x200+200+200")
        dialog.configure(bg="#F5F7FA")

        tk.Label(dialog, text="ファイル: student_001.jpg",
                 bg="#F5F7FA", font=("", 10)).pack(pady=(10, 2))
        tk.Label(dialog, text="現在のスコア: 3",
                 bg="#F5F7FA", font=("", 10)).pack(pady=2)
        tk.Label(dialog, text="配点: 0 ～ 5",
                 bg="#F5F7FA", font=("", 10)).pack(pady=2)

        bf = tk.Frame(dialog, bg="#F5F7FA"); bf.pack(pady=10)
        for s in range(6):
            bg = "#81C784" if s == 3 else "#E0E0E0"
            tk.Button(bf, text=str(s), width=4, font=("", 12, "bold"),
                      bg=bg, relief=tk.RAISED).pack(side=tk.LEFT, padx=2)

        tk.Button(dialog, text="キャンセル", bg="#BDBDBD",
                  relief=tk.FLAT).pack(pady=5)

        dialog.update_idletasks(); dialog.update()
        _capture_window(dialog, "08a_edit_score_buttons")
        dialog.destroy()

    def test_capture_edit_score_entry(self):
        """配点 > 10 の Entry 入力式"""
        root = get_shared_tk_root()

        dialog = tk.Toplevel(root)
        dialog.title("スコア修正: student_001.jpg")
        dialog.geometry("350x220+200+200")
        dialog.configure(bg="#F5F7FA")

        tk.Label(dialog, text="ファイル: student_001.jpg",
                 bg="#F5F7FA", font=("", 10)).pack(pady=(10, 2))
        tk.Label(dialog, text="現在のスコア: 15",
                 bg="#F5F7FA", font=("", 10)).pack(pady=2)
        tk.Label(dialog, text="配点: 0 ～ 25",
                 bg="#F5F7FA", font=("", 10)).pack(pady=2)

        ef = tk.Frame(dialog, bg="#F5F7FA"); ef.pack(pady=10)
        tk.Label(ef, text="得点:", bg="#F5F7FA", font=("", 10)).pack(side=tk.LEFT)
        entry = tk.Entry(ef, width=6, font=("", 14), justify=tk.CENTER)
        entry.pack(side=tk.LEFT, padx=5)
        entry.insert(0, "15")
        tk.Button(ef, text="確定", bg="#81C784", fg="white",
                  font=("", 10, "bold"), relief=tk.FLAT).pack(side=tk.LEFT, padx=5)

        tk.Button(dialog, text="キャンセル", bg="#BDBDBD",
                  relief=tk.FLAT).pack(pady=5)

        dialog.update_idletasks(); dialog.update()
        _capture_window(dialog, "08b_edit_score_entry")
        dialog.destroy()


# ============================================================
# 9. DescriptiveReviewGUI レイアウト (モック)
# ============================================================


class TestDescriptiveReviewGUICapture:

    def test_capture_review_gui(self):
        """記述採点 確認・修正 GUI — グリッド付きモックレイアウト"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("🔎 記述採点の確認・修正")
        win.geometry("1100x700+50+50")
        win.configure(bg="#F5F7FA")

        # 左ペイン: 設問リスト
        left = tk.Frame(win, bg="#F5F7FA", width=220)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0), pady=8)
        left.pack_propagate(False)

        tk.Label(left, text="設問一覧", font=("", 12, "bold"),
                 bg="#F5F7FA").pack(pady=(0, 5))

        lb = tk.Listbox(left, font=("", 11), activestyle="none")
        lb.pack(fill=tk.BOTH, expand=True)
        for q in ["問題1  (配点: 5)", "問題2  (配点: 3)", "記述3  (配点: 10)"]:
            lb.insert(tk.END, q)
        lb.selection_set(0)

        ff = tk.Frame(left, bg="#F5F7FA"); ff.pack(fill=tk.X, pady=(5, 0))
        tk.Label(ff, text="フィルタ:", bg="#F5F7FA", font=("", 9)).pack(side=tk.LEFT)
        fc = ttk.Combobox(ff, values=["全て", "○ 満点", "× 0点", "△ 中間点", "未採点",
                                       "0", "1", "2", "3", "4", "5"],
                          state="readonly", width=10)
        fc.pack(side=tk.LEFT, padx=3); fc.set("全て")

        # 並び順（1C改善: ソートドロップダウン追加）
        sf = tk.Frame(left, bg="#F5F7FA"); sf.pack(fill=tk.X, pady=(3, 0))
        tk.Label(sf, text="並び順:", bg="#F5F7FA", font=("", 9)).pack(side=tk.LEFT)
        sc_combo = ttk.Combobox(sf, values=["ファイル名順","得点 昇順","得点 降順",
                                            "画像の白さ（白い順）"],
                                state="readonly", width=18)
        sc_combo.pack(side=tk.LEFT, padx=3); sc_combo.set("ファイル名順")

        tk.Label(left, text="採点済: 8/10\n平均: 3.50 / 5\n表示: 10件",
                 bg="#F5F7FA", font=("", 9), fg="#555", justify=tk.LEFT,
                 ).pack(fill=tk.X, pady=(5, 0))

        tk.Button(left, text="💾 変更を保存", bg="#81C784", fg="white",
                  font=("", 11, "bold"), relief=tk.FLAT, cursor="hand2",
                  ).pack(fill=tk.X, pady=(8, 0))

        # 右ペイン: グリッド
        right = tk.Frame(win, bg="#F5F7FA")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8)

        # ズームスライダー
        zoom_bar = tk.Frame(right, bg="#37474F", padx=10, pady=4)
        zoom_bar.pack(fill=tk.X)
        tk.Label(zoom_bar, text="🔍 サイズ:",
                 font=("Yu Gothic UI", 9), bg="#37474F", fg="white"
                 ).pack(side=tk.LEFT)
        review_slider = tk.Scale(zoom_bar, from_=80, to=400, orient=tk.HORIZONTAL,
                                  length=200, bg="#37474F", fg="#FFD54F",
                                  troughcolor="#546E7A", highlightthickness=0,
                                  sliderlength=20)
        review_slider.set(200)
        review_slider.pack(side=tk.LEFT, padx=5)
        tk.Label(zoom_bar, text="200px",
                 font=("Yu Gothic UI", 9, "bold"), bg="#37474F", fg="#FFD54F",
                 width=8, anchor=tk.CENTER).pack(side=tk.LEFT, padx=2)

        g_canvas = tk.Canvas(right, bg="#FFFFFF", highlightthickness=0)
        g_scroll = tk.Scrollbar(right, orient=tk.VERTICAL, command=g_canvas.yview)
        g_frame = tk.Frame(g_canvas, bg="#FFFFFF")
        g_canvas.create_window((0, 0), window=g_frame, anchor="nw")
        g_canvas.configure(yscrollcommand=g_scroll.set)
        g_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        g_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        GRID_COLS = 4
        scores = [5, 3, 0, None, 4, 2, 5, 1, None, 3]
        max_sc = 5
        for idx in range(10):
            row, col = divmod(idx, GRID_COLS)
            
            # 1C改善: カード背景色
            sc = scores[idx]
            if sc is None:
                card_bg = "#F5F5F5"
            elif sc >= max_sc:
                card_bg = "#E3F2FD"
            elif sc == 0:
                card_bg = "#FFEBEE"
            else:
                card_bg = "#FFF3E0"
            
            cell = tk.Frame(g_frame, bg=card_bg, bd=1, relief=tk.SOLID,
                            padx=3, pady=3)
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

            c = tk.Canvas(cell, width=150, height=100, bg="#E0E0E0",
                          highlightthickness=0)
            c.pack()
            c.create_text(75, 50, text=f"答案{idx+1}", fill="#666")

            fn = f"student_{idx+1:03d}.jpg"
            tk.Label(cell, text=fn, bg=card_bg, font=("", 8),
                     fg="#555").pack()

            if sc is not None:
                sc_color = "#4CAF50" if sc == max_sc else ("#F44336" if sc == 0 else "#333")
                tk.Label(cell, text=f"{sc} / {max_sc}", bg=card_bg,
                         font=("", 10, "bold"), fg=sc_color).pack()
            else:
                tk.Label(cell, text="未採点", bg=card_bg,
                         font=("", 10, "bold"), fg="#999").pack()

        for c in range(GRID_COLS):
            g_frame.columnconfigure(c, weight=1)

        g_frame.update_idletasks()
        g_canvas.configure(scrollregion=g_canvas.bbox("all"))

        win.update_idletasks(); win.update()
        _capture_window(win, "09_descriptive_review_gui")
        win.destroy()


# ============================================================
# 10. DescriptiveScorerGUI  問題一覧画面 (実コード構造再現)
# ============================================================


class TestDescriptiveScorerListCapture:

    def test_capture_scorer_question_list(self):
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("記述問題 採点")
        win.geometry("600x520+100+100")
        win.resizable(True, True)
        win.minsize(500, 350)

        frame = tk.Frame(win, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="記述問題 採点",
                 font=("Yu Gothic UI", 13, "bold")).pack(pady=(0, 5))
        tk.Label(frame,
                 text="採点する問題を選択してください。完了後「採点完了」を押してください。",
                 font=("Yu Gothic UI", 8), fg="gray", wraplength=540).pack(pady=(0, 8))

        # モード選択プルダウン
        mode_frame = tk.Frame(frame, bg="#F3E5F5", padx=8, pady=4)
        mode_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(mode_frame, text="採点モード:",
                 font=("Yu Gothic UI", 9, "bold"), bg="#F3E5F5"
                 ).pack(side=tk.LEFT)
        mode_cb = ttk.Combobox(mode_frame, values=["1枚ずつ", "一覧（グリッド）"],
                               state="readonly", width=16,
                               font=("Yu Gothic UI", 9))
        mode_cb.set("1枚ずつ")
        mode_cb.pack(side=tk.LEFT, padx=(8, 8))
        tk.Label(mode_frame, text="※ モードを変えるには一度採点を中断してください",
                 font=("Yu Gothic UI", 8), bg="#F3E5F5", fg="#7B1FA2"
                 ).pack(side=tk.LEFT)

        # スクロール対応の問題リスト
        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        questions_frame = tk.Frame(canvas)

        questions_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=questions_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        questions = [
            ("記述1", 5, 1, "3/10 採点済", "gray"),
            ("記述2", 3, 1, "0/10 未着手", "gray"),
            ("記述3", 10, 2, "10/10 完了", "green"),
            ("記述4", 8, 1, "5/10 採点済", "gray"),
            ("記述5", 4, 1, "0/10 未着手", "gray"),
            ("記述6", 6, 2, "10/10 完了", "green"),
            ("記述7", 7, 1, "2/10 採点済", "gray"),
            ("記述8", 3, 1, "0/10 未着手", "gray"),
        ]
        for name, ms, asp, status, color in questions:
            r = tk.Frame(questions_frame, pady=4); r.pack(fill=tk.X)
            tk.Label(r, text=f"{name}  (配点:{ms}点  観点:{asp})",
                     font=("Yu Gothic UI", 9), anchor=tk.W,
                     ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(r, text=status, font=("Yu Gothic UI", 8),
                     width=14, fg=color).pack(side=tk.LEFT, padx=5)
            tk.Button(r, text="設定", width=3, font=("Yu Gothic UI", 8),
                      bg="#FFE082", relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=(0, 3))
            tk.Button(r, text="採点", width=5, font=("Yu Gothic UI", 9),
                      bg="#90CAF9", relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT)

        bf = tk.Frame(frame, pady=10); bf.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Button(bf, text="✔ 採点完了・保存", bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 10, "bold"), width=20, height=2,
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=5)
        tk.Button(bf, text="キャンセル", font=("Yu Gothic UI", 9),
                  width=10).pack(side=tk.LEFT, padx=5)

        win.update_idletasks(); win.update()
        _capture_window(win, "10_descriptive_scorer_list")
        win.destroy()


# ============================================================
# 11. StudentAnswerSheetViewer (モック)
# ============================================================


class TestStudentViewerCapture:

    def test_capture_student_viewer(self):
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("📋 答案表示: student_001.jpg")
        win.geometry("1200x800+50+50")
        win.configure(bg="#F5F7FA")

        main = tk.Frame(win, bg="#F5F7FA", padx=4, pady=4)
        main.pack(fill=tk.BOTH, expand=True)

        # 右パネル
        right = tk.Frame(main, bg="#FFFFFF", width=300, padx=10, pady=10,
                         relief=tk.FLAT, bd=1)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        right.pack_propagate(False)

        tk.Label(right, text="📋 答案ビューア",
                 font=("Yu Gothic UI", 11, "bold"),
                 bg="#FFFFFF", fg="#1565C0").pack(anchor=tk.W, pady=(0, 5))
        tk.Label(right, text="ファイル: student_001.jpg",
                 font=("Yu Gothic UI", 8), bg="#FFFFFF",
                 fg="#546E7A").pack(anchor=tk.W, pady=(0, 10))

        tk.Label(right, text="凡例",
                 font=("Yu Gothic UI", 9, "bold"),
                 bg="#FFFFFF", fg="#546E7A").pack(anchor=tk.W)
        tk.Frame(right, bg="#90CAF9", height=2).pack(fill=tk.X, pady=(2, 5))

        # 灰色枠: 全マーク領域
        legend_row1 = tk.Frame(right, bg="#FFFFFF"); legend_row1.pack(anchor=tk.W)
        c1 = tk.Canvas(legend_row1, width=14, height=14, bg="#FFFFFF", highlightthickness=0)
        c1.pack(side=tk.LEFT, padx=(0, 4))
        c1.create_rectangle(1, 1, 13, 13, outline="#9E9E9E", width=2)
        tk.Label(legend_row1, text="全マーク領域（灰色枠）",
                 font=("Yu Gothic UI", 8), bg="#FFFFFF", fg="#666").pack(side=tk.LEFT)

        # 赤枠: マーク有判定
        legend_row2 = tk.Frame(right, bg="#FFFFFF"); legend_row2.pack(anchor=tk.W)
        c2 = tk.Canvas(legend_row2, width=14, height=14, bg="#FFFFFF", highlightthickness=0)
        c2.pack(side=tk.LEFT, padx=(0, 4))
        c2.create_rectangle(1, 1, 13, 13, outline="#D32F2F", width=2)
        tk.Label(legend_row2, text="マーク有判定（赤枠）",
                 font=("Yu Gothic UI", 8), bg="#FFFFFF", fg="#666").pack(side=tk.LEFT)

        # シアン枠: クリックした設問
        legend_row3 = tk.Frame(right, bg="#FFFFFF"); legend_row3.pack(anchor=tk.W)
        c3 = tk.Canvas(legend_row3, width=14, height=14, bg="#FFFFFF", highlightthickness=0)
        c3.pack(side=tk.LEFT, padx=(0, 4))
        c3.create_rectangle(1, 1, 13, 13, outline="#00B4DC", width=2)
        tk.Label(legend_row3, text="クリックした設問（注目）",
                 font=("Yu Gothic UI", 8), bg="#FFFFFF", fg="#666").pack(side=tk.LEFT)

        tk.Label(right, text="─" * 30, fg="#ccc", bg="#FFFFFF").pack(pady=5)

        tk.Label(right, text="Color Threshold:",
                 font=("Yu Gothic UI", 9, "bold"), bg="#FFFFFF").pack(anchor=tk.W)
        s1 = tk.Scale(right, from_=0.03, to=0.35, resolution=0.005, orient=tk.HORIZONTAL,
                 bg="#FFFFFF", length=260)
        s1.set(0.15); s1.pack()
        tk.Label(right, text="Area Threshold:",
                 font=("Yu Gothic UI", 9, "bold"), bg="#FFFFFF").pack(anchor=tk.W)
        s2 = tk.Scale(right, from_=0.05, to=0.80, resolution=0.01, orient=tk.HORIZONTAL,
                 bg="#FFFFFF", length=260)
        s2.set(0.40); s2.pack()

        # 統計パネル
        tk.Label(right, text="─" * 30, fg="#ccc", bg="#FFFFFF").pack(pady=5)
        tk.Label(right, text="この答案の統計",
                 font=("Yu Gothic UI", 9, "bold"), bg="#FFFFFF").pack(anchor=tk.W)
        stats_text = tk.Text(right, height=8, font=("Consolas", 8), bg="#FAFAFA",
                             relief=tk.FLAT, bd=1, state=tk.DISABLED, wrap=tk.WORD)
        stats_text.pack(fill=tk.X, pady=(3, 5))

        # ボタン
        tk.Button(right, text="↑ キャリブレーターに閾値を反映",
                  bg="#BBDEFB", font=("Yu Gothic UI", 8),
                  relief=tk.FLAT, cursor="hand2").pack(fill=tk.X, pady=2)
        tk.Button(right, text="↓ キャリブレーターから閾値を取得",
                  bg="#C8E6C9", font=("Yu Gothic UI", 8),
                  relief=tk.FLAT, cursor="hand2").pack(fill=tk.X, pady=2)
        tk.Button(right, text="閉じる",
                  bg="#EEEEEE", font=("Yu Gothic UI", 8),
                  relief=tk.FLAT, cursor="hand2").pack(fill=tk.X, pady=2)

        # 左: Canvas
        cv = tk.Canvas(main, bg="white", highlightthickness=1,
                       highlightbackground="#ccc")
        cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cv.create_rectangle(10, 10, 850, 760, outline="#ccc", dash=(4, 4))
        cv.create_text(430, 385, text="(答案画像表示エリア)", fill="#aaa",
                       font=("Yu Gothic UI", 14))

        win.update_idletasks(); win.update()
        _capture_window(win, "11_student_viewer")
        win.destroy()


# ============================================================
# 12. 記述設定3択ダイアログ
# ============================================================


class TestDescriptiveSetupActionCapture:

    def test_capture_descriptive_setup_action(self):
        """既に設定がある場合の 3択ダイアログ"""
        root = get_shared_tk_root()

        dialog = tk.Toplevel(root)
        dialog.title("記述問題設定")
        dialog.resizable(False, False)

        tk.Label(dialog,
                 text="既に記述問題の設定が存在します。\nどの操作を行いますか？",
                 font=("Yu Gothic UI", 10), justify=tk.LEFT,
                 padx=20, pady=15).pack(fill=tk.X)

        bf = tk.Frame(dialog, padx=20, pady=10); bf.pack(fill=tk.X)

        tk.Button(bf, text="設定を続行（問題を追加）",
                  bg="#A5D6A7", font=("Yu Gothic UI", 9, "bold"),
                  relief=tk.FLAT, cursor="hand2", height=2).pack(fill=tk.X, pady=2)
        tk.Button(bf, text="🗑 既存設定を初期化",
                  bg="#FFCDD2", font=("Yu Gothic UI", 9),
                  relief=tk.FLAT, cursor="hand2", height=2).pack(fill=tk.X, pady=2)
        tk.Button(bf, text="キャンセル",
                  bg="#EEEEEE", font=("Yu Gothic UI", 9),
                  relief=tk.FLAT, cursor="hand2").pack(fill=tk.X, pady=2)

        dialog.update_idletasks()
        w = dialog.winfo_width(); h = dialog.winfo_height()
        dialog.geometry(
            f"+{(dialog.winfo_screenwidth()-w)//2}+{(dialog.winfo_screenheight()-h)//2}"
        )
        dialog.update(); dialog.update_idletasks()

        _capture_window(dialog, "12_descriptive_setup_action")
        dialog.destroy()


# ============================================================
# 13. select_total_position モック
# ============================================================


class TestSelectTotalPositionCapture:

    def test_capture_select_total_position(self):
        """合計得点位置選択ウィンドウのモック"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("合計点表示位置 — ボックスをドラッグで移動、端でリサイズ")
        win.geometry("900x700+80+80")
        win.resizable(False, False)
        win.configure(bg="#F5F7FA")

        main = tk.Frame(win, bg="#F5F7FA")
        main.pack(fill=tk.BOTH, expand=True)

        # 左: Canvas + 画像
        cv = tk.Canvas(main, bg="white", width=650, height=670,
                       highlightthickness=1, highlightbackground="#ccc")
        cv.pack(side=tk.LEFT, padx=5, pady=5)
        cv.create_rectangle(10, 10, 640, 660, outline="#ccc", dash=(4, 4))
        cv.create_text(325, 335, text="(答案画像プレビュー)", fill="#aaa",
                       font=("Yu Gothic UI", 12))
        # ドラッグボックス疑似描画
        cv.create_rectangle(200, 50, 450, 120, outline="#FF5722", width=2,
                            dash=(6, 3))
        cv.create_text(325, 85, text="合計: 85点",
                       fill="#FF5722", font=("Yu Gothic UI", 14, "bold"))

        # 右: 操作パネル
        panel = tk.Frame(main, bg="#F5F7FA", width=220, padx=10, pady=10)
        panel.pack(side=tk.RIGHT, fill=tk.Y)
        panel.pack_propagate(False)

        tk.Label(panel, text="合計得点 記入位置",
                 font=("Yu Gothic UI", 11, "bold"), bg="#F5F7FA",
                 fg="#1976D2").pack(anchor=tk.W, pady=(0, 10))
        tk.Label(panel,
                 text="赤枠をドラッグして\n合計得点の記入位置を\n指定してください。\n\n四隅のハンドルで\nサイズを変更できます。",
                 font=("Yu Gothic UI", 9), bg="#F5F7FA", fg="#666",
                 justify=tk.LEFT, wraplength=190).pack(anchor=tk.W, pady=(0, 15))

        tk.Label(panel, text="─" * 20, fg="#ccc", bg="#F5F7FA").pack(pady=5)
        tk.Label(panel, text="サイズ: 250 × 70",
                 font=("Yu Gothic UI", 9), bg="#F5F7FA").pack(anchor=tk.W)

        tk.Label(panel, text="─" * 20, fg="#ccc", bg="#F5F7FA").pack(pady=5)
        tk.Button(panel, text="✔ 決定", bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 10, "bold"), width=16,
                  relief=tk.FLAT, cursor="hand2").pack(pady=3)
        tk.Button(panel, text="✖ キャンセル",
                  font=("Yu Gothic UI", 9), width=16).pack(pady=3)

        win.update_idletasks(); win.update()
        _capture_window(win, "13_select_total_position")
        win.destroy()


# ============================================================
# 14. 画面遷移: スタートアップ → メイン
# ============================================================


class TestScreenTransitionCapture:

    def test_capture_transition_startup_to_main(self):
        root = get_shared_tk_root()

        # Step 1: スタートアップ
        from gui_components import StartupModeDialog
        d = StartupModeDialog.__new__(StartupModeDialog)
        d.root = root; d.result = None; d._session_path = None
        d._build_dialog()
        d.dialog.update_idletasks(); d.dialog.update()
        _capture_window(d.dialog, "14a_transition_startup")
        d.dialog.destroy()

        # Step 2: メイン GUI
        from main_gui import SaitenSamuraiGUI
        gw = tk.Toplevel(root)
        gui = SaitenSamuraiGUI(gw, mode=MODE_MARK_AND_DESCRIPTIVE)
        gw.geometry("1100x600+80+80")
        gw.update_idletasks(); gw.update()
        _capture_window(gw, "14b_transition_main")
        gw.destroy()


# ============================================================
# 15. select_region_on_image (名前領域選択) モック
# ============================================================


class TestSelectRegionCapture:

    def test_capture_select_region(self):
        """名前領域選択ウィンドウのモック"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("名前エリアの選択 — ドラッグで矩形を描いてください")
        win.geometry("900x700+80+80")
        win.resizable(False, False)
        win.configure(bg="#F5F7FA")

        main = tk.Frame(win, bg="#F5F7FA")
        main.pack(fill=tk.BOTH, expand=True)

        cv = tk.Canvas(main, bg="white", width=650, height=670,
                       highlightthickness=1, highlightbackground="#ccc")
        cv.pack(side=tk.LEFT, padx=5, pady=5)
        cv.create_rectangle(10, 10, 640, 660, outline="#ccc", dash=(4, 4))
        cv.create_text(325, 335, text="(マークシート画像)",
                       fill="#aaa", font=("Yu Gothic UI", 12))

        # 名前領域ドラッグ矩形
        cv.create_rectangle(30, 20, 300, 80, outline="#2196F3", width=2)
        cv.create_text(165, 50, text="名前エリア", fill="#2196F3",
                       font=("Yu Gothic UI", 10, "bold"))

        panel = tk.Frame(main, bg="#F5F7FA", width=220, padx=10, pady=10)
        panel.pack(side=tk.RIGHT, fill=tk.Y)
        panel.pack_propagate(False)

        tk.Label(panel, text="名前エリア 選択",
                 font=("Yu Gothic UI", 11, "bold"), bg="#F5F7FA",
                 fg="#1976D2").pack(anchor=tk.W, pady=(0, 10))
        tk.Label(panel,
                 text="画像上でドラッグして\n名前エリアを選択して\nください。",
                 font=("Yu Gothic UI", 9), bg="#F5F7FA", fg="#666",
                 justify=tk.LEFT, wraplength=190).pack(anchor=tk.W, pady=(0, 15))

        tk.Label(panel, text="─" * 20, fg="#ccc", bg="#F5F7FA").pack(pady=5)
        tk.Button(panel, text="✔ 決定", bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 10, "bold"), width=16,
                  relief=tk.FLAT, cursor="hand2").pack(pady=3)
        tk.Button(panel, text="✖ キャンセル",
                  font=("Yu Gothic UI", 9), width=16).pack(pady=3)

        win.update_idletasks(); win.update()
        _capture_window(win, "15_select_region")
        win.destroy()


# ============================================================
# 16. パス修復ダイアログ モック
# ============================================================


class TestPathRepairCapture:

    def test_capture_path_repair_dialog(self):
        root = get_shared_tk_root()

        dialog = tk.Toplevel(root)
        dialog.title("パスの修復")
        dialog.resizable(False, False)

        tk.Label(dialog,
                 text="一部のファイルパスが見つかりません。\n正しいパスを指定してください。",
                 font=("Yu Gothic UI", 10), justify=tk.LEFT,
                 padx=20, pady=15).pack(fill=tk.X)

        items_frame = tk.Frame(dialog, padx=20, pady=5)
        items_frame.pack(fill=tk.X)

        paths = [
            ("画像フォルダ", "C:/old/path/images"),
            ("座標ファイル", "C:/old/path/coords.xlsx"),
        ]
        for label, old_path in paths:
            r = tk.Frame(items_frame, pady=3); r.pack(fill=tk.X)
            tk.Label(r, text=f"{label}:", font=("Yu Gothic UI", 9),
                     width=12, anchor=tk.W).pack(side=tk.LEFT)
            e = tk.Entry(r, font=("Yu Gothic UI", 9), width=35)
            e.pack(side=tk.LEFT, padx=3)
            e.insert(0, old_path)
            tk.Button(r, text="参照...", font=("Yu Gothic UI", 8)).pack(side=tk.LEFT)

        bf = tk.Frame(dialog, padx=20, pady=15); bf.pack(fill=tk.X)
        tk.Button(bf, text="復元する", bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 9, "bold"), width=12,
                  relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(bf, text="中断", font=("Yu Gothic UI", 9),
                  width=12).pack(side=tk.LEFT, padx=5)

        dialog.update_idletasks()
        w = dialog.winfo_width(); h = dialog.winfo_height()
        dialog.geometry(
            f"+{(dialog.winfo_screenwidth()-w)//2}+{(dialog.winfo_screenheight()-h)//2}"
        )
        dialog.update(); dialog.update_idletasks()

        _capture_window(dialog, "16_path_repair_dialog")
        dialog.destroy()


# ============================================================
# 17. ThresholdCalibratorGUI レイアウト (モック)
# ============================================================


class TestThresholdCalibratorCapture:

    def test_capture_threshold_calibrator(self):
        """閾値キャリブレーション画面のモックレイアウト"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("🔧 閾値キャリブレーション")
        win.geometry("1100x700+50+50")

        main = tk.Frame(win)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 左: コントロールパネル
        left = tk.Frame(main, width=280, padx=10, pady=5)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        tk.Label(left, text="🔧 閾値キャリブレーション",
                 font=("Yu Gothic UI", 12, "bold"),
                 fg="#7B1FA2").pack(anchor=tk.W, pady=(0, 10))

        tk.Button(left, text="▶ 自動計算 実行",
                  bg="#CE93D8", fg="white",
                  font=("Yu Gothic UI", 10, "bold"),
                  relief=tk.FLAT, cursor="hand2", width=22).pack(pady=5)

        tk.Label(left, text="計算中...",
                 font=("Yu Gothic UI", 9), fg="#888").pack(anchor=tk.W)
        tk.Label(left, text="推奨値: ---",
                 font=("Yu Gothic UI", 9), fg="#1976D2").pack(anchor=tk.W, pady=(0, 5))

        tk.Label(left, text="─" * 25, fg="#ccc").pack(pady=5)

        tk.Label(left, text="色の読取感度:",
                 font=("Yu Gothic UI", 9, "bold")).pack(anchor=tk.W)
        s1 = tk.Scale(left, from_=0.03, to=0.35, resolution=0.005,
                      orient=tk.HORIZONTAL, length=250)
        s1.set(0.15); s1.pack()

        tk.Label(left, text="面積の読取感度:",
                 font=("Yu Gothic UI", 9, "bold")).pack(anchor=tk.W)
        s2 = tk.Scale(left, from_=0.05, to=0.80, resolution=0.01,
                      orient=tk.HORIZONTAL, length=250)
        s2.set(0.40); s2.pack()

        tk.Label(left, text="─" * 25, fg="#ccc").pack(pady=5)

        tk.Button(left, text="🔄 この閾値で再判定",
                  bg="#B3E5FC", fg="black",
                  font=("Yu Gothic UI", 9),
                  relief=tk.FLAT, width=22,
                  state=tk.DISABLED).pack(pady=3)

        # 統計テキスト
        stats_text = tk.Text(left, height=6, font=("Consolas", 8),
                             bg="#FAFAFA", relief=tk.FLAT, bd=1,
                             state=tk.DISABLED, wrap=tk.WORD)
        stats_text.pack(fill=tk.X, pady=5)

        tk.Label(left, text="─" * 25, fg="#ccc").pack(pady=5)

        tk.Button(left, text="✓ 適用して閉じる",
                  bg="#A5D6A7", fg="black",
                  font=("Yu Gothic UI", 9, "bold"),
                  relief=tk.FLAT, width=22).pack(pady=3)
        tk.Button(left, text="キャンセル",
                  font=("Yu Gothic UI", 9), width=22).pack(pady=3)

        # 右: サムネイルギャラリー
        right = tk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        gallery = tk.Frame(right, bg="#FFFFFF", bd=1, relief=tk.SOLID)
        gallery.pack(fill=tk.BOTH, expand=True)

        # プレースホルダーテキストを grid で配置
        placeholder = tk.Label(gallery, text="（自動計算後にサムネイルが表示されます）",
                 font=("Yu Gothic UI", 10), fg="#999", bg="#FFFFFF")
        placeholder.grid(row=0, column=0, columnspan=5, sticky="nsew", pady=10)

        COLS = 5
        for idx in range(15):
            r, c = divmod(idx, COLS)
            cell = tk.Frame(gallery, bg="#FFFFFF", padx=2, pady=2)
            cell.grid(row=r + 1, column=c, padx=3, pady=3, sticky="nsew")

            cv = tk.Canvas(cell, width=80, height=80, bg="#E8E8E8",
                           highlightthickness=1, highlightbackground="#ccc")
            cv.pack()
            cv.create_text(40, 40, text=f"{idx+1}", fill="#888",
                           font=("", 10))
            tk.Label(cell, text=f"img_{idx+1:03d}.jpg", bg="#FFFFFF",
                     font=("", 7), fg="#888").pack()

        for c in range(COLS):
            gallery.columnconfigure(c, weight=1)

        win.update_idletasks(); win.update()
        _capture_window(win, "17_threshold_calibrator")
        win.destroy()


# ============================================================
# 18. MarkCheckerGUI レイアウト (モック)
# ============================================================


class TestMarkCheckerCapture:

    def test_capture_mark_checker(self):
        """マークエラーチェック GUI のモックレイアウト（実際の MarkCheckerGUI に準拠）"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("マークエラーチェック")
        win.geometry("1200x750+50+50")

        # --- 入力ファイル情報 ---
        file_info_frame = tk.Frame(win, bg='#e8f4f8', padx=10, pady=8, relief=tk.RIDGE, bd=2)
        file_info_frame.pack(fill=tk.X)
        tk.Label(file_info_frame, text="【入力ファイル情報】",
                 font=('Arial', 10, 'bold'), bg='#e8f4f8').pack(anchor=tk.W)
        info_text = tk.Text(file_info_frame, height=4, font=('Consolas', 8),
                            bg='#f5f5f5', relief=tk.FLAT, wrap=tk.NONE)
        info_text.pack(fill=tk.X, pady=(5, 0))
        info_text.insert(tk.END,
            "画像フォルダ: exam_2026/images\n"
            "座標CSV:      _saiten_grading_results/_temp/reading_results/coordinates.csv\n"
            "Result Excel: _saiten_grading_results/_temp/reading_results/Mark2-Result.xlsx\n"
            "画像枚数: 25枚"
        )
        info_text.config(state=tk.DISABLED)

        # --- ステータスバー ---
        status_frame = tk.Frame(win, bg='lightblue', padx=10, pady=10)
        status_frame.pack(fill=tk.X)
        tk.Label(status_frame,
                 text="要チェック数5件 / チェック済み0件 / 進捗0%",
                 font=('Arial', 12, 'bold'), bg='lightblue').pack()

        # --- 画像表示エリア ---
        display_frame = tk.Frame(win, padx=10, pady=10)
        display_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(display_frame,
                 text="ファイル: student_003.jpg / 問題番号: Q5 / エラー種別: 複数マーク",
                 font=('Arial', 10)).pack(fill=tk.X, pady=(0, 10))

        img_label = tk.Label(display_frame, bg='white', relief=tk.SUNKEN,
                             text="(マークシート画像 + エラー箇所ハイライト)",
                             font=('Arial', 12), fg='#aaa')
        img_label.pack(fill=tk.BOTH, expand=True)

        # --- 操作パネル ---
        control_frame = tk.Frame(win, padx=10, pady=10)
        control_frame.pack(fill=tk.X)

        # 読み取り結果
        result_frame = tk.Frame(control_frame)
        result_frame.pack(pady=(0, 10))
        tk.Label(result_frame, text="読み取り結果:", font=('Arial', 10)).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(result_frame, text="1, 3 (複数マーク)", font=('Arial', 12, 'bold'), fg='red').pack(side=tk.LEFT)

        # 選択肢ボタン行
        choice_frame = tk.Frame(control_frame)
        choice_frame.pack(pady=(0, 5))
        tk.Label(choice_frame, text="選択:", font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 5))
        for i in range(1, 11):
            tk.Button(choice_frame, text=str(i), width=3, font=('Arial', 10, 'bold'),
                      bg='#E3F2FD', relief=tk.RAISED).pack(side=tk.LEFT, padx=1)
        tk.Button(choice_frame, text="-1", width=3, font=('Arial', 10, 'bold'),
                  bg='#FFCDD2', relief=tk.RAISED).pack(side=tk.LEFT, padx=(5, 0))

        # 手入力行
        input_frame = tk.Frame(control_frame)
        input_frame.pack(pady=(0, 10))
        tk.Label(input_frame, text="修正:", font=('Arial', 9), fg='gray').pack(side=tk.LEFT, padx=(0, 5))
        ent = tk.Entry(input_frame, font=('Arial', 10), width=6, fg='#555')
        ent.pack(side=tk.LEFT, padx=(0, 5))
        ent.insert(0, "-1")
        tk.Label(input_frame, text="(1-10, -1=マークなし / Enterで保存)",
                 font=('Arial', 8), fg='#999').pack(side=tk.LEFT)

        # ナビゲーションボタン
        nav_frame = tk.Frame(control_frame)
        nav_frame.pack(pady=(0, 10))
        tk.Button(nav_frame, text="← 前へ", width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text="保存して次へ →", bg='#4CAF50', fg='white',
                  font=('Arial', 10, 'bold'), width=18).pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text="SKIP", bg='#FF9800', fg='white',
                  font=('Arial', 10, 'bold'), width=10).pack(side=tk.LEFT, padx=5)

        # 反映ボタン
        tk.Button(control_frame, text="チェック結果をxlsxに反映", bg='darkgreen', fg='white',
                  font=('Arial', 11, 'bold'), width=30, height=2).pack()

        win.update_idletasks(); win.update()
        _capture_window(win, "18_mark_checker")
        win.destroy()


# ============================================================
# 19. 統合記述設定ウィンドウ (Phase 2A)
# ============================================================


class TestIntegratedDescriptiveSetupCapture:

    def test_capture_integrated_setup(self):
        """統合記述設定ウィンドウのモック"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("📝 記述問題の設定")
        win.geometry("1040x720")
        win.configure(bg="#F5F7FA")
        BG = "#F5F7FA"

        main = tk.Frame(win, bg=BG, padx=8, pady=8)
        main.pack(fill=tk.BOTH, expand=True)

        # 左 Canvas
        left = tk.Frame(main, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH)
        tk.Label(left, text="答案画像（ドラッグで領域を選択）",
                 font=("Yu Gothic UI", 10, "bold"), bg=BG, fg="#333").pack(anchor=tk.W, pady=(0, 3))
        canvas = tk.Canvas(left, width=500, height=600, bg="white",
                           highlightthickness=1, highlightbackground="#999", cursor="crosshair")
        canvas.pack()
        # ダミー矩形
        canvas.create_rectangle(20, 50, 480, 180, outline="#FF6464", width=3)
        canvas.create_text(30, 60, text="D1: 記述1", anchor="nw", fill="#FF6464",
                           font=("Yu Gothic UI", 10))
        canvas.create_rectangle(20, 220, 480, 380, outline="#6464FF", width=3)
        canvas.create_text(30, 230, text="D2: 記述2", anchor="nw", fill="#6464FF",
                           font=("Yu Gothic UI", 10))

        tk.Label(left, text="💡 ドラッグで新しい記述領域を追加できます",
                 font=("Yu Gothic UI", 8), bg=BG, fg="#777").pack(anchor=tk.W, pady=(3, 0))

        # 右 テーブル
        right = tk.Frame(main, bg=BG, padx=10)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(right, text="設問一覧",
                 font=("Yu Gothic UI", 11, "bold"), bg=BG, fg="#333").pack(anchor=tk.W, pady=(0, 5))

        cols = ("id", "name", "score", "aspect")
        tree = ttk.Treeview(right, columns=cols, show="headings", height=10,
                            selectmode="browse")
        tree.heading("id", text="#")
        tree.heading("name", text="問題名")
        tree.heading("score", text="配点")
        tree.heading("aspect", text="観点")
        tree.column("id", width=40, anchor="center")
        tree.column("name", width=120)
        tree.column("score", width=50, anchor="center")
        tree.column("aspect", width=50, anchor="center")
        tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        tree.insert("", tk.END, values=("D1", "記述1", 5, 1))
        tree.insert("", tk.END, values=("D2", "記述2", 10, 1))

        btn_frame = tk.Frame(right, bg=BG)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        tk.Button(btn_frame, text="🗑 選択行を削除",
                  font=("Yu Gothic UI", 9), bg="#FFCDD2", relief=tk.FLAT,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(btn_frame, text="", bg=BG).pack(side=tk.LEFT, expand=True)
        tk.Button(btn_frame, text="キャンセル",
                  font=("Yu Gothic UI", 9), bg="#E0E0E0", relief=tk.FLAT,
                  cursor="hand2").pack(side=tk.RIGHT, padx=(5, 0))
        tk.Button(btn_frame, text="✔ 設定を保存",
                  font=("Yu Gothic UI", 10, "bold"), bg="#81C784", fg="white",
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.RIGHT)

        tk.Label(right, text="登録済み: 2 問  |  合計配点: 15 点",
                 bg=BG, font=("Yu Gothic UI", 9), fg="#555").pack(anchor=tk.W, pady=(5, 0))

        win.update_idletasks(); win.update()
        _capture_window(win, "19_integrated_descriptive_setup")
        win.destroy()


# ============================================================
# 20. 一覧グリッド採点モード (Phase 2B)
# ============================================================


class TestGridScoringModeCapture:

    def test_capture_grid_scoring(self):
        """一覧グリッド採点モードのモック"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("採点: 記述1 (配点:5点)")
        win.geometry("1000x700")
        win.configure(bg="#F5F7FA")
        BG = "#F5F7FA"

        # ズームバー (ウィンドウ上部)
        zoom_bar = tk.Frame(win, bg="#37474F", padx=10, pady=4)
        zoom_bar.pack(fill=tk.X)
        zoom_frame = tk.Frame(zoom_bar, bg="#37474F")
        zoom_frame.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        tk.Label(zoom_frame, text="🔍 サイズ:",
                 font=("Yu Gothic UI", 9), bg="#37474F", fg="white"
                 ).pack(side=tk.LEFT)
        zoom_slider = tk.Scale(zoom_frame, from_=80, to=800, orient=tk.HORIZONTAL,
                               length=200, bg="#37474F", fg="#FFD54F",
                               troughcolor="#546E7A", highlightthickness=0,
                               sliderlength=20)
        zoom_slider.set(160)
        zoom_slider.pack(side=tk.LEFT, padx=5)
        tk.Label(zoom_frame, text="160px",
                 font=("Yu Gothic UI", 9, "bold"), bg="#37474F", fg="#FFD54F",
                 width=8, anchor=tk.CENTER).pack(side=tk.LEFT, padx=2)

        # 上部バー
        top_bar = tk.Frame(win, bg=BG, padx=8, pady=5)
        top_bar.pack(fill=tk.X)
        tk.Label(top_bar, text="並び順:", font=("Yu Gothic UI", 9), bg=BG).pack(side=tk.LEFT)
        sort_combo = ttk.Combobox(top_bar, values=["ファイル名順", "得点 昇順", "得点 降順",
                                                  "画像の白さ（白い順）"],
                                  state="readonly", width=18)
        sort_combo.set("ファイル名順")
        sort_combo.pack(side=tk.LEFT, padx=(3, 10))
        tk.Label(top_bar, text="採点済み: 3/6  (未採点: 3)",
                 font=("Yu Gothic UI", 9, "bold"), bg=BG, fg="#555").pack(side=tk.LEFT)
        tk.Label(top_bar, text="", bg=BG).pack(side=tk.LEFT, expand=True)
        tk.Button(top_bar, text="✔ この問題の採点完了", bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 9, "bold"), relief=tk.FLAT).pack(side=tk.RIGHT)

        # グリッドエリア
        grid_area = tk.Frame(win, bg=BG, padx=8)
        grid_area.pack(fill=tk.BOTH, expand=True)

        # ダミーカード
        card_data = [
            ("student01.jpg", 5, "#E3F2FD", "○", "#1565C0"),
            ("student02.jpg", 3, "#FFF3E0", "△", "#E65100"),
            ("student03.jpg", 0, "#FFEBEE", "×", "#C62828"),
            ("student04.jpg", None, "#F5F5F5", "─", "#999"),
            ("student05.jpg", None, "#F5F5F5", "─", "#999"),
            ("student06.jpg", 5, "#E3F2FD", "○", "#1565C0"),
        ]

        for i, (fn, score, bg_col, mark, mark_fg) in enumerate(card_data):
            r, c = divmod(i, 4)
            card = tk.Frame(grid_area, bg=bg_col, bd=1, relief=tk.RAISED,
                            padx=3, pady=3, width=180, height=150)
            card.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
            card.grid_propagate(False)

            # プレースホルダーサムネイル
            thumb = tk.Label(card, text="📄", font=("", 24), bg=bg_col)
            thumb.pack(pady=(5, 0))

            sf = tk.Frame(card, bg=bg_col)
            sf.pack(fill=tk.X)
            tk.Label(sf, text=mark, font=("Yu Gothic UI", 12, "bold"),
                     fg=mark_fg, bg=bg_col).pack(side=tk.LEFT)
            score_text = f"{score}点" if score is not None else "未採点"
            tk.Label(sf, text=score_text, font=("Yu Gothic UI", 8),
                     fg="#555", bg=bg_col).pack(side=tk.LEFT, padx=3)

            tk.Label(card, text=fn, font=("Yu Gothic UI", 7),
                     fg="#777", bg=bg_col).pack()

        for c in range(4):
            grid_area.columnconfigure(c, weight=1)

        # 下部得点ボタンバー
        score_bar = tk.Frame(win, bg="#ECEFF1", padx=8, pady=8)
        score_bar.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(score_bar, text="得点ボタン（クリック後、サムネイルをクリックで得点付与）:",
                 font=("Yu Gothic UI", 9), bg="#ECEFF1", fg="#555").pack(side=tk.LEFT, padx=(0, 8))
        for i in range(6):
            bg_c = "#FF8A65" if i == 3 else "#E3F2FD"
            rel = tk.SUNKEN if i == 3 else tk.RAISED
            tk.Button(score_bar, text=str(i), width=3, font=("Yu Gothic UI", 10, "bold"),
                      bg=bg_c, relief=rel, cursor="hand2").pack(side=tk.LEFT, padx=2)
        # 📷 答案を表示ボタン
        tk.Button(score_bar, text="📷 答案を表示",
                  font=("Yu Gothic UI", 9, "bold"),
                  bg="#E3F2FD", relief=tk.RAISED,
                  cursor="hand2").pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(score_bar, text="選択解除", font=("Yu Gothic UI", 8),
                  bg="#E0E0E0", relief=tk.FLAT,
                  cursor="hand2").pack(side=tk.RIGHT, padx=(4, 0))
        tk.Label(score_bar, text="アクティブ: 3点",
                 font=("Yu Gothic UI", 9, "bold"), bg="#ECEFF1", fg="#E65100"
                 ).pack(side=tk.RIGHT, padx=(0, 10))

        win.update_idletasks(); win.update()
        _capture_window(win, "20_grid_scoring_mode")
        win.destroy()


# ============================================================
# インベントリメタテスト
# ============================================================


class TestCaptureInventory:

    def test_captures_directory_exists(self):
        assert CAPTURE_DIR.exists()

    def test_captures_summary(self):
        """生成されたキャプチャの一覧を表示"""
        pngs = sorted(CAPTURE_DIR.glob("*.png"))
        print(f"\n  キャプチャ数: {len(pngs)}")
        for f in pngs:
            print(f"    {f.name} ({f.stat().st_size:,} bytes)")
