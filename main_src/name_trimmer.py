#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
name_trimmer.py — 氏名エリアトリミングモジュール

概要:
    解答用紙画像から「氏名エリア」をGUIで選択し、全画像から一括トリミングする。
    Mark2の射影変換済み画像（00_Processing/）を入力とすることで、
    スキャン傾きの影響を排除した正確なトリミングを実現する。

設計方針:
    - GUI矩形選択（select_region_on_image）とトリミング処理（trim_images）を
      独立した汎用関数として提供し、将来の記述式得点エリア選択等にも再利用可能
    - NameTrimmer クラスは上記を組み合わせた統合実行（run）を提供
    - Excel出力は呼び出し側（generate_student_summary）の責務とし、ここでは行わない

元コード:
    legacy_trim_app/name_trim.py（NameTrimmerクラス）を Mark2 用に再設計

必要ライブラリ:
    - Pillow (PIL) : 画像処理（crop, resize）
    - tkinter      : GUI（矩形選択）
"""

import logging
import shutil
import tempfile
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from typing import Optional, Tuple, List, Dict

logger = logging.getLogger(__name__)

from constants import get_app_temp_dir

from PIL import Image, ImageTk


# ============================================================
# 定数
# ============================================================

# 画像ファイルとして扱う拡張子
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff'}

# トリミング後の名前画像の最大高さ（ピクセル）
DEFAULT_MAX_HEIGHT = 50

# GUI表示用の最大幅・高さ（ズーム倍率1.0の時のビューポートサイズとしても使う）
MAX_DISPLAY_WIDTH = 700
MAX_DISPLAY_HEIGHT = 700

# ズーム対応の矩形選択ダイアログ用の定数
MIN_ZOOM = 1.0
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25


# ============================================================
# ユーティリティ関数
# ============================================================

def get_image_files(folder_path: str) -> List[str]:
    """
    指定フォルダ内の画像ファイルをソート済みリストで返す。

    Args:
        folder_path: 画像フォルダのパス

    Returns:
        画像ファイルのフルパスのソート済みリスト
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        return []

    image_files = []
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(str(f))
    return image_files


# ============================================================
# 汎用関数: GUI矩形選択
# ============================================================

