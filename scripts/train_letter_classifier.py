#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_letter_classifier.py — EMNIST(letters split)で、軽量な英字(A〜Z)分類モデルを学習する。

このモデルは、答案から切り出した学籍番号の1マス分の画像のうち、教員が「英字マス」と
指定した位置(main_src/id_area_config.py の alpha_positions)だけを分類するために使う。
数字専用モデル(resources/digit_classifier.joblib)には一切手を入れない。学籍番号中の
英字がA〜Zのどれになるか事前には分からない(位置は固定・文字種は不明)という前提のため、
26クラス全てを学習する。

データセットの取得元について:
    本来 sklearn.datasets.fetch_openml で EMNIST を取得する構想だったが、実行時点で
    OpenMLのAPI(www.openml.org)がゲートウェイタイムアウトを返し続け利用できなかった。
    そのため、NIST公式配布のEMNIST(idx-ubyte形式、gzip.zip)を直接ダウンロードして
    パースする方式に変更した。データセットは https://biometrics.nist.gov/cs_links/EMNIST/gzip.zip
    (約560MB、letters以外の全split込み)で配布されており、本スクリプトは letters split
    のみを抽出して使う。

EMNISTのidx-ubyte画像は、MNISTと異なり行列が転置された状態で格納されている既知の
仕様上の癖があるため、読み込み後に転置(transpose)して向きを補正する。学習前に
コンタクトシート画像を出力するので、必ず目視で文字が正しい向きで読めるか確認すること。

前処理について:
    EMNIST(letters)はMNISTと同じ変換パイプライン(文字のbounding boxを20x20に正規化し、
    重心を28x28キャンバス中心に置く)でNISTが作成済みのため、生のピクセル値をそのまま
    [0,1]に正規化するだけでよい(main_src/digit_ocr_recognizer.py が推論時に使う
    digit_ocr_preprocessing.preprocess_digit_image() は、実際の答案の生画像をこの
    MNIST/EMNIST形式に変換するためのものであり、EMNIST自体に対しては不要)。
    数字モデルの学習(~/Developer/grading-app/grading_app/scripts/train_digit_classifier.py)
    でもMNISTの生ピクセルをそのまま使っており、同じ方針に揃えている。
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import struct
import time
import zipfile
from pathlib import Path

import joblib
import numpy as np
from PIL import Image
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier

EMNIST_ZIP_URL = "https://biometrics.nist.gov/cs_links/EMNIST/gzip.zip"
MODEL_PATH = Path(__file__).resolve().parent.parent / "resources" / "letter_classifier.joblib"

# EMNIST letters mapping: ラベル1〜26 → 'A'〜'Z' (大文字・小文字は同一クラスにマージ済み)
LABEL_TO_LETTER = {i: chr(ord("A") + i - 1) for i in range(1, 27)}

# 紛らわしい文字ペア（混同行列で個別に確認する）
CONFUSABLE_PAIRS = [("O", "Q"), ("I", "L"), ("U", "V"), ("M", "N"), ("G", "Q")]


def _read_idx_images(path: Path) -> np.ndarray:
    """idx3-ubyte形式の画像ファイルを読み込み、(N, 28, 28) のuint8配列を返す。"""
    with open(path, "rb") as f:
        magic, num, rows, cols = struct.unpack(">IIII", f.read(16))
        if magic != 0x00000803:
            raise ValueError(f"idx3ファイルのマジックナンバーが不正です: {path} (magic={magic:#x})")
        data = np.frombuffer(f.read(), dtype=np.uint8)
    return data.reshape(num, rows, cols)


def _read_idx_labels(path: Path) -> np.ndarray:
    """idx1-ubyte形式のラベルファイルを読み込み、(N,) のuint8配列を返す。"""
    with open(path, "rb") as f:
        magic, num = struct.unpack(">II", f.read(8))
        if magic != 0x00000801:
            raise ValueError(f"idx1ファイルのマジックナンバーが不正です: {path} (magic={magic:#x})")
        data = np.frombuffer(f.read(), dtype=np.uint8)
    return data


def _fix_emnist_orientation(images: np.ndarray) -> np.ndarray:
    """EMNISTのidx-ubyte画像は行列が転置された状態で格納されているため補正する。"""
    return np.transpose(images, (0, 2, 1))


