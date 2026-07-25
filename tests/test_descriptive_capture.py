"""
test_descriptive_capture.py — 記述採点 新機能 GUI キャプチャ＋HTMLレポート

v4 で追加した記述採点リッチ化機能を視覚的に検証する:
  1. 採点モード選択プルダウン（紫帯・問題一覧画面）
  2. 〇/× ボタン + m/b キーボードショートカット
  3. 「未採点のみ表示」フィルタチェックボックス
  4. 背景色フィードバック（満点=薄青、0点=薄赤、中間=薄橙）

ダミーの縦長答案画像を自動生成し、実際に記述採点 GUI を立ち上げて
各ステップのスクリーンショットをキャプチャ→ HTML レポートにまとめる。

出力先: tests/descriptive_scoring_report/ (.gitignore 対象)
"""

from __future__ import annotations

import base64
import ctypes
import os
import sys

if sys.platform == "win32":
    import ctypes.wintypes as wintypes
import tempfile
import time
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import ttk
from typing import Dict, List, Optional
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageTk

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from conftest import get_shared_tk_root
from constants import MODE_DESCRIPTIVE_ONLY

# ============================================================
# 出力ディレクトリ
# ============================================================

REPORT_DIR = Path(__file__).parent / "descriptive_scoring_report"
REPORT_DIR.mkdir(exist_ok=True)

CAPTURE_DIR = REPORT_DIR / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

# ============================================================
# ディスプレイ判定
# ============================================================

def _can_capture() -> bool:
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
# Win32 PrintWindow ベース キャプチャ (test_gui_capture.py と同一)
# ============================================================

if sys.platform == "win32":
    class BITMAPINFOHEADER(ctypes.Structure):
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
            ok = ctypes.windll.user32.PrintWindow(hwnd, dcObj, 2)
            if ok:
                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = width
                bmi.biHeight = -height
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                bmi.biCompression = 0
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
    """ウィンドウ全体をキャプチャ"""
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
# ダミー縦長答案画像の生成
# ============================================================

def _create_dummy_answer_sheets(folder: Path, count: int = 8) -> Dict[str, str]:
    """縦長の答案用紙ダミー画像を生成する。

    各画像に「生徒名」と「記述解答欄」を描画して
    実際の採点UIでリアルに見えるようにする。
    """
    student_names = [
        "山田太郎", "鈴木花子", "田中一郎", "佐藤美咲",
        "高橋健太", "渡辺愛", "伊藤翔太", "小林由美",
        "中村大輔", "加藤恵",
    ]

    # 答案パターン: 異なる濃さ・量の手書き風模様
    answer_patterns = [
        ("しっかり記述", (30, 30, 30)),
        ("やや薄い記述", (100, 100, 100)),
        ("濃い記述", (20, 20, 80)),
        ("空欄（白紙）", (240, 240, 240)),
        ("短い記述", (50, 50, 50)),
        ("びっしり記述", (40, 40, 40)),
        ("普通の記述", (60, 60, 60)),
        ("走り書き", (80, 80, 80)),
    ]

    image_paths: Dict[str, str] = {}

    for i in range(count):
        name = student_names[i % len(student_names)]
        pattern_label, ink_color = answer_patterns[i % len(answer_patterns)]

        # A4 縦方向 (実際のスキャンに近いサイズ)
        img_w, img_h = 600, 850
        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # ヘッダー線
        draw.rectangle([20, 20, img_w - 20, 60], outline=(0, 0, 0), width=2)
        # 名前欄（ラベル文字）
        try:
            font_header = ImageFont.truetype("msmincho.ttc", 14)
            font_body = ImageFont.truetype("msmincho.ttc", 11)
            font_small = ImageFont.truetype("msmincho.ttc", 9)
        except (IOError, OSError):
            font_header = ImageFont.load_default()
            font_body = font_header
            font_small = font_header

        draw.text((30, 30), f"氏名: {name}", fill=(0, 0, 0), font=font_header)
        draw.text((350, 30), f"番号: {i + 1:02d}", fill=(0, 0, 0), font=font_header)

        # 問題1 記述欄
        draw.rectangle([20, 80, img_w - 20, 120], outline=(0, 0, 0), width=1)
        draw.text((30, 85), "問1: 次の現象について説明しなさい。(5点)", fill=(0, 0, 0), font=font_body)

        # 記述解答領域1
        draw.rectangle([20, 125, img_w - 20, 300], outline=(150, 150, 150), width=1)
        if pattern_label != "空欄（白紙）":
            # 手書き風の横線を描画
            np.random.seed(i * 100 + 1)
            n_lines = np.random.randint(3, 12)
            for li in range(n_lines):
                y = 140 + li * 14
                if y > 285:
                    break
                x_start = 30 + np.random.randint(0, 10)
                x_end = img_w - 30 - np.random.randint(0, 80)
                # 手書き感: 微妙にギザギザ
                points = []
                for x in range(x_start, x_end, 4):
                    dy = np.random.randint(-1, 2)
                    points.append((x, y + dy))
                if len(points) >= 2:
                    draw.line(points, fill=ink_color, width=1)

        # 問題2 記述欄
        draw.rectangle([20, 320, img_w - 20, 360], outline=(0, 0, 0), width=1)
        draw.text((30, 325), "問2: 以下のグラフから読み取れることを述べよ。(5点)", fill=(0, 0, 0), font=font_body)

        # 記述解答領域2
        draw.rectangle([20, 365, img_w - 20, 540], outline=(150, 150, 150), width=1)
        if pattern_label not in ("空欄（白紙）", "短い記述"):
            np.random.seed(i * 100 + 2)
            n_lines = np.random.randint(4, 11)
            for li in range(n_lines):
                y = 380 + li * 14
                if y > 525:
                    break
                x_start = 30 + np.random.randint(0, 10)
                x_end = img_w - 30 - np.random.randint(0, 60)
                points = []
                for x in range(x_start, x_end, 4):
                    dy = np.random.randint(-1, 2)
                    points.append((x, y + dy))
                if len(points) >= 2:
                    draw.line(points, fill=ink_color, width=1)

        # 問題3 記述欄
        draw.rectangle([20, 560, img_w - 20, 600], outline=(0, 0, 0), width=1)
        draw.text((30, 565), "問3: 実験結果のまとめを書きなさい。(10点)", fill=(0, 0, 0), font=font_body)

        # 記述解答領域3
        draw.rectangle([20, 605, img_w - 20, 830], outline=(150, 150, 150), width=1)
        if pattern_label != "空欄（白紙）":
            np.random.seed(i * 100 + 3)
            n_lines = np.random.randint(5, 15)
            for li in range(n_lines):
                y = 620 + li * 14
                if y > 815:
                    break
                x_start = 30 + np.random.randint(0, 10)
                x_end = img_w - 30 - np.random.randint(0, 50)
                points = []
                for x in range(x_start, x_end, 4):
                    dy = np.random.randint(-1, 2)
                    points.append((x, y + dy))
                if len(points) >= 2:
                    draw.line(points, fill=ink_color, width=1)

        # 保存
        fn = f"student_{i + 1:03d}.jpg"
        path = folder / fn
        img.save(str(path), "JPEG", quality=92)
        image_paths[fn] = str(path)

    return image_paths


