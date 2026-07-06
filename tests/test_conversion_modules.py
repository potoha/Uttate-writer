import pytest

from uttate.conversion import ConversionRequest, DirectProviderCore
from uttate.conversion.direct import build_conversion_prompt
from uttate.conversion.response_parser import parse_provider_result
from uttate.pipeline.response_parser import parse_provider_result as legacy_parse_provider_result
from uttate.providers.base import Candidate, ProviderResult
from uttate.providers.direct_conversion import (
    build_conversion_prompt as legacy_build_conversion_prompt,
)


class RecordingProvider:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        self.calls.append((raw_text, previous_context, candidate_count))
        return ProviderResult(candidates=(Candidate("faithful", "本文"),), provider=self.name)


def test_legacy_direct_conversion_module_reexports_new_prompt_builder() -> None:
    prompt = build_conversion_prompt(
        "system",
        raw_text="\\dedodamu\\ to =English= to $tokiori$",
        previous_context="前文",
        candidate_count=2,
    )
    legacy_prompt = legacy_build_conversion_prompt(
        "system",
        raw_text="\\dedodamu\\ to =English= to $tokiori$",
        previous_context="前文",
        candidate_count=2,
    )

    assert legacy_prompt == prompt
    assert "入力:\nデドダム to English to ときおり" in prompt


def test_legacy_response_parser_module_reexports_new_parser() -> None:
    text = '{"candidates":[{"label":"faithful","text":"本文"}],"uncertain":[]}'

    result = parse_provider_result(text, provider="test", model="model")
    legacy_result = legacy_parse_provider_result(text, provider="test", model="model")

    assert legacy_result == result


def test_conversion_request_validates_core_contract() -> None:
    with pytest.raises(ValueError, match="raw_text"):
        ConversionRequest("")
    with pytest.raises(ValueError, match="candidate_count"):
        ConversionRequest("text", candidate_count=0)


def test_direct_provider_core_adapts_current_provider_contract() -> None:
    provider = RecordingProvider()
    core = DirectProviderCore(provider)

    result = core.convert_request(
        ConversionRequest("rough", previous_context="前文", candidate_count=3)
    )

    assert result.candidates[0].text == "本文"
    assert core.name == "recording"
    assert provider.calls == [("rough", "前文", 3)]
