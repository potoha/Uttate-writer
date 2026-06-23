from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from uttate.providers.base import ConversionProvider
from uttate.ui.main_window import MainWindow


def create_application(
    argv: Sequence[str] | None = None,
    provider: ConversionProvider | None = None,
) -> tuple[QApplication, MainWindow]:
    """Create the Qt application and its main window."""

    application = QApplication.instance()
    if application is None:
        application = QApplication(list(argv) if argv is not None else sys.argv)
    if not isinstance(application, QApplication):
        raise RuntimeError("The active Qt application is not a QApplication instance.")

    application.setApplicationName("Uttate Writer")
    application.setOrganizationName("Uttate")
    window = MainWindow(provider)
    return application, window
