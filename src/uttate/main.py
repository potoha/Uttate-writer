from __future__ import annotations

from collections.abc import Sequence

from uttate.app import create_application
from uttate.config import load_settings
from uttate.logging_config import configure_logging
from uttate.prompts.registry import LocalAIPromptRegistry
from uttate.providers.factory import create_conversion_provider


def main(argv: Sequence[str] | None = None) -> int:
    """Run Uttate Writer."""

    configure_logging()
    settings = load_settings()
    prompt_registry = LocalAIPromptRegistry.load()
    conversion_provider = create_conversion_provider(
        settings.provider,
        prompt_registry=prompt_registry,
    )
    application, window = create_application(
        argv,
        conversion_provider,
        settings=settings,
        prompt_registry=prompt_registry,
    )
    window.show()
    return application.exec()
