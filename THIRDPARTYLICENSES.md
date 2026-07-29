# サードパーティライセンス / Third-Party Licenses

マル之助 (Marunosuke) が利用している外部ライブラリ・プロジェクトのライセンス情報です。

---

## 上流プロジェクト

### Mark2 (Mark2OSS)

- **ライセンス**: MIT License
- **著作権**: Copyright (c) 慶應義塾大学 SFC 研究所 社会イノベーション・ラボ
- **URL**: https://mark2.sfc.keio.ac.jp/ja/
- **用途**: マークシート座標系 (595×842 pt)・OMR 認識ロジックの原典
- **備考**: 本プロジェクトは Mark2 の座標系およびマーク処理ロジックを基盤としています

### 採点斬り 2021

- **ライセンス**: GPL-3.0
- **著作権**: Copyright (c) phys-ken
- **URL**: https://phys-ken.github.io/saitenGiri2021/
- **用途**: 記述式採点のキーボード入力方式の設計参考

---

## コア依存パッケージ

### scikit-learn

- **ライセンス**: BSD 3-Clause License
- **著作権**: Copyright (c) 2007-2026 The scikit-learn developers
- **URL**: https://github.com/scikit-learn/scikit-learn
- **用途**: K-means クラスタリング（`KMeans`）、特徴量標準化（`StandardScaler`）、主成分分析（`PCA`）
- **バージョン**: 1.8.0

### OpenCV (opencv-python-headless)

- **ライセンス**: Apache License 2.0 (OpenCV 本体) / MIT License (Python ラッパー)
- **著作権**: Copyright (c) OpenCV team
- **URL**: https://github.com/opencv/opencv-python
- **用途**: 画像処理・OMR 認識・射影変換・二値化

### NumPy

- **ライセンス**: BSD 3-Clause License
- **著作権**: Copyright (c) 2005-2026, NumPy Developers
- **URL**: https://github.com/numpy/numpy
- **用途**: 数値計算・配列処理

### pandas

- **ライセンス**: BSD 3-Clause License
- **著作権**: Copyright (c) 2008-2011, AQR Capital Management LLC, Lambda Foundry, Inc. and PyData Development Team
- **URL**: https://github.com/pandas-dev/pandas
- **用途**: データフレーム操作・集計処理

### Pillow

- **ライセンス**: HPND (Historical Permission Notice and Disclaimer)
- **著作権**: Copyright (c) 2010-2026 Jeffrey A. Clark and contributors
- **URL**: https://github.com/python-pillow/Pillow
- **用途**: 画像読み込み・描画・Excel 画像埋め込み・フォントレンダリング

### openpyxl

- **ライセンス**: MIT License
- **著作権**: Copyright (c) 2010 openpyxl contributors
- **URL**: https://foss.heptapod.net/openpyxl/openpyxl
- **用途**: Excel ファイル生成・読み込み

---

## オプション依存パッケージ

### PyMuPDF (fitz)

- **ライセンス**: AGPL-3.0
- **著作権**: Copyright (c) Artifex Software, Inc.
- **URL**: https://github.com/pymupdf/PyMuPDF
- **用途**: PDF → 画像変換（PDF 入力機能）
- **⚠ 備考**: AGPL-3.0 ライセンスのため、本パッケージを組み込んだ成果物（exe 版を含む）は AGPL-3.0 の条件に従う必要があります。ソースコードの開示義務が生じます。

## 開発用ツール（配布物には含まれません）

### pytest

- **ライセンス**: MIT License
- **URL**: https://github.com/pytest-dev/pytest
- **用途**: テストフレームワーク

### pytest-timeout

- **ライセンス**: MIT License
- **URL**: https://github.com/pytest-dev/pytest-timeout
- **用途**: テストのタイムアウト制御

### pytest-cov

- **ライセンス**: MIT License
- **URL**: https://github.com/pytest-dev/pytest-cov
- **用途**: テストカバレッジ計測

---

## ライセンスの互換性について

本プロジェクトは **GPL-3.0** でライセンスされています。
上記のコア依存パッケージ（Apache-2.0, BSD, MIT, HPND）はすべて GPL-3.0 と互換性があります。

オプション依存の **PyMuPDF (AGPL-3.0)** を含む exe を配布する場合は、
AGPL-3.0 の条件（ネットワーク越しの利用者にもソースコードを提供する義務等）に
従う必要があります。本プロジェクトのソースコードは GitHub で公開されています。