def download_and_extract_letters(cache_dir: Path) -> dict:
    """EMNISTのzipをダウンロード・展開し、letters splitのidx-ubyteパスを返す。

    キャッシュ済みなら再ダウンロードしない。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "gzip.zip"
    extract_dir = cache_dir / "gzip"

    letters_files = [
        "emnist-letters-train-images-idx3-ubyte",
        "emnist-letters-train-labels-idx1-ubyte",
        "emnist-letters-test-images-idx3-ubyte",
        "emnist-letters-test-labels-idx1-ubyte",
    ]
    result = {name: extract_dir / name for name in letters_files}
    if all(p.exists() for p in result.values()):
        print("EMNIST(letters)は既にキャッシュ済みです。ダウンロードをスキップします。")
        return result

    if not zip_path.exists():
        print(f"EMNISTデータセットをダウンロード中(約560MB): {EMNIST_ZIP_URL}")
        import urllib.request

        t0 = time.time()
        urllib.request.urlretrieve(EMNIST_ZIP_URL, zip_path)
        print(f"ダウンロード完了({time.time() - t0:.1f}秒)")

    print("letters splitのみ展開中...")
    with zipfile.ZipFile(zip_path) as zf:
        members = [
            f"gzip/{name}.gz" for name in letters_files
        ] + ["gzip/emnist-letters-mapping.txt"]
        zf.extractall(cache_dir, members=members)

    for name in letters_files:
        gz_path = extract_dir / f"{name}.gz"
        out_path = extract_dir / name
        if not out_path.exists():
            with gzip.open(gz_path, "rb") as f_in, open(out_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    return result


def save_contact_sheet(images: np.ndarray, labels: np.ndarray, output_path: Path, per_class: int = 3) -> None:
    """クラスごとに数枚ずつ並べたコンタクトシート画像を保存する(向き確認用)。"""
    classes = sorted(set(labels.tolist()))
    cell = 32
    cols = per_class
    rows = len(classes)
    sheet = Image.new("L", (cell * cols, cell * rows), color=255)
    for row, cls in enumerate(classes):
        idxs = np.where(labels == cls)[0][:per_class]
        for col, idx in enumerate(idxs):
            tile = Image.fromarray(images[idx]).resize((cell - 4, cell - 4))
            sheet.paste(tile, (col * cell + 2, row * cell + 2))
    sheet.save(output_path)
    print(f"コンタクトシートを保存しました(向きを目視確認してください): {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--cache-dir", type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "_emnist_cache",
        help="EMNISTのダウンロード・展開先キャッシュディレクトリ",
    )
    parser.add_argument(
        "--skip-confirm", action="store_true",
        help="コンタクトシート確認のための一時停止をスキップする(CI等での自動実行用)",
    )
    args = parser.parse_args()

    paths = download_and_extract_letters(args.cache_dir)

    print("画像・ラベルを読み込み中...")
    train_images_raw = _read_idx_images(paths["emnist-letters-train-images-idx3-ubyte"])
    train_labels_raw = _read_idx_labels(paths["emnist-letters-train-labels-idx1-ubyte"])
    test_images_raw = _read_idx_images(paths["emnist-letters-test-images-idx3-ubyte"])
    test_labels_raw = _read_idx_labels(paths["emnist-letters-test-labels-idx1-ubyte"])

    train_images = _fix_emnist_orientation(train_images_raw)
    test_images = _fix_emnist_orientation(test_images_raw)

    train_letters = np.array([LABEL_TO_LETTER[int(v)] for v in train_labels_raw])
    test_letters = np.array([LABEL_TO_LETTER[int(v)] for v in test_labels_raw])

    contact_sheet_path = args.cache_dir / "contact_sheet.png"
    save_contact_sheet(train_images, train_letters, contact_sheet_path)
    if not args.skip_confirm:
        input("コンタクトシートを確認してください(文字が正しい向きで読めるか)。問題なければEnterキーで学習を続行: ")

    X_train = train_images.reshape(len(train_images), -1).astype("float32") / 255.0
    X_test = test_images.reshape(len(test_images), -1).astype("float32") / 255.0
    y_train = train_letters
    y_test = test_letters

    print(f"学習データ: {X_train.shape[0]}件, テストデータ: {X_test.shape[0]}件, クラス数: {len(set(y_train))}")

    clf = MLPClassifier(
        hidden_layer_sizes=(128, 64),
        activation="relu",
        alpha=1e-4,
        max_iter=30,
        random_state=42,
        early_stopping=True,
        n_iter_no_change=5,
    )

    t0 = time.time()
    clf.fit(X_train, y_train)
    print(f"学習時間: {time.time() - t0:.1f}秒")
    print(f"classes_: {list(clf.classes_)}")

    pred = clf.predict(X_test)
    acc = accuracy_score(y_test, pred)
    print(f"\nテストデータでの精度: {acc * 100:.2f}%")
    print(classification_report(y_test, pred, digits=3))

    print("紛らわしい文字ペアの混同行列:")
    labels_sorted = sorted(set(y_test.tolist()))
    cm = confusion_matrix(y_test, pred, labels=labels_sorted)
    idx_of = {c: i for i, c in enumerate(labels_sorted)}
    for a, b in CONFUSABLE_PAIRS:
        if a not in idx_of or b not in idx_of:
            continue
        ia, ib = idx_of[a], idx_of[b]
        print(
            f"  {a}→{a}:{cm[ia, ia]:4d}  {a}→{b}:{cm[ia, ib]:4d}   "
            f"{b}→{b}:{cm[ib, ib]:4d}  {b}→{a}:{cm[ib, ia]:4d}"
        )

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, MODEL_PATH)
    print(f"\nモデルを保存しました: {MODEL_PATH}")


if __name__ == "__main__":
    main()
