#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
student_id_review_gui.py — 学籍番号OCR候補の確認・修正画面。

student_id_ocr.py が生成したOCR候補（{ファイル名: {'thumbnail_path','text',
'confidence','per_digit','per_digit_proba'}}）を、教員が答案画像を見ながら
確認・修正するためのモーダル画面。main_src/gui_components.py の MarkCheckerGUI
（OMRの未マーク/ダブルマークを画像を見ながら確認する画面）と同じ設計思想を踏襲する:

    - デフォルトはグリッド一覧（サムネイル＋OCR候補を並べて一覧表示）
    - 確信度が低いカードは枠を目立たせる
    - カードをクリックすると単体表示に切り替わり、Entry で修正できる
    - クリックしなかったカードは OCR 候補をそのまま採用する

名簿がある場合、1位候補の文字列がそのまま名簿と完全一致しなくても、
roster_matcher.rank_roster_candidates で桁ごとの確率分布から名簿候補を
ランキングし、単体表示にクリックで採用できる候補ボタンとして提示する
（手書き数字OCRは1桁だけ誤読することが多く、1位候補だけでは名簿に
一致しないケースを拾うため）。最有力候補が十分優勢(AUTO_APPLY_MIN_
CANDIDATE_PROB以上)な場合は、グリッド一覧を開いた時点で確定値(text/name)
にその候補を自動採用する。これは、候補を「表示するだけ」だと教員が全カード
を単体表示で開いて確認しない限り集計（学籍番号(確認済み)列）へ反映されない
ためで、自動採用したカードは橙色の枠で「要確認」と分かるようにする。

