"""
R連携エクスポート テスト
========================
r_export.py の機能テスト。
ダミーMark2データを用いて、R分析キットの出力を検証する。
"""
import sys
import os
import tempfile
import pytest
from pathlib import Path

import numpy as np
import pandas as pd

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "main_src"))

from r_export import (
    export_r_analysis_kit,
    _export_scored_data,
    _export_item_info,
    _generate_r_script,
    _generate_rmd_template,
    R_EXPORT_FOLDER,
    R_DATA_CSV,
    R_ITEM_INFO_CSV,
    R_SCRIPT_FILE,
    R_RMD_TEMPLATE_FILE,
    DEFAULT_N_RANKS,
    DEFAULT_N_FIELDS,
)

from ctt_analyzer import CTTAnalyzer


# ── ダミーデータ生成 ─────────────────────────────────────

def make_dummy_mark2_files(tmpdir, n_students=30, n_questions=15, skip_questions=4, seed=42):
    """
    export_r_analysis_kit 用のダミー Mark2形式 Excel ファイルを生成。
    test_ctt_integration.py と同じ形式。
    """
    rng = np.random.default_rng(seed)

    # テンプレート (answer_key.xlsx)
    template_rows = []
    for i in range(1, n_questions + 1):
        template_rows.append({
            "問題番号": i,
            "正答": rng.integers(1, 6),
            "配点": rng.choice([2, 3]),
            "観点": rng.choice([1, 2, 3]),
        })
    template_df = pd.DataFrame(template_rows)
    template_path = os.path.join(tmpdir, "answer_key.xlsx")
    template_df.to_excel(template_path, index=False)

    # Mark2結果 Excel
    total_cols = skip_questions + n_questions
    header_row = ["No", "File"] + [str(i) for i in range(1, total_cols + 1)]

    id_names = ["学年", "クラス", "出席番号（十の位）", "出席番号（一の位）"]
    name_row = [np.nan, np.nan] + id_names[:skip_questions] + [str(i) for i in range(1, n_questions + 1)]

    data_rows = []
    for s in range(n_students):
        row = [s + 1, f"page_{s+1:03d}.png"]
        row += [1, rng.integers(1, 4), s // 10, (s % 10) + 1][:skip_questions]
        for q in range(n_questions):
            row.append(int(rng.integers(1, 6)))
        data_rows.append(row)

    all_rows = [header_row, name_row] + data_rows
    result_df = pd.DataFrame(all_rows)
    result_path = os.path.join(tmpdir, "Mark2-Result.xlsx")
    result_df.to_excel(result_path, index=False, header=False)

    return template_path, result_path


def make_dummy_score_matrix(n_students=20, n_questions=10, seed=42):
    """0/1バイナリスコアマトリクスのダミー生成"""
    rng = np.random.default_rng(seed)
    data = rng.integers(0, 2, size=(n_students, n_questions))
    columns = [str(i + 1) for i in range(n_questions)]
    index = [f"student_{i+1:03d}" for i in range(n_students)]
    return pd.DataFrame(data, columns=columns, index=index)


# ── テスト ────────────────────────────────────────────


class TestRExportConstants:
    """定数の整合性テスト"""

    def test_folder_name_numbering(self):
        """フォルダ名が006番台で他レポートとの番号体系が整合している"""
        assert R_EXPORT_FOLDER.startswith("006")

    def test_file_names_defined(self):
        """必要なファイル名定数がすべて定義されている"""
        assert R_DATA_CSV
        assert R_ITEM_INFO_CSV
        assert R_SCRIPT_FILE
        assert R_RMD_TEMPLATE_FILE

    def test_script_file_is_create_report(self):
        """Rスクリプトファイル名がcreate_report.Rである"""
        assert R_SCRIPT_FILE == "create_report.R"

    def test_default_n_ranks(self):
        """デフォルトランク数が妥当な範囲"""
        assert 2 <= DEFAULT_N_RANKS <= 10

    def test_default_n_fields(self):
        """デフォルトフィールド数が妥当な範囲"""
        assert 2 <= DEFAULT_N_FIELDS <= 10


class TestExportScoredData:
    """正誤データCSV出力のテスト"""

    def test_export_creates_csv(self, tmp_path):
        """CSVファイルが生成される"""
        score_matrix = make_dummy_score_matrix()
        output_path = tmp_path / "scored_data.csv"
        _export_scored_data(score_matrix, output_path)
        assert output_path.exists()

    def test_exported_csv_shape(self, tmp_path):
        """出力CSVの行数・列数がスコアマトリクスと一致する"""
        n_students, n_questions = 15, 8
        score_matrix = make_dummy_score_matrix(n_students, n_questions)
        output_path = tmp_path / "scored_data.csv"
        _export_scored_data(score_matrix, output_path)

        df = pd.read_csv(output_path, index_col=0)
        assert df.shape == (n_students, n_questions)

    def test_exported_csv_binary_only(self, tmp_path):
        """出力CSVの値が0/1のみ"""
        score_matrix = make_dummy_score_matrix()
        output_path = tmp_path / "scored_data.csv"
        _export_scored_data(score_matrix, output_path)

        df = pd.read_csv(output_path, index_col=0)
        unique_vals = set(df.values.flatten())
        assert unique_vals <= {0, 1}

    def test_exported_csv_encoding(self, tmp_path):
        """BOM付きUTF-8で読み込める"""
        score_matrix = make_dummy_score_matrix()
        output_path = tmp_path / "scored_data.csv"
        _export_scored_data(score_matrix, output_path)

        # BOM付きUTF-8で開けること
        with open(output_path, encoding="utf-8-sig") as f:
            content = f.read()
        assert len(content) > 0


class TestExportItemInfo:
    """設問情報CSV出力のテスト"""

    def test_export_creates_csv(self, tmp_path):
        """設問情報CSVが生成される"""
        score_matrix = make_dummy_score_matrix(n_questions=5)
        key_df = pd.DataFrame({
            "QuestionID": [str(i + 1) for i in range(5)],
            "Key": ["1", "2", "3", "4", "5"],
        })
        output_path = tmp_path / "item_info.csv"
        _export_item_info(score_matrix, key_df, output_path)
        assert output_path.exists()

    def test_item_info_columns(self, tmp_path):
        """設問情報CSVに必要な列がある"""
        score_matrix = make_dummy_score_matrix(n_questions=5)
        key_df = pd.DataFrame({
            "QuestionID": [str(i + 1) for i in range(5)],
            "Key": ["1", "2", "3", "4", "5"],
        })
        output_path = tmp_path / "item_info.csv"
        _export_item_info(score_matrix, key_df, output_path)

        df = pd.read_csv(output_path)
        assert "ItemID" in df.columns
        assert "MeanScore" in df.columns

    def test_item_info_row_count(self, tmp_path):
        """設問情報の行数が設問数と一致する"""
        n_q = 7
        score_matrix = make_dummy_score_matrix(n_questions=n_q)
        key_df = pd.DataFrame({
            "QuestionID": [str(i + 1) for i in range(n_q)],
            "Key": [str(i + 1) for i in range(n_q)],
        })
        output_path = tmp_path / "item_info.csv"
        _export_item_info(score_matrix, key_df, output_path)

        df = pd.read_csv(output_path)
        assert len(df) == n_q


class TestGenerateRScript:
    """Rスクリプト生成のテスト"""

    def test_script_created(self, tmp_path):
        """Rスクリプトファイルが生成される"""
        output_path = tmp_path / "test.R"
        _generate_r_script(output_path, 5)
        assert output_path.exists()

    def test_script_contains_exametrika(self, tmp_path):
        """Rスクリプトにexametrikaの記述がある"""
        output_path = tmp_path / "test.R"
        _generate_r_script(output_path, 5)

        content = output_path.read_text(encoding="utf-8")
        assert "exametrika" in content

    def test_script_contains_data_file_reference(self, tmp_path):
        """Rスクリプトがデータファイルを参照している"""
        output_path = tmp_path / "test.R"
        _generate_r_script(output_path, 5)

        content = output_path.read_text(encoding="utf-8")
        assert R_DATA_CSV in content
        assert R_ITEM_INFO_CSV in content

    def test_script_japanese_readable(self, tmp_path):
        """Rスクリプトの日本語がリテラル文字列で読める（Unicode escapeでない）"""
        output_path = tmp_path / "test.R"
        _generate_r_script(output_path, 5)

        content = output_path.read_text(encoding="utf-8")
        # Unicode escape が含まれていないこと
        assert "\\u30" not in content
        assert "\\u5" not in content
        # リテラル日本語が含まれていること
        assert "エラー" in content
        assert "レポート" in content

    def test_script_no_unnecessary_packages(self, tmp_path):
        """不要なパッケージの参照がないこと（openxlsxは推奨パッケージなので許可）"""
        output_path = tmp_path / "test.R"
        _generate_r_script(output_path, 5)

        content = output_path.read_text(encoding="utf-8")
        assert "tidyverse" not in content
        assert "psych" not in content
        assert "biclust" not in content
        assert "pheatmap" not in content
        assert "kableExtra" not in content
        # openxlsx は推奨パッケージとしてコメント・チェックに含まれるのは正常
        assert "openxlsx" in content

    def test_script_generates_html(self, tmp_path):
        """RスクリプトがHTML出力を生成する（PDF/LaTeX不要）"""
        output_path = tmp_path / "test.R"
        _generate_r_script(output_path, 5)

        content = output_path.read_text(encoding="utf-8")
        assert "html" in content.lower()
        assert "xelatex" not in content.lower()


class TestGenerateRmdTemplate:
    """RMarkdownテンプレート生成のテスト"""

    def test_rmd_created(self, tmp_path):
        """Rmdファイルが生成される"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 3, "テスト", "Author")
        assert output_path.exists()

    def test_rmd_contains_title(self, tmp_path):
        """Rmdにタイトルが含まれる"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 3, "期末試験レポート", "Tester")

        content = output_path.read_text(encoding="utf-8")
        assert "期末試験レポート" in content

    def test_rmd_contains_ctt(self, tmp_path):
        """RmdにCTT分析セクションがある"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 3, "テスト", "Author")

        content = output_path.read_text(encoding="utf-8")
        assert "CTT" in content

    def test_rmd_contains_irt(self, tmp_path):
        """RmdにIRT分析セクションがある"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 3, "テスト", "Author")

        content = output_path.read_text(encoding="utf-8")
        assert "IRT" in content

    def test_rmd_contains_lra(self, tmp_path):
        """RmdにLRA分析セクションがある"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 3, "テスト", "Author")

        content = output_path.read_text(encoding="utf-8")
        assert "LRA" in content

    def test_rmd_contains_biclustering(self, tmp_path):
        """Rmdにバイクラスタリング分析セクションがある"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 3, "テスト", "Author")

        content = output_path.read_text(encoding="utf-8")
        assert "Biclustering" in content
        assert "Ranklustering" in content or "ランクラスタリング" in content

    def test_rmd_uses_html_output(self, tmp_path):
        """RmdがHTML出力を使用する（xelatex不要）"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 3, "テスト", "Author")

        content = output_path.read_text(encoding="utf-8")
        assert "html_document" in content
        assert "xelatex" not in content

    def test_rmd_only_exametrika(self, tmp_path):
        """Rmdがexametrikaのみを使用する（不要パッケージなし）"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 3, "テスト", "Author")

        content = output_path.read_text(encoding="utf-8")
        assert "library(exametrika)" in content
        assert "tidyverse" not in content
        assert "psych" not in content
        assert "library(biclust)" not in content
        assert "pheatmap" not in content

    def test_rmd_n_fields_parameter(self, tmp_path):
        """Rmdにフィールド数パラメータが反映される"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 5, 4, "テスト", "Author")

        content = output_path.read_text(encoding="utf-8")
        assert "nfld = 4" in content

    def test_rmd_n_ranks_parameter(self, tmp_path):
        """Rmdにランク数パラメータが反映される"""
        output_path = tmp_path / "test.Rmd"
        _generate_rmd_template(output_path, 7, 3, "テスト", "Author")

        content = output_path.read_text(encoding="utf-8")
        assert "nrank = 7" in content


def make_dummy_descriptive_data(n_students=20, n_questions=5, seed=42):
    """記述式のみモード用のダミー descriptive_config / descriptive_scores を生成"""
    rng = np.random.default_rng(seed)
    questions = [
        {"id": f"D{i+1}", "name": f"設問{i+1}", "max_score": 5, "aspect": 1}
        for i in range(n_questions)
    ]
    config = {"questions": questions}
    scores = {}
    for s in range(n_students):
        fname = f"student_{s+1:03d}.jpg"
        scores[fname] = {q["id"]: int(rng.integers(0, 6)) for q in questions}
    return config, scores


class TestExportRAnalysisKit:
    """統合エクスポート関数のテスト（記述式のみモード）"""

    def test_full_export_success(self, tmp_path):
        """記述式データからR分析キットがエクスポートできる"""
        config, scores = make_dummy_descriptive_data()
        output_folder = tmp_path / "output"
        output_folder.mkdir()

        result = export_r_analysis_kit(
            str(output_folder), descriptive_config=config, descriptive_scores=scores,
        )

        assert result["success"] is True
        assert result["error"] is None

    def test_full_export_creates_all_files(self, tmp_path):
        """必要な全ファイルが生成される"""
        config, scores = make_dummy_descriptive_data()
        output_folder = tmp_path / "output"
        output_folder.mkdir()

        export_r_analysis_kit(
            str(output_folder), descriptive_config=config, descriptive_scores=scores,
        )

        kit_folder = output_folder / R_EXPORT_FOLDER
        assert (kit_folder / R_DATA_CSV).exists()
        assert (kit_folder / R_ITEM_INFO_CSV).exists()
        assert (kit_folder / R_SCRIPT_FILE).exists()
        assert (kit_folder / R_RMD_TEMPLATE_FILE).exists()

    def test_export_with_custom_ranks(self, tmp_path):
        """カスタムランク数がRmdテンプレートに反映される"""
        config, scores = make_dummy_descriptive_data()
        output_folder = tmp_path / "output"
        output_folder.mkdir()

        export_r_analysis_kit(
            str(output_folder), n_ranks=3,
            descriptive_config=config, descriptive_scores=scores,
        )

        kit_folder = output_folder / R_EXPORT_FOLDER
        rmd_content = (kit_folder / R_RMD_TEMPLATE_FILE).read_text(encoding="utf-8")
        assert "nrank = 3" in rmd_content


class TestConstantsIntegration:
    """constants.pyとの統合テスト"""

    def test_r_export_folder_in_constants(self):
        """R_EXPORT_FOLDERがconstants.pyに定義されている"""
        from constants import R_EXPORT_FOLDER as const_folder
        assert const_folder == R_EXPORT_FOLDER

    def test_r_export_folder_matches_module(self):
        """r_export.pyとconstants.pyのフォルダ名が一致する"""
        from constants import R_EXPORT_FOLDER as const_folder
        from r_export import R_EXPORT_FOLDER as mod_folder
        assert const_folder == mod_folder
