from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vidgenie import main
from vidgenie.config import Settings
from vidgenie.storage import Storage


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    return TestClient(main.app)


def test_settings_page_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Pengaturan LLM" in resp.text
    assert 'name="base_url"' in resp.text
    assert 'name="model"' in resp.text


def test_settings_save_persists_and_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.post(
        "/settings",
        data={
            "base_url": "https://llm.example/v1",
            "model": "my-model",
            "timeout": "30",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings?saved=1"

    page = client.get("/settings?saved=1").text
    assert "Pengaturan tersimpan." in page
    assert 'value="https://llm.example/v1"' in page
    assert 'value="my-model"' in page
    assert 'value="30"' in page

    config = main._llm_config()
    assert config.base_url == "https://llm.example/v1"
    assert config.model == "my-model"
    assert config.timeout == 30.0


def test_settings_save_never_leaks_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.post(
        "/settings",
        data={"base_url": "https://llm.example/v1", "model": "m", "api_key": "super-secret"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = client.get("/settings").text
    assert "super-secret" not in page
    assert "********" in page
    assert main._llm_config().api_key == "super-secret"


def test_settings_save_blank_api_key_keeps_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post(
        "/settings",
        data={"base_url": "https://llm.example/v1", "model": "m", "api_key": "keep-me"},
    )
    client.post("/settings", data={"base_url": "https://llm.example/v1", "model": "m"})
    assert main._llm_config().api_key == "keep-me"

    page = client.get("/settings").text
    assert "keep-me" not in page
    assert "********" in page


def test_settings_save_clear_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post(
        "/settings",
        data={"base_url": "https://llm.example/v1", "model": "m", "api_key": "drop-me"},
    )
    resp = client.post(
        "/settings",
        data={"base_url": "https://llm.example/v1", "model": "m", "clear_api_key": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert main._llm_config().api_key == ""

    page = client.get("/settings").text
    assert "drop-me" not in page
    assert "********" not in page
    assert 'name="clear_api_key"' not in page


def test_settings_save_invalid_numbers_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    for field in ("timeout", "max_tokens", "max_retries"):
        data = {"base_url": "https://llm.example/v1", "model": "m", field: "abc"}
        resp = client.post("/settings", data=data)
        assert resp.status_code == 400
        assert "harus" in resp.text


def test_settings_save_missing_required_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/settings", data={"model": "m"}).status_code == 400
    assert client.post("/settings", data={"base_url": "https://llm.example/v1"}).status_code == 400
