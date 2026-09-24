from pathlib import Path

from vidgenie.config import Settings
from vidgenie.llm import LLMConfig
from vidgenie.settings_store import MASK, SettingsStore, mask_api_key, resolve_llm_config


def _store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(Settings(data_dir=tmp_path))


def test_set_and_get(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set("model", "gpt-4o-mini")
    assert store.get("model") == "gpt-4o-mini"
    assert store.get("tidak-ada") is None
    store.close()


def test_persist_across_reopen(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_many({"base_url": "https://x/v1", "api_key": "abc", "model": "m1"})
    store.close()
    reopened = _store(tmp_path)
    assert reopened.all() == {"base_url": "https://x/v1", "api_key": "abc", "model": "m1"}
    reopened.close()


def test_set_many_overwrites_and_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_many({"model": "m1", "timeout": "30"})
    store.set_many({"model": "m2", "max_tokens": "512"})
    assert store.all() == {"model": "m2", "timeout": "30", "max_tokens": "512"}
    store.delete("timeout")
    assert store.get("timeout") is None
    store.close()


def test_mask_api_key() -> None:
    assert mask_api_key("super-secret") == MASK
    assert mask_api_key("") == ""
    assert mask_api_key(None) == ""


def test_resolve_prefers_store_over_settings(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        llm_base_url="https://env/v1",
        llm_model="env-model",
        llm_timeout=10.0,
    )
    store = _store(tmp_path)
    store.set_many(
        {
            "base_url": "https://db/v1",
            "api_key": "db-key",
            "model": "db-model",
            "timeout": "25",
            "max_tokens": "2048",
            "max_retries": "5",
        }
    )
    config = resolve_llm_config(settings, store)
    assert isinstance(config, LLMConfig)
    assert config.base_url == "https://db/v1"
    assert config.api_key == "db-key"
    assert config.model == "db-model"
    assert config.timeout == 25.0
    assert config.max_tokens == 2048
    assert config.max_retries == 5
    store.close()


def test_resolve_empty_store_falls_back_to_settings(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        llm_base_url="https://env/v1",
        llm_api_key="env-key",
        llm_model="env-model",
        llm_timeout=7.5,
    )
    store = _store(tmp_path)
    config = resolve_llm_config(settings, store)
    assert config.base_url == "https://env/v1"
    assert config.api_key == "env-key"
    assert config.model == "env-model"
    assert config.timeout == 7.5
    store.close()


def test_resolve_none_store_uses_settings(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, llm_model="env-model")
    config = resolve_llm_config(settings, None)
    assert config.model == "env-model"


def test_resolve_ignores_invalid_stored_numbers(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, llm_timeout=60.0, llm_max_tokens=1024)
    store = _store(tmp_path)
    store.set_many({"timeout": "abc", "max_tokens": "xyz"})
    config = resolve_llm_config(settings, store)
    assert config.timeout == 60.0
    assert config.max_tokens == 1024
    store.close()
