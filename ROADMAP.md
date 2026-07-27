# ロードマップ（今後実装したいこと）

まだ着手していないが、実装したいと考えている機能・修正をここに記録する。
着手したら該当セクションの先頭に `[着手中]` を付け、実装が終わったら
このファイルから削除して構わない（詳細な設計は各セクション内に残す）。

---

## 1. Step1「採点準備」統合セットアップウィザード

### 背景

現状、記述式のみモードのセットアップ作業のうち、いくつかがStep3(集計実行)の中に
埋め込まれてしまっている:

- **氏名欄選択**(`name_trimmer.NameTrimmer`)と**名簿入力**(`roster_loader.select_roster_gui`)は、
  Step3の集計実行を押すたびに**毎回**モーダルで聞かれる。矩形位置も名簿も**一切保存されない**ため、
  採点が全部終わった後になって初めて「氏名欄はどこ？」「名簿ある？」と聞かれる状態になっている。
- **学籍番号欄指定**(`id_area_config_gui.IdAreaConfigDialog`)は`student_id_ocr.StudentIdOcrTrimmer.run()`の
  中で初回のみ呼ばれ、`student_id_area_config.json`に保存されて2回目以降は自動再利用される
  ——設計としては良いが、Step3の「学籍番号OCR」チェックボックスをONにして初めて呼ばれるため、
  セットアップのタイミングとしては遅い。
- **ページ番号確認**(`page_number_checker.check_page_numbers`)は「1. データソース」欄にある独立ボタンで、
  Step1〜3の流れとは完全に切り離されている。

ユーザーの要望: これら全部を **Step1「採点準備」の段階で先にまとめて設定してしまいたい**。
その方が、答案の採点や集計をする前に「この試験の準備は全部終わっている」という状態を
作れて分かりやすい。

### 確定済みの方針（ユーザーとの合意事項）

1. **「ページ設定」の範囲**: 新しい永続化の仕組みは追加せず、既存の
   「🔢 ページ番号確認」ツール(`page_number_checker.py`)を**Step1の流れに移動するだけ**。
   「このフォルダは何ページ目か」という値を保存する仕組みは作らない。
2. **UI形状**: 5項目(名簿・ページ・氏名欄・学籍番号欄・解答欄)を**1つのボタン**で
   順番に連続実行する(既存の「⚙ 記述問題設定」ボタンを置き換える)。
   5つの別々のボタンを並べる形にはしない。各ステップは個別にスキップ可能
   (解答欄指定を除く——これはアプリの動作上、実質必須のため)。

### 実装方針

#### 新規の永続化モジュール（`id_area_config.py`と同じパターンに揃える）

**`main_src/roster_config.py`**（新規）— 名簿を`roster_config.json`として保存/読込。
`roster_loader.py`(名簿の"取得"担当のGUI)とは責務を分離する。

```python
ROSTER_CONFIG_FILE = "roster_config.json"
REQUIRED_CONFIG_KEYS = ["roster"]

def load_roster_config(config_path) -> Optional[Dict[str, str]]:
    data = load_json_safe(config_path, required_keys=REQUIRED_CONFIG_KEYS)
    return data["roster"] if data else None

def save_roster_config(config_path, roster: Dict[str, str]) -> None:
    atomic_json_save(config_path, {"roster": roster})
```

**`main_src/name_area_config.py`**（新規）— 氏名欄の矩形を割合(fraction)で
`name_area_config.json`として保存/読込(`id_area_config.py`の`manual_digit_rects_frac`と
同じ考え方。画像サイズが多少違っても崩れないようにするため)。

```python
NAME_AREA_CONFIG_FILE = "name_area_config.json"
REQUIRED_CONFIG_KEYS = ["rect_frac"]

def load_name_area_config(config_path) -> Optional[Tuple[float, float, float, float]]:
    data = load_json_safe(config_path, required_keys=REQUIRED_CONFIG_KEYS)
    return tuple(data["rect_frac"]) if data else None

def save_name_area_config(config_path, rect_frac) -> None:
    atomic_json_save(config_path, {"rect_frac": list(rect_frac)})

def resolve_rect_for_image(rect_frac, img_w, img_h) -> Tuple[int, int, int, int]:
    l, t, r, b = rect_frac
    return round(l * img_w), round(t * img_h), round(r * img_w), round(b * img_h)
```

#### `main_src/name_trimmer.py` — `NameTrimmer.run()`に`preset_rect`を追加

```python
def run(self, image_folder, parent=None, max_height=DEFAULT_MAX_HEIGHT,
        original_image_folder=None, preset_rect=None):
    ...
    if preset_rect is not None:
        trim_rect = preset_rect  # GUI選択をスキップ(Step3での再利用用)
    else:
        trim_rect = select_region_on_image(image_files[0], parent=parent)  # 従来通り(Step1の初回選択用)
        if trim_rect is None:
            return None
    self._last_trim_rect = trim_rect
    ...
```