def select_region_on_image(
    image_path: str,
    parent: Optional[tk.Tk] = None,
    title: str = "名前エリアの選択 — ドラッグで矩形を描いてください",
    label_text: str = "名前エリア",
    instruction_text: str = "画像上でマウスを\nドラッグして、\n名前が書かれた\nエリアを囲んで\nください。\n\n何度でも\nやり直せます。",
) -> Optional[Tuple[int, int, int, int]]:
    """
    GUIウィンドウを表示し、ユーザーにマウスドラッグで矩形を選択させる。

    マウスホイール／＋－ボタンで拡大縮小しながら選択できる（細かい範囲を
    正確に選びたい場合向け）。将来、記述式得点エリアの選択などにも再利用
    可能な汎用関数。legacy_trim_app/name_trim.py の select_name_area() を
    参考に再実装。

    Args:
        image_path: 表示する画像のパス
        parent:     親となるtkinterウィンドウ（Noneの場合は新規作成）
        title:      ウィンドウタイトル
        label_text: 選択領域に表示するラベルテキスト
        instruction_text: 操作説明テキスト

    Returns:
        (left, top, right, bottom) の座標タプル（元画像の実寸座標）。
        キャンセルされた場合は None。
    """
    original_img = Image.open(image_path).convert("RGB")
    orig_w, orig_h = original_img.size

    # zoom=1.0 のとき画像全体がビューポートに収まる基準スケール
    base_scale = min(MAX_DISPLAY_WIDTH / orig_w, MAX_DISPLAY_HEIGHT / orig_h, 1.0)

    state = {
        'zoom': 1.0,
        'rect_orig': None,   # 確定済み矩形（元画像実寸座標）
        'drag_id': None,     # ドラッグ中の仮矩形のcanvas item id
        'start_x': 0.0, 'start_y': 0.0,
        'photo': None,       # PhotoImage参照保持(GC対策)
        'overlay_photo': None,
    }

    owns_root = False
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        owns_root = True
    else:
        root = parent

    selector_win = tk.Toplevel(root)
    selector_win.title(title)

    main_frame = tk.Frame(selector_win)
    main_frame.pack(fill=tk.BOTH, expand=True)

    canvas_frame = tk.Frame(main_frame)
    canvas_frame.pack(side=tk.LEFT, padx=5, pady=5)

    button_frame = tk.Frame(main_frame)
    button_frame.pack(side=tk.RIGHT, padx=10, pady=10, fill=tk.Y)

    h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
    v_scroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
    canvas = tk.Canvas(
        canvas_frame, width=MAX_DISPLAY_WIDTH, height=MAX_DISPLAY_HEIGHT, bg="black",
        highlightthickness=0, xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set,
    )
    h_scroll.config(command=canvas.xview)
    v_scroll.config(command=canvas.yview)
    canvas.grid(row=0, column=0)
    v_scroll.grid(row=0, column=1, sticky='ns')
    h_scroll.grid(row=1, column=0, sticky='ew')

    def _total_scale():
        return base_scale * state['zoom']

    def _redraw_confirmed_rect():
        canvas.delete("region_overlay")
        canvas.delete("region_rect")
        canvas.delete("region_label")
        if state['rect_orig'] is None:
            return
        scale = _total_scale()
        ox1, oy1, ox2, oy2 = state['rect_orig']
        x1, y1, x2, y2 = ox1 * scale, oy1 * scale, ox2 * scale, oy2 * scale
        overlay_img = Image.new('RGBA', (max(1, round(x2 - x1)), max(1, round(y2 - y1))), (0, 200, 0, 80))
        overlay_tk = ImageTk.PhotoImage(overlay_img, master=selector_win)
        state['overlay_photo'] = overlay_tk
        canvas.create_image(x1, y1, image=overlay_tk, anchor='nw', tag="region_overlay")
        canvas.create_rectangle(x1, y1, x2, y2, outline="green", width=2, tag="region_rect")
        canvas.create_text(
            (x1 + x2) / 2, (y1 + y2) / 2, text=label_text, fill="white",
            font=("", 14, "bold"), tag="region_label",
        )

    def _redraw_image():
        scale = _total_scale()
        disp_w = max(1, round(orig_w * scale))
        disp_h = max(1, round(orig_h * scale))
        resized = original_img.resize((disp_w, disp_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(resized, master=selector_win)
        state['photo'] = photo
        canvas.delete("bg_image")
        canvas.create_image(0, 0, image=photo, anchor=tk.NW, tag="bg_image")
        canvas.tag_lower("bg_image")
        canvas.configure(scrollregion=(0, 0, disp_w, disp_h))
        _zoom_label.config(text=f"{state['zoom'] * 100:.0f}%")
        _redraw_confirmed_rect()

    def _on_press(event):
        """マウスボタン押下 → ドラッグ開始"""
        state['start_x'] = canvas.canvasx(event.x)
        state['start_y'] = canvas.canvasy(event.y)
        if state['drag_id'] is not None:
            canvas.delete(state['drag_id'])
            state['drag_id'] = None
        canvas.delete("region_overlay")
        canvas.delete("region_rect")
        canvas.delete("region_label")

    def _on_drag(event):
        """マウスドラッグ中 → 矩形をリアルタイム描画"""
        cx = canvas.canvasx(event.x)
        cy = canvas.canvasy(event.y)
        if state['drag_id'] is not None:
            canvas.coords(state['drag_id'], state['start_x'], state['start_y'], cx, cy)
        else:
            state['drag_id'] = canvas.create_rectangle(
                state['start_x'], state['start_y'], cx, cy,
                outline="red", width=2, dash=(4, 4),
            )

    def _on_release(event):
        """マウスボタン離す → 矩形確定"""
        cx = canvas.canvasx(event.x)
        cy = canvas.canvasy(event.y)
        sx, sy = state['start_x'], state['start_y']

        # 選択範囲が小さすぎる場合は無視
        if abs(cx - sx) < 5 or abs(cy - sy) < 5:
            return

        # 座標を正規化（左上 → 右下）
        x1, x2 = min(sx, cx), max(sx, cx)
        y1, y2 = min(sy, cy), max(sy, cy)

        if state['drag_id'] is not None:
            canvas.delete(state['drag_id'])
            state['drag_id'] = None

        scale = _total_scale()
        state['rect_orig'] = (x1 / scale, y1 / scale, x2 / scale, y2 / scale)
        _redraw_confirmed_rect()

    canvas.bind("<ButtonPress-1>", _on_press)
    canvas.bind("<B1-Motion>", _on_drag)
    canvas.bind("<ButtonRelease-1>", _on_release)

    def _zoom(factor):
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, state['zoom'] * factor))
        if new_zoom == state['zoom']:
            return
        state['zoom'] = new_zoom
        _redraw_image()

    def _pan(dx_units=0, dy_units=0):
        if dx_units:
            canvas.xview_scroll(dx_units, "units")
        if dy_units:
            canvas.yview_scroll(dy_units, "units")

    def _wheel_units(event) -> int:
        # Windows/Linuxではevent.deltaが120単位、macOSでは±1程度と環境依存のため、
        # 120で割った結果が0になる場合は符号だけで1単位動かす。
        units = int(-1 * (event.delta / 120))
        return units if units != 0 else (-1 if event.delta > 0 else 1)

    def _on_mousewheel(event):
        canvas.yview_scroll(_wheel_units(event), "units")

    def _on_shift_mousewheel(event):
        canvas.xview_scroll(_wheel_units(event), "units")

    canvas.bind("<MouseWheel>", _on_mousewheel)
    canvas.bind("<Shift-MouseWheel>", _on_shift_mousewheel)

    # --- 説明ラベル ---
    tk.Label(
        button_frame,
        text="操作方法",
        font=("", 12, "bold"),
    ).pack(pady=(0, 10))

    tk.Label(
        button_frame,
        text=instruction_text,
        justify=tk.LEFT,
        wraplength=160,
    ).pack(pady=(0, 15))

    # --- ズーム操作 ---
    zoom_group = tk.Frame(button_frame)
    zoom_group.pack(pady=(0, 15))
    tk.Label(zoom_group, text="拡大縮小", font=("", 9), wraplength=160, justify=tk.LEFT).pack()
    zoom_btns = tk.Frame(zoom_group)
    zoom_btns.pack(pady=5)
    tk.Button(zoom_btns, text="－", width=3, command=lambda: _zoom(1 / ZOOM_STEP)).pack(side=tk.LEFT, padx=2)
    _zoom_label = tk.Label(zoom_btns, text="100%", width=6)
    _zoom_label.pack(side=tk.LEFT, padx=4)
    tk.Button(zoom_btns, text="＋", width=3, command=lambda: _zoom(ZOOM_STEP)).pack(side=tk.LEFT, padx=2)

    # --- 移動(パン)操作 ---
    pan_group = tk.Frame(button_frame)
    pan_group.pack(pady=(0, 20))
    tk.Label(
        pan_group, text="移動（拡大後、マウスホイールや\nスクロールバーでも移動できます）",
        font=("", 9), wraplength=160, justify=tk.LEFT,
    ).pack()
    pan_grid = tk.Frame(pan_group)
    pan_grid.pack(pady=5)
    tk.Button(pan_grid, text="▲", width=3, command=lambda: _pan(dy_units=-2)).grid(row=0, column=1)
    tk.Button(pan_grid, text="◀", width=3, command=lambda: _pan(dx_units=-2)).grid(row=1, column=0)
    tk.Button(pan_grid, text="▶", width=3, command=lambda: _pan(dx_units=2)).grid(row=1, column=2)
    tk.Button(pan_grid, text="▼", width=3, command=lambda: _pan(dy_units=2)).grid(row=2, column=1)

    # --- ボタン ---
    def _confirm():
        if state['rect_orig'] is None:
            messagebox.showwarning(
                "未選択",
                "エリアが選択されていません。\n画像上でドラッグしてください。",
                parent=selector_win,
            )
            return
        selector_win.destroy()

    def _cancel():
        state['rect_orig'] = None
        selector_win.destroy()

    tk.Button(
        button_frame,
        text="✔ 決定",
        command=_confirm,
        width=15, height=2,
        bg="#4CAF50", fg="black",
        font=("", 11, "bold"),
    ).pack(pady=5)

    tk.Button(
        button_frame,
        text="✖ キャンセル",
        command=_cancel,
        width=15, height=2,
    ).pack(pady=5)

    selector_win.protocol("WM_DELETE_WINDOW", _cancel)

    _redraw_image()

    # モーダルにする
    selector_win.grab_set()
    selector_win.wait_window()

    if owns_root:
        root.destroy()

    if state['rect_orig'] is None:
        return None
    return tuple(round(v) for v in state['rect_orig'])


