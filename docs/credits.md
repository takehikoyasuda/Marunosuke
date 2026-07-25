# クレジット・謝辞

採点侍は、デジタル採点に携わってこられた方々のソフトウェアやプロジェクトを参考にして開発しました。
ここに感謝と敬意を表します。

---

## 開発者

<div class="feature-card" markdown>

### phys-ken

採点侍（SaitenSamurai）および採点斬り 2021 のオリジナル開発者（Windows 向け）。本フォークは氏の [phys-ken/SaitenSamurai](https://github.com/phys-ken/SaitenSamurai)（GPL-3.0）を macOS 向けに移植したものです。

:material-web: [https://phys-ken.github.io/phys-ken/](https://phys-ken.github.io/phys-ken/)  
:material-github: [https://github.com/phys-ken](https://github.com/phys-ken)

</div>

<div class="feature-card" markdown>

### Takehiko Yasuda

本フォーク（[SaitenSamurai-mac](https://github.com/takehikoyasuda/SaitenSamurai-mac)）の macOS 対応。

:material-github: [https://github.com/takehikoyasuda](https://github.com/takehikoyasuda)

</div>

---

## 採点侍の成り立ち

**採点侍（SaitenSamurai）** は、開発者が 2021 年に公開した **[採点斬り 2021](https://github.com/phys-ken/saitenGiri2021)** の後継ソフトです。

採点斬り 2021 は記述式答案の採点に特化していましたが、採点侍ではそこに **Mark2 対応のマークシート自動採点** と **CTT（古典的テスト理論）分析** を加え、マーク式・記述式・混合試験のすべてを 1 本で処理できるソフトウェアとして生まれ変わりました。

---

## 参考にしたソフトウェア

### 採点斬り — 島守睦美 氏

「答案をスキャナで読み込み、問題ごとに画像を切り出して効率的に採点する」というデジタル採点のコンセプトを確立したフリーソフトです。採点斬り 2021 → 採点侍の出発点となりました。

- **開発者**: 島守睦美 氏
- **技術**: Visual Basic
- **公開サイト**: 私立島守学園（現在はアクセス不可）
- **紹介ページ**: [アーカイブ（Wayback Machine）](https://web.archive.org/web/20160625063811/http://www.nurs.or.jp/~lionfan/freesoft_49.html)

### 採点革命 — 竹内俊彦 氏

採点斬りの元となった「採点革命」は、竹内俊彦氏が開発したデジタル採点のソフトウェアです。

- **開発者**: 竹内俊彦 氏
- **技術**: HSP
- **紹介ページ**: [アーカイブ（Wayback Machine）](https://web.archive.org/web/20161024200711/http://www.nurs.or.jp/~lionfan/freesoft_45.html)

### MarkScan — 神奈川県教育委員会

神奈川県教育委員会が公開しているマークシート処理フリーソフトです。開発者自身が教員として日常的に使用しており、操作フローを参考にしました。

- **公式サイト**: [MarkScan](https://markscan.sakuraweb.com/)
- **用途**: マークシートの読み取り・集計

### デジタル採点 All in One — Object Pascalと僕と

模範解答の表示方法など、採点結果の出力の見せ方を参考にさせていただきました。マークシートリーダーと手書き答案採点を含む統合パッケージを公開されています。

- :material-web: [https://coding-tips-memoranda.com/デジタル採点-all-in-one/](https://coding-tips-memoranda.com/%E3%83%87%E3%82%B8%E3%82%BF%E3%83%AB%E6%8E%A1%E7%82%B9-all-in-one/)

---

## 技術基盤

### Mark2 — 慶應義塾大学 SFC 研究所

マークシートの座標系（595×842 pt, A4）と OMR 認識ロジックの技術基盤として利用しています。採点侍は Mark2 形式の座標ファイルに全面的に依存しており、Mark2 なしには成立しないソフトウェアです。

- **ライセンス**: MIT
- :material-web: [https://mark2.sfc.keio.ac.jp/ja/](https://mark2.sfc.keio.ac.jp/ja/)

### 採点斬り 2021 — phys-ken

「採点革命」「採点斬り」「MarkScan」のコンセプトを参考に、現在の環境でも動作する Python 版として開発したプロジェクトです。採点侍の記述式採点機能は、このプロジェクトの設計をベースにしています。

- **ライセンス**: GPL-3.0
- :material-web: [https://phys-ken.github.io/saitenGiri2021/](https://phys-ken.github.io/saitenGiri2021/)
- :material-github: [https://github.com/phys-ken/saitenGiri2021](https://github.com/phys-ken/saitenGiri2021)

---

## 使用ライブラリ

| ライブラリ | ライセンス | 用途 |
|---|---|---|
| OpenCV (headless) | Apache-2.0 / MIT | 画像処理・OMR |
| NumPy | BSD 3-Clause | 数値計算 |
| pandas | BSD 3-Clause | データフレーム処理 |
| Pillow | HPND | 画像描画 |
| openpyxl | MIT | Excel 入出力 |
| PyMuPDF | AGPL-3.0 | PDF→画像変換（オプション） |
| matplotlib | PSF/BSD 互換 | CTT グラフ描画 |
| ReportLab | BSD 3-Clause | CTT PDF レポート |
| PyInstaller | GPL-2.0+（Bootloader Exception 付） | exe ビルド |

詳細は [THIRDPARTYLICENSES.md](https://github.com/takehikoyasuda/SaitenSamurai-mac/blob/main/THIRDPARTYLICENSES.md) をご確認ください。
