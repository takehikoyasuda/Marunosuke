"""アプリの表示名とバージョン管理に関するテスト。"""

import re
from pathlib import Path

from PIL import Image

from constants import APP_NAME, APP_NAME_EN, APP_TITLE, APP_VERSION


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "resources"


def test_app_identity():
    assert APP_NAME == "マル之助"
    assert APP_NAME_EN == "Marunosuke"
    assert APP_TITLE == "マル之助 v0.1.0"


def test_app_version_uses_semantic_versioning():
    assert re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)",
        APP_VERSION,
    )


def test_marunosuke_brand_assets_exist():
    expected_assets = {
        "marunosuke-logo.png",
        "marunosuke-icon.png",
        "marunosuke-icon.icns",
    }
    assert expected_assets <= {path.name for path in RESOURCE_DIR.iterdir()}


def test_marunosuke_png_dimensions():
    with Image.open(RESOURCE_DIR / "marunosuke-logo.png") as logo:
        assert logo.size == (1024, 1024)
    with Image.open(RESOURCE_DIR / "marunosuke-icon.png") as icon:
        assert icon.size == (256, 256)
