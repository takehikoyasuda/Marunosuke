"""
summary_generator.py - サマリー生成モジュール

記述式採点結果をもとに、学生別得点サマリー(記述式のみモード)を
Excelファイルとして生成する。観点別・設問別の統計を出力する。
"""

from pathlib import Path
import logging
import re
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XlImage

from constants import (
    combine_images_to_pdf,
    RESULTS_FOLDER,
    SCORED_FOLDER,
    FINAL_REPORT_FOLDER,
    STUDENT_SUMMARY_FILE,
    EXAM_SUMMARY_FILE,
    CTT_ANALYSIS_EXCEL_FILE,
    CTT_ANALYSIS_PDF_FILE,
    SCORED_PDF_FILE,
    R_EXPORT_FOLDER,
    escape_excel_formula,
    get_excel_font_family,
)


def _natural_sort_key(text: str):
    """Windows Explorer 互換の自然順ソートキー

    文字列内の数値部分を int に変換し、非数値部分は小文字化して比較する。
    例: 'page2.jpg' < 'page10.jpg' (辞書順だと逆になる)
    """
    return [int(c) if c.isdigit() else c.lower()
            for c in re.split(r'(\d+)', text)]


def process_descriptive_only_summary(
    image_folder,
    descriptive_config,
    descriptive_scores,
    name_images=None,
    student_id_result=None,
    output_base_folder=None,
):
    """記述のみモードのサマリー生成。

    マーク採点結果なしで、記述採点データだけから
    学生別サマリーと試験統計を生成する。

    Args:
        image_folder: 画像フォルダパス
        descriptive_config: descriptive_config dict
        descriptive_scores: {filename: {question_id: score}}
        name_images: {filename: trimmed_image_path}
        student_id_result: {filename: {'thumbnail_path','text','name'}}
            （学籍番号OCR＋人間確認済みのデータ）
        output_base_folder: 出力先 (None→image_folder)

    Returns:
        {'success': bool, 'stats': dict, ...} or {'success': False, 'error': str}
    """
    image_folder = Path(image_folder)
    if output_base_folder is None:
        output_base_folder = image_folder
    else:
        output_base_folder = Path(output_base_folder)

    results_folder = output_base_folder / RESULTS_FOLDER
    final_report = results_folder / FINAL_REPORT_FOLDER
    final_report.mkdir(parents=True, exist_ok=True)

    student_summary_path = final_report / STUDENT_SUMMARY_FILE
    exam_summary_path = final_report / EXAM_SUMMARY_FILE

    questions = descriptive_config.get("questions", [])
    if not questions:
        return {"success": False, "error": "記述問題が設定されていません"}

    logger.info("=" * 60)
    logger.info("サマリー生成（記述のみモード）")
    logger.info("=" * 60)
    logger.info("✓ 記述問題: %d問", len(questions))
    logger.info("✓ 対象画像: %d件", len(descriptive_scores))
    if name_images:
        logger.info("✓ 氏名欄画像: %d枚", len(name_images))
    has_student_id_result = student_id_result is not None and len(student_id_result) > 0
    has_roster_names = has_student_id_result and any(v.get('name') for v in student_id_result.values())
    if has_student_id_result:
        logger.info("✓ 学籍番号OCR確認済み: %d枚", len(student_id_result))
    logger.info("")

    try:
        # --- 学生別サマリー ---
        wb_student = Workbook()
        ws = wb_student.active
        ws.title = "学生別サマリー"

        # ヘッダースタイル
        header_font = Font(bold=True, size=11)
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font_white = Font(bold=True, size=11, color="FFFFFF")
        center = Alignment(horizontal="center", vertical="center")
        thin_border = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )

        # ヘッダー構築
        headers = ["No.", "ファイル名"]
        if name_images:
            headers.append("氏名欄")
        if has_student_id_result:
            headers.append("学籍番号欄")
            headers.append("学籍番号(確認済み)")
            if has_roster_names:
                headers.append("氏名候補(名簿照合)")
        for q in questions:
            headers.append(f"{q['name']} ({q['max_score']})")
        headers.append("合計")
        full_score = sum(q["max_score"] for q in questions)
        headers.append(f"配点計 ({full_score})")

        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = header_font_white
            cell.fill = header_fill
            cell.alignment = center
            cell.border = thin_border

        # データ行
        sorted_files = sorted(descriptive_scores.keys())
        totals = []
        for row_idx, fname in enumerate(sorted_files, 2):
            scores_for_file = descriptive_scores.get(fname, {})
            col = 1
            ws.cell(row=row_idx, column=col, value=row_idx - 1).border = thin_border
            col += 1
            ws.cell(row=row_idx, column=col, value=escape_excel_formula(fname)).border = thin_border
            col += 1

            if name_images:
                name_path = name_images.get(fname)
                if name_path and Path(name_path).exists():
                    try:
                        img = XlImage(str(name_path))
                        img.width = 120
                        img.height = 30
                        ws.add_image(img, get_column_letter(col) + str(row_idx))
                    except Exception:
                        pass
                ws.cell(row=row_idx, column=col).border = thin_border
                col += 1

            if has_student_id_result:
                sid_info = student_id_result.get(fname, {})
                sid_thumb = sid_info.get('thumbnail_path')
                if sid_thumb and Path(sid_thumb).exists():
                    try:
                        img = XlImage(str(sid_thumb))
                        img.width = 120
                        img.height = 30
                        ws.add_image(img, get_column_letter(col) + str(row_idx))
                    except Exception:
                        pass
                ws.cell(row=row_idx, column=col).border = thin_border
                col += 1

                ws.cell(row=row_idx, column=col, value=escape_excel_formula(sid_info.get('text') or '')).border = thin_border
                ws.cell(row=row_idx, column=col).alignment = center
                col += 1

                if has_roster_names:
                    ws.cell(row=row_idx, column=col, value=escape_excel_formula(sid_info.get('name') or '')).border = thin_border
                    ws.cell(row=row_idx, column=col).alignment = center
                    col += 1

            student_total = 0
            for q in questions:
                sc = scores_for_file.get(q["id"], 0)
                if sc is None:
                    sc = 0
                ws.cell(row=row_idx, column=col, value=sc).border = thin_border
                ws.cell(row=row_idx, column=col).alignment = center
                student_total += sc
                col += 1

            ws.cell(row=row_idx, column=col, value=student_total).border = thin_border
            ws.cell(row=row_idx, column=col).alignment = center
            ws.cell(row=row_idx, column=col).font = Font(bold=True)
            col += 1
            ws.cell(row=row_idx, column=col, value=full_score).border = thin_border
            ws.cell(row=row_idx, column=col).alignment = center
            totals.append(student_total)

        # 列幅調整
        ws.column_dimensions["A"].width = 6
        ws.column_dimensions["B"].width = 30
        img_col_idx = 3
        if name_images:
            ws.column_dimensions[get_column_letter(img_col_idx)].width = 18
            img_col_idx += 1
        if has_student_id_result:
            ws.column_dimensions[get_column_letter(img_col_idx)].width = 18
            img_col_idx += 1
            ws.column_dimensions[get_column_letter(img_col_idx)].width = 14
            img_col_idx += 1
            if has_roster_names:
                ws.column_dimensions[get_column_letter(img_col_idx)].width = 16
                img_col_idx += 1
        if name_images or has_student_id_result:
            ws.row_dimensions[1].height = 20
            for r in range(2, len(sorted_files) + 2):
                ws.row_dimensions[r].height = 25

        wb_student.save(str(student_summary_path))
        logger.info("✓ 学生別サマリー: %s", student_summary_path.name)

        # --- 試験統計 ---
        totals_arr = np.array(totals) if totals else np.array([0])
        exam_stats = {
            "受験者数": len(totals),
            "満点": full_score,
            "平均点": float(np.mean(totals_arr)) if totals else 0.0,
            "標準偏差": float(np.std(totals_arr, ddof=1)) if len(totals) > 1 else 0.0,
            "最高点": int(np.max(totals_arr)) if totals else 0,
            "最低点": int(np.min(totals_arr)) if totals else 0,
        }

        wb_exam = Workbook()
        ws_exam = wb_exam.active
        ws_exam.title = "試験統計"
        stat_items = [
            ("受験者数", exam_stats["受験者数"]),
            ("満点", exam_stats["満点"]),
            ("平均点", f"{exam_stats['平均点']:.2f}"),
            ("標準偏差", f"{exam_stats['標準偏差']:.2f}"),
            ("最高点", exam_stats["最高点"]),
            ("最低点", exam_stats["最低点"]),
        ]
        ws_exam.cell(row=1, column=1, value="項目").font = header_font
        ws_exam.cell(row=1, column=2, value="値").font = header_font
        for r, (k, v) in enumerate(stat_items, 2):
            ws_exam.cell(row=r, column=1, value=k)
            ws_exam.cell(row=r, column=2, value=v)
        ws_exam.column_dimensions["A"].width = 20
        ws_exam.column_dimensions["B"].width = 20

        # 設問別統計シート
        ws_q = wb_exam.create_sheet("設問別統計")
        q_headers = ["設問", "配点", "平均", "標準偏差", "最高", "最低", "正答率(%)"]
        for ci, h in enumerate(q_headers, 1):
            cell = ws_q.cell(row=1, column=ci, value=h)
            cell.font = header_font_white
            cell.fill = header_fill
            cell.alignment = center

        for qi, q in enumerate(questions, 2):
            qid = q["id"]
            q_scores = [
                descriptive_scores.get(f, {}).get(qid, 0) or 0
                for f in sorted_files
            ]
            q_arr = np.array(q_scores) if q_scores else np.array([0])
            ws_q.cell(row=qi, column=1, value=q["name"])
            ws_q.cell(row=qi, column=2, value=q["max_score"]).alignment = center
            ws_q.cell(row=qi, column=3, value=f"{np.mean(q_arr):.2f}").alignment = center
            sd = float(np.std(q_arr, ddof=1)) if len(q_scores) > 1 else 0.0
            ws_q.cell(row=qi, column=4, value=f"{sd:.2f}").alignment = center
            ws_q.cell(row=qi, column=5, value=int(np.max(q_arr))).alignment = center
            ws_q.cell(row=qi, column=6, value=int(np.min(q_arr))).alignment = center
            rate = float(np.mean(q_arr)) / q["max_score"] * 100 if q["max_score"] > 0 else 0.0
            ws_q.cell(row=qi, column=7, value=f"{rate:.1f}").alignment = center

        wb_exam.save(str(exam_summary_path))
        logger.info("✓ 試験統計: %s", exam_summary_path.name)

        # 統合PDF
        scored_folder = results_folder / SCORED_FOLDER
        scored_pdf_path = final_report / SCORED_PDF_FILE
        if scored_folder.exists():
            try:
                combine_images_to_pdf(scored_folder, scored_pdf_path)
                logger.info("✓ 統合PDF: %s", scored_pdf_path.name)
            except Exception as pdf_e:
                logger.warning("統合PDF生成エラー: %s", pdf_e)

        # CTT分析レポート生成（記述のみモード: マーク問題なし）
        ctt_excel_path = final_report / CTT_ANALYSIS_EXCEL_FILE
        ctt_pdf_path = final_report / CTT_ANALYSIS_PDF_FILE
        ctt_result = None
        try:
            from ctt_analyzer import generate_ctt_analysis
            ctt_result = generate_ctt_analysis(
                excel_output_path=ctt_excel_path,
                pdf_output_path=ctt_pdf_path,
                descriptive_config=descriptive_config,
                descriptive_scores=descriptive_scores,
            )
        except Exception as ctt_e:
            logger.warning("CTT分析レポート生成エラー: %s", ctt_e, exc_info=True)

        # R連携エクスポート（記述のみモード）
        r_export_result = None
        try:
            from r_export import export_r_analysis_kit
            r_export_result = export_r_analysis_kit(
                output_folder=final_report,
                descriptive_config=descriptive_config,
                descriptive_scores=descriptive_scores,
            )
        except Exception as r_e:
            logger.warning("R連携エクスポートエラー: %s", r_e, exc_info=True)

        logger.info("")
        logger.info("=" * 60)
        logger.info("サマリー生成完了（記述のみモード）")
        logger.info("=" * 60)
        logger.info("✓ 学生別サマリー: %s", student_summary_path.name)
        logger.info("✓ 試験統計: %s", exam_summary_path.name)
        if ctt_result and ctt_result.get('success'):
            logger.info("✓ CTT分析Excel: %s", ctt_excel_path.name)
            if ctt_result.get('pdf_success'):
                logger.info("✓ CTT分析PDF: %s", ctt_pdf_path.name)
        if r_export_result and r_export_result.get('success'):
            logger.info("✓ R分析キット: %s/", R_EXPORT_FOLDER)

        result = {
            "success": True,
            "student_summary_path": str(student_summary_path),
            "exam_summary_path": str(exam_summary_path),
            "stats": exam_stats,
        }
        if ctt_result and ctt_result.get('success'):
            result['ctt_excel_path'] = str(ctt_excel_path)
            if ctt_result.get('pdf_success'):
                result['ctt_pdf_path'] = str(ctt_pdf_path)
        if r_export_result and r_export_result.get('success'):
            result['r_export_dir'] = r_export_result['output_dir']
        return result

    except Exception as e:
        logger.error("エラー: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


