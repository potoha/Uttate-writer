from __future__ import annotations

import json
import time
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from uttate.addons.dataset_collection import load_dataset_items
from uttate.addons.dataset_curator import load_candidates
from uttate.config import (
    AppearanceSettings,
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


class ContextRecordingProvider:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        self.contexts.append(previous_context)
        return ProviderResult(
            candidates=(Candidate("faithful", f"変換: {raw_text}"),)[:candidate_count],
            provider="context",
            model="test",
        )


def submit(qtbot, window: MainWindow, text: str) -> None:
    window.input_panel.editor.setPlainText(text)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_Return)


def wait_until_idle(qtbot, window: MainWindow) -> None:
    qtbot.waitUntil(lambda: window.conversion_queue.active_count == 0, timeout=3000)


def test_conversion_receives_bounded_accepted_context(qtbot) -> None:
    provider = ContextRecordingProvider()
    settings = AppSettings(provider=ProviderSettings(previous_context_chars=3))
    window = MainWindow(provider, settings=settings)
    qtbot.addWidget(window)

    window.commit_chunk("first")
    wait_until_idle(qtbot, window)
    window.document.chunks[0].adopt("ABCDE")
    window.commit_chunk("second")
    wait_until_idle(qtbot, window)

    assert provider.contexts == ["", "CDE"]


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


