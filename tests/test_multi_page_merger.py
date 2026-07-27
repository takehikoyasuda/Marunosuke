#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_multi_page_merger.py — multi_page_merger.py（複数ページ答案の統合ツール）のテスト。

process_descriptive_only_summary が出力する「記述のみモード」の集計Excelと
同じ列構成を openpyxl で組み立て、read_page_summary / merge_page_summaries /
write_merged_excel の各ロジック（GUI非依存）を検証する。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))


def _build_summary_excel(path, questions, students, include_sid_column=True):
    """記述のみモードの集計Excelと同じ列構成のダミーファイルを作る。

    Args:
        questions: [(name, max_score), ...]
        students: [{'file': str, 'sid': str|None, 'scores': {name: score}}]
        include_sid_column: '学籍番号(確認済み)' 列を含めるか
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "学生別サマリー"

    headers = ["No.", "ファイル名"]
    if include_sid_column:
        headers += ["学籍番号欄", "学籍番号(確認済み)"]
    for name, max_score in questions:
        headers.append(f"{name} ({max_score})")
    headers.append("合計")
    full_score = sum(m for _, m in questions)
    headers.append(f"配点計 ({full_score})")
    ws.append(headers)

    for i, student in enumerate(students, 1):
        row = [i, student['file']]
        if include_sid_column:
            row += ['', student.get('sid')]
        total = 0
        for name, _ in questions:
            score = student['scores'].get(name, 0)
            row.append(score)
            total += score
        row.append(total)
        ws.append(row)

    wb.save(path)


class TestReadPageSummary(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_merger_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_extracts_question_columns_and_rows(self):
        from multi_page_merger import read_page_summary
        path = Path(self.test_dir) / "page1.xlsx"
        _build_summary_excel(
            path,
            questions=[("問1", 10), ("問2", 15)],
            students=[
                {'file': 'a.jpg', 'sid': '1001', 'scores': {'問1': 8, '問2': 12}},
                {'file': 'b.jpg', 'sid': '1002', 'scores': {'問1': 10, '問2': 15}},
            ],
        )
        page = read_page_summary(str(path), "ページ1")
        self.assertEqual(page.question_columns, ["問1 (10)", "問2 (15)"])
        self.assertEqual(page.unmatched_count, 0)
        self.assertEqual(page.max_score, 25.0)
        self.assertEqual(page.rows_by_student_id["1001"]["問1 (10)"], 8)
        self.assertEqual(page.rows_by_student_id["1001"]["合計"], 20)

    def test_02_counts_unmatched_blank_student_id(self):
        from multi_page_merger import read_page_summary
        path = Path(self.test_dir) / "page1.xlsx"
        _build_summary_excel(
            path,
            questions=[("問1", 10)],
            students=[
                {'file': 'a.jpg', 'sid': '1001', 'scores': {'問1': 8}},
                {'file': 'b.jpg', 'sid': None, 'scores': {'問1': 5}},
                {'file': 'c.jpg', 'sid': '', 'scores': {'問1': 3}},
            ],
        )
        page = read_page_summary(str(path), "ページ1")
        self.assertEqual(page.unmatched_count, 2)
        self.assertEqual(len(page.rows_by_student_id), 1)

    def test_03_raises_when_no_student_id_column(self):
        from multi_page_merger import read_page_summary
        path = Path(self.test_dir) / "page1.xlsx"
        _build_summary_excel(
            path, questions=[("問1", 10)],
            students=[{'file': 'a.jpg', 'sid': '1001', 'scores': {'問1': 8}}],
            include_sid_column=False,
        )
        with self.assertRaises(ValueError):
            read_page_summary(str(path), "ページ1")


class TestMergePageSummaries(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_merger_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _read(self, filename, questions, students):
        path = Path(self.test_dir) / filename
        _build_summary_excel(path, questions, students)
        from multi_page_merger import read_page_summary
        label = filename.replace('.xlsx', '')
        return read_page_summary(str(path), label)

    def test_01_all_pages_complete_no_missing(self):
        from multi_page_merger import merge_page_summaries
        p1 = self._read("p1.xlsx", [("問1", 10)], [
            {'file': 'a.jpg', 'sid': '1001', 'scores': {'問1': 8}},
        ])
        p2 = self._read("p2.xlsx", [("問2", 15)], [
            {'file': 'a.jpg', 'sid': '1001', 'scores': {'問2': 12}},
        ])
        merged, warnings = merge_page_summaries([p1, p2])
        self.assertEqual(warnings, [])
        row = merged["1001"]
        self.assertEqual(row["p1: 問1 (10)"], 8)
        self.assertEqual(row["p2: 問2 (15)"], 12)
        self.assertEqual(row["総合計"], 20)
        self.assertEqual(row["総配点"], 25.0)
        self.assertEqual(row["欠落ページ"], "")

    def test_02_missing_page_flagged_and_excluded_from_total(self):
        from multi_page_merger import merge_page_summaries
        p1 = self._read("p1.xlsx", [("問1", 10)], [
            {'file': 'a.jpg', 'sid': '1001', 'scores': {'問1': 8}},
            {'file': 'b.jpg', 'sid': '1002', 'scores': {'問1': 5}},
        ])
        p2 = self._read("p2.xlsx", [("問2", 15)], [
            {'file': 'a.jpg', 'sid': '1001', 'scores': {'問2': 12}},
            # 1002はページ2を提出していない
        ])
        merged, warnings = merge_page_summaries([p1, p2])
        self.assertEqual(warnings, [])

        complete_row = merged["1001"]
        self.assertEqual(complete_row["欠落ページ"], "")
        self.assertEqual(complete_row["総合計"], 20)

        incomplete_row = merged["1002"]
        self.assertEqual(incomplete_row["欠落ページ"], "p2")
        self.assertIsNone(incomplete_row["p2: 問2 (15)"])
        self.assertEqual(incomplete_row["総合計"], 5)  # p1の得点のみ

    def test_03_inconsistent_max_score_yields_none_total(self):
        from multi_page_merger import PageSummary, merge_page_summaries
        p1 = PageSummary(
            label="p1", source_path="p1.xlsx", question_columns=["問1 (10)"],
            rows_by_student_id={"1001": {"問1 (10)": 8, "合計": 8}},
            max_score=10.0, unmatched_count=0,
        )
        p2 = PageSummary(
            label="p2", source_path="p2.xlsx", question_columns=["問2 (15)"],
            rows_by_student_id={"1001": {"問2 (15)": 12, "合計": 12}},
            max_score=None, unmatched_count=0,  # 配点計の抽出に失敗したケース
        )
        merged, _ = merge_page_summaries([p1, p2])
        self.assertIsNone(merged["1001"]["総配点"])
        self.assertEqual(merged["1001"]["総合計"], 20)

    def test_04_unmatched_rows_reported_as_warning(self):
        from multi_page_merger import merge_page_summaries
        p1 = self._read("p1.xlsx", [("問1", 10)], [
            {'file': 'a.jpg', 'sid': '1001', 'scores': {'問1': 8}},
            {'file': 'b.jpg', 'sid': None, 'scores': {'問1': 5}},
        ])
        p2 = self._read("p2.xlsx", [("問2", 15)], [
            {'file': 'a.jpg', 'sid': '1001', 'scores': {'問2': 12}},
        ])
        _, warnings = merge_page_summaries([p1, p2])
        self.assertEqual(len(warnings), 1)
        self.assertIn("p1", warnings[0])
        self.assertIn("1件", warnings[0])


class TestWriteMergedExcel(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_merger_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_output_has_expected_columns_and_highlight(self):
        from multi_page_merger import PageSummary, write_merged_excel

        p1 = PageSummary(
            label="ページ1", source_path="p1.xlsx", question_columns=["問1 (10)"],
            rows_by_student_id={}, max_score=10.0, unmatched_count=0,
        )
        p2 = PageSummary(
            label="ページ2", source_path="p2.xlsx", question_columns=["問2 (15)"],
            rows_by_student_id={}, max_score=15.0, unmatched_count=0,
        )
        merged_rows = {
            "1001": {
                "ページ1: 問1 (10)": 8, "ページ1 合計": 8,
                "ページ2: 問2 (15)": 12, "ページ2 合計": 12,
                "総合計": 20, "総配点": 25.0, "欠落ページ": "",
            },
            "1002": {
                "ページ1: 問1 (10)": 5, "ページ1 合計": 5,
                "ページ2: 問2 (15)": None, "ページ2 合計": None,
                "総合計": 5, "総配点": 25.0, "欠落ページ": "ページ2",
            },
        }
        output_path = str(Path(self.test_dir) / "merged.xlsx")
        write_merged_excel(merged_rows, [p1, p2], output_path)

        wb = load_workbook(output_path)
        ws = wb.active
        headers = [c.value for c in ws[1]]
        self.assertEqual(
            headers,
            ["No", "学籍番号", "ページ1: 問1 (10)", "ページ1 合計",
             "ページ2: 問2 (15)", "ページ2 合計", "総合計", "総配点", "欠落ページ"],
        )

        # 1001(欠落なし)は2行目、1002(欠落あり)は3行目(sorted順)
        row2 = [c.value for c in ws[2]]
        row3 = [c.value for c in ws[3]]
        self.assertEqual(row2[1], "1001")
        self.assertEqual(row3[1], "1002")

        # 欠落ページがある行は背景色がついていること
        self.assertEqual(ws.cell(row=3, column=2).fill.fgColor.rgb, "00FFCDD2")
        self.assertNotEqual(ws.cell(row=2, column=2).fill.fgColor.rgb, "00FFCDD2")


if __name__ == '__main__':
    unittest.main()
