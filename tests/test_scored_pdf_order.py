#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
採点済み答案PDFの並び順に関するテスト。

- summary_generator._scored_pdf_order: 名簿順/学籍番号順の並び決定ロジック
- constants.combine_images_to_pdf: ordered_filenames 引数によるPDF組み立て順
"""
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from constants import combine_images_to_pdf  # noqa: E402
from summary_generator import _scored_pdf_order  # noqa: E402


class TestScoredPdfOrder:
    """_scored_pdf_order のテスト"""

    def test_no_roster_no_student_id_returns_none(self):
        """名簿・学籍番号OCR結果のどちらも無ければNone（ファイル名順に委ねる）"""
        result = _scored_pdf_order(["b.jpg", "a.jpg"], None, None)
        assert result is None

    def test_roster_order_applied(self):
        """名簿がある場合、名簿の並び順でファイルが並ぶ"""
        scored_files = ["c.jpg", "a.jpg", "b.jpg"]
        student_id_result = {
            "a.jpg": {"text": "102"},
            "b.jpg": {"text": "101"},
            "c.jpg": {"text": "103"},
        }
        roster = {"101": "Aさん", "102": "Bさん", "103": "Cさん"}
        result = _scored_pdf_order(scored_files, student_id_result, roster)
        assert result == ["b.jpg", "a.jpg", "c.jpg"]

    def test_roster_unmatched_files_appended_at_end(self):
        """名簿にもOCR結果にも対応しないファイルは末尾に自然順で追加される"""
        scored_files = ["z_unmatched.jpg", "a.jpg", "b.jpg"]
        student_id_result = {
            "a.jpg": {"text": "101"},
            "b.jpg": {"text": "102"},
        }
        roster = {"101": "Aさん", "102": "Bさん"}
        result = _scored_pdf_order(scored_files, student_id_result, roster)
        assert result == ["a.jpg", "b.jpg", "z_unmatched.jpg"]

    def test_no_roster_but_student_id_result_sorts_by_id(self):
        """名簿は無いが学籍番号OCR結果がある場合、確認済み学籍番号の昇順"""
        scored_files = ["c.jpg", "a.jpg", "b.jpg"]
        student_id_result = {
            "a.jpg": {"text": "300"},
            "b.jpg": {"text": "100"},
            "c.jpg": {"text": "200"},
        }
        result = _scored_pdf_order(scored_files, student_id_result, None)
        assert result == ["b.jpg", "c.jpg", "a.jpg"]

    def test_student_id_result_with_blank_text_goes_last(self):
        """学籍番号が空欄のファイルは末尾に回る"""
        scored_files = ["a.jpg", "b.jpg"]
        student_id_result = {
            "a.jpg": {"text": ""},
            "b.jpg": {"text": "100"},
        }
        result = _scored_pdf_order(scored_files, student_id_result, None)
        assert result == ["b.jpg", "a.jpg"]


class TestCombineImagesToPdfOrder:
    """combine_images_to_pdf の ordered_filenames 引数のテスト"""

    def _make_image(self, path, color):
        img = Image.new("RGB", (50, 50), color=color)
        img.save(path)

    def test_ordered_filenames_filters_missing_files(self, tmp_path):
        """存在しないファイル名が混ざっていても無視して組み立てる"""
        folder = tmp_path / "scored"
        folder.mkdir()
        self._make_image(folder / "a.jpg", (255, 0, 0))
        self._make_image(folder / "b.jpg", (0, 255, 0))

        output = tmp_path / "out.pdf"
        result = combine_images_to_pdf(
            str(folder), str(output),
            ordered_filenames=["b.jpg", "does_not_exist.jpg", "a.jpg"],
        )
        assert result is not None
        assert output.exists()

    def test_no_ordered_filenames_keeps_default_behavior(self, tmp_path):
        """ordered_filenames省略時は従来通りファイル名順で全画像が対象になる"""
        folder = tmp_path / "scored"
        folder.mkdir()
        self._make_image(folder / "b.jpg", (0, 255, 0))
        self._make_image(folder / "a.jpg", (255, 0, 0))

        output = tmp_path / "out.pdf"
        result = combine_images_to_pdf(str(folder), str(output))
        assert result is not None
        assert output.exists()

    def test_empty_ordered_filenames_returns_none(self, tmp_path):
        """ordered_filenamesを指定したが1件も実在しない場合はNone"""
        folder = tmp_path / "scored"
        folder.mkdir()
        self._make_image(folder / "a.jpg", (255, 0, 0))

        output = tmp_path / "out.pdf"
        result = combine_images_to_pdf(
            str(folder), str(output), ordered_filenames=["missing.jpg"],
        )
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
