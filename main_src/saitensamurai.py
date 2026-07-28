#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
マル之助 (Marunosuke) — 記述式答案の採点支援アプリケーション

モジュール構成:
  constants.py          : 共通定数・ユーティリティ
  image_alignment.py    : 画像読み込み・コーナーマーカー検出・射影補正
  descriptive_scorer.py : 記述式採点
  descriptive_renderer.py : 記述式採点結果の描画
  summary_generator.py  : サマリーExcel生成
  ctt_analyzer.py       : CTT分析
  student_id_ocr.py     : 学籍番号OCR
  name_trimmer.py       : 氏名トリミング
  page_number_checker.py : 印刷ページ番号確認
  multi_page_merger.py  : 複数ページ答案の統合
  gui_components.py     : サブウィンドウGUI
  main_gui.py           : メインGUI

このファイルは後方互換 API と旧エントリーポイントを提供する。
新しい正式な起動入口は marunosuke.py。
"""

# ========================================
# PyInstaller frozen EXE 対策 (全インポートより前に実行)
# ========================================
import sys as _sys
import os as _os
import multiprocessing as _mp

# 1) freeze_support: multiprocessing/loky が子プロセスを生成した際に
#    EXE が再実行されるのを検出して即座に終了する。
#    全インポートより前に呼ぶことで GUI 多重起動を防止する。
_mp.freeze_support()

if getattr(_sys, 'frozen', False):
    # 2) stdio リダイレクト: console=False EXE では sys.stdout/stderr が None
    if _sys.stdout is None:
        _sys.stdout = open(_os.devnull, 'w', encoding='utf-8')
    if _sys.stderr is None:
        _sys.stderr = open(_os.devnull, 'w', encoding='utf-8')

    # 3) joblib/loky の子プロセス生成を抑止
    #    sklearn 内部の KMeans 等が joblib で並列処理を行う際に
    #    loky が EXE を再実行してウィンドウが大量に開くのを防止する。
    _os.environ['LOKY_MAX_CPU_COUNT'] = '1'
    _os.environ['JOBLIB_START_METHOD'] = 'loky'

# ========================================
# ビルド検証用スモークテスト（CI専用・通常起動には影響しない）
# ========================================
# 環境変数 MARUNOSUKE_SMOKE_TEST=1 が設定されている場合のみ実行。
# 旧 SAITENSAMURAI_SMOKE_TEST も後方互換のため受け付ける。
# sklearn/joblib が exe に正しく同梱されているかを GUI を開かずに検証し、
# 結果を smoke_test_result.txt に書き出して終了する。
# console=False の GUI exe では stdout が devnull になるため、
# 結果はファイル経由で外部（CI）に伝える。
def _smoke_test_requested(environ=None):
    """新旧どちらかのスモークテスト環境変数が有効なら True。"""
    environ = _os.environ if environ is None else environ
    return (
        environ.get('MARUNOSUKE_SMOKE_TEST') == '1'
        or environ.get('SAITENSAMURAI_SMOKE_TEST') == '1'
    )


if _smoke_test_requested():
    if getattr(_sys, 'frozen', False):
        _result_dir = _os.path.dirname(_sys.executable)
    else:
        _result_dir = _os.path.dirname(_os.path.abspath(__file__))
    _result_path = _os.path.join(_result_dir, 'smoke_test_result.txt')
    try:
        import numpy as _np
        from sklearn.cluster import KMeans as _KMeans
        import joblib as _joblib
        _KMeans(n_clusters=2, n_init=10, random_state=0).fit(
            _np.array([[0, 0], [1, 1], [0, 1], [1, 0]])
        )
        with open(_result_path, 'w', encoding='utf-8') as _f:
            _f.write('OK')
    except Exception as _e:
        with open(_result_path, 'w', encoding='utf-8') as _f:
            _f.write(f'FAIL: {type(_e).__name__}: {_e}')
    _sys.exit(0)

# ========================================
# 後方互換 re-export
# ========================================

import tkinter as tk

# 共通定数・ユーティリティ
from constants import (
    APP_NAME,
    setup_logging,
    safe_print, extract_pdf_to_images, combine_images_to_pdf,
    HAS_PYMUPDF, fitz,
    RESULTS_FOLDER, BOXED_FOLDER, RESULTS_DATA_FOLDER,
    SCORED_FOLDER, FINAL_REPORT_FOLDER,
    ANSWER_KEY_FILE,
    STUDENT_SUMMARY_FILE, EXAM_SUMMARY_FILE,
    CTT_ANALYSIS_EXCEL_FILE, CTT_ANALYSIS_PDF_FILE,
    READING_RESULTS_FOLDER_NAME, SESSION_STATE_FILE,
)

# CTT分析ライブラリ可否フラグ（テストで参照される）
try:
    import matplotlib
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    import reportlab
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# 画像アライメント（採点モード非依存）
from image_alignment import (
    imread_unicode, detect_corner_markers,
    apply_perspective_transform, compute_output_scale,
)

# サマリー生成
from summary_generator import process_descriptive_only_summary

# CTT分析
from ctt_analyzer import (
    convert_mark2_to_ctt_data,
    _sort_choices,
    _is_invalid_response,
    _is_no_answer,
    CTTAnalyzer,
    CTTPlotGenerator,
    CTTExcelExporter,
    CTTPDFReporter,
    generate_ctt_analysis,
)

# R連携エクスポート
from r_export import (
    export_r_analysis_kit,
    R_EXPORT_FOLDER,
    R_DATA_CSV,
    R_ITEM_INFO_CSV,
    R_SCRIPT_FILE,
    R_RMD_TEMPLATE_FILE,
)

# メインGUI
from main_gui import MarunosukeGUI, SaitenSamuraiGUI

# 後方互換エイリアス
Mark2GUI = MarunosukeGUI


# ========================================
# エントリポイント
# ========================================

import sys
import os
import traceback
import datetime


def _get_crash_log_path():
    """クラッシュログの保存先パスを返す。

    exe 環境では exe と同じディレクトリに保存。
    通常の Python 実行ではカレントディレクトリに保存。
    """
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.getcwd()
    return os.path.join(base, "marunosuke_crash.log")


def main():
    """メイン関数 — メインGUIを直接起動"""
    setup_logging()
    root = tk.Tk()
    app = MarunosukeGUI(root)
    root.mainloop()


def run():
    """クラッシュレポート処理を含めてアプリを起動する。"""
    # freeze_support はファイル冒頭で既に呼び出し済み
    try:
        main()
    except Exception as e:
        # エラー詳細をログファイルに保存
        log_path = _get_crash_log_path()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_detail = traceback.format_exc()

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{timestamp}] {APP_NAME} クラッシュレポート\n")
                f.write(f"{'='*60}\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"Frozen: {getattr(sys, 'frozen', False)}\n")
                f.write(f"Executable: {sys.executable}\n")
                f.write(f"\n{error_detail}\n")
        except Exception:
            pass

        # GUI でエラーメッセージを表示
        try:
            from tkinter import messagebox
            try:
                # 既存の Tk ルートがあれば使う
                root = getattr(tk, '_default_root', None)
                if root is None:
                    root = tk.Tk()
                    root.withdraw()
            except Exception:
                root = tk.Tk()
                root.withdraw()

            messagebox.showerror(
                f"{APP_NAME} - エラー",
                f"アプリケーションの起動中にエラーが発生しました。\n\n"
                f"エラー: {type(e).__name__}: {e}\n\n"
                f"詳細ログ:\n{log_path}\n\n"
                f"このファイルを開発者に送付してください。"
            )
        except Exception:
            pass

        sys.exit(1)


if __name__ == '__main__':
    run()
