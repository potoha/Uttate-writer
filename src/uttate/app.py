from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget


class MainWindow(QMainWindow):
    """Top-level Uttate window.

    M0 intentionally keeps the surface minimal. The input, chunk list, and review
    panels are introduced in M2 after the document model exists.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Uttate Writer")
        self.resize(960, 640)
        self.setMinimumSize(720, 480)

        message = QLabel("Uttate Writer\nM0 development foundation is ready.")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout()
        layout.addWidget(message)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.statusBar().showMessage("Ready")


def create_application(argv: Sequence[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Create the Qt application and its main window."""

    application = QApplication.instance()
    if application is None:
        application = QApplication(list(argv) if argv is not None else sys.argv)
    if not isinstance(application, QApplication):
        raise RuntimeError("The active Qt application is not a QApplication instance.")

    application.setApplicationName("Uttate Writer")
    application.setOrganizationName("Uttate")
    window = MainWindow()
    return application, window
