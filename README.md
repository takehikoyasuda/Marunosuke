<p align="center">
  <img src="resources/samurai.png" alt="採点侍ロゴ" width="160">
</p>

<h1 align="center">採点侍 — SaitenSamurai (Mac版)</h1>

<p align="center">
  <strong>記述式の採点を、これ1本で。</strong><br>
  教員による教員のための、macOS 向け無料採点支援ソフトウェアです。
</p>

<p align="center">
  <a href="https://phys-ken.github.io/SaitenSamurai/">
    <img src="https://img.shields.io/badge/%E3%83%89%E3%82%AD%E3%83%A5%E3%83%A1%E3%83%B3%E3%83%88-Windows%E7%89%88-F5921B?style=for-the-badge" alt="ドキュメント (Windows版)">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/github/license/takehikoyasuda/SaitenSamurai-mac?style=for-the-badge&color=gray" alt="License">
  </a>
</p>

> [!WARNING]
> **本フォークは開発初期段階です**
> 現時点では起動して基本的な操作ができることを確認した段階であり、すべての機能・異常系を隅々まで検証したわけではありません。成績処理など実際の業務にお使いになる場合は、必ずご自身の目で結果を確認してください。
>
> また、README・コード内コメントなどに、移植元（Windows 版）の説明がそのまま残っている箇所がある可能性があります。実際の挙動と記載内容が食い違う場合はお知らせいただけると助かります。
>
> 本フォークの開発には Anthropic の Claude（Claude Code）を活用しています。

