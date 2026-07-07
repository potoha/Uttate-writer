from __future__ import annotations

import time
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from uttate.addons.dataset_curator import load_candidates
from uttate.config import (
    AppSettings,
    DatasetCaptureSettings,
    ProviderSettings,
    ReviewHUDSettings,
)
from uttate.models import ChunkStatus
from uttate.prompts.registry import LocalAIPromptProfile, LocalAIPromptRegistry
from uttate.providers.base import Candidate, ProviderResult
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


class DeterministicProvider:
    def __init__(self, *, delay_seconds: float = 0) -> None:
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
        return ProviderResult(
            candidates=(
                Candidate("faithful", f"変換候補A: {raw_text}"),
                Candidate("natural", f"変換候補B: {raw_text}"),
            )[:candidate_count],
            provider="test",
            model="test",
        )


def submit(qtbot, window: MainWindow, text: str) -> None:
    window.input_panel.editor.setPlainText(text)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_Return)


def wait_until_idle(qtbot, window: MainWindow) -> None:
    qtbot.waitUntil(lambda: window.conversion_queue.active_count == 0, timeout=3000)


def prompt_registry_for_tests(tmp_path) -> LocalAIPromptRegistry:
    return LocalAIPromptRegistry(
        tmp_path / "local_ai_prompts.yaml",
        {
            "default": LocalAIPromptProfile(
                name="default",
                model="",
                prompt="default prompt",
                default_prompt_snapshot="default prompt",
            )
        },
        default_prompt="default prompt",
    )


def test_enter_commits_multiple_chunks_without_waiting(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0.12), max_workers=2)
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
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)

    submit(qtbot, window, "  \n\t")

    assert window.document.chunks == []
    assert window.chunk_list.count() == 0


def test_shift_enter_inserts_newline_without_committing(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
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
    window = MainWindow(DeterministicProvider(delay_seconds=0))
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
    window = MainWindow(DeterministicProvider(delay_seconds=0.01))
    qtbot.addWidget(window)

    submit(qtbot, window, "review me")
    wait_until_idle(qtbot, window)

    assert window.review_panel.status_label.text() == "Status: ready_for_review / test:test"
    assert window.review_panel.raw_field.toPlainText() == "review me"
    assert window.review_panel.candidate_1_field.toPlainText() == "変換候補A: review me"


def test_main_window_stays_hidden_root_when_show_is_called(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)

    window.show()

    assert not window.isVisible()
    assert window.input_panel.isVisible()
    assert not window.debug_console.isVisible()


def test_long_chunk_text_is_not_elided_and_review_fields_wrap(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
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
    window = MainWindow(DeterministicProvider(delay_seconds=0))
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


def test_review_hud_shows_three_pending_with_single_detail(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "one")
    submit(qtbot, window, "two")
    submit(qtbot, window, "three")
    wait_until_idle(qtbot, window)

    assert window.review_hud.queue.count() == 3
    assert window.review_hud.summary_label.text() == "pending 3 / selected 3"
    assert window.review_hud.preview_text.toPlainText() == "変換候補A: three"
    assert "変換候補A: one" not in window.review_hud.preview_text.toPlainText()


def test_review_hud_always_show_displays_empty_hud_without_f2(qtbot) -> None:
    settings = AppSettings(review_hud=ReviewHUDSettings(always_show=True))
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)

    window.show()

    assert not window.isVisible()
    assert window.review_hud.isVisible()
    assert window.review_hud.queue.count() == 0
    assert window.review_hud.preview_text.toPlainText() == "No pending chunks"


def test_review_hud_always_show_f2_raises_existing_window(qtbot) -> None:
    settings = AppSettings(review_hud=ReviewHUDSettings(always_show=True))
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()
    review_hud = window.review_hud

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)

    assert window.review_hud is review_hud
    assert window.review_hud.isVisible()


