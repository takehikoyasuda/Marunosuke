#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_loader.py — 学籍番号OCRの照合に使う名簿Excelの読み込み。

任意機能: 名簿を読み込まなくても学籍番号OCR自体は使える。
読み込む場合は列名「学籍番号」「氏名」を固定で要求する
(このアプリに動的な列マッピングUIの前例がないため、既存の
scoring_engine.load_template() と同じ「固定列名＋存在チェック」方式に合わせる)。
"""

from typing import Dict

import pandas as pd


def load_roster(excel_path: str) -> Dict[str, str]:
    """名簿Excelを読み込み、{学籍番号(str): 氏名} の辞書を返す。

    学籍番号は前後の空白を除去した文字列として扱う(ゼロ埋め等の表記ゆれの
    吸収は行わない、MVPのため単純な文字列一致に留める)。

    Args:
        excel_path: 名簿Excelファイルのパス

    Returns:
        {学籍番号: 氏名} の辞書

    Raises:
        ValueError: 必須列(学籍番号・氏名)が見つからない場合
    """
    df = pd.read_excel(excel_path)

    required_columns = ['学籍番号', '氏名']
    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"名簿に列'{col}'が見つかりません")

    roster: Dict[str, str] = {}
    for _, row in df.iterrows():
        student_id = str(row['学籍番号']).strip()
        name = str(row['氏名']).strip()
        if student_id and student_id.lower() != 'nan':
            roster[student_id] = name

    return roster