#### `main_src/student_id_ocr.py` — エリア設定だけを取り出せる関数を追加

現状`StudentIdOcrTrimmer.run()`が「エリア設定の確保(初回のみダイアログ)」と
「OCR実行」を1メソッドに同居させている。Step1では前者だけが要るので、
モジュール関数として切り出す(外部から見た`run()`のシグネチャ・戻り値・
Step3の既存呼び出し側は無変更):

```python
def ensure_id_area_config(image_folder, parent, config_path,
                            default_digit_count=8, force_reconfigure=False) -> Optional[Dict]:
    """学籍番号欄の位置設定を確保する(既存ならロード、なければダイアログ表示して保存)。
    OCR認識は行わない。"""
    image_files = get_image_files(image_folder)
    if not image_files:
        return None
    config = None if force_reconfigure else (load_id_area_config(config_path) if config_path else None)
    if config is None:
        from id_area_config_gui import IdAreaConfigDialog
        dialog = IdAreaConfigDialog(parent, image_files[0], default_digit_count=default_digit_count)
        config = dialog.run()
        if config is None:
            return None
        if config_path:
            save_id_area_config(config_path, config)
    return config
```

#### `main_src/id_area_config_gui.py` — 2つのバグ修正

`_redraw_final_overlay()`(現状374-402行)で以下を修正:

- **バグA**: 認識済みの桁位置ラベルが枠の内側左上(`dx0+3, dy0+2`, `anchor=tk.NW`)に
  描画されており、画像の内容(記入された数字)を隠してしまう。→ ラベルを**枠の上**
  (`anchor="s"`、`dy0`から少し上)に描画するよう変更。枠がキャンバス上端に近すぎて
  収まらない場合のみ、従来に近い枠内側にフォールバックする。
- **バグB**: 英字マスのラベル文字が現在`"{位置番号}:英"`(漢字)になっている。
  枠のオレンジ色(`#EF6C00`)・破線(`dash=(5,3)`)は既に実装済みで変更不要——
  ラベル文字だけ`"{位置番号}:A"`(数字マスの`"{位置番号}:数"`と表記を揃える)に変更する。

```python
label_text = f"{i + 1}:A" if is_alpha else f"{i + 1}:数"   # バグB: 英→A

label_gap = 4
label_y = dy0 - label_gap
font_size_px = get_ui_font_size(8) + 4  # ラベル高さの概算
if label_y - font_size_px < 0:
    label_anchor, label_y = "n", dy0 + 2  # 上端に近すぎる場合のフォールバック
else:
    label_anchor = "s"

self.canvas.create_text(
    dx0, label_y, text=label_text, fill=color, anchor=label_anchor,
    font=(UI_FONT, get_ui_font_size(8), "bold"), tag="id_box_preview",
)
```

#### `main_src/main_gui.py` — Step1ウィザードの新設

**ボタンの置き換え**: `self.desc_setup_btn`の`command`を`self.setup_descriptive`→
`self._run_step1_setup_wizard`に変更。ラベル文言は「記述問題設定」という部分文字列を
残す(例: `"⚙ 記述問題設定（まとめて実行）"`)——既存テストの文字列アサーションを
壊さないため。

**新規メソッド `_run_step1_setup_wizard()`**:

```python
def _run_step1_setup_wizard(self):
    if not self.image_folder_path.get():
        messagebox.showerror("エラー", "画像フォルダを選択してください")
        return
    boxed_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / BOXED_FOLDER
    if not boxed_folder.exists():
        messagebox.showerror("エラー", "補正済み画像フォルダが存在しません。\nStep 1（画像準備）を先に実行してください。")
        return

    results_data_folder = Path(self.image_folder_path.get()) / RESULTS_FOLDER / RESULTS_DATA_FOLDER
    results_data_folder.mkdir(parents=True, exist_ok=True)

    self._wizard_step_roster(results_data_folder)
    self._wizard_step_page_check()
    self._wizard_step_name_area(boxed_folder, results_data_folder)
    self._wizard_step_id_area(boxed_folder, results_data_folder)
    self.setup_descriptive()  # 既存メソッドをそのまま最後に呼ぶ
```

重要: `setup_descriptive()`自体が既に「既存設定あり→続行/初期化/キャンセル」の
3択ダイアログを内包しているので、ウィザード側で重複した確認ダイアログは**出さない**
(同じ確認が2回出るのを防ぐ)。

各サブステップの共通ルール:「既存ファイルがあれば自動スキップ」「キャンセル/スキップは
次のステップへ進むだけ(全体を中断しない)」。

