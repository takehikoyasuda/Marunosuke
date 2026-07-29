"""生徒向けコメントの返却答案描画テスト。"""

from pathlib import Path
import sys

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "main_src"))

from constants import get_rendering_settings
from descriptive_renderer import draw_descriptive_on_image, wrap_student_comment


def _config():
    return {
        "questions": [{
            "id": "D1", "name": "記述1", "max_score": 5, "aspect": 1,
            "region": [20, 20, 380, 180],
        }],
    }


def test_comment_wraps_and_truncates_to_requested_lines():
    lines = wrap_student_comment("これは長い日本語のコメントです。理由も書きましょう。", 12, 2)
    assert len(lines) == 2
    assert lines[-1].endswith("…")


def test_comment_normalizes_whitespace():
    assert wrap_student_comment("  理由を\n 書こう  ", 20) == ["理由を 書こう"]


def test_comment_is_drawn_when_enabled():
    image = np.full((220, 420, 3), 255, dtype=np.uint8)
    without = draw_descriptive_on_image(image, _config(), {}, comments_for_image={})
    with_comment = draw_descriptive_on_image(
        image, _config(), {}, comments_for_image={"D1": "途中式も書きましょう"},
    )
    assert np.any(with_comment != without)


def test_comment_is_not_drawn_when_disabled():
    image = np.full((220, 420, 3), 255, dtype=np.uint8)
    settings = get_rendering_settings({"descriptive_show_comment": False})
    without = draw_descriptive_on_image(image, _config(), {}, rendering_settings=settings)
    disabled = draw_descriptive_on_image(
        image, _config(), {}, rendering_settings=settings,
        comments_for_image={"D1": "答案には表示しない"},
    )
    assert np.array_equal(disabled, without)


def test_teacher_memo_is_not_an_accepted_rendering_input():
    """描画APIはコメント辞書だけを受け、教員用メモを渡す経路を持たない。"""
    import inspect

    parameters = inspect.signature(draw_descriptive_on_image).parameters
    assert "comments_for_image" in parameters
    assert "annotations" not in parameters
    assert "memo" not in parameters
