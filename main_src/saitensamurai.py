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
    READING_RESULTS_FOLDER_NAME, SESSION_STATE_FILE,
)

# 画像アライメント（採点モード非依存）
from image_alignment import (
    imread_unicode, detect_corner_markers,
    apply_perspective_transform, compute_output_scale,
)

# サマリー生成
from summary_generator import process_descriptive_only_summary

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
    """カレントディレクトリ内のクラッシュログパスを返す。"""
    return os.path.join(os.getcwd(), "marunosuke_crash.log")


def main():
    """メイン関数 — メインGUIを直接起動"""
    setup_logging()
    root = tk.Tk()
    app = MarunosukeGUI(root)
    root.mainloop()


def run():
    """クラッシュレポート処理を含めてアプリを起動する。"""
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