```python
def _wizard_step_roster(self, results_data_folder):
    from roster_config import ROSTER_CONFIG_FILE, load_roster_config, save_roster_config
    config_path = str(results_data_folder / ROSTER_CONFIG_FILE)
    if load_roster_config(config_path) is not None:
        self.log_message("✓ 名簿は設定済みです — スキップします")
        return
    from roster_loader import select_roster_gui
    roster = select_roster_gui(parent=self.root)
    if roster:
        save_roster_config(config_path, roster)
        self.log_message(f"✓ 名簿を保存しました: {len(roster)}件")
    else:
        self.log_message("名簿入力: 該当なし（スキップ）")

def _wizard_step_page_check(self):
    if not messagebox.askyesno("ページ設定", "複数ページに分かれた答案ですか？\n（ページ番号の取り違えを確認する場合は「はい」）"):
        self.log_message("ページ設定: 該当なし（スキップ）")
        return
    self.run_page_number_check()  # 既存メソッドをそのまま流用(状態を持たないため)

def _wizard_step_name_area(self, boxed_folder, results_data_folder):
    from name_area_config import NAME_AREA_CONFIG_FILE, load_name_area_config, save_name_area_config
    config_path = str(results_data_folder / NAME_AREA_CONFIG_FILE)
    if load_name_area_config(config_path) is not None:
        self.log_message("✓ 氏名欄は設定済みです — スキップします")
        return
    from name_trimmer import NameTrimmer, get_image_files
    image_files = get_image_files(str(boxed_folder))
    if not image_files:
        return
    trimmer = NameTrimmer()
    result = trimmer.run(str(boxed_folder), parent=self.root)
    trimmer.cleanup()
    if result is None:
        self.log_message("氏名欄選択: 該当なし（スキップ）")
        return
    with Image.open(image_files[0]) as img:
        img_w, img_h = img.size
    l, t, r, b = trimmer.last_trim_rect
    save_name_area_config(config_path, (l / img_w, t / img_h, r / img_w, b / img_h))
    self.log_message("✓ 氏名欄の位置を保存しました")

def _wizard_step_id_area(self, boxed_folder, results_data_folder):
    from id_area_config import ID_AREA_CONFIG_FILE, load_id_area_config
    config_path = str(results_data_folder / ID_AREA_CONFIG_FILE)
    if load_id_area_config(config_path) is not None:
        self.log_message("✓ 学籍番号欄は設定済みです — スキップします")
        return
    if not messagebox.askyesno("学籍番号欄指定", "学籍番号欄の位置を設定しますか？\n（後からでも設定できます）"):
        self.log_message("学籍番号欄指定: 該当なし（スキップ）")
        return
    from student_id_ocr import ensure_id_area_config
    config = ensure_id_area_config(
        str(boxed_folder), parent=self.root, config_path=config_path,
        default_digit_count=int(self.skip_questions.get() or 8),
    )
    if config:
        self.log_message("✓ 学籍番号欄の位置を保存しました")
        self.student_id_ocr_enabled.set(True)  # Step1で設定したのでOCRを有効化(Step3で解除も可)
    else:
        self.log_message("学籍番号欄指定: 該当なし（スキップ）")
```

**`_reset_descriptive_data()`の拡張**: 既存の削除対象4ファイル
(`descriptive_config.json`/`descriptive_scores.json`/`total_display_config.json`/
`student_id_area_config.json`)に加えて、`roster_config.json`・`name_area_config.json`も
同じチェック→バックアップ→削除の流れに追加する。「記述設定をリセットしたら
関連の位置設定も全部消える」という既存の設計思想をそのまま踏襲する。

**Step3側を「保存済みなら再利用」に変更**:

- `_run_summary_generation_descriptive_only()`の氏名欄トリミング部分:
  `name_area_config.json`があれば`resolve_rect_for_image()`で絶対座標に変換し、
  `NameTrimmer.run(..., preset_rect=...)`でGUI選択をスキップ。保存済み矩形が
  無い場合(Step1でスキップした/古いフォルダ)は、これまで通り毎回聞く動作に
  フォールバックする(後方互換)。
- `_run_student_id_ocr_flow()`の名簿読み込み部分: `roster_config.json`があれば
  それを使い、`select_roster_gui`は呼ばない。

**`session_state.json`のスキーマは変更しない** — 名簿・氏名欄設定は
`student_id_area_config.json`と同じ「別ファイル+存在チェック」方式に統一する。

#### 変更対象ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `main_src/roster_config.py` | 新規。名簿の永続化(load/save)。 |
| `main_src/name_area_config.py` | 新規。氏名欄矩形の永続化(fraction保存)+解決関数。 |
| `main_src/name_trimmer.py` | `NameTrimmer.run()`に`preset_rect`引数を追加。 |
| `main_src/student_id_ocr.py` | `ensure_id_area_config()`をモジュール関数として切り出し(外部シグネチャ不変)。 |
| `main_src/id_area_config_gui.py` | `_redraw_final_overlay()`: バグA(ラベル位置)・バグB(英字ラベル)。 |
| `main_src/main_gui.py` | Step1ボタンの付け替え、`_run_step1_setup_wizard`+4サブステップ新設、`_reset_descriptive_data()`拡張、Step3の「保存済みなら再利用」化。 |
| `main_src/roster_loader.py`, `main_src/page_number_checker.py`, `main_src/id_area_config.py`, `main_src/summary_generator.py` | 変更不要(呼び出し側だけ変わる、または既に対応済み)。 |

