# Main merge preparation

This note summarizes the merge-ready state of the API-backed Uttate branch.
Git operations are intentionally left to the human/YURA flow.

## Provider cleanup

- User-facing providers are now only `local_ai`, `openai`, and `gemini`.
- The UI shows `Local AI`, `OpenAI`, and `Google Gemini`.
- `lmstudio` is accepted only as a legacy config alias and is mapped to `local_ai`.
- `mock` is accepted only as a removed-provider config alias and is mapped to `local_ai`.
- Production `MockProvider` was removed. UI tests use test-local fake providers instead.
- Standalone `openai_compatible` provider selection was removed. OpenAI-compatible HTTP behavior now lives under the `local_ai` / LM Studio path.

## Local AI path

`local_ai` is the canonical provider ID for the main-derived local conversion flow.
It uses the LM Studio OpenAI-compatible endpoint configured with:

```env
UTTATE_PROVIDER=local_ai
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_MODEL=
```

If `LMSTUDIO_MODEL` is empty, the loaded model is auto-detected from `/v1/models`.

## Merge-sensitive files

Expect conflicts or review attention around these files:

- `src/uttate/config.py`
- `src/uttate/providers/factory.py`
- `src/uttate/providers/local_ai.py`
- `src/uttate/conversion/local_ai.py`
- `src/uttate/ui/provider_panel.py`
- `src/uttate/ui/main_window.py`
- `tests/test_config.py`
- `tests/test_provider_panel.py`
- `tests/test_providers.py`
- `tests/test_m2_ui.py`
- `README.md`
- `.env.example`

Deleted provider files:

- `src/uttate/providers/mock.py`
- `src/uttate/providers/openai_compatible.py`

## Validation commands

Run from the repository root:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pytest.exe
```

Expected result at preparation time:

- Ruff check passes.
- Ruff format check passes.
- Pytest passes with 95 tests.

## Startup compatibility

Old local settings such as:

```env
UTTATE_PROVIDER=mock
```

or:

```env
UTTATE_PROVIDER=lmstudio
```

are mapped to `local_ai` during settings load. This preserves startup compatibility
without restoring either `mock` or `lmstudio` as user-facing provider choices.
