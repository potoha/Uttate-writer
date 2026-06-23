from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from uttate.models import ChunkStatus, JsonObject
from uttate.pipeline.normalizer import ReadingNormalizationProvider, ReadingNormalizer
from uttate.providers.base import LLMProvider
from uttate.providers.mock import MockProvider
from uttate.ui.main_window import MainWindow


class StaticLLMProvider(LLMProvider):
    def __init__(self, response: JsonObject) -> None:
        self.response = response
        self.messages: list[JsonObject] = []
        self.schema: JsonObject | None = None

    def complete_json(
        self, messages: list[JsonObject], schema: JsonObject | None = None
    ) -> JsonObject:
        self.messages = messages
        self.schema = schema
        return self.response


def valid_response() -> JsonObject:
    return {
        "normalized": "keyboard は ぶんぼうぐ",
        "segments": [
            {
                "raw": "keyboard",
                "reading": "keyboard",
                "type": "english",
                "confidence": 0.95,
            },
            {"raw": "bunbougu", "reading": "ぶんぼうぐ", "type": "noun", "confidence": 0.9},
        ],
        "uncertain": [],
    }


def test_normalizer_passes_prompt_input_and_schema() -> None:
    provider = StaticLLMProvider(valid_response())

    result = ReadingNormalizer(provider).normalize("keyboardhabunbougu")

    assert result.normalized == "keyboard は ぶんぼうぐ"
    assert result.segments[1]["reading"] == "ぶんぼうぐ"
    assert provider.messages[-1] == {"role": "user", "content": "keyboardhabunbougu"}
    assert provider.schema is not None
    assert provider.schema["required"] == ["normalized", "segments", "uncertain"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(normalized=""), "normalized"),
        (lambda value: value.update(segments={}), "segments"),
        (lambda value: value["segments"][0].update(type="invalid"), "unsupported type"),
        (lambda value: value["segments"][0].update(confidence=2), "between 0 and 1"),
        (lambda value: value.update(uncertain={}), "uncertain"),
    ],
)
def test_normalizer_rejects_invalid_stage_1_shapes(mutation, message: str) -> None:
    response = valid_response()
    mutation(response)

    with pytest.raises(ValueError, match=message):
        ReadingNormalizer(StaticLLMProvider(response)).normalize("rough")


def test_reading_normalization_provider_stops_queue_at_normalized(qtbot) -> None:
    stage_1 = ReadingNormalizationProvider(ReadingNormalizer(MockProvider(delay_seconds=0.01)))
    window = MainWindow(stage_1)
    qtbot.addWidget(window)
    window.input_panel.editor.setPlainText("keyboardhabunbougu")

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window.conversion_queue.active_count == 0, timeout=3000)

    chunk = window.document.chunks[0]
    assert chunk.status == ChunkStatus.NORMALIZED
    assert chunk.normalized == "keyboardhabunbougu"
    assert chunk.candidate_1 is None
    assert window.review_panel.normalized_field.toPlainText() == "keyboardhabunbougu"
