"""Provider-neutral conversion modules.

This package owns the conversion contract that can accept either the current
not-local direct API flow or a later main-derived local conversion core.
"""

from uttate.conversion.core import ConversionCore, ConversionRequest, DirectProviderCore
from uttate.conversion.direct import CONVERSION_SCHEMA, build_conversion_prompt, load_system_prompt
from uttate.conversion.response_parser import parse_provider_result

__all__ = [
    "CONVERSION_SCHEMA",
    "ConversionCore",
    "ConversionRequest",
    "DirectProviderCore",
    "build_conversion_prompt",
    "load_system_prompt",
    "parse_provider_result",
]
