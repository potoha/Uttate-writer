from uttate.logging_config import configure_logging


def test_configure_logging_creates_ignored_local_log_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    log_path = configure_logging()

    assert log_path == tmp_path / "logs" / "uttate.log"
    assert log_path.exists()
