#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_config.py — Step1で読み込んだ名簿の永続化。

roster_loader.py(名簿の"取得"担当のGUI・各種フォーマットの読込)とは責務を
分離し、こちらは id_area_config.py と同じ「load/save + 存在チェック」の
パターンで {学籍番号: 氏名} を roster_config.json に保存/読込するだけを行う。
"""

from typing import Dict, Optional

from constants import atomic_json_save, load_json_safe

ROSTER_CONFIG_FILE = "roster_config.json"

REQUIRED_CONFIG_KEYS = ["roster"]


def load_roster_config(config_path: str) -> Optional[Dict[str, str]]:
    """roster_config.json を読み込む。ファイル不在や破損時は None。"""
    data = load_json_safe(config_path, required_keys=REQUIRED_CONFIG_KEYS)
    return data["roster"] if data else None


def save_roster_config(config_path: str, roster: Dict[str, str]) -> None:
    """roster_config.json をアトミックに保存する(名簿の並び順を保持)。"""
    atomic_json_save(config_path, {"roster": roster})