def test_review_hud_checkbox_updates_shared_setting(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UTTATE_CONFIG_DIR", str(tmp_path))
    settings = AppSettings(review_hud=ReviewHUDSettings(always_show=True))
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()
    window._open_settings_window()

    window.review_hud.always_show_checkbox.setChecked(False)

    assert window.settings.review_hud.always_show is False
    assert not window.review_hud.always_show_checkbox.isChecked()
    assert window._settings_window is not None
    assert not window._settings_window.always_show_review_hud.isChecked()


def test_settings_always_show_updates_review_hud(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    window._open_settings_window()
    assert window._settings_window is not None
    window._settings_window.always_show_review_hud.setChecked(True)
    window._apply_app_settings(
        replace(
            window.settings,
            review_hud=replace(window.settings.review_hud, always_show=True),
        )
    )

    assert window.settings.review_hud.always_show is True
    assert window.review_hud.always_show_checkbox.isChecked()
    assert window.review_hud.isVisible()


def test_review_hud_and_input_panel_are_independent_windows(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "separate")
    wait_until_idle(qtbot, window)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_F)

    assert window.review_hud.isVisible()
    assert window.input_panel.isVisible()
    assert window.review_hud.windowFlags() & Qt.WindowType.Window
    assert window.input_panel.windowFlags() & Qt.WindowType.Window
    assert window.review_hud.status_label.text() == "status: editing"

    window.input_panel.close()

    assert window.review_hud.isVisible()
    assert window.review_hud.queue.count() == 1


def test_review_hud_up_down_selects_pending_chunks(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "first")
    submit(qtbot, window, "second")
    wait_until_idle(qtbot, window)

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_Up)

    assert window.review_hud.preview_text.toPlainText() == "変換候補A: first"

    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_Down)

    assert window.review_hud.preview_text.toPlainText() == "変換候補A: second"


def test_review_hud_accept_removes_accepted_chunk_by_default(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "accept me")
    wait_until_idle(qtbot, window)

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_Return)

    assert window.document.chunks[0].status == ChunkStatus.ADOPTED
    assert window.review_hud.queue.count() == 0


def test_review_mode_shift_enter_accepts_and_records_dataset_candidate(qtbot, tmp_path) -> None:
    store = tmp_path / "review_candidates.jsonl"
    settings = AppSettings(
        dataset=DatasetCaptureSettings(capture_enabled=True, capture_store_path=str(store))
    )
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
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
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
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
    window = MainWindow(DeterministicProvider(delay_seconds=0))
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
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "fix me")
    wait_until_idle(qtbot, window)
    window.input_panel.editor.setPlainText("unsent draft")

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.chunk_list, Qt.Key.Key_F)

    assert window.mode == ConsoleMode.CANDIDATE_EDIT
    assert window.input_panel.editor.toPlainText() == "変換候補A: fix me"
    assert window.review_hud.status_label.text() == "status: editing"

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