#### テスト計画

- 既存テスト(`test_name_trimmer.py`, `test_student_id_ocr.py`, `test_session_state.py`,
  `test_gui_widgets.py`, `test_cross_cutting.py`, `test_descriptive_scorer.py`)は
  `desc_setup_btn`という属性名とボタン文言中の「記述問題設定」を維持するため、
  大部分は無変更で通る想定。`TestResetDescriptiveData`には新規ファイル2つの
  削除を検証するテストを追加。
- 新規: `test_roster_config.py`(save/load往復・順序保持)、
  `test_name_area_config.py`(save/load往復・座標変換の検証)、
  `test_id_area_config_gui_overlay.py`(`_redraw_final_overlay()`を直接呼びバグA・Bを検証)、
  `test_step1_wizard.py`(各サブGUI呼び出しをモックし、実行順序・自動スキップ・
  キャンセル時の継続・2回目実行時の全スキップを検証)。
- 実機検証: `conftest.get_shared_tk_root()`で共有Tkルート上に実GUIクラスを生成し、
  `tkinter.messagebox`と各サブステップの対話UIをモックして、ウィジェット/ファイルの
  状態を直接アサートする(画面録画権限がない環境のため)。
- 最後に `pytest tests/ -q --timeout=60 --timeout-method=thread` で全体を確認。

#### 実装時の細かい判断(合意済み)

- ボタン文言は「記述問題設定」という部分文字列を残す(テスト互換のため)。
- 英字マスのラベルは桁番号プレフィックス付き`"N:A"`(数字マスの`"N:数"`と表記を揃える)。
- ウィザード先頭での「続行/初期化/キャンセル」確認は追加せず、既存の
  `setup_descriptive()`内蔵の3択ダイアログのみを使う(二重確認を避ける)。
- `student_id_ocr_enabled`チェックボックスは、Step1で学籍番号欄設定に成功した
  タイミングで自動的にONにする(デフォルト値自体は変更しない、Step3で手動OFFも可)。

---

## 2. 採点補助機能（採点基準メモ・一言コメント・採点保留タグ）

マークシート採点機能を削除して記述式のみに一本化する大改訂の際に相談した、
「不要な機能は削除する一方、自分の用途では足りない機能を追加したい」という
要望の中から、まだ未着手の3機能。いずれも記述式採点(`descriptive_gui.py`の
採点画面、`descriptive_scorer.py`のデータ構造)に手を入れる必要がある。

### 2-1. 採点基準メモ

採点する際に、採点基準をメモできる枠を表示してほしい。

- **設問ごと**のメモ(ルーブリック的なもの)と、**回答ごと**の個別メモの
  **両方**が欲しい(ユーザー確認済み)。
- 設問ごとのメモは記述問題設定(解答欄指定)の段階で入力できるようにし、
  採点画面では常に表示しておく。
- 回答ごとのメモは採点画面で各答案を見ながら自由に書き込める欄として用意する。

### 2-2. 一言コメント機能

部分点・減点などの場合、その理由を一言、採点済み答案の印刷時に記入できるように
したい。

- これまで使ったのと同じコメントは、リストから選択するだけでOK。
- 新しいコメントはその場で自由に入力できる。
- 再利用リストは**設問ごとに独立**させる(ユーザー確認済み・推奨案のまま採用)。
  例えば問1で使ったコメント一覧と問2で使ったコメント一覧は別々に管理する。
- 記入したコメントは採点済み答案の印刷(画像描画)に反映させる。

### 2-3. 採点保留タグ

採点を保留にした回答に、タグを付けられるようにしたい。後から似たような答案を
見つけやすく・比較しやすくするため。

- タグは**自由入力**で、**1つの回答に複数**付けられる(ユーザー確認済み)。
- 保留状態そのものの概念(「この答案は保留中」というフラグ)と、タグ付けは
  セットで設計する必要がある。

### 検討が必要な点(未確定)

上記3機能は方向性は合意済みだが、具体的な実装(データの保存先・スキーマ、
採点画面のUIレイアウトへの組み込み方、印刷描画への反映方法など)はまだ
詳細設計していない。着手する際は、他のセクション同様にExplore/Planエージェントで
`descriptive_gui.py`・`descriptive_scorer.py`・`descriptive_renderer.py`の
現状構造を調査してから設計する想定。
