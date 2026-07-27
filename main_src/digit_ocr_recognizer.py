#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
digit_ocr_recognizer.py — MNIST/EMNISTで学習した軽量モデルによる、学籍番号1桁ずつの
ローカルOCR認識。

外部への通信は一切行わない(モデルは resources/ 以下にローカル保存済み)。
認識結果はあくまで「候補」であり、人間が確認・修正することを前提とする。

数字マス用(resources/digit_classifier.joblib, MNISTで学習)と英字マス用
(resources/letter_classifier.joblib, EMNIST letters splitで学習)の2つのモデルを
使い分ける。どのマスが英字かは答案画像ごとに検出せず、教員があらかじめ位置を指定した
ものを recognize() の alpha_mask で渡す(main_src/id_area_config.py の
alpha_positions 参照)。数字マスと英字マスの分類器を分けているのは、1つの分類器に
数字・英字を混在させると視覚的に紛らわしい文字同士(0/O, 1/I, 5/S等)で誤分類が増え、
かつ既存の実績ある数字専用モデルにも手を入れることになるため。

元コード: ~/Developer/grading-app の app/student_id/ocr_recognizer.py を移植・簡略化。
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import joblib
import numpy as np

from constants import resource_path
from digit_ocr_preprocessing import preprocess_digit_image

logger = logging.getLogger(__name__)

MODEL_RELATIVE_PATH = "resources/digit_classifier.joblib"
LETTER_MODEL_RELATIVE_PATH = "resources/letter_classifier.joblib"


@dataclass
class DigitOcrCandidate:
    """学籍番号OCRの認識結果(候補)。"""
    value: Optional[str]  # 認識した数字列。1桁でも空欄・認識失敗ならNone
    confidence: float  # 平均確信度 (0.0-1.0)
    per_digit: List[Tuple[str, float]] = field(default_factory=list)  # 各桁の (文字, 確信度)


class LocalDigitOcrRecognizer:
    """学籍番号1桁ずつのローカルOCR認識(外部通信なし、モデルはresources/に同梱)。"""

    def __init__(self, model_path: Optional[str] = None, letter_model_path: Optional[str] = None):
        self._model_path = model_path or resource_path(MODEL_RELATIVE_PATH)
        self._letter_model_path = letter_model_path or resource_path(LETTER_MODEL_RELATIVE_PATH)
        self._model = None
        self._letter_model = None

    def _load_model(self):
        if self._model is None:
            try:
                self._model = joblib.load(self._model_path)
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"数字分類モデルが見つかりません: {self._model_path}\n"
                    "resources/digit_classifier.joblib が配置されているか確認してください。"
                )
        return self._model

    def _load_letter_model(self):
        if self._letter_model is None:
            try:
                self._letter_model = joblib.load(self._letter_model_path)
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"英字分類モデルが見つかりません: {self._letter_model_path}\n"
                    "resources/letter_classifier.joblib が配置されているか確認してください。"
                )
        return self._letter_model

    def recognize(
        self, digit_images: List[np.ndarray], alpha_mask: Optional[List[bool]] = None,
    ) -> DigitOcrCandidate:
        """1マスずつの画像リストを受け取り、学籍番号候補を返す。

        Args:
            digit_images: 1マスずつ切り出した画像のリスト。
            alpha_mask: digit_imagesと同じ長さのbool列。Trueの位置だけ英字分類器
                (resources/letter_classifier.joblib)を使い、それ以外(Noneの場合は
                全桁)は既存の数字分類器を使う。
        """
        if not digit_images:
            return DigitOcrCandidate(value=None, confidence=0.0, per_digit=[])

        if alpha_mask is not None and len(alpha_mask) != len(digit_images):
            raise ValueError("alpha_mask は digit_images と同じ長さである必要があります")

        digit_model = self._load_model()

        digits: List[str] = []
        confidences: List[float] = []
        per_digit: List[Tuple[str, float]] = []

        for i, image in enumerate(digit_images):
            is_alpha = bool(alpha_mask[i]) if alpha_mask is not None else False
            model = self._load_letter_model() if is_alpha else digit_model

            processed = preprocess_digit_image(image)
            if processed is None:
                digits.append("")
                confidences.append(0.0)
                per_digit.append(("", 0.0))
                continue

            proba = model.predict_proba(processed.reshape(1, -1))[0]
            top_idx = int(np.argmax(proba))
            label = str(model.classes_[top_idx])
            digits.append(label)
            confidences.append(float(proba[top_idx]))
            per_digit.append((label, float(proba[top_idx])))

        value = "".join(digits) if all(d != "" for d in digits) else None
        overall_confidence = float(np.mean(confidences)) if confidences else 0.0

        return DigitOcrCandidate(value=value, confidence=overall_confidence, per_digit=per_digit)