MarkCheckerGUI が独立ツール(fire-and-forget)として動くのに対し、この画面は
name_trimmer.select_region_on_image() と同様に「モーダルで開いて、閉じたら
結果を返す」同期的な使い方をする(run() が最終結果を返す)。
"""

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Dict, List, Optional

from PIL import Image, ImageTk

from constants import get_ui_font_family, get_ui_font_size, fit_window_to_content
from roster_matcher import rank_roster_candidates

logger = logging.getLogger(__name__)

UI_FONT = get_ui_font_family()

LOW_CONFIDENCE_THRESHOLD = 0.80

# 名簿候補（roster_matcher.rank_roster_candidates）の提示件数
ROSTER_CANDIDATE_TOP_K = 3

# 名簿候補の最有力候補をこの相対確率(%)以上で自動採用する（未満の場合は
# 候補が拮抗している＝自動採用せず、教員の手動選択に委ねる）。
AUTO_APPLY_MIN_CANDIDATE_PROB = 50.0

# 1位候補が2位候補よりこのポイント(pt)以上勝っていない場合は自動採用しない。
# 学籍番号の末尾1桁だけが違う学生が多い名簿では、1位候補が閾値を超えていても
# 2位候補（＝別の実在する学生）とほぼ拮抗しているケースがあり、その場合に
# 自動採用すると誤って別人に確定してしまう。
AUTO_APPLY_MIN_MARGIN = 20.0

# 学籍番号の重複（同じ学籍番号が複数枚に割り当てられている）を示す警告色。
# 他のどの状態（確信度・自動採用）よりも優先して表示する。
DUPLICATE_BORDER_COLOR = '#BA68C8'

GRID_THUMB_WIDTH = 140
GRID_COLUMNS = 4

SINGLE_THUMB_WIDTH = 420

# 氏名欄サムネイル（学籍番号欄と並べて表示し、見比べやすくする）
GRID_NAME_THUMB_WIDTH = 100
SINGLE_NAME_THUMB_WIDTH = 220


class StudentIdReviewGUI:
    """学籍番号OCR候補の確認・修正画面。"""

    def __init__(
        self, parent, ocr_results: Dict[str, Dict], roster: Optional[Dict[str, str]] = None,
        exam_page: Optional[int] = None,
    ):
        self.parent = parent
        self.roster = roster or {}
        self.exam_page = exam_page  # 複数ページ案件のみ設定される
        self._photo_refs = []  # ImageTk.PhotoImage の参照保持(GC対策)

        self._filenames: List[str] = sorted(ocr_results.keys())
        # 確認前の候補をそのままコピーして「確定値」の初期状態とする
        self.confirmed: Dict[str, Dict] = {}
        for filename, info in ocr_results.items():
            raw_text = (info.get('text') or '').strip()
            exact_name = self.roster.get(raw_text) if self.roster else None
            candidates = (
                rank_roster_candidates(
                    info.get('per_digit_proba') or [], self.roster, top_k=ROSTER_CANDIDATE_TOP_K,
                )
                if self.roster else []
            )

            text, name, auto_applied = raw_text, exact_name, False
            if self.roster and not exact_name and candidates:
                # 完全一致がない場合、名簿候補の最有力候補が「十分優勢」なら
                # 初期値として自動採用する。手書き数字OCRは1桁だけの誤読が
                # 多く、生のOCR文字列のままでは集計時に誤った学籍番号が
                # 使われてしまうため（候補の提示だけでは教員が全カードを
                # 開いて確認しない限り集計へ反映されない）。
                # 「十分優勢」は絶対値(AUTO_APPLY_MIN_CANDIDATE_PROB)と
                # 2位候補との差(AUTO_APPLY_MIN_MARGIN)の両方で判定する。
                # 末尾1桁違いの学生が多い名簿では、1位候補が閾値を超えていても
                # 2位候補（＝別の実在学生）と僅差なことがあり、差が小さい
                # 場合は自動採用せず教員の目視判断に委ねる。
                top_id, top_name, top_pct = candidates[0]
                runner_up_pct = candidates[1][2] if len(candidates) > 1 else 0.0
                if (
                    top_pct >= AUTO_APPLY_MIN_CANDIDATE_PROB
                    and (top_pct - runner_up_pct) >= AUTO_APPLY_MIN_MARGIN
                ):
                    text, name, auto_applied = top_id, top_name, True

            self.confirmed[filename] = {
                'thumbnail_path': info.get('thumbnail_path'),
                'text': text,
                'confidence': info.get('confidence', 0.0),
                'name': name,
                'edited': False,
                'auto_applied': auto_applied,
                'roster_candidates': candidates,
            }

        self._current_index = 0

        self.window = tk.Toplevel(parent)
        title = "学籍番号OCR候補の確認"
        if self.exam_page is not None:
            title += f"（試験ページ {self.exam_page}）"
        self.window.title(title)
        self.window.geometry("900x650")
        self.window.protocol("WM_DELETE_WINDOW", self._finish)

        self._grid_frame = tk.Frame(self.window)
        self._single_frame = tk.Frame(self.window)

        self._build_grid_view()
        self._grid_frame.pack(fill=tk.BOTH, expand=True)
        fit_window_to_content(self.window, min_width=640, min_height=480)

        self.window.grab_set()

    def run(self) -> Dict[str, Dict]:
        """モーダル表示し、閉じられたら確定結果を返す。"""
        self.window.wait_window()
        return self.confirmed

    # ------------------------------------------------------------
    # グリッド一覧
    # ------------------------------------------------------------

    def _duplicate_ids(self) -> Dict[str, List[str]]:
        """現在の確定値内で同じ学籍番号が複数枚に割り当てられている場合、
        {学籍番号: [ファイル名, ...]} を返す(2枚以上の場合のみ)。"""
        by_id: Dict[str, List[str]] = {}
        for filename, info in self.confirmed.items():
            text = (info.get('text') or '').strip()
            if text:
                by_id.setdefault(text, []).append(filename)
        return {sid: files for sid, files in by_id.items() if len(files) > 1}

    def _missing_students(self) -> Dict[str, str]:
        """名簿にいるが、現在の確定値のどれにも割り当てられていない学籍番号を
        {学籍番号: 氏名} で返す。名簿が無ければ空。"""
        if not self.roster:
            return {}
        assigned = {(info.get('text') or '').strip() for info in self.confirmed.values()}
        return {sid: name for sid, name in self.roster.items() if sid not in assigned}

    def _build_grid_view(self):
        for child in self._grid_frame.winfo_children():
            child.destroy()

        header = tk.Frame(self._grid_frame, bg="#37474F")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="学籍番号OCR候補の確認 — おかしいものだけクリックして修正してください",
            font=(UI_FONT, get_ui_font_size(11), 'bold'), bg="#37474F", fg="white",
        ).pack(side=tk.LEFT, padx=10, pady=8)
        tk.Button(
            header, text="完了", command=self._finish,
            bg="#2E7D32", fg="black", font=(UI_FONT, get_ui_font_size(10), 'bold'),
        ).pack(side=tk.RIGHT, padx=10, pady=6)

        duplicates = self._duplicate_ids()
        missing = self._missing_students()
        if duplicates or missing:
            warn = tk.Frame(self._grid_frame, bg="#FFF3E0")
            lines = []
            if duplicates:
                dup_text = "、".join(f"{sid}（{len(files)}枚）" for sid, files in duplicates.items())
                lines.append(f"⚠ 学籍番号が重複しています（同じ番号が複数枚に付いています）: {dup_text}")
            if missing:
                miss_text = "、".join(f"{sid} {name}" for sid, name in missing.items())
                lines.append(f"⚠ 名簿にいるが対応する答案が見つからない学生（未提出、または別番号に誤認識された可能性）: {miss_text}")
            tk.Label(
                warn, text="\n".join(lines), font=(UI_FONT, get_ui_font_size(9), 'bold'),
                bg="#FFF3E0", fg="#E65100", justify=tk.LEFT, wraplength=820, anchor=tk.W,
            ).pack(fill=tk.X, padx=10, pady=6)
            warn.pack(fill=tk.X)

        # 縦スクロールに加え、横スクロールバーも付ける（カード幅×列数が
        # ウィンドウ幅を超えても、右側が見えないまま気付けない状態を防ぐ）。
        canvas_frame = tk.Frame(self._grid_frame, bg="#ECEFF1")
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(canvas_frame, bg="#ECEFF1", highlightthickness=0)
        v_scrollbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        h_scrollbar = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)
        inner = tk.Frame(canvas, bg="#ECEFF1")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _on_shift_mousewheel(event):
            canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Shift-MouseWheel>", _on_shift_mousewheel)

        for i, filename in enumerate(self._filenames):
            row, col = divmod(i, GRID_COLUMNS)
            self._create_grid_card(inner, filename, row, col, duplicates)

    def _quick_select_candidate(self, filename: str, student_id: str):
        """グリッドカード上の候補ボタンから直接学籍番号を選び直す（単体表示を
        開かなくても、目視確認だけでその場で修正できるようにするため）。"""
        info = self.confirmed[filename]
        name = self.roster.get(student_id) if self.roster else None
        info['edited'] = info['edited'] or (student_id != (info.get('text') or ''))
        info['text'] = student_id
        info['name'] = name
        info['auto_applied'] = False
        self._build_grid_view()

    def _create_grid_card(self, parent, filename, row, col, duplicates=None):
        info = self.confirmed[filename]
        confidence = info.get('confidence', 0.0)
        edited = info.get('edited', False)
        auto_applied = info.get('auto_applied', False)
        current_text = (info.get('text') or '').strip()
        is_duplicate = bool(duplicates and current_text in duplicates)

        if is_duplicate:
            border_color = DUPLICATE_BORDER_COLOR  # 紫: 学籍番号の重複（最優先で警告）
        elif edited:
            border_color = '#81C784'  # 緑: 教員が確認・修正済み
        elif confidence < LOW_CONFIDENCE_THRESHOLD:
            border_color = '#EF5350'  # 赤: 要確認（OCR自体の確信度が低い）
        elif auto_applied:
            border_color = '#FFB74D'  # 橙: 名簿候補を自動採用・要確認
        else:
            border_color = '#E0E0E0'  # グレー: 通常

        card = tk.Frame(parent, bg=border_color, padx=2, pady=2)
        card.grid(row=row, column=col, padx=6, pady=6, sticky='nsew')
        parent.columnconfigure(col, weight=1)

        inner = tk.Frame(card, bg='white')
        inner.pack(fill=tk.BOTH, expand=True)

        # 学籍番号欄画像の下に、氏名欄画像（あれば）を並べて表示し、見比べやすく
        # する。氏名欄画像はStudentIdReviewGUI呼び出し側でトリミング済みの
        # 場合のみ('name_thumbnail_path')渡ってくる（無くても従来通り動作する）。
        img_col = tk.Frame(inner, bg='white')
        img_col.pack(padx=2, pady=2)

        clickable_widgets = [card, inner, img_col]

        photo = self._load_photo(info.get('thumbnail_path'), GRID_THUMB_WIDTH)
        if photo:
            img_label = tk.Label(img_col, image=photo, bg='white')
        else:
            img_label = tk.Label(img_col, text="(画像なし)", bg='white', fg='gray')
        img_label.pack(side=tk.TOP)
        clickable_widgets.append(img_label)

        name_photo = self._load_photo(info.get('name_thumbnail_path'), GRID_NAME_THUMB_WIDTH)
        if name_photo:
            name_img_label = tk.Label(img_col, image=name_photo, bg='white')
            name_img_label.pack(side=tk.TOP, pady=(3, 0))
            clickable_widgets.append(name_img_label)

        name_text = info.get('name')
        candidates = info.get('roster_candidates') or []
        if self.roster and info.get('auto_applied') and name_text:
            # 名簿候補を自動採用した値。教員の確認前であることが分かるよう明示する。
            top_pct = candidates[0][2] if candidates else None
            name_text = f"{name_text}（推定{top_pct:.0f}%・要確認）" if top_pct is not None else f"{name_text}（推定・要確認）"
        elif self.roster and not name_text:
            if candidates:
                top_id, top_name, top_pct = candidates[0]
                name_text = f"候補: {top_id} {top_name}（{top_pct:.0f}%）"
            else:
                name_text = "名簿に一致なし"
        display_text = info.get('text') or "(空欄)"
        if is_duplicate:
            display_text += "\n⚠ 学籍番号が重複"
        if name_text:
            display_text += f"\n{name_text}"

        info_label = tk.Label(
            inner, text=display_text, font=(UI_FONT, get_ui_font_size(9)),
            bg='white', fg='#333', justify=tk.CENTER,
        )
        info_label.pack(padx=2, pady=(0, 4))
        clickable_widgets.append(info_label)

        def on_click(event, target=filename):
            self._switch_to_single(target)
        for widget in clickable_widgets:
            widget.bind("<Button-1>", on_click)
            widget.configure(cursor='hand2')

        # 名簿候補を上位から並べたクリック選択ボタン（末尾1桁違いなど、複数の
        # 実在する学生が候補になり得る場合に、単体表示を開かず一目で見比べて
        # その場で選び直せるようにする）。現在採用中の候補には✓を付ける。
        if self.roster and candidates:
            cand_box = tk.Frame(inner, bg='white')
            cand_box.pack(fill=tk.X, padx=3, pady=(0, 3))
            for rank, (cand_id, cand_name, pct) in enumerate(candidates, start=1):
                is_selected = (cand_id == current_text)
                tk.Button(
                    cand_box,
                    text=f"{'✓ ' if is_selected else ''}{rank}位 {cand_name}（{pct:.0f}%）",
                    font=(UI_FONT, get_ui_font_size(7), 'bold' if is_selected else 'normal'),
                    bg='#C8E6C9' if is_selected else '#F5F5F5', fg='#333',
                    relief=tk.FLAT, anchor='w', padx=2, pady=1,
                    command=lambda cid=cand_id, fn=filename: self._quick_select_candidate(fn, cid),
                ).pack(fill=tk.X, pady=1)

    # ------------------------------------------------------------
    # 単体表示（修正画面）
    # ------------------------------------------------------------

    def _switch_to_single(self, filename):
        self._current_index = self._filenames.index(filename)
        self._grid_frame.pack_forget()
        self._build_single_view()
        self._single_frame.pack(fill=tk.BOTH, expand=True)

    def _build_single_view(self):
        for child in self._single_frame.winfo_children():
            child.destroy()

        filename = self._filenames[self._current_index]
        info = self.confirmed[filename]

        header = tk.Frame(self._single_frame, bg="#37474F")
        header.pack(fill=tk.X)
        tk.Label(
            header, text=f"{filename}  ({self._current_index + 1}/{len(self._filenames)})",
            font=(UI_FONT, get_ui_font_size(11), 'bold'), bg="#37474F", fg="white",
        ).pack(side=tk.LEFT, padx=10, pady=8)
        tk.Button(
            header, text="一覧に戻る", command=self._back_to_grid,
            bg="#546E7A", fg="black", font=(UI_FONT, get_ui_font_size(9)),
        ).pack(side=tk.RIGHT, padx=10, pady=6)

        img_col = tk.Frame(self._single_frame)
        img_col.pack(padx=20, pady=20)

        photo = self._load_photo(info.get('thumbnail_path'), SINGLE_THUMB_WIDTH)
        img_label = tk.Label(img_col, image=photo, bg='white', relief=tk.SUNKEN)
        img_label.pack(side=tk.TOP)

        name_photo = self._load_photo(info.get('name_thumbnail_path'), SINGLE_NAME_THUMB_WIDTH)
        if name_photo:
            name_img_label = tk.Label(img_col, image=name_photo, bg='white', relief=tk.SUNKEN)
            name_img_label.pack(side=tk.TOP, pady=(12, 0))

        input_frame = tk.Frame(self._single_frame)
        input_frame.pack(pady=10)
        tk.Label(input_frame, text="学籍番号:", font=(UI_FONT, get_ui_font_size(10))).pack(side=tk.LEFT)
        entry = tk.Entry(input_frame, font=(UI_FONT, get_ui_font_size(12)), width=16, justify=tk.CENTER)
        entry.insert(0, info.get('text') or '')
        entry.pack(side=tk.LEFT, padx=8)
        entry.focus_set()
        entry.selection_range(0, tk.END)
        self._current_entry = entry

        self._match_label = tk.Label(self._single_frame, text='', font=(UI_FONT, get_ui_font_size(10)), fg='#1565C0')
        self._match_label.pack(pady=(0, 6))
        self._update_match_label(entry.get())
        entry.bind('<KeyRelease>', lambda e: self._update_match_label(entry.get()))
        entry.bind('<Return>', lambda e: self._confirm_and_next())

        candidates = info.get('roster_candidates') or []
        if candidates:
            cand_frame = tk.Frame(self._single_frame)
            cand_frame.pack(pady=(0, 10))
            tk.Label(
                cand_frame, text="名簿候補（確信度順・クリックで採用）:",
                font=(UI_FONT, get_ui_font_size(8)), fg='#555',
            ).pack(anchor=tk.W)
            btn_row = tk.Frame(cand_frame)
            btn_row.pack()
            for cand_id, cand_name, pct in candidates:
                tk.Button(
                    btn_row, text=f"{cand_id} {cand_name}（{pct:.0f}%）",
                    font=(UI_FONT, get_ui_font_size(9)),
                    command=lambda cid=cand_id: self._apply_candidate(cid),
                ).pack(side=tk.LEFT, padx=3)

        nav_frame = tk.Frame(self._single_frame)
        nav_frame.pack(pady=10)
        tk.Button(nav_frame, text="◀ 前へ", command=self._go_previous,
                  font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text="確定 (Enter)", command=self._confirm_and_next,
                  bg="#2E7D32", fg="black", font=(UI_FONT, get_ui_font_size(10), 'bold')).pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text="次へ ▶", command=self._go_next,
                  font=(UI_FONT, get_ui_font_size(9))).pack(side=tk.LEFT, padx=5)

    def _apply_candidate(self, student_id: str):
        """名簿候補ボタンのクリック時、Entryへ候補の学籍番号を反映する。"""
        self._current_entry.delete(0, tk.END)
        self._current_entry.insert(0, student_id)
        self._update_match_label(student_id)

    def _update_match_label(self, text):
        text = text.strip()
        name = self.roster.get(text) if self.roster else None
        if not self.roster:
            self._match_label.config(text='')
        elif name:
            self._match_label.config(text=f"名簿照合: {name}", fg='#1565C0')
        else:
            self._match_label.config(text="名簿に一致する学籍番号がありません", fg='#C62828')

    def _confirm_current(self):
        filename = self._filenames[self._current_index]
        info = self.confirmed[filename]
        new_text = self._current_entry.get().strip()
        name = self.roster.get(new_text) if self.roster else None
        info['edited'] = info['edited'] or (new_text != (info.get('text') or ''))
        info['text'] = new_text
        info['name'] = name
        if info['edited']:
            # 教員が値を変えた時点で「自動採用（推定）」の表示は役目を終える。
            info['auto_applied'] = False

    def _confirm_and_next(self):
        self._confirm_current()
        self._go_next()

    def _go_next(self):
        self._confirm_current_silent_if_unsaved()
        if self._current_index < len(self._filenames) - 1:
            self._current_index += 1
            self._build_single_view()
        else:
            self._back_to_grid()

    def _go_previous(self):
        self._confirm_current_silent_if_unsaved()
        if self._current_index > 0:
            self._current_index -= 1
            self._build_single_view()

    def _confirm_current_silent_if_unsaved(self):
        """前へ/次へ移動時、Entryの内容を確定してから移動する。"""
        self._confirm_current()

    def _back_to_grid(self):
        self._confirm_current()
        self._single_frame.pack_forget()
        self._build_grid_view()
        self._grid_frame.pack(fill=tk.BOTH, expand=True)

    def _finish(self):
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    # ------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------

    def _load_photo(self, path, max_width):
        if not path or not Path(path).exists():
            return None
        try:
            with Image.open(path) as img:
                w, h = img.size
                if w > max_width:
                    ratio = max_width / w
                    img = img.resize((max_width, max(1, int(h * ratio))), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img, master=self.window)
        except Exception as e:
            logger.warning("画像の読み込みに失敗しました: %s — %s", path, e)
            return None
        self._photo_refs.append(photo)
        return photo
