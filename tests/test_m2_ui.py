from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from uttate.models import ChunkStatus
from uttate.providers.base import ConversionResult
from uttate.providers.mock import MockProvider
from uttate.ui.main_window import MainWindow


class VariableDelayProvider:
    def convert(self, raw_text: str) -> ConversionResult:
        time.sleep(0.08 if raw_text == "slow first" else 0.01)
        return ConversionResult(
            normalized=f"normalized:{raw_text}",
            candidate_1=f"A:{raw_text}",
            candidate_2=f"B:{raw_text}",
        )


class FailingProvider:
    def convert(self, raw_text: str) -> ConversionResult:
        raise RuntimeError(f"cannot convert {raw_text}")


def submit(qtbot, window: MainWindow, text: str) -> None:
    window.input_panel.editor.setPlainText(text)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_Return)


def wait_until_idle(qtbot, window: MainWindow) -> None:
    qtbot.waitUntil(lambda: window.conversion_queue.active_count == 0, timeout=3000)


def test_enter_commits_multiple_chunks_without_waiting(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0.12), max_workers=2)
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "first rough chunk")
    submit(qtbot, window, "second rough chunk")

    assert [chunk.raw_text for chunk in window.document.chunks] == [
        "first rough chunk",
        "second rough chunk",
    ]
    assert window.chunk_list.count() == 2
    assert window.conversion_queue.active_count == 2

    qtbot.keyClicks(window.input_panel.editor, "third chunk still being written")
    assert window.input_panel.editor.toPlainText() == "third chunk still being written"

    wait_until_idle(qtbot, window)
    assert all(chunk.status == ChunkStatus.READY_FOR_REVIEW for chunk in window.document.chunks)


def test_empty_input_is_not_committed(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)

    submit(qtbot, window, "  \n\t")

    assert window.document.chunks == []
    assert window.chunk_list.count() == 0


def test_shift_enter_inserts_newline_without_committing(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.input_panel.editor.setPlainText("line one")
    window.input_panel.editor.moveCursor(QTextCursor.MoveOperation.End)

    qtbot.keyClick(
        window.input_panel.editor,
        Qt.Key.Key_Return,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )

    assert window.input_panel.editor.toPlainText() == "line one\n"
    assert window.document.chunks == []


def test_out_of_order_results_update_the_matching_chunk(qtbot) -> None:
    window = MainWindow(VariableDelayProvider(), max_workers=2)
    qtbot.addWidget(window)

    submit(qtbot, window, "slow first")
    submit(qtbot, window, "fast second")
    wait_until_idle(qtbot, window)

    first, second = window.document.chunks
    assert first.candidate_1 == "A:slow first"
    assert second.candidate_1 == "A:fast second"
    assert [chunk.raw_text for chunk in window.document.chunks] == [
        "slow first",
        "fast second",
    ]


def test_selected_chunk_review_refreshes_after_conversion(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0.01))
    qtbot.addWidget(window)

    submit(qtbot, window, "review me")
    wait_until_idle(qtbot, window)

    assert window.review_panel.status_label.text() == "Status: ready_for_review"
    assert window.review_panel.raw_field.toPlainText() == "review me"
    assert window.review_panel.candidate_1_field.toPlainText() == "変換候補A: review me"


def test_provider_failure_marks_only_its_chunk_failed(qtbot) -> None:
    window = MainWindow(FailingProvider())
    qtbot.addWidget(window)

    submit(qtbot, window, "broken")
    wait_until_idle(qtbot, window)

    chunk = window.document.chunks[0]
    assert chunk.status == ChunkStatus.FAILED
    assert chunk.error_message == "cannot convert broken"
    assert window.input_panel.editor.isEnabled()