> **本リポジトリについて**
> 本ソフトウェアは、phys-ken 氏が開発・公開している Windows 向け採点支援ソフト **[採点侍 SaitenSamurai](https://github.com/phys-ken/SaitenSamurai)**（GPL-3.0）を fork し、macOS 上で動作するように移植したものです。日本語フォントの扱い・ファイル/フォルダを開く処理・パス解決などをクロスプラットフォーム対応させています。
>
> 本フォークでは開発方針の見直しにより、**マークシート採点機能を廃止し、記述式採点に特化**しています。マークシート採点も含めて利用したい場合は、フォーク元の Windows 版をご利用ください。

---

## :book: ドキュメント

本フォークでは Mac 専用のドキュメントサイトは公開していません（Mac 版の変更を追いかけて逐一更新するのが大変なため）。使い方や画面の考え方は、フォーク元（**Windows 版**）のドキュメントサイトの「記述式採点」に関する部分をご覧ください。

> [!NOTE]
> フォーク元のドキュメントは「マーク採点」「マーク＋記述」モードも解説していますが、本フォークにはそれらの機能はありません。記述式採点に関する記述のみが対象です。

### **:point_right: [https://phys-ken.github.io/SaitenSamurai/](https://phys-ken.github.io/SaitenSamurai/)**（Windows 版の説明です）

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

### 対応する採点モード

現在は **記述式採点のみ** に対応しています。スキャンした答案画像があれば、Mark2 座標ファイルなどの事前準備なしに採点を始められます。

### 主な特徴

- **記述式採点** — マウスで採点領域を設定、○×ボタンや数字キーで効率的に採点
- **学籍番号OCR（実験的機能）** — 学籍番号欄を自動認識し、名簿と照合
- **CTT 分析** — α 係数・P 値・D 値・I-T 相関を自動算出、PDF レポート出力
- **Excel 一括出力** — 生徒別成績サマリー・試験統計を自動生成
- **R 連携エクスポート** — exametrika 等による項目反応理論分析用のデータキットを出力
- **セッション保存** — 作業途中の状態を保存・復元
- **PDF 入力対応** — スキャン PDF をそのまま読み込み、画像に展開
- **クロスプラットフォーム対応** — macOS の日本語フォント・ファイル操作に対応

### 動作環境

| 項目 | 要件 |
|---|---|
| **OS** | **macOS**（Apple Silicon / Intel、動作確認中） |
| **Python** | 3.9 以上、かつ **Tkinter（Tcl/Tk）が有効なビルド** |
| **実行方法** | Python 3.9 以上のソースから実行（単体アプリの配布は未対応） |

> [!IMPORTANT]
> pyenv などで Python をソースビルドした環境では、ビルド時に Tcl/Tk が見つからず `_tkinter` モジュールが無効なままインストールされることがあります。その場合 `python main_src/saitensamurai.py` は次のようなエラーで起動に失敗します。
>
> ```
> ModuleNotFoundError: No module named '_tkinter'
> ```
>
> **pyenv を使っている場合、`brew install tcl-tk` してから `pyenv install -f` でビルドし直しても直らないことがあります**（2025年時点の Homebrew 版 tcl-tk は 9.0 系だが、pyenv 付属のビルドスクリプトがこの新しいライブラリ名に対応しておらず `_tkinter` が組み込まれないまま失敗する既知の不具合があるため）。その場合は pyenv を諦め、下記の「ソースから実行」の手順どおり **Homebrew 版 Python**（`python3.11`/`python3.12` など、`brew install python@3.12` で入るもの）と `brew install python-tk@3.12`（使う Python のバージョンに合わせる）を使って仮想環境を作ってください。`python3 -c "import tkinter"` がエラーなく通ることを事前に確認してください。

---

## クイックスタート

詳しい使い方は **[ドキュメントサイト（Windows 版）](https://phys-ken.github.io/SaitenSamurai/)** をご覧ください（「記述式採点」の解説部分のみ対象です）。

### ソースから実行

```bash
git clone https://github.com/takehikoyasuda/SaitenSamurai-mac.git
cd SaitenSamurai-mac

# Tkinter が有効な Python であることを確認（エラーが出たら下の「補足」を参照）
python3 -c "import tkinter"

# 仮想環境を作成して依存パッケージをインストール
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 起動
python main_src/saitensamurai.py
```

2 回目以降に起動する際も、`source .venv/bin/activate` で仮想環境を有効化してから `python main_src/saitensamurai.py` を実行してください。

#### 補足: macOSでTkinterが使えない場合（pyenv環境など）

`python3 -c "import tkinter"` が `ModuleNotFoundError: No module named '_tkinter'` で失敗する場合、上の手順の `python3` を **Homebrew版Python** に置き換えてください（pyenv版Pythonの再ビルドでは直らないことが多いため）。

```bash
brew install python@3.12 python-tk@3.12   # 使うバージョンに合わせて@3.12を変える

# .venv作成時、pyenv/system の python3 ではなく Homebrew の python3.12 を明示的に指定する
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main_src/saitensamurai.py
```

`python3` コマンド自体を毎回打つのが面倒な場合は、`~/.zshrc` に以下を追記すると通常の `python3` コマンドがこの仮想環境を指すようになります（他のプロジェクトでpyenvのバージョン切り替えを使う場合は該当行を一時的にコメントアウトしてください）。

```bash
alias python3="$HOME/.venvs/<venvの場所>/bin/python3"
```

より詳しい原因（pyenv付属ビルドスクリプトのTcl/Tk 9.0未対応の既知の不具合）は [DEVELOPMENT.md](DEVELOPMENT.md) を参照してください。

---

## 開発者向け

開発環境のセットアップ、モジュール構成、テストの実行方法については [DEVELOPMENT.md](DEVELOPMENT.md) をご覧ください。

---

## ライセンス

**GPL-3.0** — 詳細は [LICENSE](LICENSE) を参照してください。

本プロジェクトは、phys-ken 氏による「採点侍 SaitenSamurai」を基にした派生版です。
原作と派生版の権利関係、変更版である旨の表示、および謝辞は
**[CREDITS.md](CREDITS.md)** に記載しています。

サードパーティライブラリのライセンスは
[THIRDPARTYLICENSES.md](THIRDPARTYLICENSES.md) に記載しています。

---

## クレジット

- **[phys-ken/SaitenSamurai](https://github.com/phys-ken/SaitenSamurai)** — phys-ken 氏（GPL-3.0）。本派生版のオリジナル作品
- 詳細な権利表示、派生版である旨、および謝辞は **[CREDITS.md](CREDITS.md)** を参照してください。

---

<p align="center">
  <sub>オリジナル開発: <a href="https://phys-ken.github.io/phys-ken/">phys-ken</a> ／ Mac 対応: <a href="https://github.com/takehikoyasuda">Takehiko Yasuda</a></sub>
</p>
