"""画像選択後の初期設定フローをGUIなしで検証する。"""

from unittest.mock import MagicMock

from main_gui import Mark2GUI
from constants import RESULTS_FOLDER, RESULTS_DATA_FOLDER, BOXED_FOLDER


def _stub_app(image_folder):
    app = object.__new__(Mark2GUI)
    app.image_folder_path = MagicMock()
    app.image_folder_path.get.return_value = str(image_folder)
    app.log_message = MagicMock()
    return app


def test_existing_config_prompt_precedes_all_setup_steps(tmp_path):
    boxed = tmp_path / RESULTS_FOLDER / BOXED_FOLDER
    boxed.mkdir(parents=True)
    data = tmp_path / RESULTS_FOLDER / RESULTS_DATA_FOLDER
    data.mkdir(parents=True)
    (data / "descriptive_config.json").write_text(
        '{"version": 2, "questions": []}', encoding="utf-8"
    )
    app = _stub_app(tmp_path)
    calls = []
    app._ask_descriptive_setup_action = MagicMock(
        side_effect=lambda: calls.append("ask") or "continue"
    )
    app._wizard_step_roster = MagicMock(side_effect=lambda *_: calls.append("roster"))
    app._wizard_step_page_check = MagicMock(side_effect=lambda: calls.append("page"))
    app._wizard_step_name_area = MagicMock(side_effect=lambda *_: calls.append("name"))
    app._wizard_step_id_area = MagicMock(side_effect=lambda *_: calls.append("id"))
    app.setup_descriptive = MagicMock(side_effect=lambda **_: calls.append("setup"))

    app._run_step1_setup_wizard()

    assert calls == ["ask", "roster", "page", "name", "id", "setup"]


def test_cancel_at_existing_config_prompt_stops_setup(tmp_path):
    boxed = tmp_path / RESULTS_FOLDER / BOXED_FOLDER
    boxed.mkdir(parents=True)
    data = tmp_path / RESULTS_FOLDER / RESULTS_DATA_FOLDER
    data.mkdir(parents=True)
    (data / "descriptive_config.json").write_text("{}", encoding="utf-8")
    app = _stub_app(tmp_path)
    app._ask_descriptive_setup_action = MagicMock(return_value="cancel")
    app._wizard_step_roster = MagicMock()

    app._run_step1_setup_wizard()

    app._wizard_step_roster.assert_not_called()


def test_selected_source_starts_automatic_image_preparation(tmp_path):
    app = object.__new__(Mark2GUI)
    app.image_folder_path = MagicMock()
    app.log_message = MagicMock()
    app._set_processing_state = MagicMock()
    app._try_auto_restore = MagicMock()
    app._update_step1_availability = MagicMock()
    app._update_step_availability = MagicMock()
    app._prepare_images_for_descriptive = MagicMock()

    app._start_setup_for_image_source(tmp_path)

    app.image_folder_path.set.assert_called_once_with(str(tmp_path))
    app._prepare_images_for_descriptive.assert_called_once_with(auto_start_setup=True)
