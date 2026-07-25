<p align="center">
  <img src="resources/samurai.png" alt="採点侍ロゴ" width="160">
</p>

<h1 align="center">採点侍 — SaitenSamurai (Mac版)</h1>

<p align="center">
  <strong>普通紙マークシート採点 ＆ 記述式採点を、これ1本で。</strong><br>
  教員による教員のための、macOS 向け無料採点支援ソフトウェアです。
</p>

<p align="center">
  <a href="https://takehikoyasuda.github.io/SaitenSamurai-mac/">
    <img src="https://img.shields.io/badge/%E3%83%89%E3%82%AD%E3%83%A5%E3%83%A1%E3%83%B3%E3%83%88-takehikoyasuda.github.io-F5921B?style=for-the-badge" alt="ドキュメント">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/github/license/takehikoyasuda/SaitenSamurai-mac?style=for-the-badge&color=gray" alt="License">
  </a>
</p>

> [!WARNING]
> **本フォークは開発初期段階です**
> 現時点では起動して基本的な操作ができることを確認した段階であり、すべての機能・異常系を隅々まで検証したわけではありません。成績処理など実際の業務にお使いになる場合は、必ずご自身の目で結果を確認してください。
>
> また、README・ドキュメントサイト・コード内コメントなどに、移植元（Windows 版）の説明がそのまま残っている箇所がある可能性があります。実際の挙動と記載内容が食い違う場合はお知らせいただけると助かります。
>
> 本フォークの開発には Anthropic の Claude（Claude Code）を活用しています。

