"""アプリの表示名とバージョン管理に関するテスト。"""

import re

from constants import APP_NAME, APP_NAME_EN, APP_TITLE, APP_VERSION


def test_app_identity():
    assert APP_NAME == "マル之助"
    assert APP_NAME_EN == "Marunosuke"
    assert APP_TITLE == "マル之助 v0.1.0"


def test_app_version_uses_semantic_versioning():
    assert re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)",
        APP_VERSION,
    )
