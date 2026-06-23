from __future__ import annotations

from collections.abc import Sequence

from uttate.app import create_application
from uttate.config import load_settings
from uttate.pipeline.normalizer import ReadingNormalizationProvider, ReadingNormalizer
from uttate.providers.factory import create_llm_provider


def main(argv: Sequence[str] | None = None) -> int:
    """Run Uttate Writer."""

    settings = load_settings()
    llm_provider = create_llm_provider(settings.provider)
    conversion_provider = ReadingNormalizationProvider(ReadingNormalizer(llm_provider))
    application, window = create_application(argv, conversion_provider)
    window.show()
    return application.exec()
