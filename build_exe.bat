@echo off
chcp 65001 >nul
REM =====================================================
REM マル之助 (Marunosuke) — exe ビルドスクリプト
REM
REM このスクリプトは以下を自動実行します:
REM   1. ビルド用仮想環境 (venv_build) の作成
REM   2. 必要最小限の依存パッケージのインストール
REM   3. PyInstaller による exe のビルド
REM
REM 使い方:
REM   build_exe.bat
REM
REM 出力:
REM   dist/Marunosuke_vX.Y.Z.exe  (バージョン番号は自動付与)
REM =====================================================

echo.
echo ===================================================
echo  マル之助 (Marunosuke) — exe ビルド
echo ===================================================
echo.

REM --- 1. ビルド用仮想環境の作成 ---
if not exist "venv_build" (
    echo [1/3] ビルド用仮想環境を作成しています...
    python -m venv venv_build
    if errorlevel 1 (
        echo エラー: Python の venv モジュールが見つかりません。
        echo Python 3.8 以上がインストールされているか確認してください。
        pause
        exit /b 1
    )
) else (
    echo [1/3] ビルド用仮想環境は既に存在します。
)

REM --- 仮想環境のアクティベート ---
call venv_build\Scripts\activate.bat

REM --- 2. 依存パッケージのインストール ---
echo [2/3] 依存パッケージをインストールしています...
pip install --upgrade pip >nul 2>&1
pip install ^
    "opencv-python-headless>=4.5.0" ^
    "numpy>=1.20.0" ^
    "pandas>=1.3.0" ^
    "Pillow>=8.0.0" ^
    "openpyxl>=3.0.0" ^
    "PyMuPDF>=1.20.0" ^
    "matplotlib>=3.4.0" ^
    "reportlab>=3.6.0" ^
    "scikit-learn>=1.0.0" ^
    "pyinstaller>=6.0.0"

if errorlevel 1 (
    echo エラー: パッケージのインストールに失敗しました。
    pause
    exit /b 1
)

REM --- 不要ファイルのクリーンアップ ---
echo     不要ファイルを削除しています...
REM opencv-python（非headless）がインストールされていた場合の残骸を削除
if exist "venv_build\Lib\site-packages\cv2\opencv_videoio_ffmpeg*.dll" (
    del /q "venv_build\Lib\site-packages\cv2\opencv_videoio_ffmpeg*.dll"
    echo     - FFmpeg DLL を削除しました
)

REM --- 3. PyInstaller でビルド ---
echo [3/3] PyInstaller で exe をビルドしています...
echo     （数分かかる場合があります）
echo.

pyinstaller marunosuke.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo エラー: ビルドに失敗しました。
    echo 上のエラーメッセージを確認してください。
    pause
    exit /b 1
)

REM --- 完了 ---
echo.
echo ===================================================
echo  ビルド完了！
echo ===================================================
echo.

REM --- ファイルサイズ表示 ---
for %%F in (dist\Marunosuke_v*.exe) do (
    echo  出力: %%F
    echo  ファイルサイズ: 約 %%~zF bytes
)

echo.
echo  デスクトップにコピーして使用してください。
echo.
echo.

call venv_build\Scripts\deactivate.bat 2>nul
pause
