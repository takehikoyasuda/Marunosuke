#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
constants.py — マル之助 共通定数・ユーティリティ

全モジュールが参照する定数と、汎用ユーティリティ関数を集約。
循環importを防止する基盤モジュール（他モジュールに依存しない）。

注: MARK2_WIDTH/HEIGHT 等の定数名は MARK2 座標フォーマット仕様に由来し、後方互換のため維持しています。
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)

# PDF入力サポート（オプション）
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    fitz = None  # type: ignore
    HAS_PYMUPDF = False


# ========================================
# 共通定数定義
# ========================================

# アプリケーション情報（一元管理）
# バージョンは Semantic Versioning（MAJOR.MINOR.PATCH）に従う。
APP_NAME = "マル之助"
APP_NAME_EN = "Marunosuke"
APP_VERSION = "0.1.0"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"

# Mark2の基準サイズ (A4: 595x842ポイント)
MARK2_WIDTH = 595
MARK2_HEIGHT = 842

# コーナーマーカーの基準位置（用紙の幅・高さに対する比率）
# Mark2様式の四隅マーカー中心位置。射影補正(omr_engine/mark_checker)と
# 記述採点の合計欄配置(descriptive_scorer)が共有する。
# この値がズレると全採点の座標系に影響するため、必ずここだけで管理する。
MARKER_X_FRAC_LEFT = 0.14 + 0.015    # 左マーカー中心 X / 幅 = 0.155
MARKER_X_FRAC_RIGHT = 0.83 + 0.015   # 右マーカー中心 X / 幅 = 0.845
MARKER_Y_FRAC_TOP = 0.03 + 0.01      # 上マーカー中心 Y / 高さ = 0.04
MARKER_Y_FRAC_BOTTOM = 0.95 + 0.01   # 下マーカー中心 Y / 高さ = 0.96

# 出力画像の高解像度スケール倍率
# output_scale を計算: 元画像解像度を基準に高画質で出力する
# 実行時に元画像サイズから動的に決定するが、上限を設定
# 2.0 = 1190x1684 (A4 200dpi相当、画質と速度のバランス最適)
OUTPUT_SCALE_MAX = 2.0

# フォルダ構造定数 (v3: 構造化出力)
RESULTS_FOLDER = "_saiten_grading_results"
BOXED_FOLDER = "00_Processing"          # 枠描画済み画像（中間ファイル）
CLEAN_FOLDER = "00_Processing_Clean"    # 補正済み画像（枠描画なし、記述採点用）
RESULTS_DATA_FOLDER = "01_Results"      # OMRデータ、Answer Key、coordinates.csv
SCORED_FOLDER = "02_Graded_Detail"      # 個別採点済み画像
FINAL_REPORT_FOLDER = "03_Final_Report" # サマリーExcel、統合PDF
ANSWER_KEY_FILE = "answer_key.xlsx"
STUDENT_SUMMARY_FILE = "001_student_summary.xlsx"
EXAM_SUMMARY_FILE = "002_exam_summary.xlsx"
SCORED_PDF_FILE = "005_scored_all.pdf"   # 統合PDF（採点済み画像まとめ）
READING_RESULTS_FOLDER_NAME = "reading_results"  # 01_Results内のOMR結果サブフォルダ
SESSION_STATE_FILE = "session_state.json"         # セッション状態保存ファイル

# 記述採点 得点描画の透過率 (0.0=完全透明 ～ 1.0=不透明)
# ※ 「詳細設定」ウィンドウから変更可能
DESCRIPTIVE_OVERLAY_OPACITY = 0.50

# ========================================
# 採点結果描画 デフォルト設定
# ========================================

