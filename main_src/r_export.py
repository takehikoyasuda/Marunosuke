"""
r_export.py — R連携エクスポートモジュール

CTT分析と同一の0/1バイナリ正誤データを使用し、
R言語の 'exametrika' パッケージで高度なテスト理論分析を
行うための分析キット（CSV + Rスクリプト + RMarkdownテンプレート）を出力する。

exametrika は古典的テスト理論(CTT)、項目反応理論(IRT)、
潜在ランク分析(LRA)、バイクラスタリング / ランクラスタリング を
一つのパッケージで統一的に扱える。

出力先: 03_Final_Report/006_R_analysis_kit/
  - scored_data.csv      (0/1正誤データ)
  - item_info.csv        (設問情報)
  - create_report.R      (実行用Rスクリプト — これを実行するだけでOK)
  - report_template.Rmd  (RMarkdownレポートテンプレート)

記述問題が指定されている場合、バイナリ(0/1)項目として統合する。
"""

import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from constants import escape_excel_formula

logger = logging.getLogger(__name__)


# ========================================
# 定数
# ========================================

R_EXPORT_FOLDER = "006_R_analysis_kit"

# R分析キット内のファイル名
R_DATA_CSV = "scored_data.csv"
R_ITEM_INFO_CSV = "item_info.csv"
R_SCRIPT_FILE = "create_report.R"
R_RMD_TEMPLATE_FILE = "report_template.Rmd"

# exametrika デフォルト設定
DEFAULT_N_RANKS = 5
DEFAULT_N_FIELDS = 3


# ========================================
# メイン関数
# ========================================

def export_r_analysis_kit(
    output_folder,
    n_ranks=DEFAULT_N_RANKS,
    n_fields=DEFAULT_N_FIELDS,
    title="定期試験分析レポート",
    author="Mark2 Analysis System",
    descriptive_config=None,
    descriptive_scores=None,
):
    """
    R言語 exametrika 分析キットを出力する。

    CTT分析と同じデータソース（記述問題の0/1正誤データ）を使用する。
    descriptive_config / descriptive_scores が指定されている場合、
    記述問題をバイナリ(0/1)項目として追加する。

    Args:
        output_folder: 出力ベースフォルダ（03_Final_Report）
        n_ranks: 潜在ランク数（デフォルト 5）
        n_fields: バイクラスタリングのフィールド数（デフォルト 3）
        title: レポートのタイトル
        author: レポートの著者
        descriptive_config: 記述問題設定dict（オプション）
        descriptive_scores: {ファイル名: {問題ID: 得点}} の辞書（オプション）

    Returns:
        dict: {'success': bool, 'output_dir': str, 'error': str|None}
    """
    logger.info("=" * 60)
    logger.info("R連携エクスポート (exametrika 分析キット)")
    logger.info("=" * 60)

    try:
        # 1. CTT と同一の変換ロジックで0/1データを取得
        from ctt_analyzer import convert_mark2_to_ctt_data, CTTAnalyzer

        ans_df, key_df = convert_mark2_to_ctt_data(
            descriptive_config=descriptive_config,
            descriptive_scores=descriptive_scores,
        )
        analyzer = CTTAnalyzer(ans_df, key_df)
        score_matrix = analyzer.score_matrix  # 0/1バイナリ DataFrame

        # ① 列名を Q001, Q002, ... 形式に変更（解答番号と対応）
        col_map = {}
        for i, col in enumerate(score_matrix.columns, start=1):
            col_map[col] = f"Q{i:03d}"
        score_matrix = score_matrix.rename(columns=col_map)

        # ② 行名を画像ファイル名（拡張子なし）に変更
        if "StudentID" in ans_df.columns:
            file_names = ans_df["StudentID"].values
            new_index = []
            for fn in file_names:
                name = str(fn)
                # 拡張子を除去
                if "." in name:
                    name = name.rsplit(".", 1)[0]
                new_index.append(name)
            score_matrix.index = new_index

        # ③ 全員が同じ得点の列を削除（分散=0: 全員正解/全員不正解/同一点）
        n_before = len(score_matrix.columns)
        constant_cols = score_matrix.columns[score_matrix.nunique() <= 1].tolist()
        if constant_cols:
            score_matrix = score_matrix.drop(columns=constant_cols)
            logger.info("  ✓ 全員同点の設問を除外: %d問 (%s)",
                        len(constant_cols), ', '.join(constant_cols))

        logger.info("  ✓ データ変換完了: 受験者数=%d, 設問数=%d (元%d問)",
                    len(score_matrix), len(score_matrix.columns), n_before)

        # 2. 出力フォルダ作成
        kit_folder = Path(output_folder) / R_EXPORT_FOLDER
        kit_folder.mkdir(parents=True, exist_ok=True)

        # 3. CSV出力
        data_csv_path = kit_folder / R_DATA_CSV
        _export_scored_data(score_matrix, data_csv_path)

        item_info_path = kit_folder / R_ITEM_INFO_CSV
        _export_item_info(score_matrix, key_df, item_info_path, col_map=col_map)

        # 4. Rスクリプト生成
        r_script_path = kit_folder / R_SCRIPT_FILE
        _generate_r_script(r_script_path, n_ranks, n_fields)

        rmd_path = kit_folder / R_RMD_TEMPLATE_FILE
        _generate_rmd_template(rmd_path, n_ranks, n_fields, title, author)

        logger.info("  ✓ R分析キットを出力: %s", kit_folder)
        logger.info("    - %s", R_DATA_CSV)
        logger.info("    - %s", R_ITEM_INFO_CSV)
        logger.info("    - %s  ← まずこれを実行！", R_SCRIPT_FILE)
        logger.info("    - %s", R_RMD_TEMPLATE_FILE)
        logger.info("  → RStudioで create_report.R を開いて実行してください。")

        return {
            "success": True,
            "output_dir": str(kit_folder),
            "error": None,
        }

    except Exception as e:
        logger.error("  ✗ R連携エクスポートエラー: %s", e, exc_info=True)
        return {
            "success": False,
            "output_dir": None,
            "error": str(e),
        }


