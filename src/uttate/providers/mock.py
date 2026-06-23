from __future__ import annotations

import time

from uttate.providers.base import ConversionResult

_KNOWN_CONVERSIONS: dict[str, tuple[str, str, str]] = {
    "keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai": (
        "keyboard は ぶんぼうぐ だから input の stress を さいしょうか しなければならない",
        "キーボードは文房具だから、入力のストレスを最小化しなければならない。",
        "キーボードは文房具なので、入力時のストレスを最小限にしたい。",
    ),
    "Uttateha ime noreplacementjanakute kakukotono frictionwoherasutool": (
        "Uttate は IME の replacement じゃなくて かくことの friction を へらす tool",
        "UttateはIMEの代替ではなく、書くことのフリクションを減らすツールである。",
        "UttateはIMEを置き換えるのではなく、書く際の摩擦を減らすツールだ。",
    ),
}


class MockProvider:
    """Deterministic local provider used to build and test the M2 UX loop."""

    def __init__(self, *, delay_seconds: float = 0.03) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative.")
        self.delay_seconds = delay_seconds

    def convert(self, raw_text: str) -> ConversionResult:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

        normalized_raw = " ".join(raw_text.split())
        normalized, candidate_1, candidate_2 = _KNOWN_CONVERSIONS.get(
            raw_text,
            (
                normalized_raw,
                f"変換候補A: {normalized_raw}",
                f"変換候補B: {normalized_raw}",
            ),
        )
        return ConversionResult(
            normalized=normalized,
            candidate_1=candidate_1,
            candidate_2=candidate_2,
            segments=(
                {
                    "raw": raw_text,
                    "reading": normalized,
                    "type": "unknown",
                    "confidence": 1.0,
                },
            ),
        )
