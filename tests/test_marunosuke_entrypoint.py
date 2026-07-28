"""マル之助の正式エントリーポイントに関するテスト。"""


def test_marunosuke_exports_shared_entrypoints():
    import marunosuke
    import saitensamurai

    assert marunosuke.MarunosukeGUI is saitensamurai.MarunosukeGUI
    assert marunosuke.main is saitensamurai.main
    assert marunosuke.run is saitensamurai.run
