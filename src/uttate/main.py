from __future__ import annotations

from collections.abc import Sequence

from uttate.app import create_application


def main(argv: Sequence[str] | None = None) -> int:
    """Run Uttate Writer."""

    application, window = create_application(argv)
    window.show()
    return application.exec()
