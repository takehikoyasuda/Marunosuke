"""記述式採点の回答注釈データモデルと永続化のテスト。"""

import json
from unittest.mock import MagicMock

from descriptive_scorer import (
    COMMENT_HISTORY_LIMIT,
    load_descriptive_annotations,
    normalize_descriptive_annotations,
    save_descriptive_annotations,
    normalize_annotation_tags,
    update_comment_history,
)


def test_missing_file_returns_empty_normalized_data(tmp_path):
    loaded = load_descriptive_annotations(str(tmp_path / "missing.json"))
    assert loaded == {"version": 1, "answers": {}, "comment_history": {}}


def test_normalize_removes_empty_answers_and_cleans_tags():
    data = {
        "version": 1,
        "answers": {
            "001.jpg": {
                "D1": {"memo": "", "comment": "", "held": False, "tags": []},
                "D2": {
                    "memo": "比較対象",
                    "comment": "",
                    "held": False,
                    "tags": [" 別解 ", "別解", "", 123],
                },
            },
            "bad.jpg": "invalid",
        },
        "comment_history": {},
    }
    normalized = normalize_descriptive_annotations(data)
    assert "D1" not in normalized["answers"]["001.jpg"]
    assert normalized["answers"]["001.jpg"]["D2"]["tags"] == ["別解"]
    assert "bad.jpg" not in normalized["answers"]


def test_comment_history_is_deduplicated_and_limited():
    comments = [" 同じ ", "同じ"] + [f"コメント{i}" for i in range(100)]
    normalized = normalize_descriptive_annotations({
        "comment_history": {"D1": comments},
    })
    history = normalized["comment_history"]["D1"]
    assert history[0] == "同じ"
    assert len(history) == COMMENT_HISTORY_LIMIT
    assert len(history) == len(set(history))


def test_roundtrip_and_backup_recovery(tmp_path):
    path = tmp_path / "descriptive_annotations.json"
    first = {
        "answers": {
            "001.jpg": {
                "D1": {
                    "memo": "教員用",
                    "comment": "理由を書きましょう",
                    "held": True,
                    "tags": ["境界答案"],
                }
            }
        },
        "comment_history": {"D1": ["理由を書きましょう"]},
    }
    save_descriptive_annotations(str(path), first)
    save_descriptive_annotations(str(path), {"answers": {}, "comment_history": {}})

    # 現行ファイルを壊すと、直前内容の .bak から復旧する。
    path.write_text("not json", encoding="utf-8")
    loaded = load_descriptive_annotations(str(path))
    assert loaded["answers"]["001.jpg"]["D1"]["held"] is True
    assert loaded["comment_history"]["D1"] == ["理由を書きましょう"]


def test_unknown_top_level_keys_are_preserved(tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps({"future": {"enabled": True}}), encoding="utf-8")
    loaded = load_descriptive_annotations(str(path))
    assert loaded["future"] == {"enabled": True}


def test_tag_limits_and_normalization():
    tags = [" 境界答案 ", "境界答案", "x" * 50] + [f"tag{i}" for i in range(20)]
    result = normalize_annotation_tags(tags)
    assert result[0] == "境界答案"
    assert result[1] == "x" * 30
    assert len(result) == 10


def test_comment_history_is_most_recent_first():
    result = update_comment_history(["以前", "今回", "以前"], " 今回 ")
    assert result == ["今回", "以前"]


def test_hold_marks_current_answer_and_moves_next():
    from descriptive_gui import _SingleQuestionScorer

    scorer = object.__new__(_SingleQuestionScorer)
    scorer.filenames = ["001.jpg", "002.jpg"]
    scorer._answer_held_var = MagicMock()
    scorer._update_held_status = MagicMock()
    scorer._commit_current_annotation = MagicMock()
    scorer.canvas = MagicMock()
    scorer._next_auto = MagicMock()

    scorer._on_hold()

    scorer._answer_held_var.set.assert_called_once_with(True)
    scorer._commit_current_annotation.assert_called_once_with()
    scorer.canvas.focus_set.assert_called_once_with()
    scorer._next_auto.assert_called_once_with()


def test_focus_scoring_canvas_commits_annotation_and_moves_focus():
    from descriptive_gui import _SingleQuestionScorer

    scorer = object.__new__(_SingleQuestionScorer)
    scorer._commit_current_annotation = MagicMock()
    scorer.canvas = MagicMock()

    result = scorer._focus_scoring_canvas()

    assert result == "break"
    scorer._commit_current_annotation.assert_called_once_with(add_comment_history=True)
    scorer.canvas.focus_force.assert_called_once_with()