DEFAULT_RENDERING_SETTINGS = {
    # --- マーク式採点結果 ---
    # 描画開始位置のオフセット（セル単位のfloat）
    # 0.0=デフォルト位置(末尾から2番目), 正=右方向, 負=左方向
    # 整数部分でセル移動、小数部分でセル内サブピクセル移動
    # 枠外はみ出しも許容（クランプなし）
    'mark_result_offset': 0.0,
    # 各表示項目のON/OFF
    'show_correct_answer': True,   # 正答選択肢番号（正答位置に数字表示）
    'show_ox_mark': True,          # ○×△マーク
    'show_score': True,            # 得点
    'show_aspect': True,           # 観点番号
    # 特例(全員正解)の設問: 正答位置に★を表示（正答未登録なら左端の選択肢位置）
    'show_all_correct_star': True,
    # ○×・得点・観点・正答番号の文字背景を白塗りする
    # (マークシートの選択肢9/0の印字と文字が重なって読みづらい場合に有効化)
    'mark_result_bg_white': False,
    # --- 記述式採点結果 ---
    'descriptive_opacity': 0.50,   # 透過率
    'descriptive_show_mark': True,  # ○×△マーク
    'descriptive_show_score': True, # 得点
    'descriptive_show_aspect': True, # 観点番号
    'descriptive_show_comment': True, # 生徒向けコメント
}


def get_rendering_settings(overrides=None):
    """デフォルト設定にオーバーライドを適用した設定辞書を返す。
    
    Args:
        overrides: 上書きする設定の辞書（Noneならデフォルト）
    
    Returns:
        完全な設定辞書
    """
    settings = DEFAULT_RENDERING_SETTINGS.copy()
    if overrides:
        for key in overrides:
            if key in settings:
                settings[key] = overrides[key]
    return settings

# ========================================
# アプリケーション動作モード
# ========================================
# 現在は記述式のみモードだが、gui_components.RenderingSettingsGUI が
# マーク/記述セクションの表示切替に参照するため定数自体は残している。
MODE_MARK_ONLY = "mark_only"                   # マーク採点のみ（廃止済み）
MODE_MARK_AND_DESCRIPTIVE = "mark_and_descriptive"  # マーク採点 ＋ 記述採点（廃止済み）
MODE_DESCRIPTIVE_ONLY = "descriptive_only"      # 記述採点のみ


# ========================================
# PyInstaller 対応ヘルパー
# ========================================

import os