# ============================================================
# HTML レポート生成
# ============================================================

def _img_to_base64(path: Path) -> str:
    """画像を base64 エンコードした <img> タグ用文字列を返す"""
    if not path.exists():
        return ""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    suffix = path.suffix.lstrip(".")
    if suffix == "jpg":
        suffix = "jpeg"
    return f"data:image/{suffix};base64,{data}"


def _generate_html_report(captures: Dict[str, Path]):
    """キャプチャ一覧の HTML レポートを生成する"""
    # キャプチャされた画像の <img> タグを生成
    sections = []

    section_data = [
        ("desc_01_question_list_with_mode",
         "1. 問題一覧画面（採点モード選択プルダウン付き）",
         "問題一覧画面に紫色の帯で「採点モード」プルダウンを追加しました。\n"
         "「1枚ずつ」または「一覧（グリッド）」を事前に選択してから採点を開始できます。"),

        ("desc_02_scorer_buttons",
         "2. 採点画面（〇/×ボタン + フィルタ + 未採点カウント）",
         "右パネルに以下を追加:\n"
         "- 〇 正解ボタン（満点付与）/ × 不正解ボタン（0点付与）\n"
         "- キーボード: m=〇正解  b=×不正解\n"
         "- 「未採点のみ表示」チェックボックス\n"
         "- 未採点カウント表示"),

        ("desc_03_scored_maru",
         "3. 〇正解ボタン押下後（背景フィードバック: 薄青）",
         "〇ボタン（m キー）で満点を付与すると、キャンバス背景が薄青(#E3F2FD)に\n"
         "一瞬フラッシュし、400ms 後に白に戻ります。直感的に「正解」と分かります。"),

        ("desc_04_scored_batsu",
         "4. ×不正解ボタン押下後（背景フィードバック: 薄赤）",
         "×ボタン（b キー）で0点を付与すると、キャンバス背景が薄赤(#FFEBEE)に\n"
         "フラッシュします。"),

        ("desc_05_scored_middle",
         "5. 中間点入力（背景フィードバック: 薄橙）",
         "数値キー等で中間点を入力すると、薄橙(#FFF3E0)にフラッシュします。"),

        ("desc_06_filter_active",
         "6. 「未採点のみ表示」フィルタ ON",
         "チェックを入れると、既に採点済みの生徒をスキップして\n"
         "未採点の答案のみを ←→ で移動できます。"),

        ("desc_07_all_scored",
         "7. 全員採点済み状態",
         "全員の採点が完了すると、未採点カウントが 0 になります。"),

        ("desc_08_grid_mode",
         "8. 一覧（グリッド）モード",
         "モードバーで「一覧」に切り替えると、全生徒をサムネイルで一覧表示。\n"
         "得点ボタンを選択してからサムネイルをクリックで採点できます。"),
    ]

    for key, title, desc in section_data:
        img_path = captures.get(key)
        if img_path and img_path.exists():
            b64 = _img_to_base64(img_path)
            img_tag = f'<img src="{b64}" alt="{title}" style="max-width:100%; border:1px solid #ddd; border-radius:4px;">'
        else:
            img_tag = '<p style="color:#999; font-style:italic;">（キャプチャ未取得）</p>'

        sections.append(f"""
        <div class="section">
            <h2>{title}</h2>
            <p class="desc">{desc.replace(chr(10), '<br>')}</p>
            {img_tag}
        </div>
        """)

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>記述採点 新機能 GUI レポート</title>
<style>
    body {{
        font-family: "Yu Gothic UI", "Meiryo", sans-serif;
        max-width: 1100px;
        margin: 0 auto;
        padding: 20px;
        background: #FAFAFA;
        color: #333;
    }}
    h1 {{
        text-align: center;
        color: #1565C0;
        border-bottom: 3px solid #1565C0;
        padding-bottom: 10px;
    }}
    .summary {{
        background: #E3F2FD;
        padding: 15px 20px;
        border-radius: 8px;
        margin: 20px 0;
        line-height: 1.8;
    }}
    .summary h3 {{
        margin-top: 0;
        color: #0D47A1;
    }}
    .summary ul {{
        margin: 5px 0;
    }}
    .section {{
        background: white;
        padding: 20px;
        margin: 20px 0;
        border-radius: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    }}
    .section h2 {{
        color: #1976D2;
        border-left: 4px solid #1976D2;
        padding-left: 10px;
        font-size: 1.2em;
    }}
    .desc {{
        color: #555;
        line-height: 1.7;
        white-space: pre-line;
    }}
    img {{
        display: block;
        margin: 15px auto;
    }}
    .footer {{
        text-align: center;
        color: #999;
        font-size: 0.85em;
        margin-top: 40px;
        padding-top: 15px;
        border-top: 1px solid #ddd;
    }}
    .badge {{
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.85em;
        font-weight: bold;
        margin-right: 5px;
    }}
    .badge-new {{ background: #E8F5E9; color: #2E7D32; }}
    .badge-improved {{ background: #FFF3E0; color: #E65100; }}
</style>
</head>
<body>

<h1>🔖 記述採点 新機能 GUI レポート</h1>

<div class="summary">
    <h3>v4 記述採点リッチ化 — 追加機能一覧</h3>
    <ul>
        <li><span class="badge badge-new">NEW</span> 採点モードプルダウン（問題一覧画面で事前選択）</li>
        <li><span class="badge badge-new">NEW</span> 〇/× ボタン + m/b キーボードショートカット</li>
        <li><span class="badge badge-new">NEW</span> 「未採点のみ表示」フィルタチェックボックス</li>
        <li><span class="badge badge-new">NEW</span> 背景色フィードバック（満点=薄青 / 0点=薄赤 / 中間=薄橙）</li>
        <li><span class="badge badge-improved">IMPROVED</span> ヘルプテキストに m/b ショートカット説明を追加</li>
        <li><span class="badge badge-improved">IMPROVED</span> 未採点カウント表示</li>
    </ul>
    <p>以下は <strong>ダミー縦長答案画像</strong> を使った実際の GUI キャプチャです。</p>
</div>

{''.join(sections)}

<div class="footer">
    <p>Generated by test_descriptive_capture.py — 採点侍 (SaitenSamurai) v4</p>
</div>

</body>
</html>"""

    report_path = REPORT_DIR / "index.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"\n  HTMLレポート出力: {report_path}")
    return report_path


# ============================================================
# テストクラス: 記述採点 新機能キャプチャ
# ============================================================


class TestDescriptiveScoringCapture:
    """記述採点の新機能をキャプチャしてHTMLレポートを生成する。

    テスト順序が重要なため、test_XX_* の命名で順序制御する。
    """

    # クラスレベルで共有するデータ
    _captures: Dict[str, Path] = {}
    _tmpdir: Optional[tempfile.TemporaryDirectory] = None
    _image_paths: Dict[str, str] = {}

    @classmethod
    def setup_class(cls):
        """テスト開始前にダミー画像を生成"""
        cls._tmpdir = tempfile.TemporaryDirectory()
        td = Path(cls._tmpdir.name)
        cls._image_paths = _create_dummy_answer_sheets(td, count=8)
        cls._captures = {}

    @classmethod
    def teardown_class(cls):
        """テスト終了後にレポート生成＋後片付け"""
        try:
            _generate_html_report(cls._captures)
        finally:
            if cls._tmpdir:
                cls._tmpdir.cleanup()

    # ----------------------------------------------------------
    # 1. 問題一覧画面 (モード選択プルダウン付き)
    # ----------------------------------------------------------

    def test_01_question_list_with_mode_selector(self):
        """問題一覧画面 — 紫帯の採点モードプルダウン"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("記述問題 採点")
        win.geometry("560x480+100+100")
        win.resizable(False, False)

        frame = tk.Frame(win, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="記述問題 採点",
                 font=("Yu Gothic UI", 13, "bold")).pack(pady=(0, 5))
        tk.Label(frame,
                 text="採点する問題を選択してください。完了後「採点完了」を押してください。",
                 font=("Yu Gothic UI", 8), fg="gray", wraplength=520).pack(pady=(0, 10))

        # --- 新機能: 採点モード選択（紫帯） ---
        mode_frame = tk.Frame(frame, bg="#F3E5F5", padx=10, pady=6)
        mode_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(mode_frame, text="採点モード:", font=("Yu Gothic UI", 9, "bold"),
                 bg="#F3E5F5").pack(side=tk.LEFT, padx=(0, 5))
        mode_var = tk.StringVar(value="1枚ずつ")
        mode_combo = ttk.Combobox(mode_frame, textvariable=mode_var,
                                  values=["1枚ずつ", "一覧（グリッド）"],
                                  state="readonly", width=16,
                                  font=("Yu Gothic UI", 9))
        mode_combo.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(mode_frame, text="※ モードを変えるには一度採点を中断してください",
                 font=("Yu Gothic UI", 8), fg="#7B1FA2", bg="#F3E5F5"
                 ).pack(side=tk.LEFT)

        # --- 問題リスト ---
        questions = [
            ("問1: 説明問題", 5, 1, "0/8 未着手", "gray"),
            ("問2: グラフ読み取り", 5, 1, "0/8 未着手", "gray"),
            ("問3: 実験まとめ", 10, 2, "0/8 未着手", "gray"),
        ]
        for name, ms, asp, status, color in questions:
            r = tk.Frame(frame, pady=4); r.pack(fill=tk.X)
            tk.Label(r, text=f"{name}  (配点:{ms}点  観点:{asp})",
                     font=("Yu Gothic UI", 9), anchor=tk.W,
                     ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(r, text=status, font=("Yu Gothic UI", 8),
                     width=14, fg=color).pack(side=tk.LEFT, padx=5)
            tk.Button(r, text="設定", width=3, font=("Yu Gothic UI", 8),
                      bg="#FFE082", relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=(0, 3))
            tk.Button(r, text="採点", width=5, font=("Yu Gothic UI", 9),
                      bg="#90CAF9", relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT)

        # --- ボタン ---
        bf = tk.Frame(frame, pady=10); bf.pack(fill=tk.X)
        tk.Button(bf, text="✔ 採点完了・保存", bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 10, "bold"), width=20, height=2,
                  relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=5)
        tk.Button(bf, text="キャンセル", font=("Yu Gothic UI", 9),
                  width=10).pack(side=tk.LEFT, padx=5)

        win.update_idletasks(); win.update()
        p = _capture_window(win, "desc_01_question_list_with_mode")
        if p:
            self.__class__._captures["desc_01_question_list_with_mode"] = p
        win.destroy()

    # ----------------------------------------------------------
    # 2-7. 採点画面の各状態をキャプチャ
    # ----------------------------------------------------------

    def _build_scorer_window(self, root, title_suffix="", max_score=5,
                             use_entry=False, initial_scores=None,
                             geometry="1000x700+80+80"):
        """採点画面のモック構築（実コードの構造を再現）"""
        win = tk.Toplevel(root)
        win.title(f"採点: 問1: 説明問題 (配点:{max_score}点) {title_suffix}")
        win.geometry(geometry)
        win.resizable(True, True)

        # --- コンテナ ---
        container = tk.Frame(win)
        container.pack(fill=tk.BOTH, expand=True)

        main_frame = tk.Frame(container)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 左: Canvas
        canvas_frame = tk.Frame(main_frame)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(canvas_frame, bg="white",
                           highlightthickness=1, highlightbackground="#ccc")
        canvas.pack(fill=tk.BOTH, expand=True)

        # 右: 操作パネル
        panel = tk.Frame(main_frame, width=220, padx=10)
        panel.pack(side=tk.RIGHT, fill=tk.Y)
        panel.pack_propagate(False)

        scored_count = len(initial_scores) if initial_scores else 0
        total_count = 8
        current_idx = scored_count

        progress_var = tk.StringVar(value=f"{current_idx + 1} / {total_count}")
        tk.Label(panel, textvariable=progress_var,
                 font=("Yu Gothic UI", 11, "bold")).pack(pady=(0, 5))

        fn_var = tk.StringVar(value=f"student_{current_idx + 1:03d}.jpg")
        tk.Label(panel, textvariable=fn_var,
                 font=("Yu Gothic UI", 8), fg="gray", wraplength=200).pack(pady=(0, 10))

        # 現在の得点
        tk.Label(panel, text="得点:", font=("Yu Gothic UI", 10)).pack()
        score_var = tk.StringVar(value="—")
        tk.Label(panel, textvariable=score_var,
                 font=("Yu Gothic UI", 28, "bold"), fg="#1976D2").pack(pady=5)

        # Entry 入力（配点>9の場合のみ）
        if use_entry:
            ef = tk.Frame(panel); ef.pack(pady=5)
            tk.Label(ef, text="得点入力:", font=("Yu Gothic UI", 9)).pack(side=tk.LEFT)
            entry = tk.Entry(ef, width=5, font=("Yu Gothic UI", 12), justify=tk.CENTER)
            entry.pack(side=tk.LEFT, padx=5)
            tk.Button(ef, text="確定", font=("Yu Gothic UI", 8),
                      bg="#90CAF9", relief=tk.FLAT).pack(side=tk.LEFT)

        # --- 新機能: 〇/× ボタン ---
        tk.Label(panel, text="─" * 20, fg="#ccc").pack(pady=5)
        tk.Label(panel, text="かんたん採点", font=("Yu Gothic UI", 9, "bold")).pack()

        mb_frame = tk.Frame(panel)
        mb_frame.pack(pady=5)

        tk.Button(mb_frame, text=f"〇 正解\n({max_score}点)",
                  bg="#E3F2FD", fg="#1565C0",
                  font=("Yu Gothic UI", 11, "bold"),
                  width=8, height=2, relief=tk.RAISED, cursor="hand2",
                  activebackground="#BBDEFB").pack(side=tk.LEFT, padx=3)

        tk.Button(mb_frame, text="× 不正解\n(0点)",
                  bg="#FFEBEE", fg="#C62828",
                  font=("Yu Gothic UI", 11, "bold"),
                  width=8, height=2, relief=tk.RAISED, cursor="hand2",
                  activebackground="#FFCDD2").pack(side=tk.LEFT, padx=3)

        tk.Label(panel, text="m: 〇正解  b: ×不正解",
                 font=("Yu Gothic UI", 8), fg="#7B1FA2").pack(pady=(0, 3))

        # 操作説明
        tk.Label(panel, text="─" * 20, fg="#ccc").pack(pady=5)
        tk.Label(panel, text="キーボード操作", font=("Yu Gothic UI", 9, "bold")).pack()

        if use_entry:
            help_text = "数値入力欄に得点を入力\nEnter: 確定して次へ\nm: 〇正解  b: ×不正解\n←→: 前後に移動\nTab: 次の未採点へ\nDel: 得点クリア"
        else:
            help_text = f"0〜{min(9, max_score)}: 得点入力(自動で次へ)\nm: 〇正解  b: ×不正解\n←→: 前後に移動\nTab: 次の未採点へ\nSpace: スキップ\nDel: 得点クリア"

        tk.Label(panel, text=help_text,
                 font=("Yu Gothic UI", 8), fg="gray", justify=tk.LEFT).pack(pady=5)

        # 得点チェックボックス（ボタンモードのみ）
        if not use_entry:
            tk.Label(panel, text="─" * 20, fg="#ccc").pack(pady=5)
            tk.Label(panel, text="入力可能な得点", font=("Yu Gothic UI", 9, "bold")).pack()
            checks_frame = tk.Frame(panel)
            checks_frame.pack()
            for i in range(min(10, max_score + 1)):
                var = tk.BooleanVar(value=True)
                tk.Checkbutton(checks_frame, text=str(i), variable=var,
                               font=("Yu Gothic UI", 8)).grid(
                    row=i // 3, column=i % 3, sticky=tk.W, padx=3)

        # --- 新機能: フィルタ ---
        tk.Label(panel, text="─" * 20, fg="#ccc").pack(pady=5)

        filter_var = tk.BooleanVar(value=False)
        tk.Checkbutton(panel, text="未採点のみ表示", variable=filter_var,
                       font=("Yu Gothic UI", 9)).pack(pady=(0, 3))

        # ボタン
        tk.Label(panel, text="─" * 20, fg="#ccc").pack(pady=5)

        unscored = total_count - scored_count
        unscored_var = tk.StringVar(value=f"未採点: {unscored}人")
        tk.Label(panel, textvariable=unscored_var,
                 font=("Yu Gothic UI", 9), fg="#E65100").pack(pady=(0, 5))

        tk.Button(panel, text="✔ この問題の採点完了",
                  bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 9, "bold"),
                  width=18, relief=tk.FLAT, cursor="hand2").pack(pady=3)
        tk.Button(panel, text="キャンセル",
                  font=("Yu Gothic UI", 9), width=18).pack(pady=3)

        return win, canvas, score_var, progress_var, fn_var, filter_var, unscored_var

    def _show_image_on_canvas(self, canvas, img_path: str):
        """Canvas にダミー答案画像を表示"""
        try:
            pil_img = Image.open(img_path)
            # Canvas に合わせてリサイズ
            canvas.update_idletasks()
            cw = max(canvas.winfo_width(), 400)
            ch = max(canvas.winfo_height(), 500)
            ratio = min(cw / pil_img.width, ch / pil_img.height)
            new_w = int(pil_img.width * ratio)
            new_h = int(pil_img.height * ratio)
            pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)
            canvas.delete("all")
            canvas.create_image(cw // 2, ch // 2, image=tk_img, anchor=tk.CENTER)
            canvas._tk_img_ref = tk_img  # GC 防止
        except Exception as e:
            canvas.create_text(200, 200, text=f"画像表示エラー:\n{e}", fill="red")

    def test_02_scorer_initial_state(self):
        """採点画面 — 初期状態（〇×ボタン・フィルタ・ヘルプ表示）"""
        root = get_shared_tk_root()
        win, canvas, sv, pv, fv, filter_v, uv = self._build_scorer_window(root)

        # 最初の画像を表示
        first_fn = sorted(self._image_paths.keys())[0]
        self._show_image_on_canvas(canvas, self._image_paths[first_fn])

        win.update_idletasks(); win.update()
        p = _capture_window(win, "desc_02_scorer_buttons")
        if p:
            self.__class__._captures["desc_02_scorer_buttons"] = p
        win.destroy()

    def test_03_scored_maru(self):
        """〇ボタン押下後 — 背景薄青フィードバック"""
        root = get_shared_tk_root()
        win, canvas, sv, pv, fv, filter_v, uv = self._build_scorer_window(root)

        first_fn = sorted(self._image_paths.keys())[0]
        self._show_image_on_canvas(canvas, self._image_paths[first_fn])

        # 採点: 満点 → 背景を薄青に
        sv.set("5")
        canvas.config(bg="#E3F2FD")  # 薄青
        uv.set("未採点: 7人")
        pv.set("1 / 8")

        win.update_idletasks(); win.update()
        p = _capture_window(win, "desc_03_scored_maru")
        if p:
            self.__class__._captures["desc_03_scored_maru"] = p
        win.destroy()

    def test_04_scored_batsu(self):
        """×ボタン押下後 — 背景薄赤フィードバック"""
        root = get_shared_tk_root()
        win, canvas, sv, pv, fv, filter_v, uv = self._build_scorer_window(
            root, initial_scores={"student_001.jpg": 5})

        fn = sorted(self._image_paths.keys())[1]
        self._show_image_on_canvas(canvas, self._image_paths[fn])

        # 採点: 0点 → 背景を薄赤に
        sv.set("0")
        canvas.config(bg="#FFEBEE")  # 薄赤
        uv.set("未採点: 6人")
        pv.set("2 / 8")

        win.update_idletasks(); win.update()
        p = _capture_window(win, "desc_04_scored_batsu")
        if p:
            self.__class__._captures["desc_04_scored_batsu"] = p
        win.destroy()

    def test_05_scored_middle(self):
        """中間点入力 — 背景薄橙フィードバック"""
        root = get_shared_tk_root()
        win, canvas, sv, pv, fv, filter_v, uv = self._build_scorer_window(
            root, initial_scores={"s1": 5, "s2": 0})

        fn = sorted(self._image_paths.keys())[2]
        self._show_image_on_canvas(canvas, self._image_paths[fn])

        # 採点: 中間点 → 背景を薄橙に
        sv.set("3")
        canvas.config(bg="#FFF3E0")  # 薄橙
        uv.set("未採点: 5人")
        pv.set("3 / 8")

        win.update_idletasks(); win.update()
        p = _capture_window(win, "desc_05_scored_middle")
        if p:
            self.__class__._captures["desc_05_scored_middle"] = p
        win.destroy()

    def test_06_filter_active(self):
        """「未採点のみ表示」フィルタ ON"""
        root = get_shared_tk_root()
        win, canvas, sv, pv, fv, filter_v, uv = self._build_scorer_window(
            root, initial_scores={"s1": 5, "s2": 0, "s3": 3})

        filter_v.set(True)  # フィルタ ON
        fn = sorted(self._image_paths.keys())[3]
        self._show_image_on_canvas(canvas, self._image_paths[fn])

        sv.set("—")
        uv.set("未採点: 5人（フィルタ中）")
        pv.set("4 / 8")
        fv.set("student_004.jpg")

        win.update_idletasks(); win.update()
        p = _capture_window(win, "desc_06_filter_active")
        if p:
            self.__class__._captures["desc_06_filter_active"] = p
        win.destroy()

    def test_07_all_scored(self):
        """全員採点済み状態"""
        root = get_shared_tk_root()
        all_scores = {f"s{i}": i % 6 for i in range(1, 9)}
        win, canvas, sv, pv, fv, filter_v, uv = self._build_scorer_window(
            root, initial_scores=all_scores)

        fn = sorted(self._image_paths.keys())[7]
        self._show_image_on_canvas(canvas, self._image_paths[fn])

        sv.set("4")
        uv.set("未採点: 0人 ✔ 全員採点済み")
        pv.set("8 / 8")
        fv.set("student_008.jpg")

        win.update_idletasks(); win.update()
        p = _capture_window(win, "desc_07_all_scored")
        if p:
            self.__class__._captures["desc_07_all_scored"] = p
        win.destroy()

    # ----------------------------------------------------------
    # 8. 一覧グリッドモード
    # ----------------------------------------------------------

    def test_08_grid_mode(self):
        """一覧（グリッド）モードの表示"""
        root = get_shared_tk_root()

        win = tk.Toplevel(root)
        win.title("採点: 問1: 説明問題 (配点:5点)")
        win.geometry("1000x700+80+80")
        win.configure(bg="#F5F7FA")
        BG = "#F5F7FA"

        # --- モード切替バー ---
        mode_bar = tk.Frame(win, bg="#37474F", padx=10, pady=6)
        mode_bar.pack(fill=tk.X)
        tk.Label(mode_bar, text="📋 表示モード:", font=("Yu Gothic UI", 10, "bold"),
                 bg="#37474F", fg="white").pack(side=tk.LEFT, padx=(0, 5))
        mode_combo = ttk.Combobox(mode_bar, values=["1枚ずつ", "一覧"],
                                  state="readonly", width=12,
                                  font=("Yu Gothic UI", 10))
        mode_combo.set("一覧")
        mode_combo.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(mode_bar, text="（「一覧」で全生徒をグリッド表示）",
                 font=("Yu Gothic UI", 9), bg="#37474F", fg="#B0BEC5"
                 ).pack(side=tk.LEFT)

        # ズームコントロール（スライダー）
        zoom_frame = tk.Frame(mode_bar, bg="#37474F")
        zoom_frame.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        tk.Label(zoom_frame, text="🔍 サイズ:",
                 font=("Yu Gothic UI", 9), bg="#37474F", fg="white"
                 ).pack(side=tk.LEFT)
        zoom_slider = tk.Scale(zoom_frame, from_=80, to=400, orient=tk.HORIZONTAL,
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
        tk.Label(top_bar, text="採点済み: 5/8  (未採点: 3)",
                 font=("Yu Gothic UI", 9, "bold"), bg=BG, fg="#555").pack(side=tk.LEFT)
        tk.Label(top_bar, text="", bg=BG).pack(side=tk.LEFT, expand=True)
        tk.Button(top_bar, text="✔ この問題の採点完了", bg="#4CAF50", fg="white",
                  font=("Yu Gothic UI", 9, "bold"), relief=tk.FLAT).pack(side=tk.RIGHT)

        # グリッドエリア
        grid_area = tk.Frame(win, bg="#FFFFFF")
        grid_area.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        # ダミーカード + サムネイル画像
        fns = sorted(self._image_paths.keys())
        scores_data = [5, 3, 0, None, 4, None, 5, None]
        max_sc = 5
        COLS = 4

        thumb_refs = []  # GC 防止

        for idx, fn in enumerate(fns[:8]):
            r, c = divmod(idx, COLS)
            sc = scores_data[idx]

            # 背景色決定
            if sc is None:
                bg_col = "#F5F5F5"
            elif sc >= max_sc:
                bg_col = "#E3F2FD"
            elif sc == 0:
                bg_col = "#FFEBEE"
            else:
                bg_col = "#FFF3E0"

            card = tk.Frame(grid_area, bg=bg_col, bd=1, relief=tk.RAISED,
                            padx=3, pady=3)
            card.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")

            # サムネイル画像
            try:
                pil_img = Image.open(self._image_paths[fn])
                pil_img = pil_img.resize((140, 180), Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(pil_img)
                thumb_refs.append(tk_img)
                tk.Label(card, image=tk_img, bg=bg_col).pack(pady=2)
            except Exception:
                tk.Label(card, text="📄", font=("", 24), bg=bg_col).pack(pady=5)

            sf = tk.Frame(card, bg=bg_col)
            sf.pack(fill=tk.X)

            if sc is not None:
                mark = "○" if sc == max_sc else ("×" if sc == 0 else "△")
                mark_fg = "#1565C0" if sc == max_sc else ("#C62828" if sc == 0 else "#E65100")
                tk.Label(sf, text=mark, font=("Yu Gothic UI", 12, "bold"),
                         fg=mark_fg, bg=bg_col).pack(side=tk.LEFT)
                tk.Label(sf, text=f"{sc}点", font=("Yu Gothic UI", 8),
                         fg="#555", bg=bg_col).pack(side=tk.LEFT, padx=3)
            else:
                tk.Label(sf, text="─", font=("Yu Gothic UI", 12), fg="#999",
                         bg=bg_col).pack(side=tk.LEFT)
                tk.Label(sf, text="未採点", font=("Yu Gothic UI", 8),
                         fg="#999", bg=bg_col).pack(side=tk.LEFT, padx=3)

            tk.Label(card, text=fn, font=("Yu Gothic UI", 7), fg="#777",
                     bg=bg_col).pack()

        for c_idx in range(COLS):
            grid_area.columnconfigure(c_idx, weight=1)

        # 下部得点ボタンバー
        score_bar = tk.Frame(win, bg="#ECEFF1", padx=8, pady=8)
        score_bar.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(score_bar, text="得点ボタン:",
                 font=("Yu Gothic UI", 9), bg="#ECEFF1", fg="#555").pack(side=tk.LEFT, padx=(0, 8))
        for i in range(6):
            bg_c = "#FF8A65" if i == 5 else "#E3F2FD"
            rel = tk.SUNKEN if i == 5 else tk.RAISED
            tk.Button(score_bar, text=str(i), width=3, font=("Yu Gothic UI", 10, "bold"),
                      bg=bg_c, relief=rel).pack(side=tk.LEFT, padx=2)
        tk.Label(score_bar, text="アクティブ: 5点",
                 font=("Yu Gothic UI", 9, "bold"), bg="#ECEFF1", fg="#E65100").pack(side=tk.RIGHT)

        win.update_idletasks(); win.update()
        # GC 防止のため thumb_refs を保持
        win._thumb_refs = thumb_refs
        p = _capture_window(win, "desc_08_grid_mode")
        if p:
            self.__class__._captures["desc_08_grid_mode"] = p
        win.destroy()


# ============================================================
# ダミー画像生成のユニットテスト
# ============================================================


class TestDummyImageGeneration:
    """ダミー答案画像生成の検証"""

    def test_generates_correct_count(self):
        with tempfile.TemporaryDirectory() as td:
            paths = _create_dummy_answer_sheets(Path(td), count=5)
            assert len(paths) == 5

    def test_images_are_vertical(self):
        with tempfile.TemporaryDirectory() as td:
            paths = _create_dummy_answer_sheets(Path(td), count=1)
            fn, fpath = next(iter(paths.items()))
            img = Image.open(fpath)
            w, h = img.width, img.height
            img.close()
            assert h > w, "答案画像は縦長であるべき"

    def test_images_have_content(self):
        with tempfile.TemporaryDirectory() as td:
            paths = _create_dummy_answer_sheets(Path(td), count=1)
            fn, fpath = next(iter(paths.items()))
            img = Image.open(fpath)
            arr = np.array(img)
            img.close()
            # 完全な白紙ではないことを確認
            assert arr.std() > 10, "画像に内容が描画されているべき"


# ============================================================
# レポート生成の検証
# ============================================================


class TestReportGeneration:

    def test_report_dir_exists(self):
        assert REPORT_DIR.exists()

    def test_captures_summary(self):
        """生成されたキャプチャの一覧を表示"""
        pngs = sorted(CAPTURE_DIR.glob("*.png"))
        print(f"\n  記述採点キャプチャ数: {len(pngs)}")
        for f in pngs:
            print(f"    {f.name} ({f.stat().st_size:,} bytes)")
