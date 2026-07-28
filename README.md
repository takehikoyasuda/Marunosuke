<p align="center">
  <img src="resources/marunosuke-logo.png" alt="マル之助ロゴ" width="180">
</p>

<h1 align="center">マル之助 — Marunosuke</h1>

<p align="center">
  <strong>記述式の採点を、これ1本で。</strong><br>
  macOS 向けの記述式採点支援ソフトウェアです。
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
> **マル之助は開発初期段階です**
> 現時点では起動して基本的な操作ができることを確認した段階であり、すべての機能・異常系を隅々まで検証したわけではありません。成績処理など実際の業務にお使いになる場合は、必ずご自身の目で結果を確認してください。
>
> また、README・コード内コメントなどに、移植元（Windows 版）の説明がそのまま残っている箇所がある可能性があります。実際の挙動と記載内容が食い違う場合はお知らせいただけると助かります。
>
> マル之助の開発には生成AIを活用しています。

> **本リポジトリについて**
> マル之助は、phys-ken 氏が開発・公開している Windows 向け採点支援ソフト **[採点侍 SaitenSamurai](https://github.com/phys-ken/SaitenSamurai)**（GPL-3.0）を基に、macOS 向けの派生版として開発しています。日本語フォントの扱い・ファイル/フォルダを開く処理・パス解決などをクロスプラットフォーム対応させています。
>
> マル之助は、**マークシート採点機能を廃止し、記述式採点に特化**しています。マークシート採点も含めて利用したい場合は、オリジナルの Windows 版をご利用ください。権利表示と詳しい由来は [CREDITS.md](CREDITS.md) を参照してください。

---

## :book: ドキュメント

現在、マル之助専用のドキュメントサイトは公開していません。使い方や画面の基本的な考え方は、オリジナル版（**Windows 版**）のドキュメントサイトにある「記述式採点」の説明をご覧ください。

> [!NOTE]
> オリジナル版のドキュメントは「マーク採点」「マーク＋記述」モードも解説していますが、マル之助にはそれらの機能はありません。記述式採点に関する記述のみが対象です。また、画面や操作が異なる場合があります。

### **:point_right: [https://phys-ken.github.io/SaitenSamurai/](https://phys-ken.github.io/SaitenSamurai/)**（Windows 版の説明です）

---

## 概要

### Mac対応について

マル之助では、以下のような macOS 向けの対応を行っています。

- 日本語 UI フォント（Hiragino Sans）・出力用フォント（ヒラギノ角ゴシック）への切り替え
- ファイル・フォルダを Finder（`open` コマンド）で開く処理への対応
- Windows/Mac 間の tkinter フォントサイズ差の補正
- Excel 出力・matplotlib グラフでの日本語フォント自動検出

### 成り立ち

マル之助は「採点侍 SaitenSamurai」のコードと成果を受け継ぎながら、独立した名称で開発する派生ソフトウェアです。オリジナル版と、その設計に影響を与えた先行ソフトウェアへの謝辞は [CREDITS.md](CREDITS.md) に記載しています。

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
> pyenv などで Python をソースビルドした環境では、ビルド時に Tcl/Tk が見つからず `_tkinter` モジュールが無効なままインストールされることがあります。その場合 `python main_src/marunosuke.py` は次のようなエラーで起動に失敗します。
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
python main_src/marunosuke.py
```

2 回目以降に起動する際も、`source .venv/bin/activate` で仮想環境を有効化してから `python main_src/marunosuke.py` を実行してください。

#### 補足: macOSでTkinterが使えない場合（pyenv環境など）

`python3 -c "import tkinter"` が `ModuleNotFoundError: No module named '_tkinter'` で失敗する場合、上の手順の `python3` を **Homebrew版Python** に置き換えてください（pyenv版Pythonの再ビルドでは直らないことが多いため）。

```bash
brew install python@3.12 python-tk@3.12   # 使うバージョンに合わせて@3.12を変える

# .venv作成時、pyenv/system の python3 ではなく Homebrew の python3.12 を明示的に指定する
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main_src/marunosuke.py
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
  <sub>オリジナル開発: <a href="https://phys-ken.github.io/phys-ken/">phys-ken</a> ／ マル之助 開発: <a href="https://github.com/takehikoyasuda">Takehiko Yasuda</a></sub>
</p>
