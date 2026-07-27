#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
後方互換テスト: saitensamurai.py から全シンボルがインポート可能か検証
============================================================================
記述式のみアーキテクチャへの移行後も、
既存コード（テスト含む）が ``from saitensamurai import X`` で
現行の全機能にアクセスできることを保証する。

マーク採点専用のシンボル（omr_engine, scoring_engine, mark_checker,
threshold_calibrator, image_renderer 等）はマークシート採点機能の
廃止に伴い削除済みのため、このリストには含めない。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))


# ================================================================
# 全 re-export シンボルのインポート可否チェック
# ================================================================

EXPECTED_SYMBOLS = [
    # --- constants.py ---
    "setup_logging",
    "safe_print",
    "extract_pdf_to_images",
    "combine_images_to_pdf",
    "HAS_PYMUPDF",
    "fitz",
    "RESULTS_FOLDER",
    "BOXED_FOLDER",
    "RESULTS_DATA_FOLDER",
    "SCORED_FOLDER",
    "FINAL_REPORT_FOLDER",
    "ANSWER_KEY_FILE",
    "STUDENT_SUMMARY_FILE",
    "EXAM_SUMMARY_FILE",
    "CTT_ANALYSIS_EXCEL_FILE",
    "CTT_ANALYSIS_PDF_FILE",
    "READING_RESULTS_FOLDER_NAME",
    "SESSION_STATE_FILE",
    # --- image_alignment.py ---
    "imread_unicode",
    "detect_corner_markers",
    "apply_perspective_transform",
    "compute_output_scale",
    # --- summary_generator.py ---
    "process_descriptive_only_summary",
    # --- ctt_analyzer.py ---
    "convert_mark2_to_ctt_data",
    "_sort_choices",
    "_is_invalid_response",
    "_is_no_answer",
    "CTTAnalyzer",
    "CTTPlotGenerator",
    "CTTExcelExporter",
    "CTTPDFReporter",
    "generate_ctt_analysis",
    # --- r_export.py ---
    "export_r_analysis_kit",
    "R_EXPORT_FOLDER",
    "R_DATA_CSV",
    "R_ITEM_INFO_CSV",
    "R_SCRIPT_FILE",
    "R_RMD_TEMPLATE_FILE",
    # --- main_gui.py ---
    "SaitenSamuraiGUI",
    "Mark2GUI",
    # --- フラグ ---
    "HAS_MATPLOTLIB",
    "HAS_REPORTLAB",
]


@pytest.mark.parametrize("symbol", EXPECTED_SYMBOLS)
def test_symbol_importable(symbol):
    """saitensamurai から各シンボルがインポート可能"""
    import saitensamurai
    assert hasattr(saitensamurai, symbol), (
        f"saitensamurai に '{symbol}' が存在しません — "
        f"re-export が漏れています"
    )


def test_no_extra_missing_constants():
    """定数モジュール由来の主要定数が正しく利用可能"""
    from saitensamurai import (
        RESULTS_FOLDER,
        RESULTS_DATA_FOLDER,
        SESSION_STATE_FILE,
    )
    assert RESULTS_FOLDER == "_saiten_grading_results"
    assert RESULTS_DATA_FOLDER == "01_Results"
    assert SESSION_STATE_FILE == "session_state.json"


def test_mark2gui_is_class():
    """Mark2GUI がクラスとしてインポートされる"""
    from saitensamurai import Mark2GUI
    assert isinstance(Mark2GUI, type)


def test_mark2gui_is_saitensamuraigui_alias():
    """Mark2GUI は SaitenSamuraiGUI の後方互換エイリアス"""
    from saitensamurai import Mark2GUI, SaitenSamuraiGUI
    assert Mark2GUI is SaitenSamuraiGUI
