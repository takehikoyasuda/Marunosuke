<p align="center">
  <img src="resources/marunosuke-logo.png" alt="マル之助ロゴ" width="180">
</p>

<h1 align="center">マル之助 — Marunosuke</h1>

<p align="center">
  macOS 向けの記述式採点支援ソフトウェアです。
</p>

<p align="center">
  <a href="LICENSE">
    <img src="https://img.shields.io/github/license/takehikoyasuda/Marunosuke?style=for-the-badge&color=gray" alt="License">
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
> マル之助は、phys-ken 氏が開発・公開している Windows 向け採点支援ソフト **[採点侍 SaitenSamurai](https://github.com/phys-ken/SaitenSamurai)**（GPL-3.0）を基に、macOS 向けの派生版として開発しています。日本語フォントの扱い・ファイル/フォルダを開く処理・パス解決などを macOS 向けに書き換えています。
>
> マル之助は、**マークシート採点機能を廃止し、記述式採点に特化**しています。マークシート採点も含めて利用したい場合は、オリジナルの Windows 版をご利用ください。権利表示と詳しい由来は [CREDITS.md](CREDITS.md) を参照してください。

---

## 概要

### Mac対応について

マル之助では、以下のような macOS 向けの対応を行っています。

- 日本語 UI フォント（Hiragino Sans）・出力用フォント（ヒラギノ角ゴシック）への切り替え
- ファイル・フォルダを Finder（`open` コマンド）で開く処理への対応
- Windows/Mac 間の tkinter フォントサイズ差の補正
- Excel 出力での日本語フォント切り替え

### 成り立ち

マル之助は「採点侍 SaitenSamurai」のコードと成果を受け継ぎながら、独立した名称で開発する派生ソフトウェアです。オリジナル版と、その設計に影響を与えた先行ソフトウェアへの謝辞は [CREDITS.md](CREDITS.md) に記載しています。

---

### 対応する採点モード

現在は **記述式採点のみ** に対応しています。スキャンした答案画像があれば、Mark2 座標ファイルなどの事前準備なしに採点を始められます。

### 主な特徴

- **記述式採点** — マウスで採点領域を設定、○×ボタンや数字キーで効率的に採点
- **学籍番号OCR（実験的機能）** — 学籍番号欄を自動認識し、名簿と照合
- **Excel 一括出力** — 生徒別成績サマリー・試験統計を自動生成
- **セッション保存** — 作業途中の状態を保存・復元
- **採点補助** — 採点基準メモ、教員用メモ、メモ履歴、生徒コメント、採点保留
- **答案レビュー** — 設問ごとの画像一覧／テキスト一覧、未採点・保留フィルタ、注釈編集
- **解答例表示** — 解答例画像の登録、答案からの切り抜き、採点画面内プレビュー
- **PDF 入力対応** — スキャン PDF をそのまま読み込み、画像に展開
- **macOS 対応** — 日本語 UI フォント・ファイル操作を macOS 向けに最適化

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

詳しい使い方は、下記の「[使い方](#使い方)」をご覧ください。

### ソースから実行

```bash
git clone https://github.com/takehikoyasuda/Marunosuke.git
cd Marunosuke

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

## 使い方

> [!NOTE]
> マル之助はオリジナル版（Windows 版・採点侍 SaitenSamurai）から画面構成・操作方法を大きく変更しています。使い方はこのセクションで説明する内容が最新です。

トップ画面には、番号付きのステップが上から順に並んでいます。基本的にはこの順番で進めます。

### 0. 案件設定（この案件で最初に1回だけ）

1. **作業スペース選択** — 採点対象の画像または PDF が入ったフォルダを選びます。
2. **答案のページ数** を入力して **確定** します。1人の学生が複数ページにまたがる答案を提出する運用（例: 大問ごとに配布したページを回収する場合）では、2以上の値を設定します。

### 1. 答案ファイル追加＆採点準備

このボタンを押すと、必要な初期設定が順番に案内されます（既に設定済みの項目は自動でスキップされます）。

- 名簿の読込（任意。試験全体で1箇所のみ保存されます）
- 別ページの答案が紛れ込んでいないかのOCR確認（任意）
- 氏名欄の位置指定
- 学籍番号をOCRで読み取るかどうかの選択（**実験的機能**）。有効にする場合、ここで学籍番号欄の位置を1回だけ指定します。実際のOCR実行と確認は、後述する「集計」のタイミングで行います
- 採点領域（解答欄）と設問情報（配点など）の設定

複数ページの答案を扱う場合は、次のページに進むときも、もう一度「答案ファイルを追加＆採点準備」から始めてください（ページ数分繰り返します）。学籍番号欄・氏名欄・解答欄の設定は、レイアウトが共通なページ同士であれば使い回せます。

### 2. 採点実行

設問ごとに採点用のウィンドウが開きます。表示モードは2種類から選べます。

- **1枚ずつモード** — 1人分の答案を大きく表示して採点します。「〇 正解（満点）」「× 不正解（0点）」「⏸ 保留して次へ」ボタン、キーボードの 0〜9 キーでの得点入力（配点10点以上の設問は数値入力欄＋Enterキー）、部分点ボタン（配点9点以下）が使えます。表示フィルタ（全件／未採点／保留）とズームで、必要な答案だけを効率よく確認できます。
- **一覧（グリッド）モード** — 全員分のサムネイルを並べて表示し、クリックで得点を直接変更します。1枚ずつモードと同じフィルタ・ズームが使えます。

採点後は「🔎 採点確認」から、設問ごとに全員分の回答を見直せる確認・修正専用の画面を開けます。「▶ 採点済み答案画像」では、採点結果を書き込んだ答案画像を生成できます。

### 3. 集計

「集計」ボタンを押すと、学籍番号OCRを有効にしている場合は、学籍番号欄のOCR結果を確認・修正する画面が開きます（名簿候補のランキング表示・自動採用、番号の重複や未提出者の警告つき）。確認が終わると、`03_Final_Report` フォルダに次のファイルが出力されます。

- **学生別サマリー**（`001_student_summary.xlsx`）— ファイル名・学籍番号・氏名・設問ごとの得点・合計点など
- **試験統計**（`002_exam_summary.xlsx`）— 受験者数・平均点・標準偏差などの全体統計と、設問別の統計
- 採点結果を書き込んだ答案画像がある場合は、それを束ねた統合PDF

複数ページの答案を扱っている場合は、各ページの集計結果を学籍番号をキーに1つへ統合した「結合サマリー」も生成できます。

### 作業の中断・再開

作業状態は主要な区切り（初期設定完了時・採点完了時など）で自動的に保存されます。次回、同じ作業フォルダを選択すると、続きから再開するかどうかを確認する画面が表示されます。

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
