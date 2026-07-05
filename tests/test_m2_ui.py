from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from uttate.addons.dataset_curator import load_candidates
from uttate.config import AppSettings, DatasetCaptureSettings, ProviderSettings
from uttate.models import ChunkStatus
from uttate.providers.base import Candidate, ProviderResult
from uttate.providers.mock import MockProvider
from uttate.ui.main_window import ConsoleMode, MainWindow


class VariableDelayProvider:
    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        del previous_context
        time.sleep(0.08 if raw_text == "slow first" else 0.01)
        return ProviderResult(
            candidates=(
                Candidate("faithful", f"A:{raw_text}"),
                Candidate("natural", f"B:{raw_text}"),
            )[:candidate_count],
            provider="variable-delay",
            model="test",
        )


class FailingProvider:
    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        del previous_context, candidate_count
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

    qtbot.keyClicks(window.input_panel.editor, "thirdchunkstillbeingwritten")
    assert window.input_panel.editor.toPlainText() == "thirdchunkstillbeingwritten"

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


def test_space_inserts_boundary_and_shift_space_inserts_real_space(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    editor = window.input_panel.editor
    editor.setFocus()

    qtbot.keyClicks(editor, "rakuten")
    qtbot.keyClick(editor, Qt.Key.Key_Space)
    qtbot.keyClicks(editor, "ka")
    qtbot.keyClick(editor, Qt.Key.Key_Space, modifier=Qt.KeyboardModifier.ShiftModifier)
    qtbot.keyClicks(editor, "do")

    assert editor.toPlainText() == "rakuten | ka do"
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

    assert window.review_panel.status_label.text() == "Status: ready_for_review / mock:mock"
    assert window.review_panel.raw_field.toPlainText() == "review me"
    assert window.review_panel.candidate_1_field.toPlainText() == "変換候補A: review me"


def test_main_window_starts_as_normal_bottom_band(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)

    assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

    screen = QApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    expected_height = max(220, int(available.height() * 0.25))

    geometry = window.geometry()
    assert geometry.x() == available.x()
    assert geometry.y() == available.bottom() - expected_height + 1
    assert geometry.width() == available.width()
    assert geometry.height() == expected_height


def test_long_chunk_text_is_not_elided_and_review_fields_wrap(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    long_text = "nagai" * 24

    submit(qtbot, window, long_text)
    wait_until_idle(qtbot, window)

    item_text = window.chunk_list.item(0).text()
    assert "..." not in item_text
    assert "…" not in item_text
    assert f"変換候補A: {long_text}" in item_text
    assert window.review_panel.raw_field.toPlainText() == long_text
    assert window.review_panel.candidate_1_field.toPlainText() == f"変換候補A: {long_text}"
    assert window.review_panel.raw_field.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
    assert window.review_panel.raw_field.maximumHeight() > 10000


def test_review_mode_enter_accepts_and_copies_selected_candidate(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "copy me")
    wait_until_idle(qtbot, window)

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    assert window.mode == ConsoleMode.REVIEW

    qtbot.keyClick(window.chunk_list, Qt.Key.Key_Return)

    chunk = window.document.chunks[0]
    assert chunk.status == ChunkStatus.ADOPTED
    assert chunk.adopted_text == "変換候補A: copy me"
    assert QApplication.clipboard().text() == "変換候補A: copy me"
    assert "[accepted]" in window.chunk_list.item(0).text()


def test_review_mode_shift_enter_accepts_and_records_dataset_candidate(qtbot, tmp_path) -> None:
    store = tmp_path / "review_candidates.jsonl"
    settings = AppSettings(
        dataset=DatasetCaptureSettings(capture_enabled=True, capture_store_path=str(store))
    )
    window = MainWindow(MockProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "dataset me")
    wait_until_idle(qtbot, window)

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(
        window.chunk_list,
        Qt.Key.Key_Return,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )

    chunk = window.document.chunks[0]
    candidates = load_candidates(store)
    assert chunk.status == ChunkStatus.ADOPTED
    assert chunk.adopted_text == "変換候補A: dataset me"
    assert len(candidates) == 1
    assert candidates[0]["status"] == "candidate"
    assert candidates[0]["raw"] == "dataset me"
    assert candidates[0]["kana"] == "dataset me"
    assert candidates[0]["literal"] == "変換候補A: dataset me"
    assert candidates[0]["natural"] == "変換候補B: dataset me"
    assert "review-accept" in candidates[0]["tags"]


def test_review_mode_shift_enter_does_not_accept_when_capture_is_off(
    qtbot,
    tmp_path,
) -> None:
    store = tmp_path / "disabled.jsonl"
    settings = AppSettings(
        dataset=DatasetCaptureSettings(capture_enabled=False, capture_store_path=str(store))
    )
    window = MainWindow(MockProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "do not record")
    wait_until_idle(qtbot, window)

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(
        window.chunk_list,
        Qt.Key.Key_Return,
        modifier=Qt.KeyboardModifier.ShiftModifier,
    )

    assert window.document.chunks[0].status == ChunkStatus.READY_FOR_REVIEW
    assert not store.exists()
    assert window.statusBar().currentMessage() == "Dataset capture is disabled"


def test_review_mode_space_can_select_second_candidate_before_accept(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "choose b")
    wait_until_idle(qtbot, window)

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.chunk_list, Qt.Key.Key_Space)
    qtbot.keyClick(window.chunk_list, Qt.Key.Key_Return)

    chunk = window.document.chunks[0]
    assert chunk.status == ChunkStatus.ADOPTED
    assert chunk.adopted_text == "変換候補B: choose b"
    assert QApplication.clipboard().text() == "変換候補B: choose b"


def test_candidate_edit_enter_accepts_edited_text_and_restores_input(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "fix me")
    wait_until_idle(qtbot, window)
    window.input_panel.editor.setPlainText("unsent draft")

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.chunk_list, Qt.Key.Key_F)

    assert window.mode == ConsoleMode.CANDIDATE_EDIT
    assert window.input_panel.editor.toPlainText() == "変換候補A: fix me"

    window.input_panel.editor.selectAll()
    qtbot.keyClicks(window.input_panel.editor, "edited candidate")
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_Return)

    chunk = window.document.chunks[0]
    assert window.mode == ConsoleMode.REVIEW
    assert chunk.status == ChunkStatus.ADOPTED
    assert chunk.candidate_1 == "edited candidate"
    assert chunk.adopted_text == "edited candidate"
    assert QApplication.clipboard().text() == "edited candidate"
    assert window.input_panel.editor.toPlainText() == "unsent draft"