def test_theme_settings_apply_to_independent_windows(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UTTATE_CONFIG_DIR", str(tmp_path / "config"))
    bg_path = tmp_path / "review-bg.png"
    settings = AppSettings(
        appearance=AppearanceSettings(
            font_family="sans-serif",
            review_font_size=18,
            input_font_size=19,
            queue_font_size=15,
            shortcut_font_size=12,
            review_bg_image_path=str(bg_path),
            review_overlay=0.7,
            review_corner_radius=14,
        )
    )
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    review_stylesheet = window.review_hud.styleSheet()
    input_stylesheet = window.input_panel.styleSheet()

    assert "QWidget#review-hud" in review_stylesheet
    assert "font-size: 18px" in review_stylesheet
    assert bg_path.as_posix() in review_stylesheet
    assert "border-radius: 14px" in review_stylesheet
    assert "font-size: 19px" in input_stylesheet


def test_settings_window_theme_controls_reload_css(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UTTATE_CONFIG_DIR", str(tmp_path / "config"))
    custom_css = tmp_path / "custom.css"
    custom_css.write_text("/* custom-marker */\n", encoding="utf-8")
    window = MainWindow(
        DeterministicProvider(delay_seconds=0),
        prompt_registry=prompt_registry_for_tests(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window._open_settings_window()
    assert window._settings_window is not None

    settings_window = window._settings_window
    settings_window.theme_preset_combo.setCurrentIndex(
        settings_window.theme_preset_combo.findData("glass")
    )
    settings_window.review_font_size.setValue(17)
    settings_window.custom_css_path.setText(str(custom_css))
    settings_window._reload_css()

    assert window.settings.appearance.theme_preset == "glass"
    assert window.settings.appearance.review_font_size == 17
    assert "custom-marker" in window.review_hud.styleSheet()


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


def test_input_panel_always_on_top_button_applies_to_all_windows(qtbot) -> None:
    settings = AppSettings(dataset=DatasetCaptureSettings(collection_enabled=True))
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()
    window.show_debug_console()
    window._open_settings_window()
    window.show_dataset_review_window()

    managed_windows = [
        window.review_hud,
        window.input_panel,
        window.debug_console,
        window._settings_window,
        window._dataset_review_window,
    ]
    assert all(managed_window is not None for managed_window in managed_windows)
    assert not window.settings.input_panel.always_on_top

    qtbot.mouseClick(window.input_panel.always_on_top_button, Qt.MouseButton.LeftButton)

    assert window.settings.input_panel.always_on_top is True
    assert window.input_panel.always_on_top_button.isChecked()
    for managed_window in managed_windows:
        assert managed_window is not None
        assert managed_window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

    qtbot.mouseClick(window.input_panel.always_on_top_button, Qt.MouseButton.LeftButton)

    assert window.settings.input_panel.always_on_top is False
    assert not window.input_panel.always_on_top_button.isChecked()
    for managed_window in managed_windows:
        assert managed_window is not None
        assert not managed_window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


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
        dataset=DatasetCaptureSettings(capture_enabled=True, candidate_store_path=str(store))
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
        dataset=DatasetCaptureSettings(capture_enabled=False, candidate_store_path=str(store))
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


def test_dataset_collection_mode_off_does_not_create_review_candidates(qtbot, tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    settings = AppSettings(
        dataset=DatasetCaptureSettings(collection_enabled=False, review_store_path=str(store))
    )
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "private draft")
    wait_until_idle(qtbot, window)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_Return)

    assert window.document.chunks[0].status == ChunkStatus.ADOPTED
    assert not store.exists()
    window.show_dataset_review_window()
    assert window._dataset_review_window is None
    assert window.statusBar().currentMessage() == "Dataset Collection Mode is disabled"


def test_dataset_collection_mode_records_accepted_candidate(qtbot, tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    settings = AppSettings(
        dataset=DatasetCaptureSettings(collection_enabled=True, review_store_path=str(store))
    )
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "collect me")
    wait_until_idle(qtbot, window)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_Return)

    items = load_dataset_items(store)
    assert len(items) == 1
    assert items[0]["dataset_status"] == "candidate"
    assert items[0]["raw_input"] == "collect me"
    assert items[0]["converted_text"] == "変換候補A: collect me"
    assert items[0]["accepted_text"] == "変換候補A: collect me"
    assert "api_key" not in items[0]


def test_dataset_review_window_whitelist_toggle_and_export(qtbot, tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    output = tmp_path / "export.jsonl"
    settings = AppSettings(
        dataset=DatasetCaptureSettings(
            collection_enabled=True,
            review_store_path=str(store),
        )
    )
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "skip me")
    submit(qtbot, window, "export me")
    wait_until_idle(qtbot, window)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_Return)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_Return)
    window.show_dataset_review_window()

    assert window._dataset_review_window is not None
    assert window._dataset_review_window.item_count() == 2
    first_item_id = load_dataset_items(store)[0]["id"]
    window._set_dataset_item_status(first_item_id, "whitelisted")

    for field in ("raw_input", "normalized_input", "accepted_text"):
        safety_checkbox = window._dataset_review_window.safety_checkbox_for(first_item_id, field)
        assert safety_checkbox is not None
        assert not safety_checkbox.isChecked()
        safety_checkbox.click()
    assert (
        window._dataset_review_window.safety_checkbox_for(first_item_id, "converted_text") is None
    )
    assert window._dataset_review_window.safety_checkbox_for(first_item_id, "edited_text") is None
    assert {
        field: safety
        for field, safety in load_dataset_items(store)[0]["field_safety"].items()
        if field in {"raw_input", "normalized_input", "accepted_text"}
    } == {
        "raw_input": "confirmed",
        "normalized_input": "confirmed",
        "accepted_text": "confirmed",
    }
    window._export_whitelisted_dataset(output, confirm=False)

    exported_lines = output.read_text(encoding="utf-8").splitlines()
    assert len(exported_lines) == 1
    exported = json.loads(exported_lines[0])
    assert exported["target_output"] == "変換候補A: export me"
    assert exported["source"] == "uttate_writer_manual_whitelist"
    assert exported["schema_version"] == 1
    assert "accepted_text" not in exported
    assert "converted_text" not in exported
    assert "api_key" not in exported
    items = load_dataset_items(store)
    assert items[0]["dataset_status"] == "exported"
    assert items[0]["exported_at"]
    assert items[1]["dataset_status"] == "candidate"