# ========================================
# 内部ヘルパー関数
# ========================================

def _export_scored_data(score_matrix, output_path):
    """0/1正誤データをCSV出力する（BOM付きUTF-8）。"""
    # インデックス（StudentID相当）は行名として出力
    score_matrix.to_csv(str(output_path), encoding="utf-8-sig")
    logger.info("  ✓ 正誤データ出力: %s", output_path.name)


def _export_item_info(score_matrix, key_df, output_path, col_map=None):
    """設問情報CSVを出力する。

    score_matrixは既にQ001形式のカラム名・定数列削除済み。
    元のkey_dfとの対応を保ちつつ、残っている列のみ出力する。
    key_dfにSummary列(問題概要、任意入力)がある場合はCSVにも含める。

    Args:
        col_map: {元QuestionID: "Q001"形式} の対応辞書(Summary引き当てに使用)
    """
    # score_matrixに残っている列の情報を出力
    item_info = pd.DataFrame({
        "ItemID": score_matrix.columns.tolist(),
        "MeanScore": score_matrix.mean().values,
    })

    # 問題概要: Q001形式 → 元QuestionID → key_df['Summary'] の順に引き当てる
    if col_map and 'Summary' in key_df.columns:
        inv_map = {v: k for k, v in col_map.items()}
        summary_by_qid = {
            str(q): ('' if pd.isna(s) else str(s))
            for q, s in zip(key_df['QuestionID'], key_df['Summary'])
        }
        # 概要はユーザー自由入力のため、CSVをExcelで直接開いた際の
        # フォーミュラインジェクション('='始まり等)を防ぐエスケープを通す
        item_info["Summary"] = [
            escape_excel_formula(summary_by_qid.get(str(inv_map.get(item_id, '')), ''))
            for item_id in item_info["ItemID"]
        ]

    item_info.to_csv(str(output_path), index=False, encoding="utf-8-sig")
    logger.info("  ✓ 設問情報出力: %s", output_path.name)


def _generate_r_script(output_path, n_ranks, n_fields=DEFAULT_N_FIELDS):
    """exametrika 実行用Rスクリプトを生成する。

    このスクリプトは create_report.R という名前で出力され、
    RStudioで開いて実行するだけでHTMLレポートが生成される。
    必要なパッケージは exametrika と rmarkdown のみ。
    """
    # --- Rスクリプト本体（リテラル日本語で記述）---
    lines = [
        '# ==============================================================================',
        '# exametrika 分析レポート生成スクリプト',
        '# Mark2 R Export Module により自動生成',
        '# ==============================================================================',
        '#',
        '# 【使い方】',
        '#   1. RStudioでこのファイル (create_report.R) を開く',
        '#   2. "Session" → "Set Working Directory" → "To Source File Location"',
        '#   3. 全体を実行 (Ctrl+Alt+R)',
        '#   → 同じフォルダに exametrika_report.html が生成されます',
        '#',
        '# 【必要なパッケージ】',
        '#   install.packages("exametrika")   # テスト理論分析',
        '#   install.packages("rmarkdown")    # レポート生成',
        '#   install.packages("openxlsx")     # Excel出力（推奨）',
        '#',
        '# ==============================================================================',
        '',
        '# --- 1. パッケージ確認 ---',
        'if (!requireNamespace("exametrika", quietly = TRUE)) {',
        '  stop("【エラー】パッケージ \'exametrika\' がインストールされていません。\\n",',
        '       "以下のコマンドでインストールしてください:\\n",',
        '       "  install.packages(\\"exametrika\\")")',
        '}',
        'if (!requireNamespace("rmarkdown", quietly = TRUE)) {',
        '  stop("【エラー】パッケージ \'rmarkdown\' がインストールされていません。\\n",',
        '       "以下のコマンドでインストールしてください:\\n",',
        '       "  install.packages(\\"rmarkdown\\")")',
        '}',
        '',
        '# openxlsx は推奨（Excelレポート出力に必要）',
        'if (!requireNamespace("openxlsx", quietly = TRUE)) {',
        '  message("【注意】パッケージ \'openxlsx\' がインストールされていません。")',
        '  message("Excelファイル出力をスキップします。")',
        '  message("install.packages(\\"openxlsx\\") でインストールすると Excel 出力も行われます。")',
        '}',
        '',
        '# --- 2. データ読み込み ---',
        f'data_file <- "{R_DATA_CSV}"',
        f'info_file <- "{R_ITEM_INFO_CSV}"',
        f'rmd_file  <- "{R_RMD_TEMPLATE_FILE}"',
        '',
        'if (!file.exists(data_file)) {',
        '  stop("データファイルが見つかりません: ", data_file, "\\n",',
        '       "ワーキングディレクトリを確認してください: ", getwd())',
        '}',
        '',
        'message("=== exametrika 分析レポート生成 ===")',
        'message(paste("データファイル:", data_file))',
        '',
        '# --- 3. HTMLレポート生成 ---',
        'if (!file.exists(rmd_file)) {',
        '  stop("Rmdテンプレートが見つかりません: ", rmd_file)',
        '}',
        '',
        'message("レポートを生成中...")',
        'rmarkdown::render(',
        '  rmd_file,',
        '  output_format = "html_document",',
        '  output_file   = "exametrika_report.html",',
        '  quiet         = FALSE',
        ')',
        'message("レポート生成完了: exametrika_report.html")',
        'message("ブラウザで開いて確認してください。")',
    ]
    content = "\n".join(lines) + "\n"
    with open(str(output_path), "w", encoding="utf-8") as f:
        f.write(content)


