import pytest
from fastapi.testclient import TestClient

from ledgerlens.api import main


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_all_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok() -> None:
        return None

    monkeypatch.setattr(main, "CHECKS", {"postgres": ok, "cache": ok, "blob": ok})
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"ready": True, "checks": {"postgres": "ok", "cache": "ok", "blob": "ok"}}


def test_readyz_reports_which_dependency_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    async def down() -> None:
        raise ConnectionRefusedError

    monkeypatch.setattr(main, "CHECKS", {"postgres": ok, "cache": down, "blob": ok})
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["checks"]["cache"] == "error: ConnectionRefusedError"
    assert body["checks"]["postgres"] == "ok"
