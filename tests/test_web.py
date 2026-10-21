import json

import pytest
import respx
from fastapi.testclient import TestClient

from app import limits, web
from app.config import settings
from app.main import app
from app.schemas import ProgressEvent

ORIGIN = {"origin": "http://testserver"}
QUERY = {"category": "рыба", "city": "Екатеринбург"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def live(monkeypatch):
    async def fake_search(category: str, city: str):
        yield ProgressEvent(type="stage", stage="queries", message=f"{category} — {city}")

    monkeypatch.setattr(web, "run_search", fake_search)
    monkeypatch.setattr(limits, "counter", limits.MemoryCounter())
    monkeypatch.setattr(settings, "live_search_enabled", True)
    monkeypatch.setattr(settings, "live_search_daily_limit", 10)
    monkeypatch.setattr(settings, "live_search_ip_hourly_limit", 3)


def search(client: TestClient, headers: dict | None = None, **query):
    return client.post("/api/search/stream", json=query or QUERY, headers=ORIGIN if headers is None else headers)


@pytest.mark.parametrize("slug", ["..%2Fapp%2Fconfig", "nope", "BAD", "%2e%2e", "a b"])
def test_bad_demo_slug(client, slug):
    assert client.get(f"/demo/{slug}").status_code == 404


def test_demo_page(client):
    assert client.get("/demo/chicken-ekb").status_code == 200


def test_search_without_params_redirects_home(client):
    response = client.get("/search", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_index_defaults_to_ekaterinburg(client):
    assert '<option value="Екатеринбург" selected>' in client.get("/").text


def test_unknown_city_or_empty_category(client, live):
    assert client.get("/search?category=x&city=Атлантида").status_code == 400
    assert search(client, category="x", city="Атлантида").status_code == 400
    assert search(client, category="", city="Екатеринбург").status_code == 400


def test_search_streams_events(client, live):
    response = search(client)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson"
    assert ProgressEvent.model_validate_json(response.text).message == "рыба — Екатеринбург"


@pytest.mark.parametrize(
    "headers",
    [{}, {"origin": "https://evil.example"}, {"referer": "https://evil.example/search"}],
)
def test_search_requires_own_origin(client, live, headers):
    assert search(client, headers=headers).status_code == 403


def test_search_accepts_own_referer(client, live):
    assert search(client, headers={"referer": "http://testserver/search?category=x"}).status_code == 200


def test_get_is_not_allowed(client, live):
    assert client.get("/api/search/stream?category=рыба&city=Екатеринбург").status_code == 405


def test_disabled_search(client, live, monkeypatch):
    monkeypatch.setattr(settings, "live_search_enabled", False)
    response = search(client)
    assert response.status_code == 429
    assert "выключен" in response.text


def test_limit_per_ip(client, live):
    for _ in range(3):
        assert search(client).status_code == 200
    refused = search(client)
    assert refused.status_code == 429
    assert "с вашего адреса" in refused.text.lower()
    other = search(client, headers={**ORIGIN, "x-forwarded-for": "203.0.113.7"})
    assert other.status_code == 200


def test_daily_limit(client, live, monkeypatch):
    monkeypatch.setattr(settings, "live_search_daily_limit", 2)
    for ip in ("203.0.113.1", "203.0.113.2"):
        assert search(client, headers={**ORIGIN, "x-forwarded-for": ip}).status_code == 200
    refused = search(client, headers={**ORIGIN, "x-forwarded-for": "203.0.113.3"})
    assert refused.status_code == 429
    assert "закончились" in refused.text
    assert client.get("/healthz").json()["live_left"] == 0


async def test_upstash_counter_increments_with_expiry():
    counter = limits.UpstashCounter("https://redis.example/", "token")
    with respx.mock() as router:
        route = router.post("https://redis.example/multi-exec").respond(json=[{"result": 4}, {"result": 1}])
        assert await counter.incr("live:day:2026-10-21", 3600) == 4
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer token"
    assert json.loads(request.content) == [["INCR", "live:day:2026-10-21"], ["EXPIRE", "live:day:2026-10-21", 3600]]