def _generate_rmd_template(output_path, n_ranks, n_fields, title, author):
    """exametrika用RMarkdownテンプレートを生成する。

    exametrika のみを使用して以下の分析を実行:
    - CTT (古典的テスト理論): 信頼性・項目統計量
    - IRT (項目反応理論): 2パラメータモデル
    - LRA (潜在ランク分析): ランク分類と TRP
    - Biclustering / Ranklustering: 受験者×項目の二次元分類

    出力形式は HTML（LaTeX不要、フォント依存なし）。
    グラフと言葉での解説を中心に表示し、
    生データ・数値テーブルはExcelファイルに出力する（openxlsx使用）。
    """
    content = f'''---
title: "{title}"
subtitle: "exametrika による総合テスト分析レポート"
author: "{author}"
date: "`r format(Sys.Date(), '%Y年%m月%d日')`"
output:
  html_document:
    toc: true
    toc_float: true
    toc_depth: 3
    number_sections: true
    theme: flatly
    highlight: tango
    self_contained: true
---

```{{r setup, include=FALSE}}
knitr::opts_chunk$set(
  echo = FALSE, warning = FALSE, message = FALSE,
  fig.align = "center", fig.width = 10, fig.height = 8,
  out.width = "100%", dpi = 120
)
library(exametrika)
```

```{{r load_data}}
data_file <- "{R_DATA_CSV}"
info_file <- "{R_ITEM_INFO_CSV}"

if (!file.exists(data_file)) stop(paste("データファイルが見つかりません:", data_file))

raw_data <- read.csv(data_file, row.names = 1, fileEncoding = "UTF-8-BOM")
item_info <- read.csv(info_file, fileEncoding = "UTF-8-BOM")

N <- nrow(raw_data)
M <- ncol(raw_data)

# exametrika が要求する形式に変換
dat <- dataFormat(raw_data)
```

# 分析概要

本レポートは **exametrika** パッケージを用いて、以下の分析を行った結果です。

| 項目 | 値 |
|------|-----|
| 受験者数 | `r N` 名 |
| 設問数 | `r M` 問 |
| 平均正答数 | `r round(mean(rowSums(raw_data)), 1)` 問 |
| 平均正答率 | `r round(mean(rowSums(raw_data)) / M * 100, 1)` % |
| 正答数の標準偏差 | `r round(sd(rowSums(raw_data)), 2)` |
| 潜在ランク数 | {n_ranks} |
| フィールド数 (バイクラスタリング) | {n_fields} |

> 各分析の詳細な数値データは、同フォルダ内の **analysis_results.xlsx** にシート別に保存されています。
> このHTMLレポートではグラフと解説を中心に結果を示します。

---

# 第1章: CTT（古典的テスト理論）

古典的テスト理論 (Classical Test Theory) は、テスト全体の信頼性と各設問の基本的な統計量を求める手法です。

```{{r ctt_analysis}}
res_ctt <- CTT(dat)
item_stats <- ItemStatistics(dat)
```

## テストの信頼性

```{{r ctt_reliability}}
# CTT結果からテスト統計量を抽出
total_scores <- rowSums(raw_data)
cat(paste0(
  "■ テスト全体の特徴:\\n",
  "  ・受験者数: ", N, " 名\\n",
  "  ・設問数: ", M, " 問\\n",
  "  ・平均正答数: ", round(mean(total_scores), 1), " 問 ",
  "(平均正答率 ", round(mean(total_scores) / M * 100, 1), "%)\\n",
  "  ・正答数の標準偏差: ", round(sd(total_scores), 2), "\\n",
  "  ・最高正答数: ", max(total_scores), " 問\\n",
  "  ・最低正答数: ", min(total_scores), " 問\\n"
))
```

```{{r ctt_interpretation}}
avg_rate <- mean(total_scores) / M * 100
difficulty_comment <- if (avg_rate > 80) {{
  "全体的にやさしいテストです。"
}} else if (avg_rate > 60) {{
  "適度な難易度のテストです。"
}} else if (avg_rate > 40) {{
  "やや難しいテストです。"
}} else {{
  "難しいテストです。"
}}
cat(paste0("■ 総合評価: ", difficulty_comment, "\\n"))
```

## 設問ごとの正答率

各設問について、正答率が高い順に確認できます。正答率が極端に高い（90%以上）または低い（10%以下）設問は、テストとしての弁別力が低い可能性があります。

```{{r ctt_item_bar, fig.height=10}}
pass_rates <- colMeans(raw_data) * 100
item_df <- data.frame(
  item = names(pass_rates),
  rate = as.numeric(pass_rates)
)
item_df <- item_df[order(item_df$rate, decreasing = TRUE), ]

par(mar = c(5, 6, 4, 2), las = 1)
barplot(item_df$rate,
        names.arg = item_df$item,
        horiz = TRUE, col = ifelse(item_df$rate > 80, "#5cb85c",
                              ifelse(item_df$rate < 20, "#d9534f", "#5bc0de")),
        xlab = "正答率 (%)", main = "設問別 正答率",
        xlim = c(0, 100), cex.names = 0.8)
abline(v = c(20, 80), lty = 2, col = "gray50")
```

```{{r ctt_item_comment}}
high_items <- names(pass_rates[pass_rates > 80])
low_items  <- names(pass_rates[pass_rates < 20])
if (length(high_items) > 0) {{
  cat(paste0("■ 正答率80%超の設問 (やさしい): ", paste(high_items, collapse = ", "), "\\n"))
}}
if (length(low_items) > 0) {{
  cat(paste0("■ 正答率20%未満の設問 (難しい): ", paste(low_items, collapse = ", "), "\\n"))
}}
if (length(high_items) == 0 && length(low_items) == 0) {{
  cat("■ 全設問が適切な難易度範囲 (20〜80%) にあります。\\n")
}}
```

---

# 第2章: IRT（項目反応理論）

項目反応理論 (Item Response Theory) は、各設問の「識別力」と「困難度」を推定し、
受験者の能力と設問特性の関係をモデル化します。ここでは 2パラメータ・ロジスティックモデル (2PLM) を使用しています。

```{{r irt_analysis}}
res_irt <- IRT(dat, model = 2)
```

## 項目特性曲線 (ICC)

各設問について、受験者の能力レベル ($\\theta$) に応じた正答確率を示すグラフです。
曲線が急なほど弁別力が高く、曲線の位置が右にあるほど困難度が高い設問です。

```{{r irt_icc, fig.height=30, fig.width=10}}
plot(res_irt, type = "ICC", nr = ceiling(M / 3), nc = 3)
```

## テスト情報曲線 (TIC)

テスト全体がどの能力レベルの受験者を精度よく測定できるかを示します。
曲線のピーク付近の能力レベルの受験者が最も精度よく測定されます。

```{{r irt_tic, fig.height=8}}
plot(res_irt, type = "TIC")
```

```{{r irt_comment}}
cat(paste0(
  "■ IRT分析の特徴:\\n",
  "  ・2パラメータモデル: 各設問の識別力（弁別力）と困難度を推定\\n",
  "  ・ICCが急勾配 → その設問は受験者の能力を鋭く弁別できる\\n",
  "  ・ICCが緩やか → 弁別力が低い（能力差が結果に反映されにくい）\\n",
  "  ・TICのピーク → テストが最も正確に測定できる能力帯\\n"
))
```

---

# 第3章: LRA（潜在ランク分析）

潜在ランク分析 (Latent Rank Analysis) は、受験者を {n_ranks} つの潜在的なランク（グループ）に分類します。
CTT のような単なる合計点による序列ではなく、設問への回答パターンに基づくより精緻な分類です。

```{{r lra_analysis}}
res_lra <- LRA(dat, nrank = {n_ranks})
```

## テスト参照プロファイル (TRP)

各ランクの受験者が各設問にどの程度正答できるかを示します。
ランクが上がるにつれ、多くの設問で正答確率が上昇する傾向が見られます。

```{{r lra_trp, fig.height=10}}
plot(res_lra, type = "TRP")
```

## 潜在ランク分布 (LRD)

受験者が各ランクにどのように分布しているかを示します。

```{{r lra_lrd, fig.height=8}}
plot(res_lra, type = "LRD")
```

```{{r lra_comment}}
cat(paste0(
  "■ 潜在ランク分析の特徴:\\n",
  "  ・受験者を ", {n_ranks}, " 段階のランクに分類\\n",
  "  ・ランクが高いほど全体的な正答率が高い\\n",
  "  ・TRPを見ることで、各ランクの受験者がどの設問で躓いているか把握可能\\n",
  "  ・ランク間で差がつきやすい設問 = 弁別力の高い設問\\n"
))
```

## ランクメンバーシッププロファイル (RMP)

個々の受験者が各ランクに所属する確率を示します（先頭数名を例示）。

```{{r lra_rmp, fig.height=8}}
n_show <- min(6, N)
plot(res_lra, type = "RMP", students = 1:n_show,
     nr = ifelse(n_show <= 3, 1, 2), nc = min(n_show, 3))
```

---

# 第4章: バイクラスタリング / ランクラスタリング

バイクラスタリングは、受験者（行）と設問（列）を**同時に**クラスタリングする手法です。
受験者を「クラス」に、設問を「フィールド」に分類し、それぞれの組み合わせでの正答パターンを分析します。

## 4.1 バイクラスタリング (Biclustering)

受験者を {n_ranks} クラス、設問を {n_fields} フィールドに分類します。

```{{r biclustering}}
res_bc <- Biclustering(dat, nfld = {n_fields}, ncls = {n_ranks}, method = "B")
```

### アレイプロット

行（受験者）と列（設問）が再配置された正誤パターンの全体像です。
濃い色は正答、薄い色は誤答を示します。クラスとフィールドの境界が確認できます。

```{{r bc_array, fig.height=12}}
plot(res_bc, type = "Array")
```

### クラス参照ベクトル (CRV)

各フィールドについて、クラスごとの正答率を示します。フィールドごとに設問群の特徴が異なることがわかります。

```{{r bc_crv, fig.height=8}}
plot(res_bc, type = "CRV")
```

### フィールド参照プロファイル (FRP)

各フィールド内の設問が、クラスに応じてどのような正答パターンを示すかを表します。

```{{r bc_frp, fig.height=12}}
plot(res_bc, type = "FRP",
     nr = ceiling({n_fields} / 2), nc = min({n_fields}, 2))
```

### テスト参照プロファイル (TRP) / 潜在クラス分布 (LCD)

```{{r bc_trp_lcd, fig.height=8}}
par(mfrow = c(1, 2))
plot(res_bc, type = "TRP")
plot(res_bc, type = "LCD")
```

```{{r bc_comment}}
cat(paste0(
  "■ バイクラスタリングの特徴:\\n",
  "  ・受験者を ", {n_ranks}, " クラス × 設問を ", {n_fields}, " フィールドに分類\\n",
  "  ・フィールド = 似た特性を持つ設問群（難易度パターンが近い設問同士）\\n",
  "  ・クラス = 似た回答パターンの受験者群\\n",
  "  ・アレイプロットで全体の正誤パターンを一目で把握可能\\n"
))
```

## 4.2 ランクラスタリング (Ranklustering)

バイクラスタリングに**順序制約**を加えた分析です。クラスに順序（ランク）があると仮定し、
ランクが上がるにつれて正答率が体系的に向上するモデルです。

```{{r ranklustering}}
res_rc <- Biclustering(dat, nfld = {n_fields}, ncls = {n_ranks}, method = "R")
```

### アレイプロット

ランクとフィールドによる分類結果です。ランク順序に沿った段階的なパターンが見られます。

```{{r rc_array, fig.height=12}}
plot(res_rc, type = "Array")
```

### ランク参照ベクトル (RRV)

各フィールドについて、ランクごとの正答率を示します。ランクが上がると正答率が上昇する傾向が確認できます。

```{{r rc_rrv, fig.height=8}}
plot(res_rc, type = "RRV")
```

### フィールド参照プロファイル (FRP)

```{{r rc_frp, fig.height=12}}
plot(res_rc, type = "FRP",
     nr = ceiling({n_fields} / 2), nc = min({n_fields}, 2))
```

### テスト参照プロファイル (TRP) / 潜在ランク分布 (LRD)

```{{r rc_trp_lrd, fig.height=8}}
par(mfrow = c(1, 2))
plot(res_rc, type = "TRP")
plot(res_rc, type = "LRD")
```

```{{r rc_comment}}
cat(paste0(
  "■ ランクラスタリングの特徴:\\n",
  "  ・バイクラスタリングに順序制約を追加（ランク1 < ランク2 < ... < ランク", {n_ranks}, "）\\n",
  "  ・ランクが上がるにつれ、より多くのフィールド（設問群）で正答率が向上\\n",
  "  ・学力の段階的な構造を把握しやすい\\n"
))
```

---

# 第5章: 分析のまとめ

```{{r summary_section}}
cat(paste0(
  "■ テスト全体の概況\\n",
  "  ・受験者 ", N, " 名、設問 ", M, " 問のテストを分析しました。\\n",
  "  ・平均正答率は ", round(mean(rowSums(raw_data)) / M * 100, 1), "% です。\\n\\n",
  "■ 各分析手法での知見\\n",
  "  【CTT】テスト全体の難易度傾向と各設問の正答率分布を確認できます。\\n",
  "  【IRT】各設問の識別力と困難度を推定し、テストの精度を評価できます。\\n",
  "  【LRA】受験者を ", {n_ranks}, " 段階のランクに分類し、各ランクの特徴を把握できます。\\n",
  "  【Biclustering/Ranklustering】受験者と設問を同時分類し、\\n",
  "     どのグループがどの設問群で躓いているかを視覚的に把握できます。\\n\\n",
  "■ 詳細データ\\n",
  "  各分析の数値データ（項目パラメータ・ランク所属確率など）は\\n",
  "  analysis_results.xlsx に保存されています。\\n"
))
```

---

```{{r excel_output, include=FALSE}}
# =============================================================
# 分析結果の詳細データを Excel に出力 (openxlsx)
# =============================================================
if (requireNamespace("openxlsx", quietly = TRUE)) {{

  library(openxlsx)
  wb <- createWorkbook()

  # --- ヘッダースタイル ---
  header_style <- createStyle(
    fontColour = "#FFFFFF", fgFill = "#4472C4",
    halign = "center", valign = "center",
    textDecoration = "bold",
    border = "TopBottomLeftRight", borderColour = "#2F528F"
  )
  body_style <- createStyle(
    border = "TopBottomLeftRight", borderColour = "#B4C6E7",
    halign = "center"
  )
  highlight_style <- createStyle(
    fgFill = "#FFEB9C", border = "TopBottomLeftRight", borderColour = "#B4C6E7"
  )

  # ========== Sheet 1: テスト概要 ==========
  addWorksheet(wb, "テスト概要")
  overview_df <- data.frame(
    項目 = c("受験者数", "設問数", "平均正答数", "平均正答率(%)",
             "正答数SD", "最高正答数", "最低正答数",
             "潜在ランク数", "フィールド数"),
    値 = c(N, M,
           round(mean(rowSums(raw_data)), 2),
           round(mean(rowSums(raw_data)) / M * 100, 1),
           round(sd(rowSums(raw_data)), 2),
           max(rowSums(raw_data)),
           min(rowSums(raw_data)),
           {n_ranks}, {n_fields})
  )
  writeData(wb, "テスト概要", overview_df, headerStyle = header_style)
  addStyle(wb, "テスト概要", body_style, rows = 2:(nrow(overview_df)+1),
           cols = 1:2, gridExpand = TRUE)
  setColWidths(wb, "テスト概要", cols = 1:2, widths = c(20, 15))
  freezePane(wb, "テスト概要", firstRow = TRUE)

  # ========== Sheet 2: 正誤データ ==========
  addWorksheet(wb, "正誤データ")
  scored_with_id <- cbind(受験者 = rownames(raw_data), raw_data)
  writeData(wb, "正誤データ", scored_with_id, headerStyle = header_style)
  addStyle(wb, "正誤データ", body_style,
           rows = 2:(N+1), cols = 1:(M+1), gridExpand = TRUE)
  setColWidths(wb, "正誤データ", cols = 1, widths = 20)
  setColWidths(wb, "正誤データ", cols = 2:(M+1), widths = 8)
  freezePane(wb, "正誤データ", firstRow = TRUE, firstCol = TRUE)

  # ========== Sheet 3: CTT 信頼性指標 ==========
  addWorksheet(wb, "CTT信頼性")
  tryCatch({{
    ctt_rel_df <- as.data.frame(res_ctt$Reliability)
    writeData(wb, "CTT信頼性", ctt_rel_df, headerStyle = header_style)
    addStyle(wb, "CTT信頼性", body_style,
             rows = 2:(nrow(ctt_rel_df)+1),
             cols = 1:ncol(ctt_rel_df), gridExpand = TRUE)
    setColWidths(wb, "CTT信頼性", cols = 1:ncol(ctt_rel_df), widths = "auto")
    freezePane(wb, "CTT信頼性", firstRow = TRUE)
  }}, error = function(e) {{
    writeData(wb, "CTT信頼性",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 4: CTT 項目除外信頼性 ==========
  addWorksheet(wb, "CTT項目除外信頼性")
  tryCatch({{
    ctt_exci_df <- as.data.frame(res_ctt$ReliabilityExcludingItem)
    writeData(wb, "CTT項目除外信頼性", ctt_exci_df, headerStyle = header_style)
    addStyle(wb, "CTT項目除外信頼性", body_style,
             rows = 2:(nrow(ctt_exci_df)+1),
             cols = 1:ncol(ctt_exci_df), gridExpand = TRUE)
    setColWidths(wb, "CTT項目除外信頼性", cols = 1:ncol(ctt_exci_df), widths = "auto")
    freezePane(wb, "CTT項目除外信頼性", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "CTT項目除外信頼性",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 5: CTT 項目統計量 ==========
  addWorksheet(wb, "CTT項目統計量")
  tryCatch({{
    ctt_items_df <- data.frame(
      設問 = item_stats$ItemLabel,
      受験者数 = as.numeric(item_stats$NR),
      正答率 = as.numeric(item_stats$CRR),
      オッズ = as.numeric(item_stats$ODDs),
      閾値 = as.numeric(item_stats$Threshold),
      エントロピー = as.numeric(item_stats$Entropy),
      IT相関 = as.numeric(item_stats$ITCrr)
    )
    writeData(wb, "CTT項目統計量", ctt_items_df, headerStyle = header_style)
    addStyle(wb, "CTT項目統計量", body_style,
             rows = 2:(nrow(ctt_items_df)+1),
             cols = 1:ncol(ctt_items_df), gridExpand = TRUE)
    # 正答率が低い設問をハイライト
    low_rows <- which(ctt_items_df[,"正答率"] < 0.2) + 1
    if (length(low_rows) > 0) {{
      addStyle(wb, "CTT項目統計量", highlight_style,
               rows = low_rows, cols = 1:ncol(ctt_items_df), gridExpand = TRUE)
    }}
    setColWidths(wb, "CTT項目統計量", cols = 1:ncol(ctt_items_df), widths = "auto")
    freezePane(wb, "CTT項目統計量", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "CTT項目統計量",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 6: IRT パラメータ ==========
  addWorksheet(wb, "IRTパラメータ")
  tryCatch({{
    irt_params_df <- as.data.frame(res_irt$params)
    irt_params_df <- cbind(設問 = rownames(irt_params_df), irt_params_df)
    rownames(irt_params_df) <- NULL
    writeData(wb, "IRTパラメータ", irt_params_df, headerStyle = header_style)
    addStyle(wb, "IRTパラメータ", body_style,
             rows = 2:(nrow(irt_params_df)+1),
             cols = 1:ncol(irt_params_df), gridExpand = TRUE)
    setColWidths(wb, "IRTパラメータ", cols = 1:ncol(irt_params_df), widths = "auto")
    freezePane(wb, "IRTパラメータ", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "IRTパラメータ",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 7: IRT 受験者能力値 ==========
  addWorksheet(wb, "IRT受験者能力値")
  tryCatch({{
    irt_ability_df <- as.data.frame(res_irt$ability)
    irt_ability_df$合計得点 <- rowSums(raw_data)
    writeData(wb, "IRT受験者能力値", irt_ability_df, headerStyle = header_style)
    addStyle(wb, "IRT受験者能力値", body_style,
             rows = 2:(nrow(irt_ability_df)+1),
             cols = 1:ncol(irt_ability_df), gridExpand = TRUE)
    setColWidths(wb, "IRT受験者能力値", cols = 1:ncol(irt_ability_df), widths = "auto")
    freezePane(wb, "IRT受験者能力値", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "IRT受験者能力値",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 8: IRT 適合度指標 ==========
  addWorksheet(wb, "IRT適合度")
  tryCatch({{
    tfi <- res_irt$TestFitIndices
    fit_df <- data.frame(指標名 = names(tfi), 値 = unlist(tfi))
    rownames(fit_df) <- NULL
    writeData(wb, "IRT適合度", fit_df, headerStyle = header_style)
    addStyle(wb, "IRT適合度", body_style,
             rows = 2:(nrow(fit_df)+1),
             cols = 1:ncol(fit_df), gridExpand = TRUE)
    setColWidths(wb, "IRT適合度", cols = 1:ncol(fit_df), widths = "auto")
    freezePane(wb, "IRT適合度", firstRow = TRUE)
  }}, error = function(e) {{
    writeData(wb, "IRT適合度",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 9: LRA ランク所属確率 ==========
  addWorksheet(wb, "LRAランク所属")
  tryCatch({{
    lra_membership <- as.data.frame(res_lra$Students)
    lra_membership <- cbind(
      受験者 = rownames(raw_data),
      合計得点 = rowSums(raw_data),
      lra_membership
    )
    rownames(lra_membership) <- NULL
    writeData(wb, "LRAランク所属", lra_membership, headerStyle = header_style)
    addStyle(wb, "LRAランク所属", body_style,
             rows = 2:(nrow(lra_membership)+1),
             cols = 1:ncol(lra_membership), gridExpand = TRUE)
    setColWidths(wb, "LRAランク所属", cols = 1:ncol(lra_membership), widths = "auto")
    freezePane(wb, "LRAランク所属", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "LRAランク所属",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 10: LRA 項目参照プロファイル (IRP) ==========
  addWorksheet(wb, "LRA項目参照プロファイル")
  tryCatch({{
    irp_df <- as.data.frame(res_lra$IRP)
    irp_df <- cbind(設問 = rownames(irp_df), irp_df)
    rownames(irp_df) <- NULL
    writeData(wb, "LRA項目参照プロファイル", irp_df, headerStyle = header_style)
    addStyle(wb, "LRA項目参照プロファイル", body_style,
             rows = 2:(nrow(irp_df)+1),
             cols = 1:ncol(irp_df), gridExpand = TRUE)
    setColWidths(wb, "LRA項目参照プロファイル", cols = 1:ncol(irp_df), widths = "auto")
    freezePane(wb, "LRA項目参照プロファイル", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "LRA項目参照プロファイル",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 11: LRA IRPインデックス ==========
  addWorksheet(wb, "LRA_IRPIndex")
  tryCatch({{
    irp_idx_df <- as.data.frame(res_lra$IRPIndex)
    irp_idx_df <- cbind(設問 = rownames(irp_idx_df), irp_idx_df)
    rownames(irp_idx_df) <- NULL
    writeData(wb, "LRA_IRPIndex", irp_idx_df, headerStyle = header_style)
    addStyle(wb, "LRA_IRPIndex", body_style,
             rows = 2:(nrow(irp_idx_df)+1),
             cols = 1:ncol(irp_idx_df), gridExpand = TRUE)
    setColWidths(wb, "LRA_IRPIndex", cols = 1:ncol(irp_idx_df), widths = "auto")
    freezePane(wb, "LRA_IRPIndex", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "LRA_IRPIndex",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 12: RC 受験者ランク所属 ==========
  addWorksheet(wb, "RCランク所属")
  tryCatch({{
    rc_students <- as.data.frame(res_rc$Students)
    rc_students <- cbind(
      受験者 = rownames(raw_data),
      合計得点 = rowSums(raw_data),
      rc_students
    )
    rownames(rc_students) <- NULL
    writeData(wb, "RCランク所属", rc_students, headerStyle = header_style)
    addStyle(wb, "RCランク所属", body_style,
             rows = 2:(nrow(rc_students)+1),
             cols = 1:ncol(rc_students), gridExpand = TRUE)
    setColWidths(wb, "RCランク所属", cols = 1:ncol(rc_students), widths = "auto")
    freezePane(wb, "RCランク所属", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "RCランク所属",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 13: RC 設問フィールド所属 ==========
  addWorksheet(wb, "RC設問フィールド所属")
  tryCatch({{
    rc_field_df <- as.data.frame(res_rc$FieldMembership)
    rc_field_df <- cbind(設問 = rownames(rc_field_df), rc_field_df)
    rownames(rc_field_df) <- NULL
    # フィールド推定値を追加
    rc_field_df$推定フィールド <- as.numeric(res_rc$FieldEstimated)
    writeData(wb, "RC設問フィールド所属", rc_field_df, headerStyle = header_style)
    addStyle(wb, "RC設問フィールド所属", body_style,
             rows = 2:(nrow(rc_field_df)+1),
             cols = 1:ncol(rc_field_df), gridExpand = TRUE)
    setColWidths(wb, "RC設問フィールド所属", cols = 1:ncol(rc_field_df), widths = "auto")
    freezePane(wb, "RC設問フィールド所属", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "RC設問フィールド所属",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 14: RC フィールド参照プロファイル (FRP) ==========
  addWorksheet(wb, "RCフィールド参照プロファイル")
  tryCatch({{
    frp_df <- as.data.frame(res_rc$FRP)
    frp_df <- cbind(フィールド = rownames(frp_df), frp_df)
    rownames(frp_df) <- NULL
    writeData(wb, "RCフィールド参照プロファイル", frp_df, headerStyle = header_style)
    addStyle(wb, "RCフィールド参照プロファイル", body_style,
             rows = 2:(nrow(frp_df)+1),
             cols = 1:ncol(frp_df), gridExpand = TRUE)
    setColWidths(wb, "RCフィールド参照プロファイル", cols = 1:ncol(frp_df), widths = "auto")
    freezePane(wb, "RCフィールド参照プロファイル", firstRow = TRUE, firstCol = TRUE)
  }}, error = function(e) {{
    writeData(wb, "RCフィールド参照プロファイル",
              data.frame(メッセージ = paste("エラー:", e$message)))
  }})

  # ========== Sheet 15: 設問情報 ==========
  addWorksheet(wb, "設問情報")
  writeData(wb, "設問情報", item_info, headerStyle = header_style)
  addStyle(wb, "設問情報", body_style,
           rows = 2:(nrow(item_info)+1),
           cols = 1:ncol(item_info), gridExpand = TRUE)
  setColWidths(wb, "設問情報", cols = 1:ncol(item_info), widths = "auto")
  freezePane(wb, "設問情報", firstRow = TRUE)

  # --- Excel保存 ---
  excel_path <- "analysis_results.xlsx"
  saveWorkbook(wb, excel_path, overwrite = TRUE)
  message(paste("Excel出力完了:", excel_path))

}} else {{
  message("openxlsxパッケージが未インストールのため、Excelファイルは生成されません。")
  message("install.packages('openxlsx') でインストールしてください。")
}}
```

*このレポートは [exametrika](https://kosugitti.github.io/exametrika/) パッケージにより生成されました。*
'''
    with open(str(output_path), "w", encoding="utf-8") as f:
        f.write(content)