> **本リポジトリについて**
> 本ソフトウェアは、phys-ken 氏が開発・公開している Windows 向け採点支援ソフト **[採点侍 SaitenSamurai](https://github.com/phys-ken/SaitenSamurai)**（GPL-3.0）を fork し、macOS 上で動作するように移植したものです。日本語フォントの扱い・ファイル/フォルダを開く処理・パス解決などをクロスプラットフォーム対応させています。採点ロジックや機能そのものはオリジナル版を踏襲しています。Windows でご利用の方はオリジナル版をご利用ください。

---

## :book: ドキュメント

使い方・FAQ・免責事項など、すべての情報は **ドキュメントサイト** にまとまっています（一部ページはオリジナル版 (Windows) の内容のままです）。

### **:point_right: [https://takehikoyasuda.github.io/SaitenSamurai-mac/](https://takehikoyasuda.github.io/SaitenSamurai-mac/)**

| ページ | 内容 |
|---|---|
| [クイックスタート](https://takehikoyasuda.github.io/SaitenSamurai-mac/quickstart/) | 5 分で最初の採点を体験 |
| [機能一覧](https://takehikoyasuda.github.io/SaitenSamurai-mac/features/) | すべての機能を一覧で確認 |
| [使い方ガイド](https://takehikoyasuda.github.io/SaitenSamurai-mac/usage/mark/) | 各採点モードの詳細な操作方法 |
| [よくある質問](https://takehikoyasuda.github.io/SaitenSamurai-mac/faq/) | トラブルシューティング |
| [免責事項](https://takehikoyasuda.github.io/SaitenSamurai-mac/disclaimer/) | 利用上の注意 |

---

## 概要

### Mac対応について

本フォークでは、以下のような macOS 向けの対応を行っています。

- 日本語 UI フォント（Hiragino Sans）・出力用フォント（ヒラギノ角ゴシック）への切り替え
- ファイル・フォルダを Finder（`open` コマンド）で開く処理への対応
- Windows/Mac 間の tkinter フォントサイズ差の補正
- Excel 出力・matplotlib グラフでの日本語フォント自動検出

### 採点斬りからの進化

本ソフトウェアは、開発者 (phys-ken) が 2021 年に公開した **[採点斬り 2021](https://phys-ken.github.io/saitenGiri2021/)** をベースに、UI の改善やコードの整理を行ったうえで大幅な機能強化を施したものです。

採点斬り 2021 は、竹内俊彦氏の「採点革命」や島守睦美氏の「採点斬り」に触発されて開発した、非公式のフリーソフトでした。当初は知人の間で使うだけのつもりでしたが、SNS 等で思いがけず多くの方に利用していただくことになりました。広く使っていただけたのは大変ありがたかったのですが、元の「採点斬り」の名前をそのまま使ってしまったことへの反省がありました。

こうした経緯を踏まえ、公開から時間が経ったことと機能の大幅な改善を機に、ソフト名を **「採点侍」** として改めました。

---

採点侍は、3 つの採点モードであらゆる試験形式に対応します。

| モード | 用途 | 必要なもの |
|---|---|---|
| **マーク採点** | マークシートのみ | スキャン画像 + Mark2 座標ファイル |
| **記述式採点** | 記述式のみ | スキャン画像のみ |
| **マーク＋記述** | 混在する試験 | スキャン画像 + Mark2 座標ファイル |

### 主な特徴

- **OMR 自動読み取り** — コーナーマーカー検出・傾き補正・閾値自動キャリブレーション
- **記述式採点** — マウスで採点領域を設定、○×ボタンや数字キーで効率的に採点
- **グリッド一覧モード** — 全生徒の解答を一覧表示で素早く処理
- **CTT 分析** — α 係数・P 値・D 値・I-T 相関を自動算出、PDF レポート出力
- **Excel 一括出力** — 生徒別成績サマリー・試験統計を自動生成
- **セッション保存** — 作業途中の状態を保存・復元
- **クロスプラットフォーム対応** — macOS の日本語フォント・ファイル操作に対応

### 動作環境

| 項目 | 要件 |
|---|---|
| **OS** | **macOS**（Apple Silicon / Intel、動作確認中） |
| **実行方法** | Python 3.9 以上のソースから実行（単体アプリの配布は未対応） |

---

## クイックスタート

詳しい使い方は **[ドキュメントサイト](https://takehikoyasuda.github.io/SaitenSamurai-mac/)** をご覧ください。

### ソースから実行

```bash
git clone https://github.com/takehikoyasuda/SaitenSamurai-mac.git
cd SaitenSamurai-mac
pip install -r requirements.txt
python main_src/saitensamurai.py
```

---

## 開発者向け

開発環境のセットアップ、モジュール構成、テストの実行方法については [開発ガイド](https://takehikoyasuda.github.io/SaitenSamurai-mac/development/) をご覧ください（[DEVELOPMENT.md](DEVELOPMENT.md) と同内容です）。

---

## ライセンス

**GPL-3.0** — 詳細は [LICENSE](LICENSE) を参照してください。

サードパーティライブラリのライセンスは [THIRDPARTYLICENSES.md](THIRDPARTYLICENSES.md) に記載しています。

---

## クレジット

- **[phys-ken/SaitenSamurai](https://github.com/phys-ken/SaitenSamurai)** — phys-ken 氏（GPL-3.0）— 本フォークの元になったオリジナル版（Windows 向け）
- **[Mark2](https://github.com/Mark2OSS/Mark2)** — 慶應義塾大学 SFC 研究所（MIT License）— 座標系・OMR 基盤
- **[採点斬り 2021](https://phys-ken.github.io/saitenGiri2021/)** — phys-ken（GPL-3.0）— 記述式採点の設計参考
- **採点斬り** — 島守睦美 氏 — デジタル採点のコンセプトの元祖
- **採点革命** — 竹内俊彦 氏 — デジタル採点の草分け
- **[デジタル採点 All in One](https://coding-tips-memoranda.com/%E3%83%87%E3%82%B8%E3%82%BF%E3%83%AB%E6%8E%A1%E7%82%B9-all-in-one/)** — 模範解答表示方法の参考

---

<p align="center">
  <sub>オリジナル開発: <a href="https://phys-ken.github.io/phys-ken/">phys-ken</a> ／ Mac 対応: <a href="https://github.com/takehikoyasuda">Takehiko Yasuda</a></sub>
</p>
