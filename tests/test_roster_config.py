#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_roster_config.py — roster_config.py（名簿の永続化）のテスト。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))


class TestRosterConfigPersistence(unittest.TestCase):
    """load_roster_config() / save_roster_config() のテスト"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_roster_config_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_round_trip(self):
        from roster_config import load_roster_config, save_roster_config
        config_path = str(Path(self.test_dir) / "roster_config.json")
        roster = {"20230001": "山田太郎", "20230002": "佐藤花子"}
        save_roster_config(config_path, roster)
        loaded = load_roster_config(config_path)
        self.assertEqual(loaded, roster)

    def test_02_preserves_order(self):
        """挿入順(=名簿の並び順)が保存/読込を通じて保持されること"""
        from roster_config import load_roster_config, save_roster_config
        config_path = str(Path(self.test_dir) / "roster_config.json")
        roster = {"20230003": "鈴木一郎", "20230001": "山田太郎", "20230002": "佐藤花子"}
        save_roster_config(config_path, roster)
        loaded = load_roster_config(config_path)
        self.assertEqual(list(loaded.keys()), ["20230003", "20230001", "20230002"])

    def test_03_missing_file_returns_none(self):
        from roster_config import load_roster_config
        config_path = str(Path(self.test_dir) / "does_not_exist.json")
        self.assertIsNone(load_roster_config(config_path))

    def test_04_missing_required_key_returns_none(self):
        from roster_config import load_roster_config
        import json
        config_path = str(Path(self.test_dir) / "incomplete.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"not_roster": {}}, f)
        self.assertIsNone(load_roster_config(config_path))


if __name__ == '__main__':
    unittest.main()
