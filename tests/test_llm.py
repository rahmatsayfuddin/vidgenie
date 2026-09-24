from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from vidgenie import llm
from vidgenie.config import Settings
from vidgenie.llm import LLMClient, LLMConfig, LLMError, Scene, extract_json


def _client(handler: Any) -> LLMClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return LLMClient(LLMConfig(api_key="secret", max_retries=2), client=http_client)


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)


def test_chat_returns_content_and_sends_auth() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _completion("halo")

    client = _client(handler)
    out = client.chat([{"role": "user", "content": "hai"}])

    assert out == "halo"
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer secret"
    assert seen["body"]["messages"][0]["content"] == "hai"


def test_chat_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, text="rate limited")
        return _completion("akhirnya")

    client = _client(handler)
    assert client.chat([{"role": "user", "content": "hai"}]) == "akhirnya"
    assert calls["n"] == 3


def test_chat_does_not_retry_4xx() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    client = _client(handler)
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hai"}])
    assert calls["n"] == 1


def test_chat_gives_up_after_max_retries() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    client = _client(handler)
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hai"}])
    assert calls["n"] == 3


def test_chat_raises_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hai"}])


def test_extract_json_layers() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('Berikut hasilnya:\n[{"a": 3}]\nSemoga membantu.') == [{"a": 3}]
    with pytest.raises(LLMError):
        extract_json("bukan json sama sekali")


def test_complete_json_uses_fallback_model() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        models.append(body["model"])
        if body["model"] == "utama":
            return _completion("maaf, ini bukan json")
        return _completion('{"ok": true}')

    client = LLMClient(
        LLMConfig(model="utama", model_fallback="kecil", max_retries=0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.complete_json([{"role": "user", "content": "x"}]) == {"ok": True}
    assert models == ["utama", "kecil"]


def test_complete_json_raises_without_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _completion("tidak ada json")

    client = LLMClient(
        LLMConfig(model="utama", model_fallback="", max_retries=0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMError):
        client.complete_json([{"role": "user", "content": "x"}])


def test_plan_scenes_parses_and_clamps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps(
            [
                {"narration": "Scene satu.", "_query": "pantai", "duration_sec": 1},
                {"narration": "Scene dua.", "_query": "gunung", "duration_sec": 99},
                {"narration": "", "_query": "kosong", "duration_sec": 5},
            ]
        )
        return _completion(content)

    client = LLMClient(
        LLMConfig(max_retries=0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    scenes = client.plan_scenes("Scene satu. Scene dua.")

    assert scenes == [
        Scene(narration="Scene satu.", search_query="pantai", duration_sec=2.0),
        Scene(narration="Scene dua.", search_query="gunung", duration_sec=12.0),
    ]


def test_plan_scenes_falls_back_to_heuristic() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _completion("model rusak, bukan json")

    client = LLMClient(
        LLMConfig(model_fallback="", max_retries=0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    narration = "Pagi cerah. Nelayan melaut! Apakah laut tenang?"
    scenes = client.plan_scenes(narration)

    assert [s.narration for s in scenes] == [
        "Pagi cerah.",
        "Nelayan melaut!",
        "Apakah laut tenang?",
    ]
    assert all(s.search_query == s.narration for s in scenes)
    assert all(s.duration_sec == llm.DEFAULT_DURATION for s in scenes)


def test_plan_scenes_rejects_empty_narration() -> None:
    client = LLMClient(LLMConfig(max_retries=0), client=httpx.Client())
    with pytest.raises(LLMError):
        client.plan_scenes("   ")


def test_llm_config_from_settings() -> None:
    settings = Settings(
        data_dir=Path("/tmp/x"),
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="k",
        llm_model="m1",
        llm_model_fallback="m2",
        llm_timeout=5.0,
        llm_max_tokens=64,
        llm_max_retries=1,
    )
    config = LLMConfig.from_settings(settings)
    assert config.base_url == "http://localhost:11434/v1"
    assert config.api_key == "k"
    assert config.model == "m1"
    assert config.model_fallback == "m2"
    assert config.timeout == 5.0
    assert config.max_tokens == 64
    assert config.max_retries == 1


def test_settings_from_env_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDGENIE_LLM_BASE_URL", "http://llm.local/v1")
    monkeypatch.setenv("VIDGENIE_LLM_API_KEY", "rahasia")
    monkeypatch.setenv("VIDGENIE_LLM_MODEL", "model-besar")
    monkeypatch.setenv("VIDGENIE_LLM_MODEL_FALLBACK", "model-kecil")
    monkeypatch.setenv("VIDGENIE_LLM_TIMEOUT", "12.5")
    monkeypatch.setenv("VIDGENIE_LLM_MAX_TOKENS", "256")
    monkeypatch.setenv("VIDGENIE_LLM_MAX_RETRIES", "1")

    settings = Settings.from_env()
    assert settings.llm_base_url == "http://llm.local/v1"
    assert settings.llm_api_key == "rahasia"
    assert settings.llm_model == "model-besar"
    assert settings.llm_model_fallback == "model-kecil"
    assert settings.llm_timeout == 12.5
    assert settings.llm_max_tokens == 256
    assert settings.llm_max_retries == 1
