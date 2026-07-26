#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
digit_ocr_recognizer.py — MNISTで学習した軽量モデルによる、学籍番号1桁ずつのローカルOCR認識。

外部への通信は一切行わない(モデルは resources/digit_classifier.joblib にローカル保存済み)。
認識結果はあくまで「候補」であり、人間が確認・修正することを前提とする。

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


@dataclass
class DigitOcrCandidate:
    """学籍番号OCRの認識結果(候補)。"""
    value: Optional[str]  # 認識した数字列。1桁でも空欄・認識失敗ならNone
    confidence: float  # 平均確信度 (0.0-1.0)
    per_digit: List[Tuple[str, float]] = field(default_factory=list)  # 各桁の (文字, 確信度)


class LocalDigitOcrRecognizer:
    """学籍番号1桁ずつのローカルOCR認識(外部通信なし、モデルはresources/に同梱)。"""

    def __init__(self, model_path: Optional[str] = None):
        self._model_path = model_path or resource_path(MODEL_RELATIVE_PATH)
        self._model = None

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

    def recognize(self, digit_images: List[np.ndarray]) -> DigitOcrCandidate:
        """1マスずつの画像リストを受け取り、学籍番号候補を返す。"""
        if not digit_images:
            return DigitOcrCandidate(value=None, confidence=0.0, per_digit=[])

        model = self._load_model()

        digits: List[str] = []
        confidences: List[float] = []
        per_digit: List[Tuple[str, float]] = []

        for image in digit_images:
            processed = preprocess_digit_image(image)
            if processed is None:
                digits.append("")
                confidences.append(0.0)
                per_digit.append(("", 0.0))
                continue

            proba = model.predict_proba(processed.reshape(1, -1))[0]
            top_idx = int(np.argmax(proba))
            digits.append(str(top_idx))
            confidences.append(float(proba[top_idx]))
            per_digit.append((str(top_idx), float(proba[top_idx])))

        value = "".join(digits) if all(d != "" for d in digits) else None
        overall_confidence = float(np.mean(confidences)) if confidences else 0.0

        return DigitOcrCandidate(value=value, confidence=overall_confidence, per_digit=per_digit)
