#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_loader.py — 学籍番号OCRの照合に使う名簿の読み込み。

任意機能: 名簿を読み込まなくても学籍番号OCR自体は使える。

名簿はいずれの入力方法でも「列名なし・2列のみ（1列目=学籍番号、2列目=氏名）」
という共通フォーマットで扱う。列名の一致判定は行わない(見出し行があると
そのまま1件のデータとして読み込まれてしまうので、見出し行は付けないこと)。

入力方法は3通り:
    1. Excelファイル読込 (load_roster) — 列名なし・2列のみ
    2. CSVファイル読込 (load_roster_csv) — 列名なし・2列のみ
    3. コピペ入力 (build_roster_from_paste) — Excelで学籍番号・氏名の2列を
       まとめて選択してコピーすると、1行につき「学籍番号<TAB>氏名」の
       TAB区切りテキストになる。それを1つのテキスト欄に貼り付ける。
       TAB区切り・改行区切りの形式であれば手入力でもよい。

いずれの方法でも、読み込んだ行の順序をそのまま保持した dict を返す
(Python 3.7+ の dict はキーの挿入順を保持するため、呼び出し側は
roster.keys() をそのまま「名簿の並び順」として扱ってよい)。この順序は
集計Excel・複数ページ統合Excelの行順を名簿と合わせるために使われる。
"""

import csv
import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional

import pandas as pd

from constants import get_ui_font_family, get_ui_font_size, fit_window_to_content

logger = logging.getLogger(__name__)

UI_FONT = get_ui_font_family()


def load_roster(excel_path: str) -> Dict[str, str]:
    """名簿Excelを読み込み、{学籍番号(str): 氏名} の辞書を返す。

    列名は付けない前提。1列目=学籍番号、2列目=氏名として位置で読み取る。
    学籍番号は前後の空白を除去した文字列として扱う(ゼロ埋め等の表記ゆれの
    吸収は行わない、MVPのため単純な文字列一致に留める)。

    Args:
        excel_path: 名簿Excelファイルのパス（列名なし・2列のみ）

    Returns:
        {学籍番号: 氏名} の辞書（Excelの行順を保持）

    Raises:
        ValueError: 列が2列に満たない、または有効な行が1件も無い場合
    """
    df = pd.read_excel(excel_path, header=None)

    if df.shape[1] < 2:
        raise ValueError("名簿には学籍番号・氏名の2列が必要です")

    roster: Dict[str, str] = {}
    for _, row in df.iterrows():
        student_id = str(row[0]).strip()
        name = str(row[1]).strip()
        if student_id and student_id.lower() != 'nan':
            roster[student_id] = name

    if not roster:
        raise ValueError("Excelから有効な学籍番号・氏名の行を読み取れませんでした")

    return roster


def _read_csv_rows(csv_path: str) -> List[List[str]]:
    """CSVを読み込み、行のリストを返す。Excel由来のCSVで多いcp932/UTF-8の
    どちらでも読めるようにエンコーディングをフォールバックする。"""
    for encoding in ("utf-8-sig", "cp932"):
        try:
            with open(csv_path, encoding=encoding, newline="") as f:
                return [row for row in csv.reader(f) if row]
        except UnicodeDecodeError:
            continue
    # 最後の手段: エラー文字を置換して読み込む
    with open(csv_path, encoding="utf-8", errors="replace", newline="") as f:
        return [row for row in csv.reader(f) if row]


def load_roster_csv(csv_path: str) -> Dict[str, str]:
    """学籍番号・氏名の2列だけのCSVを読み込み、{学籍番号: 氏名} を返す。

    列名は付けない前提。1列目=学籍番号、2列目=氏名として位置で読み取る。

    Args:
        csv_path: CSVファイルパス（列名なし・2列のみ）

    Returns:
        {学籍番号: 氏名} の辞書（CSVの行順を保持）

    Raises:
        ValueError: 有効な行が1件も無い場合
    """
    rows = _read_csv_rows(csv_path)
    if not rows:
        raise ValueError("CSVにデータがありません")

    roster: Dict[str, str] = {}
    for row in rows:
        if len(row) < 2:
            continue
        student_id = row[0].strip()
        name = row[1].strip()
        if student_id:
            roster[student_id] = name

    if not roster:
        raise ValueError("CSVから有効な学籍番号・氏名の行を読み取れませんでした")

    return roster


def build_roster_from_paste(text: str) -> Dict[str, str]:
    """「学籍番号<TAB>氏名」を1行1件としたテキストから名簿を構築する。

    Excelで学籍番号・氏名の2列(隣接していなくても可、Ctrl+クリックで
    複数列選択してコピー可)をまとめてコピーすると、1行につき
    「学籍番号\\t氏名」のTAB区切りテキストになるので、それをそのまま
    貼り付けられる。手入力する場合もTabキーで区切ればよい。

    Args:
        text: 「学籍番号<TAB>氏名」の行を改行区切りで並べたテキスト

    Returns:
        {学籍番号: 氏名} の辞書（貼り付けた行順を保持）

    Raises:
        ValueError: TAB区切りになっていない行がある、または有効な行が
            1件も無い場合
    """
    roster: Dict[str, str] = {}
    for line_no, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip('\r')
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            raise ValueError(
                f"{line_no}行目がTAB区切りになっていません: {line!r}\n"
                "Excelで学籍番号・氏名の2列を選択してコピーするか、"
                "手入力の場合はTabキーで区切ってください。"
            )
        student_id = parts[0].strip()
        name = parts[1].strip()
        if student_id:
            roster[student_id] = name

    if not roster:
        raise ValueError("有効な行がありません")

    return roster


def select_roster_gui(parent: Optional[tk.Tk] = None) -> Optional[Dict[str, str]]:
    """名簿の入力方法(Excel/CSV/コピペ)を選ばせ、{学籍番号: 氏名} を返すダイアログ。

    「スキップ」した場合は None を返す(名簿照合なしで続行)。

    Returns:
        {学籍番号: 氏名} の辞書、またはキャンセル/スキップ時 None
    """
    window = tk.Toplevel(parent)
    window.title("名簿の読み込み（任意）")
    window.transient(parent)
    window.grab_set()

    result: List[Optional[Dict[str, str]]] = [None]

    body = tk.Frame(window, padx=14, pady=12)
    body.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        body,
        text="学籍番号OCRの結果と照合する名簿を読み込みます（任意）",
        font=(UI_FONT, get_ui_font_size(10), 'bold'), justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(0, 6))

    tk.Label(
        body,
        text="Excel・CSVは、1列目を学籍番号、2列目を氏名にしてください。\n"
             "先頭行の「学籍番号」「氏名」などの見出しセルは不要です。\n"
             "入力例：  20260001  ｜  山田 太郎",
        font=(UI_FONT, get_ui_font_size(8)), fg="#555", justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(0, 10))

    # ----- 方法選択ボタン行 -----
    method_row = tk.Frame(body)
    method_row.pack(fill=tk.X, pady=(0, 10))

    paste_frame = tk.Frame(body)  # コピペ用UI（ボタン押下時に表示）

    def _finish(roster: Optional[Dict[str, str]]):
        result[0] = roster
        window.grab_release()
        window.destroy()

    def _pick_excel():
        path = filedialog.askopenfilename(
            title="名簿Excelを選択（列名なし・1列目:学籍番号 2列目:氏名）",
            filetypes=[("Excelファイル", "*.xlsx *.xls"), ("すべてのファイル", "*.*")],
            parent=window,
        )
        if not path:
            return
        try:
            roster = load_roster(path)
        except Exception as e:
            messagebox.showerror("エラー", f"名簿の読込に失敗しました:\n{e}", parent=window)
            return
        _finish(roster)

    def _pick_csv():
        path = filedialog.askopenfilename(
            title="名簿CSVを選択（列名なし・1列目:学籍番号 2列目:氏名）",
            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")],
            parent=window,
        )
        if not path:
            return
        try:
            roster = load_roster_csv(path)
        except Exception as e:
            messagebox.showerror("エラー", f"名簿の読込に失敗しました:\n{e}", parent=window)
            return
        _finish(roster)

    def _show_paste_ui():
        paste_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        method_row.pack_forget()
        # コピペ用のTextウィジェット・確定ボタン分、ウィンドウを広げ直す
        # (最初の fit_window_to_content はこのUIが未表示の時点でのサイズなので、
        # 表示後に呼び直さないと確定ボタンが見えない位置に隠れてしまう)
        fit_window_to_content(window, min_width=480, min_height=430)

    def _show_method_ui():
        paste_frame.pack_forget()
        method_row.pack(fill=tk.X, pady=(0, 10))
        fit_window_to_content(window, min_width=460, min_height=220)

    tk.Button(
        method_row, text="📄 Excelファイルから読み込む", command=_pick_excel,
        font=(UI_FONT, get_ui_font_size(9)),
    ).pack(fill=tk.X, pady=2)
    tk.Button(
        method_row, text="📄 CSVファイルから読み込む", command=_pick_csv,
        font=(UI_FONT, get_ui_font_size(9)),
    ).pack(fill=tk.X, pady=2)
    tk.Button(
        method_row, text="📋 コピー＆ペースト／手入力", command=_show_paste_ui,
        font=(UI_FONT, get_ui_font_size(9)),
    ).pack(fill=tk.X, pady=2)

    # ----- コピペ入力UI（初期状態では非表示） -----
    tk.Label(
        paste_frame,
        text="Excelなどから、1列目「学籍番号」・2列目「氏名」のデータを貼り付けてください。\n"
             "「学籍番号」「氏名」という見出し行は含めません。\n"
             "下の欄へ直接手入力してもOKです（学籍番号と氏名の間はTabキーで区切ります）。\n"
             "入力例：  20260001  → Tab →  山田 太郎",
        font=(UI_FONT, get_ui_font_size(8)), fg="#555", justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(0, 6))

    paste_text = tk.Text(
        paste_frame, width=40, height=14,
        font=(UI_FONT, get_ui_font_size(9)),
        bg="#FFFFFF", fg="#222222", insertbackground="#222222",
        relief=tk.SOLID, bd=1, highlightthickness=1,
        highlightbackground="#9E9E9E", highlightcolor="#1976D2",
    )
    paste_text.pack(fill=tk.BOTH, expand=True)

    def _confirm_paste():
        try:
            roster = build_roster_from_paste(paste_text.get("1.0", tk.END))
        except Exception as e:
            messagebox.showerror("エラー", str(e), parent=window)
            return
        _finish(roster)

    paste_btn_row = tk.Frame(paste_frame)
    paste_btn_row.pack(fill=tk.X, pady=(8, 0))
    tk.Button(
        paste_btn_row, text="◀ 戻る", command=_show_method_ui,
        font=(UI_FONT, get_ui_font_size(9)),
    ).pack(side=tk.LEFT)
    tk.Button(
        paste_btn_row, text="✔ この内容で名簿を作成", command=_confirm_paste,
        bg="#81C784", fg="black", font=(UI_FONT, get_ui_font_size(9), 'bold'),
    ).pack(side=tk.RIGHT)

    # ----- 共通: スキップ -----
    tk.Button(
        body, text="名簿なしでスキップ", command=lambda: _finish(None),
        font=(UI_FONT, get_ui_font_size(9)), fg="#777",
    ).pack(anchor=tk.E, pady=(10, 0))

    window.protocol("WM_DELETE_WINDOW", lambda: _finish(None))
    fit_window_to_content(window, min_width=500, min_height=290)
    window.wait_window()

    return result[0]
