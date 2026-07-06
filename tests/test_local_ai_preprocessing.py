import json

from uttate.conversion.local_ai import _input_payload, _prepare_local_ai_input


def test_local_ai_payload_includes_boundary_segments_and_two_mechanical_patterns() -> None:
    prepared = _prepare_local_ai_input("rakuten | ka do | nyuryok")
    payload = json.loads(_input_payload(prepared))

    segments = payload["preprocessed_segments"]

    assert payload["boundary_rule"].startswith("Treat `|` as the Uttate rough-input separator")
    assert [segment["kind"] for segment in segments] == [
        "text",
        "boundary",
        "text",
        "boundary",
        "text",
    ]
    assert segments[0]["raw_masked"] == "rakuten "
    assert segments[0]["mechanical_strict"] == "らくてん "
    assert segments[2]["mechanical_strict"] == " か ど "
    assert segments[4]["raw_masked"] == " nyuryok"
    assert segments[4]["mechanical_strict"] == " nyuryok"
    assert segments[4]["mechanical_typo_tolerant"] != " nyuryok"
    assert segments[4]["suspicious_tokens"][0]["raw"] == "nyuryok"