# ============================================================
# 汎用関数: 一括トリミング
# ============================================================

def trim_images(
    image_folder: str,
    trim_rect: Tuple[int, int, int, int],
    output_folder: str,
    max_height: int = DEFAULT_MAX_HEIGHT,
    original_image_folder: Optional[str] = None,
) -> List[str]:
    """
    全画像から指定座標をcropし、リサイズして保存する。
    
    original_image_folder が指定された場合、元画像から射影補正して
    高解像度で切り出す。00_Processing の 595x842 より鮮明な画像が得られる。

    Args:
        image_folder:  トリミング前の画像が格納されたフォルダのパス
        trim_rect:     (left, top, right, bottom) トリミング座標 (595x842座標系)
        output_folder: トリミング後の画像を保存するフォルダのパス
        max_height:    画像の最大高さ（px）。超える場合はアスペクト比保持リサイズ。
        original_image_folder: 元画像フォルダ (指定時は高解像度で切り出し)

    Returns:
        保存された画像ファイルパスのリスト
    """
    left, top, right, bottom = trim_rect

    output_path = Path(output_folder)
    if output_path.exists():
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    image_files = get_image_files(image_folder)
    if not image_files:
        return []

    # 高解像度モードの準備
    use_highres = original_image_folder is not None
    if use_highres:
        try:
            from image_alignment import (
                detect_corner_markers, apply_perspective_transform,
                compute_output_scale,
            )
        except ImportError:
            use_highres = False

    saved_files = []

    for img_path in image_files:
        try:
            filename = Path(img_path).name
            output_file = output_path / filename

            if use_highres:
                orig_path = Path(original_image_folder) / filename
                if orig_path.exists():
                    import cv2
                    import numpy as np
                    with open(str(orig_path), 'rb') as f:
                        img_bytes = f.read()
                    orig_img = cv2.imdecode(
                        np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR
                    )
                    if orig_img is not None:
                        try:
                            markers = detect_corner_markers(orig_img, debug=False)
                            scale = compute_output_scale(orig_img)
                            corrected, _ = apply_perspective_transform(
                                orig_img, markers, output_scale=scale
                            )
                            pil_corrected = Image.fromarray(
                                cv2.cvtColor(corrected, cv2.COLOR_BGR2RGB)
                            )
                            img_w, img_h = pil_corrected.size
                            cl = max(0, min(int(left * scale), img_w))
                            ct = max(0, min(int(top * scale), img_h))
                            cr = max(0, min(int(right * scale), img_w))
                            cb = max(0, min(int(bottom * scale), img_h))
                            if cl < cr and ct < cb:
                                cropped = pil_corrected.crop((cl, ct, cr, cb))
                                cropped.save(str(output_file), quality=90)
                                saved_files.append(str(output_file))
                                pil_corrected.close()
                                del orig_img, corrected
                                continue
                            else:
                                logger.debug("高解像度crop範囲が無効、フォールバック: %s", filename)
                                pil_corrected.close()
                                del orig_img, corrected
                        except Exception as marker_err:
                            logger.debug("高解像度マーカー検出失敗、フォールバック: %s — %s", filename, marker_err)
                            del orig_img

            # フォールバック: 00_Processing画像から直接切り出し
            with Image.open(img_path) as img:
                img_w, img_h = img.size
                clamped_left = max(0, min(left, img_w))
                clamped_top = max(0, min(top, img_h))
                clamped_right = max(0, min(right, img_w))
                clamped_bottom = max(0, min(bottom, img_h))

                if clamped_left >= clamped_right or clamped_top >= clamped_bottom:
                    logger.warning("トリミング領域が無効（スキップ）: %s", filename)
                    continue

                cropped = img.crop((clamped_left, clamped_top, clamped_right, clamped_bottom))
                cropped.save(str(output_file), quality=90)
                saved_files.append(str(output_file))
        except Exception as e:
            logger.error("トリミングエラー（スキップ）: %s — %s", Path(img_path).name, e)

    # 高さが max_height を超える場合はリサイズ
    if saved_files:
        with Image.open(saved_files[0]) as sample:
            name_w, name_h = sample.size
        if name_h > max_height:
            resize_ratio = name_h / max_height
            new_w = max(1, int(name_w / resize_ratio))
            new_h = max(1, int(name_h / resize_ratio))
            for f in saved_files:
                with Image.open(f) as img:
                    resized = img.resize((new_w, new_h), Image.LANCZOS)
                resized.save(f)

    return saved_files


