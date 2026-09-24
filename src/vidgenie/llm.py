from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from vidgenie.config import Settings

MIN_DURATION = 2.0
MAX_DURATION = 12.0
DEFAULT_DURATION = 4.0
_RETRY_BASE_DELAY = 1.0
_MAX_ERROR_BODY = 500


class LLMError(Exception):
    """Kesalahan saat memanggil LLM atau mem-parsing outputnya."""


@dataclass
class Scene:
    narration: str
    search_query: str
    duration_sec: float


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    model_fallback: str = ""
    timeout: float = 60.0
    max_tokens: int = 1024
    max_retries: int = 3

    @classmethod
    def from_settings(cls, settings: Settings) -> LLMConfig:
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            model_fallback=settings.llm_model_fallback,
            timeout=settings.llm_timeout,
            max_tokens=settings.llm_max_tokens,
            max_retries=settings.llm_max_retries,
        )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_BLOCK_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def extract_json(text: str) -> Any:
    """Ambil JSON dari output LLM berlapis: langsung -> code fence -> regex blok."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError, ValueError:
        pass

    candidate = stripped
    fence = _FENCE_RE.search(stripped)
    if fence:
        candidate = fence.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError, ValueError:
            pass

    block = _BLOCK_RE.search(candidate)
    if block:
        try:
            return json.loads(block.group(1))
        except json.JSONDecodeError, ValueError:
            pass

    raise LLMError("output LLM bukan JSON yang valid")


def _clamp_duration(value: Any) -> float:
    try:
        number = float(value)
    except TypeError, ValueError:
        return DEFAULT_DURATION
    return max(MIN_DURATION, min(MAX_DURATION, number))


def _heuristic_scenes(narration: str) -> list[Scene]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", narration.strip())
    scenes: list[Scene] = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        scenes.append(Scene(narration=text, search_query=text, duration_sec=DEFAULT_DURATION))
    if not scenes and narration.strip():
        text = narration.strip()
        scenes.append(Scene(narration=text, search_query=text, duration_sec=DEFAULT_DURATION))
    return scenes


def _parse_scenes(data: Any) -> list[Scene]:
    if isinstance(data, dict):
        data = data.get("scenes") or data.get("plan") or []
    if not isinstance(data, list):
        raise LLMError("JSON plan bukan array")

    scenes: list[Scene] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        narration = str(item.get("narration") or item.get("text") or "").strip()
        if not narration:
            continue
        query = str(item.get("_query") or narration).strip()
        scenes.append(
            Scene(
                narration=narration,
                search_query=query or narration,
                duration_sec=_clamp_duration(item.get("duration_sec")),
            )
        )
    if not scenes:
        raise LLMError("JSON plan tidak memuat scene valid")
    return scenes


_PLAN_SYSTEM = (
    "Kamu memecah narasi Bahasa Indonesia menjadi daftar scene untuk video vertikal 9:16. "
    "Balas HANYA JSON array valid tanpa penjelasan atau code fence. "
    'Setiap elemen: {"narration": string, "_query": string, "duration_sec": number}. '
    "Aturan: 'narration' adalah potongan asli dari narasi (jangan parafrase, jangan ubah kata); "
    "'_query' adalah cue visual ringkas (subjek, aksi, suasana, komposisi) dalam Bahasa Indonesia; "
    "'duration_sec' antara 2 sampai 12 detik."
)

_PLAN_FEWSHOT_USER = (
    "Pagi itu matahari terbit di balik pegunungan berkabut. Seorang nelayan melaut mencari ikan."
)

_PLAN_FEWSHOT_ASSISTANT = (
    '[{"narration": "Pagi itu matahari terbit di balik pegunungan berkabut.", '
    '"_query": "matahari terbit di balik pegunungan berkabut, suasana pagi", '
    '"duration_sec": 4}, '
    '{"narration": "Seorang nelayan melaut mencari ikan.", '
    '"_query": "nelayan di atas perahu melaut mencari ikan di laut", '
    '"duration_sec": 5}]'
)


class LLMClient:
    def __init__(self, config: LLMConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _endpoint(self) -> str:
        return self.config.base_url.rstrip("/") + "/chat/completions"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        last_error: LLMError | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.post(
                    self._endpoint(),
                    json=payload,
                    headers=self._headers(),
                    timeout=self.config.timeout,
                )
            except httpx.HTTPError as exc:
                raise LLMError(f"gagal menghubungi LLM: {exc}") from exc

            if response.status_code == 429 or response.status_code >= 500:
                last_error = LLMError(
                    f"LLM membalas {response.status_code}: {response.text[:_MAX_ERROR_BODY]}"
                )
                if attempt < self.config.max_retries:
                    time.sleep(_RETRY_BASE_DELAY * (2**attempt))
                    continue
                raise last_error

            if response.status_code >= 400:
                raise LLMError(
                    f"LLM membalas {response.status_code}: {response.text[:_MAX_ERROR_BODY]}"
                )

            return self._extract_content(response)

        raise last_error or LLMError("permintaan LLM gagal")

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("respons LLM bukan JSON") from exc
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("respons LLM tanpa choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMError("respons LLM tanpa konten teks")
        return content

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = 0.2,
    ) -> Any:
        raw = self.chat(messages, temperature=temperature)
        try:
            return extract_json(raw)
        except LLMError as first_error:
            if not self.config.model_fallback:
                raise
            try:
                raw_fallback = self.chat(
                    messages,
                    model=self.config.model_fallback,
                    temperature=temperature,
                )
                return extract_json(raw_fallback)
            except LLMError:
                raise first_error from None

    def plan_scenes(self, narration: str) -> list[Scene]:
        text = narration.strip()
        if not text:
            raise LLMError("narasi kosong")

        messages = [
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": _PLAN_FEWSHOT_USER},
            {"role": "assistant", "content": _PLAN_FEWSHOT_ASSISTANT},
            {"role": "user", "content": text},
        ]
        try:
            data = self.complete_json(messages)
            return _parse_scenes(data)
        except LLMError:
            return _heuristic_scenes(text)
