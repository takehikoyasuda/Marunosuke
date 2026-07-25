# ダウンロード

## ソースコードを取得

現時点では macOS 向けの単体アプリ配布は行っておらず、**ソースコードから実行する形**でのご利用となります。

```bash
git clone https://github.com/takehikoyasuda/SaitenSamurai-mac.git
cd SaitenSamurai-mac
pip install -r requirements.txt
python main_src/saitensamurai.py
```

---

## 動作環境

| 項目 | 内容 |
|---|---|
| **対応 OS** | **macOS**（Apple Silicon / Intel、動作確認中） |
| **実行方法** | Python 3.9 以上のソースから実行 |

---

## セットアップ手順

1. **リポジトリを取得**
   上のコマンドで `git clone` するか、[GitHub](https://github.com/takehikoyasuda/SaitenSamurai-mac) から ZIP でダウンロードしてください。

2. **依存パッケージをインストール**
   `pip install -r requirements.txt` を実行してください。

3. **起動**
   `python main_src/saitensamurai.py` を実行すると、モード選択画面が表示されます。

!!! tip "サンプルデータで試す"
    初回は、リポジトリの `sample_basefile/` フォルダに含まれるサンプルファイルを使って動作確認するのがおすすめです。

    - `M2-03-002_座標ファイル.xlsx` — Mark2 座標ファイル
    - `answer_key_sample.xlsx` — 正答テンプレート
    - `sample_marksheet.jpg` — スキャン画像のサンプル

!!! info "Windows 版をお探しの方へ"
    Windows 向けの単体 exe 配布は、フォーク元の [phys-ken/SaitenSamurai](https://github.com/phys-ken/SaitenSamurai) をご利用ください。

---

## 過去のバージョン

このフォークでの変更履歴は [GitHub のコミット履歴](https://github.com/takehikoyasuda/SaitenSamurai-mac/commits/main/) から確認できます。オリジナル版（Windows）のリリース履歴は [phys-ken/SaitenSamurai Releases](https://github.com/phys-ken/SaitenSamurai/releases) ページをご覧ください。

---

## アンインストール

リポジトリのフォルダを削除するだけで完了です。レジストリ等の変更は一切行いません。

採点の作業データ（`_saiten_grading_results/` フォルダ）は、作業フォルダ内に生成されます。
不要な場合はフォルダごと削除してください。