def resource_path(relative_path):
    """リソースファイルの絶対パスを返す。
    
    PyInstaller でビルドした exe 環境では sys._MEIPASS を、
    通常の Python 実行では main_src/ の親ディレクトリを基準にする。
    
    Args:
        relative_path: リソースへの相対パス (例: "resources/marunosuke-icon.png")
    Returns:
        str: リソースの絶対パス
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller exe 環境
        base = sys._MEIPASS
    else:
        # 通常の Python 実行: main_src/ の親ディレクトリ
        base = str(Path(__file__).resolve().parent.parent)
    return os.path.join(base, relative_path)


def get_app_temp_dir(image_folder_path=None):
    """アプリ用一時ディレクトリのパスを返す。
    
    業務PCのセキュリティ制約を考慮し、システムの TEMP ではなく
    採点結果フォルダ内に一時ディレクトリを作成する。
    
    Args:
        image_folder_path: 画像フォルダのパス。None の場合はシステム TEMP を使用。
    Returns:
        str: 一時ディレクトリのパス (存在保証済み)
    """
    if image_folder_path:
        temp_dir = Path(image_folder_path) / RESULTS_FOLDER / "_temp"
    else:
        # フォールバック: システムの TEMP
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "marunosuke_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return str(temp_dir)


def atomic_json_save(filepath, data, *, indent=2, ensure_ascii=False):
    """JSONファイルのアトミック保存。

    一時ファイルに書き込んでから ``os.replace()`` でアトミックに差し替える。
    書き込み途中でプロセスが中断されてもファイルが壊れることを防ぐ。
    成功した場合、直前の内容を ``*.bak`` にバックアップする。

    Args:
        filepath: 保存先パス (str or Path)
        data: JSONシリアライズ可能なオブジェクト
        indent: JSONインデント (デフォルト 2)
        ensure_ascii: ascii以外をエスケープするか (デフォルト False)
    Raises:
        OSError: 一時ファイル作成・リネームに失敗した場合
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # 同一ディレクトリにtempfileを作成（os.replace がクロスデバイスになるのを防ぐ）
    fd, tmp_path = tempfile.mkstemp(
        dir=str(filepath.parent), suffix=".tmp", prefix=filepath.stem + "_"
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
            f.flush()
            os.fsync(f.fileno())

        # 既存ファイルのバックアップ
        if filepath.exists():
            bak_path = filepath.with_suffix(filepath.suffix + ".bak")
            for _attempt in range(5):
                try:
                    if bak_path.exists():
                        bak_path.unlink()
                    filepath.rename(bak_path)
                    break
                except PermissionError:
                    import time
                    time.sleep(0.05)
                except OSError:
                    break  # バックアップ失敗は許容

        # アトミック差し替え（Windows でリトライ）
        for _attempt in range(5):
            try:
                os.replace(tmp_path, str(filepath))
                break
            except PermissionError:
                import time
                time.sleep(0.05)
        else:
            os.replace(tmp_path, str(filepath))  # 最後の試行（例外は伝播）
    except BaseException:
        # 失敗時は一時ファイルを掃除
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_json_safe(filepath, *, required_keys=None):
    """JSON読み込み。破損時は .bak からのリカバリを試行する。

    Args:
        filepath: 読み込み対象パス (str or Path)
        required_keys: 存在チェックするキーのリスト (Noneならバリデーションなし)
    Returns:
        dict | None: 読み込み結果。読めなければ None。
    """
    filepath = Path(filepath)

    for candidate in [filepath, filepath.with_suffix(filepath.suffix + ".bak")]:
        if not candidate.exists():
            continue
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            if required_keys and not all(k in data for k in required_keys):
                continue
            return data
        except (json.JSONDecodeError, OSError):
            continue
    return None


# ========================================
# クロスプラットフォーム対応ヘルパー (Windows/Mac)
# ========================================

import subprocess


def open_in_default_viewer(path):
    """ファイルをOS既定のビューア/アプリケーションで開く。

    Windows: os.startfile、Mac: open、それ以外: xdg-open。
    """
    if sys.platform == 'win32':
        os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])


def open_in_file_manager(path):
    """フォルダをOS標準のファイラーで開く。

    Windows: エクスプローラー、Mac: Finder、それ以外: xdg-open。
    """
    if sys.platform == 'win32':
        subprocess.Popen(['explorer', str(path)])
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])


def get_cjk_font_path():
    """Pillow ImageFont.truetype 用の日本語フォント (path, ttcインデックス) を返す。"""
    if sys.platform == 'darwin':
        return ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 0)
    return ("C:/Windows/Fonts/msgothic.ttc", 0)


def get_ui_font_family():
    """tkinterウィジェット用の日本語UIフォントファミリー名を返す。"""
    return "Hiragino Sans" if sys.platform == 'darwin' else "Yu Gothic UI"


MAC_FONT_SCALE = 1.6


def get_ui_font_size(base_size):
    """WindowsとMacのポイント→ピクセル換算の差を補正したフォントサイズを返す。

    tkinterの正の整数フォントサイズは「ポイント」指定だが、WindowsのTkは
    96dpi、MacのTkは72dpi換算でピクセルに変換するため、同じ数値を指定しても
    Macでは約25%小さく表示される（tk scalingでは補正できないことを実機検証済み）。
    実機での見え方を踏まえ、96/72(約1.33倍)よりさらに大きい1.6倍を採用している。
    """
    if sys.platform == 'darwin':
        return round(base_size * MAC_FONT_SCALE)
    return base_size


