# ダウンロード数の自動集計

GitHub Actions が **毎日 23:55 (JST)** にリリースアセットのダウンロード数を記録し、`downloads.csv` に追記します。
集計データは **`stats-data` 専用ブランチ** に保存され、`main` には自動コミットされません。

---

## CSV の内容

| 列名 | 内容 |
|---|---|
| `date` | 記録日（YYYY-MM-DD、JST） |
| `tag` | リリースタグ名（例: `v4.1`） |
| `asset` | アセットファイル名（例: `Marunosuke_v0.1.0.exe`） |
| `download_count` | その時点での累計ダウンロード数 |

個人情報は一切含まれません。日次の累計値なので、差分を取れば 1 日あたりのダウンロード数が分かります。

---

## 集計を停止する方法

### 方法 1: ワークフローを無効化する（推奨・復帰可能）

1. GitHub リポジトリの **Actions** タブを開く
2. 左メニューから **「Track Release Downloads」** を選択
3. 右上の **「…」（三点メニュー）→「Disable workflow」** をクリック

再開したくなったら同じ場所で **「Enable workflow」** を選ぶだけです。

### 方法 2: YAML ファイルを削除する（完全停止）

```bash
git rm .github/workflows/track-downloads.yml
git commit -m "chore: ダウンロード集計を停止"
git push
```

### 方法 3: スケジュールだけ止めて手動実行は残す

`.github/workflows/track-downloads.yml` の `schedule:` セクションをコメントアウトします。

```yaml
on:
  # schedule:
  #   - cron: "55 14 * * *"
  workflow_dispatch:          # 手動実行のみ残す
```

---

## ブランチ構成（運用メモ）

| ブランチ | 用途 |
|---|---|
| `main` | アプリ本体・ドキュメント・ワークフロー定義 |
| `stats-data` | `downloads.csv` の自動更新履歴（機械生成データ専用） |

この構成により、`main` の履歴ノイズや `git pull` 時の競合を減らせます。

---

## 過去データの削除

CSV のデータが不要になったら削除できます。

```bash
git rm .github/download_stats/downloads.csv
git commit -m "chore: ダウンロード集計データを削除"
git push
```

---

## 関連ファイル

| ファイル | 役割 |
|---|---|
| `.github/workflows/track-downloads.yml` | GitHub Actions の定期実行設定 |
| `.github/scripts/track_downloads.py` | API 取得 → CSV 追記のスクリプト |
| `.github/download_stats/downloads.csv` | 集計データ（自動生成） |
| `.github/download_stats/README.md` | このファイル |
