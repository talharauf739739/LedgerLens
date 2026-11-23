from collections.abc import Iterator

import pytest

from ledgerlens.config import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tests never read the developer's real .env."""
    monkeypatch.chdir(__import__("pathlib").Path(__file__).parent)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