def test_dataset_review_window_shortcut_anonymizes_and_undoes_without_whitelist_change(
    qtbot,
    tmp_path,
) -> None:
    store = tmp_path / "dataset_review.jsonl"
    settings = AppSettings(
        dataset=DatasetCaptureSettings(collection_enabled=True, review_store_path=str(store))
    )
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    submit(qtbot, window, "Alice visits Tokyo")
    wait_until_idle(qtbot, window)
    qtbot.keyClick(window.input_panel.editor, Qt.Key.Key_F2)
    qtbot.keyClick(window.review_hud.queue, Qt.Key.Key_Return)
    item_id = load_dataset_items(store)[0]["id"]
    window._set_dataset_item_status(item_id, "whitelisted")
    window.show_dataset_review_window()

    assert window._dataset_review_window is not None
    editor = window._dataset_review_window.editor_for(item_id, "accepted_text")
    assert editor is not None
    _select_text(editor, "Alice")
    qtbot.keyClick(editor, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)

    items = load_dataset_items(store)
    assert items[0]["dataset_status"] == "whitelisted"
    assert items[0]["accepted_text"] == "変換候補A: [PERSON_1] visits Tokyo"
    assert items[0]["converted_text"] == "変換候補A: [PERSON_1] visits Tokyo"
    assert items[0]["raw_input"] == "[PERSON_1] visits Tokyo"
    assert items[0]["normalized_input"] == "[PERSON_1] visits Tokyo"
    redaction = items[0]["redactions"][0]
    assert redaction["type"] == "PERSON"
    assert redaction["placeholder"] == "[PERSON_1]"
    assert redaction["original_text"] == "Alice"
    assert redaction["target_field"] == "accepted_text"
    assert isinstance(redaction["start"], int)
    assert isinstance(redaction["end"], int)
    assert redaction["created_at"]
    assert {entry["field"] for entry in redaction["replacements"]} >= {
        "accepted_text",
        "converted_text",
        "raw_input",
        "normalized_input",
    }

    editor = window._dataset_review_window.editor_for(item_id, "accepted_text")
    assert editor is not None
    qtbot.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    items = load_dataset_items(store)
    assert items[0]["dataset_status"] == "whitelisted"
    assert items[0]["accepted_text"] == "変換候補A: Alice visits Tokyo"
    assert items[0]["converted_text"] == "変換候補A: Alice visits Tokyo"
    assert items[0]["raw_input"] == "Alice visits Tokyo"
    assert items[0]["normalized_input"] == "Alice visits Tokyo"
    assert items[0]["redactions"] == []


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


def _select_text(editor: QPlainTextEdit, text: str) -> None:
    full_text = editor.toPlainText()
    start = full_text.index(text)
    cursor = editor.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(start + len(text), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor.setFocus()


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
    assert "privacy-warning-external" in window.input_panel.warning.property("class")

    window.input_panel.provider_combo.setCurrentIndex(
        window.input_panel.provider_combo.findData("local_ai")
    )

    assert window.settings.provider.type == "local_ai"
    assert "Local AI / model not selected" in window.input_panel.model_label.text()
    assert "外部APIへ送信されません" in window.input_panel.warning.text()
    assert "privacy-warning-local" in window.input_panel.warning.property("class")


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


def test_input_panel_shows_gemini_privacy_warning(qtbot) -> None:
    settings = AppSettings(provider=ProviderSettings(type="gemini", gemini_api_key="secret"))
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    warning = window.input_panel.warning.text()

    assert window.input_panel.warning.isVisible()
    assert warning == (
        "外部API使用中: Gemini API。個人情報・未公開原稿・秘密情報は入力しないでください。"
    )
    assert "privacy-warning-external" in window.input_panel.warning.property("class")
    assert "secret" not in warning


def test_input_panel_privacy_warning_can_be_hidden_from_settings(qtbot) -> None:
    settings = AppSettings(
        provider=ProviderSettings(type="openai", openai_api_key="secret"),
        dataset=DatasetCaptureSettings(warn_external_api_active=False),
    )
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    assert not window.input_panel.warning.isVisible()


def test_unknown_provider_uses_external_privacy_warning(qtbot) -> None:
    settings = AppSettings(provider=ProviderSettings(type="custom_api", model="custom-model"))
    window = MainWindow(DeterministicProvider(delay_seconds=0), settings=settings)
    qtbot.addWidget(window)
    window.show()

    warning = window.input_panel.warning.text()

    assert window.input_panel.warning.isVisible()
    assert warning == (
        "外部API使用中: External API。個人情報・未公開原稿・秘密情報は入力しないでください。"
    )
    assert "privacy-warning-external" in window.input_panel.warning.property("class")