def test_input_panel_settings_button_opens_existing_settings_window(qtbot, tmp_path) -> None:
    window = MainWindow(
        DeterministicProvider(delay_seconds=0),
        prompt_registry=prompt_registry_for_tests(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()

    qtbot.mouseClick(window.input_panel.settings_button, Qt.MouseButton.LeftButton)
    first_settings_window = window._settings_window
    qtbot.mouseClick(window.input_panel.settings_button, Qt.MouseButton.LeftButton)

    assert first_settings_window is not None
    assert first_settings_window.isVisible()
    assert window._settings_window is first_settings_window


def test_input_panel_provider_selector_updates_model_and_warning(qtbot, tmp_path) -> None:
    settings = AppSettings(provider=ProviderSettings(type="openai", openai_api_key="dummy"))
    window = MainWindow(
        DeterministicProvider(delay_seconds=0),
        settings=settings,
        prompt_registry=prompt_registry_for_tests(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()

    assert "OpenAI API / gpt-5-nano" in window.input_panel.model_label.text()
    assert "OpenAI API" in window.input_panel.warning.text()

    window.input_panel.provider_combo.setCurrentIndex(
        window.input_panel.provider_combo.findData("local_ai")
    )

    assert window.settings.provider.type == "local_ai"
    assert "Local AI / model not selected" in window.input_panel.model_label.text()
    assert "外部APIへ送信されません" in window.input_panel.warning.text()


def test_input_panel_send_button_commits_new_input(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    window.input_panel.editor.setPlainText("button send")
    qtbot.mouseClick(window.input_panel.send_button, Qt.MouseButton.LeftButton)
    wait_until_idle(qtbot, window)

    assert window.document.chunks[0].raw_text == "button send"
    assert window.document.chunks[0].candidate_1 == "変換候補A: button send"
    assert window.input_panel.editor.toPlainText() == ""
    assert window.review_hud.queue.count() == 1


def test_input_panel_convert_button_reconverts_candidate_edit(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "first")
    wait_until_idle(qtbot, window)
    window.input_panel.editor.setPlainText("kept")
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_F)
    window.input_panel.editor.selectAll()
    qtbot.keyClicks(window.input_panel.editor, "second")
    qtbot.mouseClick(window.input_panel.send_button, Qt.MouseButton.LeftButton)
    wait_until_idle(qtbot, window)

    assert window.document.chunks[0].raw_text == "second"
    assert window.document.chunks[0].candidate_1 == "変換候補A: second"
    assert window.input_panel.editor.toPlainText() == "kept"


def test_candidate_edit_escape_cancels_and_restores_input(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
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
    window = MainWindow(DeterministicProvider(delay_seconds=0))
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

    window.conversion_queue.set_provider(DeterministicProvider(delay_seconds=0))
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.chunk_list, Qt.Key.Key_R)
    wait_until_idle(qtbot, window)

    chunk = window.document.chunks[0]
    assert chunk.status == ChunkStatus.READY_FOR_REVIEW
    assert chunk.candidate_1 == "変換候補A: retry me"
    assert window.review_hud.queue.count() == 1


def test_provider_switch_updates_future_chunks(qtbot, tmp_path) -> None:
    settings = AppSettings(provider=ProviderSettings(type="openai", openai_api_key="dummy-openai"))
    window = MainWindow(
        DeterministicProvider(delay_seconds=0),
        settings=settings,
        prompt_registry=prompt_registry_for_tests(tmp_path),
    )
    qtbot.addWidget(window)

    window.provider_panel.provider_combo.setCurrentIndex(
        window.provider_panel.provider_combo.findData("local_ai")
    )

    assert window.provider_panel.provider_combo.currentData() == "local_ai"
    assert "auto-detect" in window.provider_panel.model_label.text()


def test_settings_button_opens_key_settings_window(qtbot, tmp_path) -> None:
    window = MainWindow(
        DeterministicProvider(delay_seconds=0),
        prompt_registry=prompt_registry_for_tests(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()

    qtbot.mouseClick(window.provider_panel.settings_button, Qt.MouseButton.LeftButton)

    assert window._settings_window is not None
    assert window._settings_window.isVisible()


def test_f12_opens_key_settings_window(qtbot, tmp_path) -> None:
    window = MainWindow(
        DeterministicProvider(delay_seconds=0),
        prompt_registry=prompt_registry_for_tests(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.input_panel.editor.setFocus()

    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F12)

    assert window._settings_window is not None
    assert window._settings_window.isVisible()


def test_debug_console_is_hidden_by_default_and_toggles(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    assert not window.debug_console.isVisible()

    qtbot.keyClick(
        window.input_panel.editor,
        Qt.Key.Key_D,
        modifier=Qt.KeyboardModifier.ControlModifier,
    )

    assert window.debug_console.isVisible()
    assert window.input_panel.isVisible()


def test_debug_console_does_not_close_review_or_input(qtbot) -> None:
    window = MainWindow(DeterministicProvider(delay_seconds=0))
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "debug keeps hud")
    wait_until_idle(qtbot, window)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    window.show_debug_console()

    assert window.debug_console.isVisible()
    assert window.review_hud.isVisible()
    assert window.input_panel.isVisible()


def test_external_provider_shows_non_secret_input_warning(qtbot) -> None:
    settings = AppSettings(provider=ProviderSettings(type="openai", openai_api_key="secret"))
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    warning = window.input_panel.warning.text()

    assert window.input_panel.warning.isVisible()
    assert "OpenAI API" in warning
    assert "秘密情報" in warning
    assert "secret" not in warning
