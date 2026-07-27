#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_name_trimmer.py — name_trimmer モジュール + generate_student_summary 氏名画像拡張テスト

テスト内容:
    Part 1: name_trimmer モジュール単体テスト
        1. モジュールインポート・クラスインスタンス化
        2. get_image_files() のファイル取得
        3. trim_images() の一括トリミング（ダミー画像）
        4. trim_images() のリサイズ動作
        5. trim_images() のクランプ動作（座標が画像外にはみ出す場合）
        6. trim_images() の空フォルダ対応
        7. NameTrimmer の cleanup 動作

    Part 2: generate_student_summary の name_images 拡張テスト
        8. name_images=None で従来通りの動作（回帰テスト）
        9. name_images 付きで氏名欄列が追加されること
        10. 氏名欄列に画像が埋め込まれていること
        11. freeze_panes の変化（C3 → D3）
        12. 列構成の正確性
"""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

# main_src をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "main_src"))

from PIL import Image


class TestNameTrimmerImport(unittest.TestCase):
    """モジュールのインポートとクラスインスタンス化テスト"""

    def test_01_import_module(self):
        """name_trimmer モジュールがインポートできること"""
        import name_trimmer
        self.assertTrue(hasattr(name_trimmer, 'select_region_on_image'))
        self.assertTrue(hasattr(name_trimmer, 'trim_images'))
        self.assertTrue(hasattr(name_trimmer, 'NameTrimmer'))
        self.assertTrue(hasattr(name_trimmer, 'get_image_files'))

    def test_02_instantiate_name_trimmer(self):
        """NameTrimmer クラスがインスタンス化できること"""
        from name_trimmer import NameTrimmer
        trimmer = NameTrimmer()
        self.assertIsNone(trimmer.last_trim_rect)
        self.assertIsNone(trimmer._temp_dir)

    def test_03_constants_defined(self):
        """定数が正しく定義されていること"""
        from name_trimmer import (
            IMAGE_EXTENSIONS, DEFAULT_MAX_HEIGHT,
            MAX_DISPLAY_WIDTH, MAX_DISPLAY_HEIGHT
        )
        self.assertIn('.jpg', IMAGE_EXTENSIONS)
        self.assertIn('.png', IMAGE_EXTENSIONS)
        self.assertEqual(DEFAULT_MAX_HEIGHT, 50)
        self.assertEqual(MAX_DISPLAY_WIDTH, 700)
        self.assertEqual(MAX_DISPLAY_HEIGHT, 700)


class TestGetImageFiles(unittest.TestCase):
    """get_image_files() のテスト"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_img_files_")
        # ダミー画像ファイルを作成
        for name in ["a.jpg", "b.png", "c.txt", "d.jpeg", "e.bmp"]:
            filepath = Path(self.test_dir) / name
            if name.endswith('.txt'):
                filepath.write_text("not an image")
            else:
                img = Image.new('RGB', (10, 10), color='red')
                img.save(str(filepath))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_returns_only_images(self):
        """画像ファイルのみを返すこと"""
        from name_trimmer import get_image_files
        files = get_image_files(self.test_dir)
        filenames = [Path(f).name for f in files]
        self.assertIn("a.jpg", filenames)
        self.assertIn("b.png", filenames)
        self.assertIn("d.jpeg", filenames)
        self.assertIn("e.bmp", filenames)
        self.assertNotIn("c.txt", filenames)

    def test_02_returns_sorted(self):
        """ソート済みで返すこと"""
        from name_trimmer import get_image_files
        files = get_image_files(self.test_dir)
        filenames = [Path(f).name for f in files]
        self.assertEqual(filenames, sorted(filenames))

    def test_03_empty_folder(self):
        """空フォルダの場合、空リストを返すこと"""
        from name_trimmer import get_image_files
        empty_dir = tempfile.mkdtemp(prefix="test_empty_")
        try:
            files = get_image_files(empty_dir)
            self.assertEqual(files, [])
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    def test_04_nonexistent_folder(self):
        """存在しないフォルダの場合、空リストを返すこと"""
        from name_trimmer import get_image_files
        files = get_image_files("/nonexistent/path")
        self.assertEqual(files, [])


