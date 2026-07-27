#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
採点侍 (SaitenSamurai) — マークシート解析・採点・チェック統合アプリケーション

バージョン: 4.7.0-beta.1

モジュール構成:
  constants.py          : 共通定数・ユーティリティ
  omr_engine.py         : OMR認識エンジン
  threshold_calibrator.py : 閾値推定ロジック
  scoring_engine.py     : 採点コアロジック
  image_renderer.py     : 画像描画
  summary_generator.py  : サマリーExcel生成
  ctt_analyzer.py       : CTT分析
  mark_checker.py       : エラー検出・修正
  gui_components.py     : サブウィンドウGUI
  main_gui.py           : メインGUI
  descriptive_scorer.py : 記述式採点
  name_trimmer.py       : 氏名トリミング

このファイルはエントリポイントと後方互換の re-export を提供する。
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
# 環境変数 SAITENSAMURAI_SMOKE_TEST=1 が設定されている場合のみ実行。
# sklearn/joblib が exe に正しく同梱されているかを GUI を開かずに検証し、
# 結果を smoke_test_result.txt に書き出して終了する。
# console=False の GUI exe では stdout が devnull になるため、
# 結果はファイル経由で外部（CI）に伝える。
if _os.environ.get('SAITENSAMURAI_SMOKE_TEST') == '1':
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
    setup_logging,
    safe_print, extract_pdf_to_images, combine_images_to_pdf,
    HAS_PYMUPDF, fitz,
    MARK2_WIDTH, MARK2_HEIGHT, OUTPUT_SCALE_MAX,
    RESULTS_FOLDER, BOXED_FOLDER, RESULTS_DATA_FOLDER,
    SCORED_FOLDER, FINAL_REPORT_FOLDER,
    MARK_AREAS_FILE, ANSWER_KEY_FILE,
    STUDENT_SUMMARY_FILE, EXAM_SUMMARY_FILE,
    CTT_ANALYSIS_EXCEL_FILE, CTT_ANALYSIS_PDF_FILE, SCORED_PDF_FILE,
    READING_RESULTS_FOLDER_NAME, SESSION_STATE_FILE,
    ERROR_TYPE_NO_MARK, ERROR_TYPE_DOUBLE_MARK, ERROR_TYPE_INVALID,
    DEFAULT_CORRECTION, DEFAULT_SCALE_FACTOR,
    DEFAULT_EXPAND_FACTOR, DEFAULT_EXPAND_FACTOR_Y,
    DEFAULT_BACKUP_FOLDER,
    MAX_DISPLAY_WIDTH, MAX_DISPLAY_HEIGHT,
    MARK2_BASE_WIDTH, MARK2_BASE_HEIGHT,
    MODE_MARK_ONLY, MODE_MARK_AND_DESCRIPTIVE, MODE_DESCRIPTIVE_ONLY,
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

# 採点コアロジック
from scoring_engine import (
    number_to_circled, normalize_value,
    normalize_zero_ten, normalize_answer_set,
    choice_to_position_index,
    load_template, load_mark2_results, score_answers,
)

# 画像アライメント（採点モード非依存）
from image_alignment import (
    imread_unicode, detect_corner_markers,
    apply_perspective_transform, compute_output_scale,
)

# OMR認識エンジン（マーク採点専用）
from omr_engine import (
    parse_excel_coordinates,
    save_template_coordinates_debug, load_coordinates_from_csv,
    draw_all_areas,
    generate_template, save_coordinates_to_csv,
    _save_coordinates_to_csv_impl,
    recognize_marks, save_recognition_results,
    process_box_drawer, process_folder,
)

# 閾値キャリブレーション
from threshold_calibrator import (
    collect_mark_fill_ratios,
    estimate_color_threshold_from_pixels,
    kmeans_2class,
    analyze_fill_ratio_distribution,
    run_threshold_calibration,
    reclassify_with_threshold,
    recollect_and_reclassify,
)

# 画像描画・採点結果レンダリング
from image_renderer import (
    draw_text_on_image,
    draw_mixed_text_on_image,
    draw_scoring_results,
    draw_total_score,
    _draw_total_score_in_box,
    _draw_total_score_fallback,
    process_scoring,
)

# サマリー生成
from summary_generator import (
    generate_student_summary,
    generate_exam_summary,
    process_summary_generation,
)

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

# Checker機能
from mark_checker import (
    create_backup_checker,
    update_xlsx_from_csv_checker,
    apply_corrections_checker,
    detect_errors_checker,
    load_errors_checker,
    save_errors_checker,
    load_coordinates_csv_checker,
    get_bbox_for_question_checker,
    crop_and_scale_image_checker,
    get_display_image_checker,
    fit_image_to_display,
    pil_to_imagetk_checker,
    CorrectedImageCache,
    _load_and_correct_image,
    crop_from_corrected_image,
)

# GUIサブウィンドウ
from gui_components import (
    MarkCheckerGUI,
    StudentAnswerSheetViewer,
    ThresholdCalibratorGUI,
    StartupModeDialog,
)

# メインGUI
from main_gui import SaitenSamuraiGUI

# 後方互換エイリアス
Mark2GUI = SaitenSamuraiGUI


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
    return os.path.join(base, "saitensamurai_crash.log")


def main():
    """メイン関数 — 起動モード選択 → メインGUI"""
    setup_logging()
    root = tk.Tk()
    root.withdraw()  # モード選択中はメインウィンドウを非表示

    # 起動モード選択ダイアログ
    dialog = StartupModeDialog(root)
    mode = dialog.result
    mark_format = getattr(dialog, 'mark_format', None)
    session_path = getattr(dialog, '_session_path', None)

    if mode is None:
        # ダイアログを閉じた → アプリ終了
        root.destroy()
        return

    root.deiconify()  # メインウィンドウを表示
    if mark_format is None:
        from constants import MARK_FORMAT_STANDARD
        mark_format = MARK_FORMAT_STANDARD
    app = SaitenSamuraiGUI(root, mode=mode, mark_format=mark_format,
                           restore_session_path=session_path)
    root.mainloop()


if __name__ == '__main__':
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
                f.write(f"[{timestamp}] 採点侍 クラッシュレポート\n")
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
                "採点侍 - エラー",
                f"アプリケーションの起動中にエラーが発生しました。\n\n"
                f"エラー: {type(e).__name__}: {e}\n\n"
                f"詳細ログ:\n{log_path}\n\n"
                f"このファイルを開発者に送付してください。"
            )
        except Exception:
            pass
        
        sys.exit(1)

