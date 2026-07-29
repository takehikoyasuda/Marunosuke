# 開発ガイド

マル之助 (Marunosuke) の開発に参加する方向けの技術情報です。

---

## 目次

- [開発環境のセットアップ](#開発環境のセットアップ)
- [リポジトリ構成](#リポジトリ構成)
- [モジュール依存関係](#モジュール依存関係)
- [採点モードのアーキテクチャ](#採点モードのアーキテクチャ)
- [テスト](#テスト)
- [Git 運用ガイド（初心者向け）](#git-運用ガイド初心者向け)
- [コーディング規約](#コーディング規約)
- [コミット禁止物](#コミット禁止物)
- [exe ビルド](#exe-ビルド)

---

## 開発環境のセットアップ

```bash
git clone https://github.com/takehikoyasuda/Marunosuke.git
cd Marunosuke
pip install -r requirements.txt
```

### アプリ名とバージョン

- 表示名は `main_src/constants.py` の `APP_NAME` / `APP_NAME_EN` で管理します。
- バージョンは同ファイルの `APP_VERSION` だけを更新します。
- バージョンは Semantic Versioning の `MAJOR.MINOR.PATCH` 形式を使用します。
- `0.x.y` は正式安定版前、`1.0.0` 以降は後方互換性を意識した安定版とします。
- 修正のみは PATCH、後方互換のある機能追加は MINOR、互換性を壊す変更は
  `1.0.0` 以降に MAJOR を上げます。
- GitHub のリリースタグには、バージョンの先頭に `v` を付けます
  （例：アプリバージョン `0.1.0`、タグ `v0.1.0`）。

### 型チェック

`pyrightconfig.json` で `main_src/` がインポートパスに設定されています。
Pylance / Pyright を使用する場合、追加設定は不要です。

```json
{
    "extraPaths": ["main_src"],
    "typeCheckingMode": "basic"
}
```

`basic` モードで型チェックを実施しています。error は 0 件を維持してください。
warning は段階的に解消中です。

### 起動確認

```bash
python main_src/marunosuke.py
```

起動すると、記述式採点専用のメイン画面が表示されます。

### macOSでの注意点: tkinter / Tcl-Tk

**症状1: `ModuleNotFoundError: No module named '_tkinter'`**

pyenvでビルドしたPythonは、ビルド時にHomebrewの`tcl-tk`が入っていないと`_tkinter`が同梱されないままインストールされてしまう。これはこのリポジトリ固有の問題ではなく、**pyenv環境自体の問題**なので、複数のMacを行き来している場合はマシンごとに同じ現象が起きる。

**`pyenv install -f`での再ビルドでは直らないことを確認済み**: 2025年時点のHomebrewの`tcl-tk`はバージョン9.0系で、ライブラリ名が`libtcl9tk9.0.dylib`のように変わっているが、pyenvの`python-build`スクリプトの自動検出ロジック（`use_homebrew_tcltk`/`use_custom_tcltk`関数、pyenv自身のコード内に`# FIXME: this function is a workaround for #1125`とある通り既知の脆さがある）がこの新しい命名規則・文字列処理にバグがあり、`--with-tcltk-libs`の指定をどう工夫しても`_tkinter`が正しくビルドされない（`PYTHON_BUILD_TCLTK_USE_PKGCONFIG=1`を使ったpkg-config経由の検出も同様に失敗した）。pyenv側の既知の不具合のため、直るまで通常のpyenv経由での運用は諦め、以下のHomebrew版Pythonを使う方法で回避する。

直し方（マシンごとに1回でよい）: Homebrew版Python + Tkで専用venvを作り、`python3`エイリアスで上書きする。

```bash
brew install tcl-tk python-tk@3.12   # 使うPythonのバージョンに合わせて python-tk@X.Y を選ぶ
python3.12 -m venv ~/.venvs/marunosuke-tk   # /opt/homebrew/bin/python3.12 を使うこと(pyenv経由のpython3.12ではない)
source ~/.venvs/marunosuke-tk/bin/activate
pip install -r requirements.txt
python -c "import tkinter; print(tkinter.Tk().tk.call('info','patchlevel'))"   # エラーが出ず、Tkのバージョンが表示されればOK
```

このプロジェクトで`python3`と打つたびに毎回`source .../activate`するのが面倒な場合は、`~/.zshrc`に以下を追記して`python3`コマンド自体をこのvenvに向けてしまうのが手軽（別プロジェクトでpyenvのバージョン切り替えを使う場合は一時的にコメントアウトすること）:

```bash
alias python3="$HOME/.venvs/marunosuke-tk/bin/python3"
```

**症状2: ボタンの枠線が消える・フラットに潰れて見える（Tk 8.5特有の描画バグ）**

Appleが`/Library/Developer/CommandLineTools/`等に同梱している古いTcl/Tk 8.5系は、macOS Big Sur以降でttkウィジェットの描画バグ（ボタンの枠線・背景色がネイティブ描画に反映されない等）を起こすことがある。上記の`brew install tcl-tk`でビルドしたPythonはTcl/Tk 9.0系にリンクされるため、この症状も併せて解消される。`python -c "import tkinter; r=tkinter.Tk(); print(r.tk.call('info','patchlevel'))"`で使用中のTcl/Tkバージョンを確認できる（8.6以上を推奨、8.5系は非推奨）。

**症状3: グリッド採点の得点ボタン等、`tk.Button`のクリック後に色が変化しない**

これはTcl/Tkのバージョンとは無関係の、macOS Aquaテーマ自体の仕様（`tk.Button`はネイティブ描画のため`bg`変更が反映されない）。アプリ側で`tk.Label`による自作ボタンに置き換えて対応済み（`main_src/descriptive_gui.py`のグリッド得点ボタン等）。新しくボタンに「選択状態」を持たせたい場合は、`tk.Button`の`bg`/`relief`変更に頼らず、この方式を踏襲すること。

---

## リポジトリ構成

```
├── main_src/                    # アプリケーション本体（16 モジュール）
│   ├── marunosuke.py            # 正式な起動エントリーポイント
│   ├── saitensamurai.py         # 後方互換 API・旧エントリーポイント
│   ├── constants.py             # 共通定数・ユーティリティ
│   ├── omr_engine.py            # OMR 認識エンジン
│   ├── threshold_calibrator.py  # 閾値自動推定
│   ├── scoring_engine.py        # 採点コアロジック
│   ├── image_renderer.py        # 採点結果の画像描画
│   ├── mark_checker.py          # エラー検出・修正補助
│   ├── descriptive_scorer.py    # 記述式採点コアロジック
│   ├── descriptive_gui.py       # 記述式採点 GUI
│   ├── descriptive_renderer.py  # 記述式採点描画
│   ├── name_trimmer.py          # 氏名トリミング
│   ├── summary_generator.py     # Excel サマリー生成
│   ├── ctt_analyzer.py          # CTT 分析
│   ├── r_export.py              # R 連携エクスポート
│   ├── gui_components.py        # サブウィンドウ GUI
│   └── main_gui.py              # メイン統合 GUI
├── tests/                       # pytest テスト（25 ファイル）
│   ├── conftest.py              # Tk ルート共有・パス設定
│   └── test_*.py
├── resources/                   # アプリリソース
│   ├── marunosuke-icon.png      # GUIウィンドウ用アイコン
│   ├── marunosuke-icon.ico      # Windows配布用アイコン
│   ├── marunosuke-icon.icns     # macOS配布用アイコン
│   └── marunosuke-logo.png      # README・広報用ロゴ
├── .github/workflows/test.yml   # GitHub Actions CI
├── marunosuke.spec              # PyInstaller 設定
├── build_exe.bat                # exe ビルドスクリプト
├── requirements.txt             # 依存パッケージ定義
├── pyrightconfig.json           # 型チェック設定（basic モード）
├── LICENSE                      # GPL-3.0
├── CREDITS.md                   # 原作・派生版の権利表示とクレジット
└── THIRDPARTYLICENSES.md        # サードパーティライセンス
```

---

## モジュール依存関係

`constants.py` が全モジュールの基盤で、循環 import を防止しています。

```
constants.py              ← 他モジュールに依存しない基盤
scoring_engine.py         ← (pandas のみ、他モジュール非依存)
    ↑
omr_engine.py             ← constants
threshold_calibrator.py   ← constants, omr_engine
mark_checker.py           ← constants, omr_engine
name_trimmer.py           ← constants
r_export.py               ← constants            [lazy: ctt_analyzer]
ctt_analyzer.py           ← constants, scoring_engine
image_renderer.py         ← constants, scoring_engine, omr_engine
                                                   [lazy: descriptive_scorer]
descriptive_scorer.py     ← constants, name_trimmer
descriptive_gui.py        ← constants, descriptive_scorer, name_trimmer
descriptive_renderer.py   ← constants, descriptive_scorer
summary_generator.py      ← constants, scoring_engine
                                                   [lazy: ctt_analyzer, r_export]
gui_components.py         ← constants, mark_checker, threshold_calibrator
                                                   [lazy: scoring_engine, omr_engine]
main_gui.py               ← 全モジュール
                                                   [lazy: descriptive_gui, name_trimmer]
marunosuke.py             ← saitensamurai（起動処理）
saitensamurai.py          ← main_gui（+ 後方互換 re-export）
```

> `[lazy: ...]` はメソッド内で遅延 import されるモジュールを示します。
> 循環 import の回避とオプショナル依存の制御に使用しています。

### 設計原則

- **constants.py** は他の `main_src/` モジュールを import してはならない
- **scoring_engine.py** は純粋ロジックのみ（ファイル I/O や画像処理に依存しない）
- **GUI 依存のない処理**は `*_engine.py` / `*_checker.py` 等に分離
- **遅延 import**: 循環回避やオプション機能の分離のため、多くのモジュールで `[lazy]` パターンを使用

---

## 画像パイプラインのアーキテクチャ

### 処理画像の生成 (`omr_engine.py`)

`process_box_drawer()` は各画像に対して以下の2種類の画像を生成します:

| フォルダ | 定数 | 内容 |
|---|---|---|
| `00_Processing/` | `BOXED_FOLDER` | マーク認識枠を描画した画像（マークチェック用） |
| `00_Processing_Clean/` | `CLEAN_FOLDER` | 射影変換のみ適用したクリーン画像（記述式採点プレビュー用） |

> **並列処理制約**: `_process_single_image()` は `ProcessPoolExecutor` で並列実行されます。
> 引数タプルのアンパック順序（現行 8 要素）を変更する場合、全ワーカーに影響するため注意してください。
> （後方互換のため 7 要素入力も受理する実装です）

### マークチェック正答オーバーレイ (`gui_components.py`)

`MarkCheckerGUI` は正答枠（赤色点線）をプレビュー画像に描画します。

**問題番号のオフセット**:

| 用途 | 問題番号 | 説明 |
|---|---|---|
| テンプレート参照 | `question_no` | skip 後の採点用番号（1始まり） |
| coordinates.csv 参照 | `question_no + skip_questions` | 元の問題番号（skip 込み） |

### OMR 値変換パイプライン

座標 Excel の row0 の値ヘッダ (`raw_choice`) をそのまま表示値として使用します。
`parse_excel_coordinates()` が row0 のヘッダセル（base_col=4,8,...）を読み取って
`raw_choice` に格納します（ヘッダ欠損時は列グループの出現順にフォールバック）。
標準テンプレート（ヘッダ 0〜9）ではヘッダ＝出現順のため従来と同一の値になりますが、
複数桁モードのテンプレート（ヘッダ -1〜13）ではヘッダ値が正となります。

```mermaid
flowchart TD
    %% Styles
    classDef data fill:#e1f5fe,stroke:#01579b,stroke-width:2px,color:#01579b,rx:5,ry:5;
    classDef process fill:#f3e5f5,stroke:#4a148c,stroke-width:2px,color:#4a148c,rx:5,ry:5;

    %% Nodes & Flow
    subgraph S1 ["1. 座標読み込み"]
        direction TB
        Excel[/"📊 座標Excel<br><small>列ヘッダ: 0-9 / raw_choice</small>"/]:::data
    end

    subgraph S2 ["2. parse_excel_coordinates()"]
        direction TB
        Sort["X座標ソート"]:::process
        Map["内部ID choice(0-N)へ変換<br><small>raw_choice を保持</small>"]:::process
        Sort --> Map
    end

    subgraph S3 ["3. recognize_marks()"]
        direction TB
        ROI["ROI判定"]:::process
        RecResult[/"📝 認識結果<br><small>{q: [choice]}</small>"/]:::data
        ROI --> RecResult
    end

    subgraph S4 ["4. save_recognition_results()"]
        direction TB
        Reverse["choice → raw_choice 逆引き"]:::process
        Final[/"💾 Excel出力<br><small>raw_choice を使用</small>"/]:::data
        Reverse --> Final
    end

    %% Edges
    Excel --> Sort
    Map --> ROI
    RecResult --> Reverse
```

### 描画位置の設計

○×マークのデフォルト描画位置は `question_coords[num_choices - 2]`（後ろから 2 番目の選択肢）です。
`rendering_settings['mark_result_offset']` でセル幅単位のオフセット調整が可能です。

---

## 採点モードのアーキテクチャ

現在は記述式採点専用のため、起動時のモード選択は行わず、
`MarunosukeGUI` のメイン画面を直接表示します。

### モード定数（`constants.py`）

```python
MODE_MARK_ONLY = "mark_only"
MODE_MARK_AND_DESCRIPTIVE = "mark_and_descriptive"
MODE_DESCRIPTIVE_ONLY = "descriptive_only"

# app_mode に直交するマーク形式フラグ（v4.7 複数桁設問モード）
MARK_FORMAT_STANDARD = "standard"
MARK_FORMAT_MULTI_DIGIT = "multi_digit"
```

### 起動フロー（`marunosuke.py`）

```
marunosuke.run() → saitensamurai.run() → main()
                 → Tk() → MarunosukeGUI(root) → mainloop()
```

### 複数桁設問モード（mark_format=multi_digit）

共通テスト数学式の紙面（各解答番号行に `-, 0〜9, a, b, c, d` の15マーク。
座標ファイルの値ヘッダは `-1, 0〜13`。配付物 M2-03-008 が対応テンプレート）向けのモードです。
トップ画面の「🔢 数学マーク採点のみ」「🔢✏ 数学マーク採点＋記述採点」から起動します。

- **answer_key.xlsx**: 問題番号列に範囲表記「1-3」を書くと、連続する3つのマーク行を
  1つの採点単位（グループ）に束ねます。正答は「-24」のような記号列（1文字=1行）。
  範囲長=正答文字数がバリデーションされます（先頭ゼロはセルを文字列書式で入力）。
  単独行は従来どおり「5」。列構成（問題番号/正答/配点/観点/特例/問題概要）は共通です。
- **自動割付**: 単独表記の行に複数文字の正答を書くと、正答の文字数ぶん連続行を
  自動消費します（問題番号「1」＋正答「-24」→ 1〜3行、group_label="1-3"）。
  範囲の手計算は不要です。各行の問題番号は固定なのでズレは起きず、消費先に
  別の登録があれば重複エラーになります。特例「全員正解」で正答空欄の複数行
  グループのみ範囲表記が必須です（消費行数を推論できないため）。
- **採点**: グループ全行の解答連結が正答と完全一致した場合のみ満点（完答）。
  無マーク・ダブルマークが1行でもあれば0点。0⇔10等価判定は**適用しません**
  （'1'+'0'→"10" が "0" に正規化される事故を防ぐため）。特例「全員正解」はグループ単位で有効。
- **値→位置解決**: `scoring_engine.choice_to_position_index(choice, num_choices, mark_format)`
  が唯一の入口。multi_digit では位置 = ヘッダ値+1（"-"=位置0、"d"=位置14）。
- **記号対応表**: `constants.MULTI_DIGIT_VALUE_TO_SYMBOL`（-1→"-"、10〜13→a〜d）。
  mark2結果Excelのセル・正答表記・描画はすべて記号側で統一。
- **データモデル**: `load_template` は先頭行intキーのまま `'span'`（消費行数）と
  `'group_label'`（"1-3"）を付与。グループ2行目以降のエントリは作られません。
- **CTT/R**: グループ=1項目（項目ID=範囲表記）。key_df の `ExactMatch` 列が True の項目は
  正答文字列との完全一致で0/1化されます（ctt_analyzer / r_export 共通）。
- **セッション**: `session_state.json` に `mark_format` を保存。
  形式が一致しないセッションの復元はエラーで中止されます。

### 正答チェックとMarkdown書き出し（`answer_key_checker.py`）

登録ミスの早期発見のため、answer_key を採点前に検証して Markdown 2ファイルを
書き出します（標準・複数桁の両モード対応）。

- **起動**: 正答データの選択/自動検出時に自動実行（要約をGUIログに表示）。
  正答データ行の「📋」ボタンでいつでも再実行できます。
- **出力先**: answer_key と同じフォルダに
  `<ファイル名>_check.md`（検証結果・行割当表・集計）と
  `<ファイル名>_模範解答.md`（問/解答番号/正答/配点/観点の配布用表。エラー時は
  書き出されない）。
- **チェック内容**: `load_template` のバリデーション（範囲重複・範囲長≠正答文字数・
  不正記号等）に加え、使用行の中抜け警告・未登録行（正答/配点空欄）警告・
  座標ファイルのマーク行数超過エラー（座標ファイル選択時）。
- 生成直後の空 answer_key（正答未入力）では自動チェックは案内メッセージのみを出します。
- API: `answer_key_checker.run_answer_key_check(template_path, mark_format, coord_excel_path, skip_questions)`

### モードごとの UI 差分

| UI 要素 | マーク採点 | マーク＋記述 | 記述採点 |
|---|:---:|:---:|:---:|
| 座標ファイル選択 | ○ | ○ | — |
| Skip 数設定 | ○ | ○ | — |
| OMR スライダー | ○ | ○ | — |
| 認識実行ボタン | ○ 認識実行 | ○ 認識実行 | ○ 画像準備 |
| 正答/OMR 結果選択 | ○ | ○ | — |
| 記述問題設定 | — | ○ | ○ |
| マークチェック | ○ | ○ | — |
| 採点ボタン | — | ○ | ○ |
| 採点の確認 | — | ○ | ○ |
| 描画詳細設定 (マーク) | ○ | ○ | — |
| 描画詳細設定 (記述) | — | ○ | ○ |

新しいモード固有 UI を追加する場合は `main_gui.py` 内で `self.app_mode` を参照して分岐してください。

### 採点のモード固定

採点は **問題一覧画面** でモードを選択してから開始します（`_scoring_mode_var`）。
前回選択したモードは `descriptive_config.json` に保存され、次回起動時に自動復元されます。
採点中はモード切替を表示せず、選択したモードで固定されます。
モードを変更したい場合は、採点を中断（自動保存）して問題一覧に戻り、再度選択してください。

採点の確認画面では、設問ごとの答案を画像一覧またはテキスト一覧で表示できます。
テキスト一覧では氏名、学籍番号、得点、保留、教員用メモ、生徒コメントを行単位で確認し、
注釈編集または採点画面への移動を行えます。氏名・学籍番号を取得できない場合は「未取得」と表示します。

---

## テスト

### テストの実行

```bash
# 標準的なテスト実行（推奨）
python -m pytest tests/ -q --timeout=60 -p no:warnings

# 特定のテストファイルのみ
python -m pytest tests/test_scoring_e2e.py -v --timeout=60

# 視覚回帰（実ウィンドウキャプチャ）を含める
python -m pytest tests/ -m "visual" -v --timeout=120

# 全テスト（通常 + visual）
python -m pytest tests/ -m "not legacy_mock" -v --timeout=120

# カバレッジ付き
python -m pytest tests/ -q --timeout=60 -p no:warnings --cov=main_src --cov-report=term-missing
```

> `--timeout=60` を必ず付けてください。GUI テストがハングした場合にタイムアウトで失敗させます。
> テスト実行には `pytest-timeout` が必要です（`pip install pytest-timeout`）。

### マーカー方針（v4.5 テスト再編）

- `visual`: スクリーンショット/視覚回帰テスト（通常実行から除外）
- `gui_heavy`: 実ウィンドウを多く開く重量GUIテスト
- `legacy_mock`: 手組みモックUIを含む移行中テスト

通常の開発サイクルでは `visual` / `legacy_mock` を除外した高速回帰を回し、
リリース前またはUI変更時に `visual` を明示実行してください。

### テスト共通設定 (`conftest.py`)

- `main_src/` をインポートパスに追加
- セッション全体で 1 つの Tk ルートウィンドウを共有
  - 各テストが `tk.Tk()` / `root.destroy()` を個別に行うと Tcl インタプリタが壊れるため
- `pytest_sessionfinish` で Tk ルートを安全に破棄

---

## Git 運用ガイド（初心者向け）

この章は、Git に不慣れな開発者が安全に運用できるようにするための最小ルールです。
アプリ本体の実装ルールとは独立しているため、引き継ぎ時の共通手順として利用できます。

### ブランチ方針

| ブランチ | 用途 | 誰が更新するか |
|---|---|---|
| `main` | アプリ本体・ドキュメント・ワークフロー定義 | 開発者 |
| `stats-data` | リリースDL集計 (`downloads.csv`) の機械生成履歴 | GitHub Actions |

`stats-data` を分離することで、`main` に日次の自動コミットが混ざらず、履歴ノイズと pull 競合を減らせます。

### 普段使う最小コマンド

```bash
# 1) 取り込み（merge commit を作らない）
git pull --rebase

# 2) 状態確認
git status -sb

# 3) 変更を記録
git add -A
git commit -m "feat: 変更内容"

# 4) 反映
git push
```

### 初回に入れておく推奨設定

```bash
git config --global pull.rebase true
git config --global rebase.autoStash true
git config --global pull.ff only
```

上記により、`git pull` 時の不要な merge commit を予防できます。

### 自動DL集計の流れ（main を汚さない）

1. Actions が GitHub API からダウンロード数を取得
2. `downloads.csv` を更新
3. 更新結果を `stats-data` ブランチへ push

`main` への自動書き込みは行いません。

### 公開してよい情報 / だめな情報

Git の運用手順そのものは個人情報ではないため、開発者向けドキュメントに記載して問題ありません。
ただし、以下は公開しないでください。

| 種別 | 例 |
|---|---|
| 秘密情報 | トークン、APIキー、パスワード |
| 個人情報 | 生徒名簿、個票データ、メールアドレス一覧 |
| 環境固有情報 | 個人PCの絶対パス、組織内サーバー名 |

### トラブル時の復旧（最小）

```bash
# 作業中変更を退避
git stash -u

# main を最新へ
git checkout main
git pull --rebase

# 退避を戻す
git stash pop
```

競合が出た場合は、慌てて push せず `git status` で競合ファイルを確認してから解決してください。

---

## コーディング規約

### 全般

- **エンコーディング**: UTF-8（BOM なし）
- **docstring**: モジュール先頭に概要と主な機能を記述
- **ログ出力**: Python 標準 `logging` モジュール経由。各モジュールで `logger = logging.getLogger(__name__)` を定義
- **パス操作**: `pathlib.Path` を推奨、`resource_path()` で PyInstaller 互換を確保

### 命名

- **関数名**: `snake_case`
- **クラス名**: `PascalCase`
- **定数**: `UPPER_SNAKE_CASE`（`constants.py` に集約）

### オプショナル依存

```python
try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    fitz = None
    HAS_PYMUPDF = False
```

PyMuPDF, matplotlib, reportlab はオプション扱いです。
未インストール時はフラグで分岐し、該当機能を無効化してください。

---

## コミット禁止物

以下はリポジトリにコミットしないでください（`.gitignore` で除外済み）:

| パターン | 理由 |
|---|---|
| `_saiten_grading_results/` | アプリが生成する採点結果 |
| `_mark2_grading_results/` | 旧フォルダ名（後方互換） |
| `template_coordinates.csv` | 座標パース時のデバッグ CSV |
| `tmp_checking_dm_nm.csv` | Checker 一時ファイル |
| `sample_bigfiles/` | 大容量テストデータ |
| `venv_build/` | exe ビルド用仮想環境 |
| `dist/` | ビルド出力 |
| `build/` | PyInstaller 中間出力 |
| `*.log` | クラッシュログ等 |
| `tests/tmp_output/` | テスト一時出力 |
| `.vscode/` | エディタ設定 |

---

## exe ビルド（Windows 向け）

> **macOS 向けパッケージについて**: 以下は Windows 版 exe のビルド手順です。macOS 向けの単体アプリ配布は現状未対応で、`python main_src/marunosuke.py` でのソース実行のみとなります。

### ビルド手順

```bash
build_exe.bat
```

出力: `dist/Marunosuke_v<バージョン>.exe`

### 仕組み

1. `venv_build/` にビルド専用仮想環境を作成
2. requirements.txt + pyinstaller をインストール
3. `marunosuke.spec` に従って PyInstaller でビルド

### spec ファイルの構成 (`marunosuke.spec`)

- **エントリポイント**: `main_src/marunosuke.py`
- **同梱データ**: `resources/marunosuke-icon.*`, `resources/marunosuke-logo.png`
- **hiddenimports**: main_src の全モジュール + オプション依存
- **excludes**: 不要なバックエンド (GTK/Qt/Wx)、テスト、開発ツール等
- **バイナリ除外**: AVIF/WebP プラグイン DLL、FFmpeg DLL
- **データ除外**: haarcascade XML、matplotlib サンプルデータ

### 軽量化のポイント

- `opencv-python-headless` を使用（highgui/FFmpeg 不要）
- matplotlib は `backend_agg` と `backend_tkagg` のみ残す
- matplotlib フォントは DejaVuSans のみ残し、AFM・STIX・CM 等を除外
- Pillow の未使用フォーマットプラグインを除外
- 不要な標準ライブラリ (`sqlite3`, `xmlrpc`, `ftplib` 等) を除外
- ネットワーク系パッケージ (`certifi`, `urllib3`, `requests`) を除外

### リリースビルドの依存関係に関する注意（重要）

`.github/workflows/release.yml` の `Install dependencies` ステップに列挙する
パッケージは **`requirements.txt` と手動で同期**させる必要がある。

過去に `scikit-learn` がこのリストから漏れていたことがあり、
`marunosuke.spec` の `collect_all('sklearn')` が「パッケージが
インストールされていない」ため全て `not found` を返しているにも関わらず
**PyInstaller のビルド自体は正常終了してしまい**、K-means クラスタリング
機能が同梱されない壊れた exe がそのまま GitHub Release として公開される
という事故が起きた（v4.5.1 で発生、v4.5.2 で修正）。

ビルドの exit code だけでは検知できないため、新しい依存を追加した際や
sklearn 関連の不具合を疑うときは、以下の手順で **exe を実際に起動して
確認する**こと。

**1. `main_src/saitensamurai.py` に組み込み済みの自己診断フック**

環境変数 `MARUNOSUKE_SMOKE_TEST=1` を設定して exe を起動すると、
GUI を開かずに `sklearn.cluster.KMeans` を実際に fit し、結果を
exe と同じフォルダの `smoke_test_result.txt` に書き出して終了する
（`OK` または `FAIL: <例外内容>`）。console=False ビルドのため
標準出力ではなくファイル経由で結果を返す。
旧 `SAITENSAMURAI_SMOKE_TEST=1` も後方互換のため引き続き受け付ける。

**2. release.yml に一時的に追加して使う検証ステップ（v4.5.2 で実際に使用・動作確認済み）**

```powershell
- name: Smoke test (sklearn/joblib bundling)
  run: |
    $exePath = "${{ steps.exe-name.outputs.EXE_PATH }}"
    $resultPath = Join-Path (Split-Path $exePath) "smoke_test_result.txt"
    if (Test-Path $resultPath) { Remove-Item $resultPath -Force }

    $env:MARUNOSUKE_SMOKE_TEST = "1"
    $proc = Start-Process -FilePath $exePath -PassThru

    $waited = 0
    while (-not (Test-Path $resultPath) -and $waited -lt 60) {
      Start-Sleep -Seconds 1
      $waited++
    }

    if (-not $proc.HasExited) {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path $resultPath)) {
      Write-Error "スモークテスト結果ファイルが生成されませんでした（${waited}秒待機）。exeの起動に失敗した可能性があります。"
      exit 1
    }

    $result = Get-Content $resultPath -Raw
    Write-Host "Smoke test result: $result"
    if ($result -notmatch "^OK") {
      Write-Error "スモークテスト失敗: $result"
      exit 1
    }
```

`Detect exe name` ステップの直後・`Create Release` ステップの直前に挿入する
（失敗時は exit 1 で job が止まり、Release が作成されないようにするため）。
恒久的には release.yml に含めず、疑わしいときだけ一時的に追加して確認し、
確認後は削除する運用とする。

**3. ビルドログでの簡易確認**

exe を起動できない環境では、`Build exe` ステップのログで
`Hidden import 'sklearn...' not found` が出ていないかを grep するだけでも
一次確認になる（ただし exe が実際に動作することの保証にはならない）。
