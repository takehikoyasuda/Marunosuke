#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
multi_page_merger.py — 複数ページ答案の集計Excelを統合するツール。

1人の学生が複数ページ（例: 3枚、各ページに異なる設問）を提出する運用を前提に、
「同じページ番号の答案だけをまとめたバッチ」ごとに独立して生成した集計Excel
（記述のみモード, summary_generator.process_descriptive_only_summary の出力）
を、学籍番号OCRで確認済みの学籍番号をキーに1つに統合する。

Step1〜3のパイプライン自体は変更しない。既に出来上がった複数の集計Excelを
後から読み込んで突合するだけの、独立した単発ツール（page_number_checker.py
と同じ思想）。マーク＋記述モード(generate_student_summary出力)は対象外。
"""

import logging
import re
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from constants import get_ui_font_family, get_ui_font_size

logger = logging.getLogger(__name__)

UI_FONT = get_ui_font_family()

# process_descriptive_only_summary が出力する列見出しのうち、設問列ではないもの
NON_QUESTION_COLUMNS = {
    'No.', 'ファイル名', '氏名欄', '学籍番号欄', '学籍番号(確認済み)', '氏名候補(名簿照合)', '合計',
}
STUDENT_ID_COLUMN = '学籍番号(確認済み)'
TOTAL_COLUMN = '合計'
MAX_SCORE_PREFIX = '配点計 ('


@dataclass
class PageSummary:
    """1ページ分の集計Excelから読み取った内容。"""
    label: str
    source_path: str
    question_columns: List[str] = field(default_factory=list)
    rows_by_student_id: Dict[str, Dict] = field(default_factory=dict)
    max_score: Optional[float] = None
    unmatched_count: int = 0


def read_page_summary(excel_path: str, label: str) -> PageSummary:
    """記述のみモードの集計Excelを読み込み、PageSummaryを構築する。

    Raises:
        ValueError: 「学籍番号(確認済み)」列が見つからない場合
            （学籍番号OCRで確認されていないExcelは統合できない）。
    """
    wb = load_workbook(excel_path, data_only=True)
    ws = wb.active

    header = [cell.value for cell in ws[1]]
    col_index: Dict[str, int] = {}
    for idx, name in enumerate(header):
        if name is not None:
            col_index[name] = idx

    if STUDENT_ID_COLUMN not in col_index:
        raise ValueError(
            f"「{STUDENT_ID_COLUMN}」列が見つかりません: {excel_path}\n"
            "学籍番号OCRで確認済みの集計Excelのみ統合できます。"
        )
    sid_idx = col_index[STUDENT_ID_COLUMN]
    total_idx = col_index.get(TOTAL_COLUMN)

    question_columns = [
        name for name in header
        if name is not None and name not in NON_QUESTION_COLUMNS and not name.startswith(MAX_SCORE_PREFIX)
    ]
    question_indices = {name: header.index(name) for name in question_columns}

    max_score = None
    for name in header:
        if isinstance(name, str) and name.startswith(MAX_SCORE_PREFIX):
            m = re.search(r'\(([\d.]+)\)', name)
            if m:
                max_score = float(m.group(1))
            break

    rows_by_student_id: Dict[str, Dict] = {}
    unmatched_count = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[sid_idx] is None or not str(row[sid_idx]).strip():
            unmatched_count += 1
            continue
        student_id = str(row[sid_idx]).strip()
        entry = {name: row[idx] for name, idx in question_indices.items()}
        entry[TOTAL_COLUMN] = row[total_idx] if total_idx is not None else None
        rows_by_student_id[student_id] = entry

    return PageSummary(
        label=label,
        source_path=excel_path,
        question_columns=question_columns,
        rows_by_student_id=rows_by_student_id,
        max_score=max_score,
        unmatched_count=unmatched_count,
    )


def merge_page_summaries(pages: List[PageSummary]) -> Tuple[Dict[str, Dict], List[str]]:
    """複数ページ分のPageSummaryを、学籍番号をキーに1つに統合する。

    Returns:
        (統合結果 {学籍番号: {列名: 値}}, 警告メッセージのリスト)
    """
    warnings: List[str] = []
    for page in pages:
        if page.unmatched_count:
            warnings.append(
                f"{page.label}（{page.source_path}）: "
                f"学籍番号未確認の行が{page.unmatched_count}件あり、統合対象から除外しました。"
            )

    all_max_scores_known = all(p.max_score is not None for p in pages)
    total_max_score = sum(p.max_score for p in pages) if all_max_scores_known else None

    student_ids: List[str] = []
    seen = set()
    for page in pages:
        for sid in page.rows_by_student_id:
            if sid not in seen:
                seen.add(sid)
                student_ids.append(sid)

    merged: Dict[str, Dict] = {}
    for sid in student_ids:
        row: Dict = {}
        missing_pages = []
        grand_total = 0.0
        any_total = False
        for page in pages:
            page_row = page.rows_by_student_id.get(sid)
            if page_row is None:
                missing_pages.append(page.label)
                for qcol in page.question_columns:
                    row[f"{page.label}: {qcol}"] = None
                row[f"{page.label} 合計"] = None
                continue
            for qcol in page.question_columns:
                row[f"{page.label}: {qcol}"] = page_row.get(qcol)
            page_total = page_row.get(TOTAL_COLUMN)
            row[f"{page.label} 合計"] = page_total
            if isinstance(page_total, (int, float)):
                grand_total += page_total
                any_total = True

        row['総合計'] = grand_total if any_total else None
        row['総配点'] = total_max_score
        row['欠落ページ'] = ", ".join(missing_pages)
        merged[sid] = row

    return merged, warnings


def write_merged_excel(merged_rows: Dict[str, Dict], pages: List[PageSummary], output_path: str) -> None:
    """統合結果をExcelに書き出す。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "複数ページ統合"

    headers = ["No", "学籍番号"]
    for page in pages:
        for qcol in page.question_columns:
            headers.append(f"{page.label}: {qcol}")
        headers.append(f"{page.label} 合計")
    headers += ["総合計", "総配点", "欠落ページ"]

    header_font_white = Font(bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    center = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    missing_fill = PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid")

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.alignment = center
        cell.border = thin_border

    for row_idx, (sid, row_data) in enumerate(sorted(merged_rows.items()), 2):
        has_missing = bool(row_data.get('欠落ページ'))
        values = [row_idx - 1, sid]
        for page in pages:
            for qcol in page.question_columns:
                values.append(row_data.get(f"{page.label}: {qcol}"))
            values.append(row_data.get(f"{page.label} 合計"))
        values += [row_data.get('総合計'), row_data.get('総配点'), row_data.get('欠落ページ')]

        for col_idx, v in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=v)
            cell.border = thin_border
            cell.alignment = center
            if has_missing:
                cell.fill = missing_fill

    ws.freeze_panes = 'C2'
    ws.column_dimensions['B'].width = 16
    for col_idx in range(3, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 14

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def run_multi_page_merge_gui(parent: Optional[tk.Tk] = None) -> Optional[str]:
    """複数ページ統合ツールのGUI本体。

    Returns:
        統合Excelの保存先パス。キャンセル時は None。
    """
    window = tk.Toplevel(parent)
    window.title("複数ページ統合")
    window.geometry("520x420")

    tk.Label(
        window,
        text="ページ順に集計Excelを追加してください\n（例: ページ1→ページ2→ページ3 の順）",
        font=(UI_FONT, get_ui_font_size(10), 'bold'), justify=tk.LEFT,
    ).pack(pady=(10, 5))

    list_frame = tk.Frame(window)
    list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    listbox = tk.Listbox(list_frame, font=(UI_FONT, get_ui_font_size(9)))
    scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    file_paths: List[str] = []

    def _refresh_listbox():
        listbox.delete(0, tk.END)
        for i, path in enumerate(file_paths, 1):
            listbox.insert(tk.END, f"ページ{i}: {Path(path).name}")

    def _add_file():
        path = filedialog.askopenfilename(
            title="集計Excelを選択",
            filetypes=[("Excelファイル", "*.xlsx *.xls"), ("すべてのファイル", "*.*")],
            parent=window,
        )
        if path:
            file_paths.append(path)
            _refresh_listbox()

    def _remove_selected():
        sel = listbox.curselection()
        if not sel:
            return
        del file_paths[sel[0]]
        _refresh_listbox()

    def _move(offset):
        sel = listbox.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + offset
        if 0 <= j < len(file_paths):
            file_paths[i], file_paths[j] = file_paths[j], file_paths[i]
            _refresh_listbox()
            listbox.selection_set(j)

    btn_row = tk.Frame(window)
    btn_row.pack(pady=5)
    tk.Button(btn_row, text="＋ 追加", command=_add_file).pack(side=tk.LEFT, padx=3)
    tk.Button(btn_row, text="↑", command=lambda: _move(-1), width=3).pack(side=tk.LEFT, padx=3)
    tk.Button(btn_row, text="↓", command=lambda: _move(1), width=3).pack(side=tk.LEFT, padx=3)
    tk.Button(btn_row, text="－ 削除", command=_remove_selected).pack(side=tk.LEFT, padx=3)

    result_path = [None]

    def _run_merge():
        if len(file_paths) < 2:
            messagebox.showwarning("エラー", "2件以上のExcelを追加してください。", parent=window)
            return

        pages = []
        for i, path in enumerate(file_paths, 1):
            try:
                pages.append(read_page_summary(path, f"ページ{i}"))
            except ValueError as e:
                messagebox.showerror("エラー", str(e), parent=window)
                return
            except Exception as e:
                messagebox.showerror("エラー", f"読み込みに失敗しました:\n{path}\n{e}", parent=window)
                return

        merged, warnings = merge_page_summaries(pages)

        output_path = filedialog.asksaveasfilename(
            title="統合結果の保存先",
            defaultextension=".xlsx",
            filetypes=[("Excelファイル", "*.xlsx")],
            initialfile="複数ページ統合結果.xlsx",
            parent=window,
        )
        if not output_path:
            return

        try:
            write_merged_excel(merged, pages, output_path)
        except Exception as e:
            messagebox.showerror("エラー", f"書き出しに失敗しました:\n{e}", parent=window)
            return

        result_path[0] = output_path
        msg = f"{len(merged)}人分を統合しました。\n保存先: {output_path}"
        if warnings:
            msg += "\n\n【警告】\n" + "\n".join(warnings)
        messagebox.showinfo("完了", msg, parent=window)
        window.destroy()

    tk.Button(
        window, text="統合実行", command=_run_merge,
        bg="#4CAF50", fg="black", font=(UI_FONT, get_ui_font_size(11), 'bold'), height=2,
    ).pack(fill=tk.X, padx=10, pady=10)

    window.grab_set()
    window.wait_window()

    return result_path[0]