def test_candidate_edit_escape_cancels_and_restores_input(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "cancel me")
    wait_until_idle(qtbot, window)
    window.input_panel.editor.setPlainText("still typing")

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.chunk_list, Qt.Key.Key_F)
    window.input_panel.editor.setPlainText("discard this")
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_Escape)

    chunk = window.document.chunks[0]
    assert window.mode == ConsoleMode.REVIEW
    assert chunk.status == ChunkStatus.READY_FOR_REVIEW
    assert chunk.candidate_1 == "変換候補A: cancel me"
    assert window.input_panel.editor.toPlainText() == "still typing"


def test_candidate_edit_ctrl_enter_reconverts_and_restores_input(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "first pass")
    wait_until_idle(qtbot, window)
    window.input_panel.editor.setPlainText("kept draft")

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.chunk_list, Qt.Key.Key_F)
    window.input_panel.editor.selectAll()
    qtbot.keyClicks(window.input_panel.editor, "second pass")
    qtbot.keyClick(
        window.input_panel.editor,
        Qt.Key.Key_Return,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )
    wait_until_idle(qtbot, window)

    chunk = window.document.chunks[0]
    assert window.mode == ConsoleMode.REVIEW
    assert chunk.status == ChunkStatus.READY_FOR_REVIEW
    assert chunk.raw_text == "second pass"
    assert chunk.candidate_1 == "変換候補A: second pass"
    assert window.input_panel.editor.toPlainText() == "kept draft"


def test_provider_failure_marks_only_its_chunk_failed(qtbot) -> None:
    window = MainWindow(FailingProvider())
    qtbot.addWidget(window)

    submit(qtbot, window, "broken")
    wait_until_idle(qtbot, window)

    chunk = window.document.chunks[0]
    assert chunk.status == ChunkStatus.FAILED
    assert chunk.error_message == "cannot convert broken"
    assert window.review_panel.error_field.toPlainText() == "cannot convert broken"
    assert window.input_panel.editor.isEnabled()


def test_review_mode_r_resends_error_chunk(qtbot) -> None:
    window = MainWindow(FailingProvider())
    qtbot.addWidget(window)

    submit(qtbot, window, "retry me")
    wait_until_idle(qtbot, window)
    assert window.document.chunks[0].status == ChunkStatus.FAILED

    window.conversion_queue.set_provider(MockProvider(delay_seconds=0))
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.chunk_list, Qt.Key.Key_R)
    wait_until_idle(qtbot, window)

    chunk = window.document.chunks[0]
    assert chunk.status == ChunkStatus.READY_FOR_REVIEW
    assert chunk.candidate_1 == "変換候補A: retry me"


def test_provider_switch_updates_future_chunks(qtbot) -> None:
    settings = AppSettings(
        provider=ProviderSettings(type="openai", openai_api_key="dummy-openai")
    )
    window = MainWindow(MockProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)

    window.provider_panel.provider_combo.setCurrentIndex(
        window.provider_panel.provider_combo.findData("local_ai")
    )

    assert window.provider_panel.provider_combo.currentData() == "local_ai"
    assert "auto-detect" in window.provider_panel.model_label.text()


def test_settings_button_opens_key_settings_window(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    qtbot.mouseClick(window.provider_panel.settings_button, Qt.MouseButton.LeftButton)

    assert window._settings_window is not None
    assert window._settings_window.isVisible()


def test_f12_opens_key_settings_window(qtbot) -> None:
    window = MainWindow(MockProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()
    window.input_panel.editor.setFocus()

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F12)

    assert window._settings_window is not None
    assert window._settings_window.isVisible()