# ============================================================
# NameTrimmer クラス
# ============================================================

class NameTrimmer:
    """
    氏名エリアのトリミングを管理するクラス。

    Mark2のメインGUIから run() を呼び出すと、
    GUI矩形選択 → 一括トリミング → ファイル名→画像パスの辞書を返却
    が一気通貫で実行される。

    射影変換済み画像（00_Processing/）を入力とすることで、
    スキャン傾きに依存しない正確なトリミングを実現する。
    """

    def __init__(self):
        """NameTrimmerを初期化する。"""
        self._last_trim_rect: Optional[Tuple[int, int, int, int]] = None
        self._temp_dir: Optional[str] = None

    @property
    def last_trim_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """最後に選択されたトリミング座標を返す。"""
        return self._last_trim_rect

    def run(
        self,
        image_folder: str,
        parent: Optional[tk.Tk] = None,
        max_height: int = DEFAULT_MAX_HEIGHT,
        original_image_folder: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """
        GUI選択 → 一括トリミング を実行し、ファイル名→画像パス辞書を返す。

        Args:
            image_folder: 射影変換済み画像が格納されたフォルダのパス
                          （通常は 00_Processing/）
            parent:       親となるtkinterウィンドウ（省略可）
            max_height:   名前画像の最大高さ（px）
            original_image_folder: 元画像フォルダ (指定時は高解像度で切り出し)

        Returns:
            {元ファイル名: トリミング画像パス} の辞書。
            キャンセルされた場合は None。
        """
        # --- Step 1: 入力画像の確認 ---
        image_files = get_image_files(image_folder)
        if not image_files:
            logger.error("画像フォルダに画像がありません: %s", image_folder)
            if parent:
                messagebox.showerror(
                    "エラー",
                    f"指定フォルダに画像がありません:\n{image_folder}",
                    parent=parent,
                )
            return None

        # --- Step 2: GUI で名前エリアを選択 ---
        logger.info("名前エリアを選択してください（1枚目の画像: %s）", Path(image_files[0]).name)
        trim_rect = select_region_on_image(image_files[0], parent=parent)
        if trim_rect is None:
            logger.info("キャンセルされました。")
            return None
        self._last_trim_rect = trim_rect
        logger.info("選択された座標: %s", trim_rect)

        # --- Step 3: 一時フォルダにトリミング ---
        _app_temp = get_app_temp_dir(str(Path(image_folder).parent.parent))
        temp_dir = tempfile.mkdtemp(prefix="name_trim_", dir=_app_temp)
        self._temp_dir = temp_dir
        logger.debug("一時保存先: %s", temp_dir)

        saved_files = trim_images(image_folder, trim_rect, temp_dir, max_height,
                                   original_image_folder=original_image_folder)
        logger.info("トリミング完了: %d枚", len(saved_files))

        # --- Step 4: ファイル名→パスの辞書を構築 ---
        name_images: Dict[str, str] = {}
        for trimmed_path in saved_files:
            filename = Path(trimmed_path).name
            name_images[filename] = trimmed_path

        return name_images

    def cleanup(self):
        """一時ファイルを削除する。"""
        if self._temp_dir and Path(self._temp_dir).exists():
            try:
                shutil.rmtree(self._temp_dir)
                logger.debug("一時ファイルを削除しました。")
            except Exception as e:
                logger.warning("一時ファイルの削除に失敗しました: %s", e)
            finally:
                self._temp_dir = None


# ============================================================
# 単体実行用エントリーポイント
# ============================================================

def main():
    """
    name_trimmer.py を単独で実行した場合のテスト用エントリーポイント。
    """
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()

    image_folder = filedialog.askdirectory(
        title="画像が入っているフォルダを選択してください"
    )
    if not image_folder:
        logger.info("キャンセルされました。")
        root.destroy()
        return

    trimmer = NameTrimmer()
    result = trimmer.run(image_folder=image_folder, parent=root)

    if result:
        logger.info("=== 結果 ===")
        for filename, path in result.items():
            logger.info("  %s → %s", filename, path)
        logger.info("合計: %d枚", len(result))
    else:
        logger.info("キャンセルまたはエラーで終了しました。")

    trimmer.cleanup()
    root.destroy()


if __name__ == "__main__":
    main()
