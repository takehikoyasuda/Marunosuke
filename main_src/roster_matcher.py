#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_matcher.py — 学籍番号OCR候補と名簿の確率的な照合。

digit_ocr_recognizer.LocalDigitOcrRecognizer.recognize() が返す桁ごとの確率分布
(DigitOcrCandidate.per_digit_proba)を使い、「1位候補の文字列がそのまま名簿に
完全一致するか」だけでなく、名簿の学籍番号それぞれについて「OCRがその番号を
読み取った尤もらしさ」を桁ごとの確率の積で見積もり、最も尤もらしい候補を提示する。

手書き数字OCRは1桁だけ誤読することが珍しくない(実測で8桁中1桁程度の誤りが多い)。
1位候補の文字が誤読でも、正解の文字に僅差の2位・3位程度の確率が乗っていることが
多いため、名簿という「あり得る学籍番号の有限集合」を手がかりに、桁ごとの確率分布
から逆算して候補を絞り込める。
"""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# per_digit_proba に無い文字(モデルの分類対象クラスに無い、または空欄で分布自体が
# 空dictの桁)に与える下限確率。0にすると1桁でも分布に無い文字を含む学籍番号の
# スコアが常に0になり、他候補との相対比較ができなくなるため、ごく小さい値で
# フロアを設ける。
FLOOR_PROBABILITY = 1e-4


def rank_roster_candidates(
    per_digit_proba: List[Dict[str, float]],
    roster: Dict[str, str],
    top_k: int = 3,
) -> List[Tuple[str, str, float]]:
    """名簿の学籍番号を、OCRの桁ごと確率分布との一致度でランキングする。

    桁数が一致する名簿の各学籍番号について、その番号の各桁の文字がOCRの確率分布
    上でどれだけ確からしいかの積をスコアとする。1位候補の文字列(argmax)を単純に
    連結した文字列と違い、「2位候補だが他の桁は高確信度」のような組み合わせも
    拾える。

    Args:
        per_digit_proba: DigitOcrCandidate.per_digit_proba
            (桁ごとの{文字: 確信度}の全クラス分布)。空リストなら空を返す。
        roster: {学籍番号: 氏名}の名簿。
        top_k: 返す候補の最大件数。

    Returns:
        (学籍番号, 氏名, 相対確率0-100) のリスト。スコアが高い順。
        桁数が一致する名簿エントリが無い場合、per_digit_proba や roster が
        空の場合は空リスト。

        相対確率は「桁数が一致する名簿エントリの中での相対的な尤もらしさ」を
        100分率で正規化したものであり、正解が名簿に含まれない場合や、桁数の
        異なる誤記入がある場合には意味を持たない参考値である点に注意。
        あくまで教員の確認作業を高速化するための目安であり、最終確認は必須。
    """
    if not per_digit_proba or not roster:
        return []

    digit_count = len(per_digit_proba)
    scored: List[Tuple[str, str, float]] = []

    for student_id, name in roster.items():
        if len(student_id) != digit_count:
            continue
        score = 1.0
        for pos, ch in enumerate(student_id):
            score *= per_digit_proba[pos].get(ch, FLOOR_PROBABILITY)
        scored.append((student_id, name, score))

    if not scored:
        return []

    total = sum(score for _, _, score in scored)
    if total <= 0:
        return []

    scored.sort(key=lambda entry: entry[2], reverse=True)
    return [
        (student_id, name, 100.0 * score / total)
        for student_id, name, score in scored[:top_k]
    ]
