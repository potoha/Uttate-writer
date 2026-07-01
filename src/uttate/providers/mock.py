from __future__ import annotations

import time

from uttate.protected_input import parse_protected_input
from uttate.providers.base import Candidate, ProviderResult

_KNOWN_CONVERSIONS: dict[str, tuple[str, str]] = {
    "AIdenyuuryokuwosaisekkeisuru.": (
        "AIで入力を再設計する。",
        "AIを使って入力を再設計する。",
    ),
    "keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai": (
        "キーボードは文房具だから、入力のストレスを最小化しなければならない。",
        "キーボードは文房具なので、入力時のストレスを最小限にしたい。",
    ),
    "Uttateha ime noreplacementjanakute kakukotono frictionwoherasutool": (
        "UttateはIMEの代替ではなく、書くことのフリクションを減らすツールである。",
        "UttateはIMEを置き換えるのではなく、書く際の摩擦を減らすツールだ。",
    ),
    "uttatewriterha ime noreplacementjanakute kakukotono frictionwoherasutool": (
        "Uttate WriterはIMEの代替ではなく、書くことのフリクションを減らすツールである。",
        "Uttate WriterはIMEを置き換えるものではなく、書くときの摩擦を減らすツールだ。",
    ),
    "haikukoushiennokeikenwo PR nitsunageru": (
        "俳句甲子園の経験をPRにつなげる。",
        "俳句甲子園での経験をPRにつなげる。",
    ),
}


class MockProvider:
    """Deterministic provider used to build and test the Project B UX loop.

    The mock is intentionally boring: it never calls the network and never reads API keys.
    That makes the app useful for OSS contributors before they configure Gemini/OpenAI.
    """

    def __init__(self, *, delay_seconds: float = 0.03) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative.")
        self.delay_seconds = delay_seconds

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        del previous_context
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

        protected_input = parse_protected_input(raw_text)
        normalized_raw = " ".join(protected_input.text.split())
        candidate_1, candidate_2 = _KNOWN_CONVERSIONS.get(
            protected_input.text,
            (
                f"変換候補A: {normalized_raw}",
                f"変換候補B: {normalized_raw}",
            ),
        )
        candidates = (
            Candidate("faithful", candidate_1),
            Candidate("natural", candidate_2),
        )[:candidate_count]
        return ProviderResult(candidates=candidates, provider="mock", model="mock")
