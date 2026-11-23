"""One LLM interface, three backends. Every model call in LedgerLens goes through here.

All backends speak the OpenAI-compatible chat API, so the rest of the code never
knows which one it's talking to:

- ``foundry_local``: Foundry Local on the dev machine. The port is assigned at runtime,
  so it's discovered with ``foundry-local-sdk`` unless ``FOUNDRY_LOCAL_BASE_URL`` is set.
- ``ollama``: Ollama / vLLM on Linux VMs.
- ``azure_foundry``: Azure AI Foundry, authenticated with Entra ID (no API keys).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from ledgerlens.config import LLMProvider, Settings, get_settings

log = logging.getLogger(__name__)

# Local servers ignore the key, but the OpenAI client requires a non-empty one.
_LOCAL_API_KEY = "not-needed"


@dataclass(frozen=True)
class LLMClient:
    """An OpenAI-compatible async client plus the model name to pass to it."""

    client: AsyncOpenAI
    model: str
    provider: LLMProvider

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        return resp.choices[0].message.content or ""


def _ensure_v1(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/v1") else f"{url}/v1"


def _discover_foundry_local(alias: str) -> tuple[str, str]:
    """Start Foundry Local in-process, load ``alias`` and return (base_url, model_id).

    Downloads the model on first use, which can take several minutes.
    """
    from foundry_local_sdk import Configuration, FoundryLocalManager

    if FoundryLocalManager.instance is None:
        config = Configuration(
            app_name="ledgerlens",
            # Port 0 lets the runtime pick a free port; we read it back from `urls`.
            web=Configuration.WebService(urls="http://127.0.0.1:0"),
            disable_nonessential_telemetry=True,
        )
        FoundryLocalManager.initialize(config)
    manager = FoundryLocalManager.instance
    assert manager is not None

    model = manager.catalog.get_model(alias)
    if model is None:
        raise RuntimeError(
            f"Model alias {alias!r} isn't in the Foundry Local catalog. "
            "Check the alias with `foundry model list`."
        )
    if not model.is_cached:
        log.info("Downloading %s (first run only)...", alias)
        model.download()
    if not model.is_loaded:
        model.load()

    if manager.urls is None:
        manager.start_web_service()
    if not manager.urls:
        raise RuntimeError("Foundry Local web service didn't report a listening URL.")
    return _ensure_v1(manager.urls[0]), model.id


def build_llm_client(settings: Settings) -> LLMClient:
    match settings.llm_provider:
        case LLMProvider.FOUNDRY_LOCAL:
            if settings.foundry_local_base_url:
                base_url, model = _ensure_v1(settings.foundry_local_base_url), settings.llm_model
            else:
                base_url, model = _discover_foundry_local(settings.llm_model)
            client = AsyncOpenAI(base_url=base_url, api_key=_LOCAL_API_KEY)
        case LLMProvider.OLLAMA:
            model = settings.llm_model
            client = AsyncOpenAI(
                base_url=_ensure_v1(settings.ollama_base_url), api_key=_LOCAL_API_KEY
            )
        case LLMProvider.AZURE_FOUNDRY:
            if not settings.azure_foundry_endpoint:
                raise ValueError(
                    "AZURE_FOUNDRY_ENDPOINT is required for llm_provider=azure_foundry"
                )
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            )
            model = settings.llm_model
            client = AsyncAzureOpenAI(
                azure_endpoint=settings.azure_foundry_endpoint,
                azure_ad_token_provider=token_provider,
                api_version=settings.azure_foundry_api_version,
            )
    log.info("LLM provider=%s model=%s", settings.llm_provider, model)
    return LLMClient(client=client, model=model, provider=settings.llm_provider)


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Process-wide client (Foundry Local discovery is expensive, so do it once)."""
    global _client
    if _client is None:
        _client = build_llm_client(get_settings())
    return _client
