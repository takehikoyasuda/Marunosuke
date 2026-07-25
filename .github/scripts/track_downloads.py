"""
track_downloads.py — GitHub Release ダウンロード数の日次記録

GitHub REST API からリリースアセットの download_count を取得し、
CSV ファイルに 1 行追記する。GitHub Actions のスケジュール実行で利用する。

CSV には個人情報は一切含まれない（日付・タグ・アセット名・DL数のみ）。
"""

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── 設定 ───────────────────────────────────────────────
REPO = os.environ.get("GITHUB_REPOSITORY", "takehikoyasuda/SaitenSamurai-mac")
CSV_PATH = Path(__file__).resolve().parent.parent / "download_stats" / "downloads.csv"
JST = timezone(timedelta(hours=9))
# ────────────────────────────────────────────────────────

CSV_COLUMNS = ["date", "tag", "asset", "download_count"]


def fetch_releases() -> list[dict]:
    """gh api でリリース情報を取得"""
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/releases", "--paginate"],
        capture_output=True, check=True,
    )
    return json.loads(result.stdout.decode("utf-8"))


def collect_rows(releases: list[dict]) -> list[dict]:
    """リリースごと・アセットごとの行を生成"""
    today = datetime.now(JST).strftime("%Y-%m-%d")
    rows = []
    for rel in releases:
        tag = rel["tag_name"]
        for asset in rel.get("assets", []):
            rows.append({
                "date": today,
                "tag": tag,
                "asset": asset["name"],
                "download_count": asset["download_count"],
            })
    return rows


def append_to_csv(rows: list[dict]) -> None:
    """CSV に行を追記（ファイルがなければヘッダー付きで新規作成）"""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = CSV_PATH.exists() and CSV_PATH.stat().st_size > 0

    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    releases = fetch_releases()
    rows = collect_rows(releases)

    if not rows:
        print("アセットが見つかりません。スキップします。")
        return

    append_to_csv(rows)

    for r in rows:
        print(f"  {r['date']}  {r['tag']}  {r['asset']}  DL={r['download_count']}")
    print(f"✓ {len(rows)} 行を {CSV_PATH.name} に追記しました。")


if __name__ == "__main__":
    main()
