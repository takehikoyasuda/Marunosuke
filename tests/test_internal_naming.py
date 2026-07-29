"""マル之助への内部名称移行と後方互換性のテスト。"""

import logging
from pathlib import Path


def test_gui_class_legacy_aliases():
    from main_gui import MarunosukeGUI, Mark2GUI, SaitenSamuraiGUI

    assert SaitenSamuraiGUI is MarunosukeGUI
    assert Mark2GUI is MarunosukeGUI


def test_new_log_filename(tmp_path):
    from constants import setup_logging

    log_path = setup_logging(tmp_path)
    assert log_path == tmp_path / "marunosuke.log"
    logging.shutdown()
    logging.getLogger().handlers.clear()


def test_new_crash_log_filename(monkeypatch, tmp_path):
    import saitensamurai

    monkeypatch.chdir(tmp_path)
    assert Path(saitensamurai._get_crash_log_path()).name == "marunosuke_crash.log"


def test_new_temp_directory_name(monkeypatch, tmp_path):
    import tempfile

    from constants import get_app_temp_dir

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    assert Path(get_app_temp_dir()).name == "marunosuke_temp"
