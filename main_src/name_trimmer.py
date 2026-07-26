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

# GUI表示用の最大幅・高さ
MAX_DISPLAY_WIDTH = 700
MAX_DISPLAY_HEIGHT = 700


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

    将来、記述式得点エリアの選択などにも再利用可能な汎用関数。
    legacy_trim_app/name_trim.py の select_name_area() を参考に再実装。

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
    # 画像を読み込み
    original_img = Image.open(image_path)
    orig_w, orig_h = original_img.size

    # --------------------------------------------------
    # 表示用リサイズ比率の計算
    # --------------------------------------------------
    if orig_w >= orig_h:
        if orig_w <= MAX_DISPLAY_WIDTH:
            resize_ratio = 1.0
        else:
            resize_ratio = orig_w / MAX_DISPLAY_WIDTH
    else:
        if orig_h <= MAX_DISPLAY_HEIGHT:
            resize_ratio = 1.0
        else:
            resize_ratio = orig_h / MAX_DISPLAY_HEIGHT

    display_w = int(orig_w / resize_ratio)
    display_h = int(orig_h / resize_ratio)
    display_img = original_img.resize(
        (display_w, display_h), Image.LANCZOS
    )
    original_img.close()  # リソース解放

    # --------------------------------------------------
    # GUI ウィンドウの構築
    # --------------------------------------------------
    result_rect = [None]  # リストで包んでクロージャ内から変更可能にする

    owns_root = False
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        owns_root = True
    else:
        root = parent

    selector_win = tk.Toplevel(root)
    selector_win.title(title)
    selector_win.geometry(f"{display_w + 200}x{display_h + 20}")
    selector_win.resizable(False, False)

    # --- レイアウト ---
    main_frame = tk.Frame(selector_win)
    main_frame.pack(fill=tk.BOTH, expand=True)

    canvas_frame = tk.Frame(main_frame)
    canvas_frame.pack(side=tk.LEFT, padx=5, pady=5)

    button_frame = tk.Frame(main_frame)
    button_frame.pack(side=tk.RIGHT, padx=10, pady=10, fill=tk.Y)

    # --- キャンバス ---
    canvas = tk.Canvas(
        canvas_frame,
        width=display_w,
        height=display_h,
        bg="black",
        highlightthickness=0,
    )
    tk_img = ImageTk.PhotoImage(display_img, master=selector_win)
    canvas.create_image(0, 0, image=tk_img, anchor=tk.NW)
    canvas.pack()

    # --- 矩形ドラッグ状態 ---
    drag_state = {"start_x": 0, "start_y": 0, "rect_id": None}
    overlay_refs = []  # GC防止用

    def _on_press(event):
        """マウスボタン押下 → ドラッグ開始"""
        drag_state["start_x"] = event.x
        drag_state["start_y"] = event.y
        if drag_state["rect_id"] is not None:
            canvas.delete(drag_state["rect_id"])
        canvas.delete("region_overlay")
        canvas.delete("region_rect")
        canvas.delete("region_label")

    def _on_drag(event):
        """マウスドラッグ中 → 矩形をリアルタイム描画"""
        ex = max(0, min(display_w, event.x))
        ey = max(0, min(display_h, event.y))

        if drag_state["rect_id"] is not None:
            canvas.coords(
                drag_state["rect_id"],
                drag_state["start_x"], drag_state["start_y"],
                ex, ey,
            )
        else:
            drag_state["rect_id"] = canvas.create_rectangle(
                drag_state["start_x"], drag_state["start_y"],
                ex, ey,
                outline="red", width=2, dash=(4, 4),
            )

    def _on_release(event):
        """マウスボタン離す → 矩形確定"""
        ex = max(0, min(display_w, event.x))
        ey = max(0, min(display_h, event.y))

        sx = drag_state["start_x"]
        sy = drag_state["start_y"]

        # 選択範囲が小さすぎる場合は無視
        if abs(ex - sx) < 5 or abs(ey - sy) < 5:
            return

        # 座標を正規化（左上 → 右下）
        x1, x2 = min(sx, ex), max(sx, ex)
        y1, y2 = min(sy, ey), max(sy, ey)

        # 仮矩形を削除し、確定版を描画
        if drag_state["rect_id"] is not None:
            canvas.delete(drag_state["rect_id"])
            drag_state["rect_id"] = None

        # 半透明の緑色オーバーレイ
        overlay_img = Image.new(
            'RGBA', (x2 - x1, y2 - y1), (0, 200, 0, 80)
        )
        overlay_tk = ImageTk.PhotoImage(overlay_img, master=selector_win)
        overlay_refs.clear()
        overlay_refs.append(overlay_tk)
        canvas.create_image(x1, y1, image=overlay_tk, anchor='nw', tag="region_overlay")

        # 矩形の枠線
        canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="green", width=2, tag="region_rect"
        )
        # ラベル
        canvas.create_text(
            (x1 + x2) / 2, (y1 + y2) / 2,
            text=label_text, fill="white",
            font=("", 14, "bold"), tag="region_label"
        )

        # 元画像の実寸座標に変換して保持
        result_rect[0] = (
            round(x1 * resize_ratio),
            round(y1 * resize_ratio),
            round(x2 * resize_ratio),
            round(y2 * resize_ratio),
        )

    canvas.bind("<ButtonPress-1>", _on_press)
    canvas.bind("<B1-Motion>", _on_drag)
    canvas.bind("<ButtonRelease-1>", _on_release)

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
    ).pack(pady=(0, 20))

    # --- ボタン ---
    def _confirm():
        if result_rect[0] is None:
            messagebox.showwarning(
                "未選択",
                "エリアが選択されていません。\n画像上でドラッグしてください。",
                parent=selector_win,
            )
            return
        selector_win.destroy()

    def _cancel():
        result_rect[0] = None
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

    # モーダルにする
    selector_win.grab_set()
    selector_win.wait_window()

    if owns_root:
        root.destroy()

    return result_rect[0]


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
            from omr_engine import (
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
