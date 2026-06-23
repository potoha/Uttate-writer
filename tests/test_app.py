from uttate.app import MainWindow


def test_main_window_smoke(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == "Uttate Writer"
    assert window.centralWidget() is not None
    assert window.statusBar().currentMessage() == "Ready"