class TestTrimImages(unittest.TestCase):
    """trim_images() のテスト"""

    def setUp(self):
        self.input_dir = tempfile.mkdtemp(prefix="test_trim_input_")
        self.output_dir = tempfile.mkdtemp(prefix="test_trim_output_")
        # 100x200 のダミー画像を3枚作成
        for i in range(3):
            img = Image.new('RGB', (100, 200), color=(i * 80, 100, 50))
            img.save(str(Path(self.input_dir) / f"test_{i:03d}.jpg"))

    def tearDown(self):
        shutil.rmtree(self.input_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_01_basic_trim(self):
        """基本的なトリミングが正しく動作すること"""
        from name_trimmer import trim_images
        # 画像の左上 (10,20) から (80,60) の領域をトリミング
        saved = trim_images(self.input_dir, (10, 20, 80, 60), self.output_dir, max_height=200)
        self.assertEqual(len(saved), 3)
        # トリミング後の画像サイズを確認
        for f in saved:
            img = Image.open(f)
            self.assertEqual(img.size, (70, 40))  # 80-10=70, 60-20=40
            img.close()

    def test_02_trim_with_resize(self):
        """max_heightを超える場合にリサイズされること"""
        from name_trimmer import trim_images
        # 画像の (0,0)-(100,200) をトリミング → 高さ200px。max_height=50でリサイズ
        saved = trim_images(self.input_dir, (0, 0, 100, 200), self.output_dir, max_height=50)
        self.assertEqual(len(saved), 3)
        for f in saved:
            img = Image.open(f)
            self.assertEqual(img.height, 50)  # リサイズ後は50px
            # アスペクト比保持: 100/200 * 50 = 25
            self.assertEqual(img.width, 25)
            img.close()

    def test_03_trim_no_resize_when_within_limit(self):
        """max_height以下の場合はリサイズされないこと"""
        from name_trimmer import trim_images
        # (10,20)-(80,50) → 高さ30px。max_height=50なのでリサイズ不要
        saved = trim_images(self.input_dir, (10, 20, 80, 50), self.output_dir, max_height=50)
        self.assertEqual(len(saved), 3)
        for f in saved:
            img = Image.open(f)
            self.assertEqual(img.size, (70, 30))
            img.close()

    def test_04_clamp_coordinates(self):
        """座標が画像範囲外にはみ出す場合にクランプされること"""
        from name_trimmer import trim_images
        # 画像は100x200。座標(-10, -20, 150, 250) → (0,0,100,200)にクランプ
        saved = trim_images(self.input_dir, (-10, -20, 150, 250), self.output_dir, max_height=200)
        self.assertEqual(len(saved), 3)
        for f in saved:
            img = Image.open(f)
            self.assertEqual(img.size, (100, 200))
            img.close()

    def test_05_empty_input_folder(self):
        """空フォルダの場合は空リストを返すこと"""
        from name_trimmer import trim_images
        empty_dir = tempfile.mkdtemp(prefix="test_empty_input_")
        try:
            saved = trim_images(empty_dir, (0, 0, 50, 50), self.output_dir)
            self.assertEqual(saved, [])
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    def test_06_output_folder_recreated(self):
        """出力フォルダが既存の場合、クリアして再作成されること"""
        from name_trimmer import trim_images
        # 先に出力先に適当なファイルを置く
        dummy_file = Path(self.output_dir) / "dummy.txt"
        dummy_file.write_text("should be removed")
        self.assertTrue(dummy_file.exists())

        saved = trim_images(self.input_dir, (10, 20, 80, 60), self.output_dir)
        self.assertEqual(len(saved), 3)
        # dummy.txt は消えているべき
        self.assertFalse(dummy_file.exists())

    def test_07_filenames_preserved(self):
        """トリミング後のファイル名が元画像と同じであること"""
        from name_trimmer import trim_images
        saved = trim_images(self.input_dir, (10, 20, 80, 60), self.output_dir)
        saved_names = sorted([Path(f).name for f in saved])
        expected_names = sorted(["test_000.jpg", "test_001.jpg", "test_002.jpg"])
        self.assertEqual(saved_names, expected_names)


class TestNameTrimmerCleanup(unittest.TestCase):
    """NameTrimmer.cleanup() のテスト"""

    def test_01_cleanup_removes_temp_dir(self):
        """cleanup() で一時ディレクトリが削除されること"""
        from name_trimmer import NameTrimmer
        trimmer = NameTrimmer()
        temp_dir = tempfile.mkdtemp(prefix="test_cleanup_")
        trimmer._temp_dir = temp_dir
        self.assertTrue(Path(temp_dir).exists())

        trimmer.cleanup()
        self.assertFalse(Path(temp_dir).exists())
        self.assertIsNone(trimmer._temp_dir)

    def test_02_cleanup_when_no_temp(self):
        """一時ディレクトリ未設定時に cleanup() がエラーにならないこと"""
        from name_trimmer import NameTrimmer
        trimmer = NameTrimmer()
        # 例外が発生しないことを確認
        trimmer.cleanup()
        self.assertIsNone(trimmer._temp_dir)


class TestTrimImagesHighresFallback(unittest.TestCase):
    """高解像度モードでマーカー検出に失敗した場合のフォールバックテスト"""

    def setUp(self):
        self.input_dir = tempfile.mkdtemp(prefix="test_trim_input_")
        self.orig_dir = tempfile.mkdtemp(prefix="test_trim_orig_")
        self.output_dir = tempfile.mkdtemp(prefix="test_trim_output_")
        # 100x200 のダミー画像を3枚作成 (input = 00_Processing相当)
        for i in range(3):
            img = Image.new('RGB', (100, 200), color=(i * 80, 100, 50))
            img.save(str(Path(self.input_dir) / f"test_{i:03d}.jpg"))
        # original_image_folder にも同名ファイルを配置 (マーカーなし画像)
        for i in range(3):
            img = Image.new('RGB', (400, 800), color=(i * 60, 80, 30))
            img.save(str(Path(self.orig_dir) / f"test_{i:03d}.jpg"))

    def tearDown(self):
        shutil.rmtree(self.input_dir, ignore_errors=True)
        shutil.rmtree(self.orig_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_fallback_when_marker_detection_fails(self):
        """マーカー検出失敗時にフォールバック(直接crop)で画像が生成されること"""
        from name_trimmer import trim_images
        # original_image_folder を指定 → 高解像度パスが使われるが、
        # ダミー画像にはマーカーがないため detect_corner_markers が失敗する。
        # フォールバックとして 00_Processing (input_dir) から直接cropされるべき。
        saved = trim_images(
            self.input_dir, (10, 20, 80, 60), self.output_dir,
            max_height=200, original_image_folder=self.orig_dir,
        )
        self.assertEqual(len(saved), 3, "マーカー検出失敗時もフォールバックで全画像処理されるべき")
        for f in saved:
            img = Image.open(f)
            # フォールバックは input_dir (100x200) からのcrop: 70x40
            self.assertEqual(img.size, (70, 40))
            img.close()

    def test_no_original_uses_direct_crop(self):
        """original_image_folder=None の場合は直接cropが使われること"""
        from name_trimmer import trim_images
        saved = trim_images(
            self.input_dir, (10, 20, 80, 60), self.output_dir,
            max_height=200, original_image_folder=None,
        )
        self.assertEqual(len(saved), 3)
        for f in saved:
            img = Image.open(f)
            self.assertEqual(img.size, (70, 40))
            img.close()


