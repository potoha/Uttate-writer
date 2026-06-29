from __future__ import annotations

from collections.abc import Sequence

from uttate.app import create_application
from uttate.config import load_settings
from uttate.providers.factory import create_conversion_provider


def main(argv: Sequence[str] | None = None) -> int:
    """Run Uttate Writer."""

    settings = load_settings()
    conversion_provider = create_conversion_provider(settings.provider)
    application, window = create_application(argv, conversion_provider, settings=settings)
    window.show()
    return application.exec()
