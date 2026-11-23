import pytest

from ledgerlens.config import LLMProvider, Settings
from ledgerlens.llm import provider
from ledgerlens.llm.provider import _ensure_v1, build_llm_client


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:5273", "http://127.0.0.1:5273/v1"),
        ("http://127.0.0.1:5273/", "http://127.0.0.1:5273/v1"),
        ("http://127.0.0.1:5273/v1", "http://127.0.0.1:5273/v1"),
        ("http://127.0.0.1:5273/v1/", "http://127.0.0.1:5273/v1"),
    ],
)
def test_ensure_v1(url: str, expected: str) -> None:
    assert _ensure_v1(url) == expected


def test_foundry_local_explicit_url_skips_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(alias: str) -> tuple[str, str]:
        raise AssertionError("discovery must not run when FOUNDRY_LOCAL_BASE_URL is set")

    monkeypatch.setattr(provider, "_discover_foundry_local", boom)
    llm = build_llm_client(
        Settings(llm_provider=LLMProvider.FOUNDRY_LOCAL, foundry_local_base_url="http://host:1234")
    )
    assert str(llm.client.base_url) == "http://host:1234/v1/"
    assert llm.model == "phi-4-mini"


def test_foundry_local_discovers_port_and_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider,
        "_discover_foundry_local",
        lambda alias: ("http://127.0.0.1:61234/v1", "phi-4-mini-cpu:1"),
    )
    llm = build_llm_client(Settings(llm_provider=LLMProvider.FOUNDRY_LOCAL))
    assert str(llm.client.base_url) == "http://127.0.0.1:61234/v1/"
    assert llm.model == "phi-4-mini-cpu:1"


def test_ollama() -> None:
    llm = build_llm_client(
        Settings(
            llm_provider=LLMProvider.OLLAMA,
            llm_model="qwen2.5:7b",
            ollama_base_url="http://vm:11434",
        )
    )
    assert str(llm.client.base_url) == "http://vm:11434/v1/"
    assert llm.model == "qwen2.5:7b"
    assert llm.provider is LLMProvider.OLLAMA


def test_azure_requires_endpoint() -> None:
    with pytest.raises(ValueError, match="AZURE_FOUNDRY_ENDPOINT"):
        build_llm_client(Settings(llm_provider=LLMProvider.AZURE_FOUNDRY))