def fit_window_to_content(window, min_width=0, min_height=0):
    """ウィジェット配置後に呼び、ウィンドウをコンテンツの実サイズに合わせてリサイズする。

    Windows向けに決め打ちした固定ピクセル値の.geometry()指定は、Mac側で
    get_ui_font_size()により文字・ボタンが約1.6倍(MAC_FONT_SCALE)に拡大される
    ため、はみ出してボタンや文字が隠れる原因になっていた。min_width/min_height
    には従来の固定値をそのまま「最小サイズ」として渡し、実際のコンテンツが
    それより大きければその分だけウィンドウを広げる。全ウィジェットを配置し
    終えた後（pack/grid呼び出しの後）に呼び出すこと。
    """
    window.update_idletasks()
    screen_w = max(1, window.winfo_screenwidth())
    screen_h = max(1, window.winfo_screenheight())
    margin_x = min(40, max(12, screen_w // 40))
    margin_y = min(60, max(12, screen_h // 30))
    max_width = max(1, screen_w - margin_x * 2)
    max_height = max(1, screen_h - margin_y * 2)
    width = min(max(min_width, window.winfo_reqwidth()), max_width)
    height = min(max(min_height, window.winfo_reqheight()), max_height)
    x = max(0, min(window.winfo_x(), screen_w - width))
    y = max(0, min(window.winfo_y(), screen_h - height))
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.minsize(min(min_width, max_width), min(min_height, max_height))


def get_excel_font_family():
    """openpyxl Font(name=...) 用の日本語フォントファミリー名を返す。"""
    return "Hiragino Sans" if sys.platform == 'darwin' else "Yu Gothic"


# ========================================
# 汎用ユーティリティ関数
# ========================================

def setup_logging(log_dir=None, level=logging.INFO):
    """標準 logging 基盤を初期化する。

    - ファイルハンドラ: DEBUG 以上を ``marunosuke.log`` に記録
    - コンソールハンドラ: *level* (既定 INFO) 以上を stdout に出力

    戻り値はログファイルの Path。
    """
    if log_dir is None:
        log_dir = get_app_temp_dir()
    log_path = Path(log_dir) / "marunosuke.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 既存ハンドラをクリア（複数回呼ばれても安全）
    root_logger.handlers.clear()

    # ファイルハンドラ
    fh = logging.FileHandler(str(log_path), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(fh)

    # コンソールハンドラ（既存 print 互換フォーマット）
    # PyInstaller console=False 環境では sys.stdout/stderr が None になるためガード
    stream = sys.stdout if sys.stdout is not None else open(os.devnull, 'w', encoding='utf-8')
    ch = logging.StreamHandler(stream)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(ch)

    # sys.stderr が None のままだと logging 内部の handleError() がクラッシュする
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')

    return log_path


def safe_print(*args, **kwargs):
    """Windows環境などでのUnicodeEncodeErrorを防ぐためのprintラッパー"""
    if sys.stdout is None:
        return
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        try:
            encoded_args = [str(arg).encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding) for arg in args]
            print(*encoded_args, **kwargs)
        except Exception as e:
            # コンソール出力は諦めるが、ログには痕跡を残す
            logger.debug("safe_print の出力に失敗: %s", e)


_FORMULA_TRIGGER_CHARS = ('=', '+', '-', '@', '\t', '\r')


def number_to_circled(num):
    """数字を丸数字に変換（1→①, 2→②, ...）"""
    if 1 <= num <= 50:
        return chr(0x2460 + num - 1)  # ①-㊿
    return str(num)


def normalize_value(value):
    """
    値を正規化して文字列に変換

    Args:
        value: 入力値（数値、文字列、NaNなど）

    Returns:
        正規化された文字列
    """
    import pandas as pd
    if pd.isna(value):
        return ''

    # 浮動小数点数の場合
    if isinstance(value, float):
        # 整数値と等しい場合は整数に変換（例: 1.0 -> 1）
        if value == int(value):
            value = int(value)

    # 文字列化して空白除去
    return str(value).strip()


def normalize_zero_ten(value):
    """マークシート選択肢の "10" を "0" に正規化する後方互換ヘルパー。"""
    s = str(value).strip()
    return '0' if s == '10' else s


def normalize_answer_set(answer_str):
    """複数正答文字列("3;10" / "3|10")を0⇔10正規化済みの集合に変換する。"""
    if not answer_str:
        return set()
    return {normalize_zero_ten(p) for p in str(answer_str).replace('|', ';').split(';')}


def escape_excel_formula(value):
    """Excelフォーミュラインジェクション対策: 値が =+-@ 等で始まる場合、
    先頭にシングルクォートを付与して文字列として書き込まれるようにする。

    採点補正CSVや生徒データ由来の値をopenpyxlのセルにそのまま書き込むと、
    先頭が '=' 等の文字列は開いた際に数式として評価されてしまうため、
    セル書き込み前に必ずこの関数を通す。
    """
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def extract_pdf_to_images(pdf_path, output_folder=None, dpi=200):
    """
    PDFファイルの各ページを画像（PNG）に変換して保存する。
    
    Args:
        pdf_path: PDFファイルのパス
        output_folder: 画像出力先フォルダ（Noneの場合、PDFと同じ場所に {PDF名}_images/ を作成）
        dpi: 出力画像の解像度（デフォルト200）
    
    Returns:
        Path: 画像が保存されたフォルダのパス
    
    Raises:
        RuntimeError: PyMuPDFがインストールされていない場合
        FileNotFoundError: PDFファイルが存在しない場合
    """
    if not HAS_PYMUPDF:
        raise RuntimeError("PDF入力にはPyMuPDFが必要です。\npip install PyMuPDF でインストールしてください。")
    
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDFファイルが見つかりません: {pdf_path}")
    
    if output_folder is None:
        output_folder = pdf_path.parent / f"{pdf_path.stem}_images"
    else:
        output_folder = Path(output_folder)
    
    output_folder.mkdir(parents=True, exist_ok=True)
    
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72  # 72 DPIが基準
    matrix = fitz.Matrix(zoom, zoom)
    
    extracted_count = 0
    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=matrix)
        # ファイル名に元PDF名を含める（複数PDFを同一フォルダへ展開しても
        # 衝突せず、画像がどのPDFの何ページ目か後から特定できる）
        # ページ番号は3桁ゼロ埋め（ソート順を保証）
        output_path = output_folder / f"{pdf_path.stem}_p{page_num + 1:03d}.png"
        pix.save(str(output_path))
        extracted_count += 1
    
    doc.close()
    logger.info("✓ PDF展開完了: %dページ → %s", extracted_count, output_folder)
    return output_folder


def combine_images_to_pdf(image_folder, output_pdf_path):
    """
    フォルダ内の画像（jpg/png）を1つのPDFにまとめる。
    
    Args:
        image_folder: 画像フォルダのパス
        output_pdf_path: 出力PDFファイルのパス
    
    Returns:
        Path: 生成されたPDFのパス（画像がない場合はNone）
    """
    image_folder = Path(image_folder)
    output_pdf_path = Path(output_pdf_path)
    
    image_files = sorted(image_folder.glob('*.jpg')) + sorted(image_folder.glob('*.png'))
    if not image_files:
        return None
    
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    
    if HAS_PYMUPDF:
        # PyMuPDFで高品質PDF生成
        doc = fitz.open()
        for img_path in image_files:
            img = fitz.open(str(img_path))
            # 画像を1ページのPDFに変換
            pdf_bytes = img.convert_to_pdf()
            img.close()
            img_pdf = fitz.open("pdf", pdf_bytes)
            doc.insert_pdf(img_pdf)
            img_pdf.close()
        doc.save(str(output_pdf_path))
        doc.close()
    else:
        # Pillow fallback — メモリ消費を抑えるため段階的に処理
        if len(image_files) > 0:
            first_img = Image.open(str(image_files[0])).convert('RGB')
            append_imgs = []
            for img_path in image_files[1:]:
                img = Image.open(str(img_path)).convert('RGB')
                append_imgs.append(img)
            first_img.save(str(output_pdf_path), save_all=True, append_images=append_imgs)
            first_img.close()
            for img in append_imgs:
                img.close()
    
    logger.info("✓ 統合PDF生成: %dページ → %s", len(image_files), output_pdf_path.name)
    return output_pdf_path
