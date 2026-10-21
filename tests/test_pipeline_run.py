import asyncio
import base64
import json

import httpx
import pytest
import respx

from app.config import settings
from app.pipeline import fetch, gigachat
from app.pipeline.run import run_search
from app.pipeline.slots import RankedSlots
from tests.test_pipeline_parse import fixture_text

SEARCH_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0"><response><results><grouping>
<group><doc><url>https://rybdvor.ru/</url><domain>rybdvor.ru</domain><title>Рыбный двор</title>
<passages><passage>Охлаждённый <hlword>лосось</hlword> оптом</passage></passages></doc></group>
<group><doc><url>https://www.avito.ru/ekaterinburg/losos</url><domain>www.avito.ru</domain><title>Лосось на Авито</title></doc></group>
<group><doc><url>https://spa.ru/</url><domain>spa.ru</domain><title>Морепродукты</title>
<passages><passage>Морепродукты в Екатеринбурге, звоните +7 (343) 111-22-33</passage></passages></doc></group>
</grouping></results></response></yandexsearch>"""


def chat_reply(request: httpx.Request) -> httpx.Response:
    if "поисковых запросов" in request.content.decode():
        content = '["лосось оптом Екатеринбург", "лосось поставщик Екатеринбург", "семга производитель Екатеринбург"]'
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 100}}
        )
    return httpx.Response(200, text=fixture_text("gigachat_extract.json"))


@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr(gigachat, "_cached_token", None)
    for key in ("gigachat_auth_key", "dadata_api_key", "yandex_search_api_key", "yandex_folder_id"):
        monkeypatch.setattr(settings, key, "test")
    html = {"content-type": "text/html; charset=utf-8"}
    with respx.mock(assert_all_called=False) as router:
        router.post("https://searchapi.api.cloud.yandex.net/v2/web/search", name="search").respond(
            json={"rawData": base64.b64encode(SEARCH_XML.encode()).decode()}
        )
        router.post(gigachat.OAUTH_URL).respond(json={"access_token": "t", "expires_at": 9_999_999_999_000})
        router.post(gigachat.CHAT_URL, name="chat").mock(side_effect=chat_reply)
        router.post("https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party").respond(
            text=fixture_text("dadata_party.json")
        )
        router.get("https://rybdvor.ru/robots.txt").respond(404)
        router.get("https://rybdvor.ru/").respond(text=fixture_text("supplier_main.html"), headers=html)
        router.get("https://rybdvor.ru/kontakty/").respond(text=fixture_text("supplier_contacts.html"), headers=html)
        router.get("https://rybdvor.ru/dostavka/").respond(301, headers={"location": "https://rybdvor.ru/kontakty/"})
        router.get("https://spa.ru/robots.txt").respond(text="User-agent: *\nDisallow: /")
        yield router


async def test_run_search_end_to_end(mocked):
    events = [event async for event in run_search("Лосось  охлаждённый", "екб")]
    assert [e.stage for e in events if e.type == "stage"] == ["queries", "search", "sites"]
    assert {e.supplier.domain for e in events if e.type == "supplier"} == {"rybdvor.ru", "spa.ru"}
    result = events[-1].result
    assert result.city == "Екатеринбург"
    assert result.category == "Лосось охлаждённый"
    assert len(result.queries) == 3
    assert [s.domain for s in result.aggregators] == ["avito.ru"]

    top = result.suppliers[0]
    assert top.domain == "rybdvor.ru"
    assert top.name == "Рыбный двор"
    assert top.site_opened
    assert top.kind == "distributor"
    assert top.phones[0] == "+7 343 200-10-21"
    assert top.inn == "6671012340"
    assert top.legal.status == "ACTIVE"
    assert set(top.facts) == {"sells_category", "min_order", "price", "delivery", "payment"}
    assert top.facts["delivery"].url == "https://rybdvor.ru/kontakty/"
    assert top.confirmed == 5
    assert (top.group, top.doubt, top.delivery_label) == ("match", None, "да — местный")
    assert top.questions and "Екатеринбург" in top.rfq

    spa = result.suppliers[1]
    assert not spa.site_opened
    assert spa.phones == ["+7 343 111-22-33"]
    assert spa.facts == {}

    stats = result.stats
    assert stats.search_calls == 3
    assert stats.llm_calls == 3
    assert stats.tokens == 100 + 2360 * 2
    assert stats.candidates == 2
    assert stats.suppliers == 2
    assert stats.with_phone == 2
    assert stats.rejected_quotes == 1 + 6
    assert stats.cost_rub == round(3 * settings.yandex_rub_per_request + 4.82 * settings.gigachat_rub_per_1k_tokens, 2)
    json.loads(result.model_dump_json())


async def collect(category: str = "лосось", city: str = "Екатеринбург") -> list:
    return [event async for event in run_search(category, city)]


async def test_search_api_failure_is_not_empty_result(mocked):
    mocked["search"].respond(403)
    events = await collect()
    assert [e.stage for e in events if e.type == "error"] == ["unavailable"]
    assert events[-1].result.suppliers == []


async def test_llm_failure_keeps_legal_info(mocked):
    mocked["chat"].mock(side_effect=None).respond(500)
    top = (await collect())[-1].result.suppliers[0]
    assert top.domain == "rybdvor.ru"
    assert top.legal.status == "ACTIVE"
    assert top.facts == {}


async def test_timeout_still_reads_contacts_from_snippet(mocked, monkeypatch):
    async def hang(*args):
        await asyncio.sleep(60)

    monkeypatch.setattr(fetch, "fetch_site", hang)
    monkeypatch.setattr(settings, "search_budget_seconds", 0.3)
    events = await collect()
    assert "timeout" in [e.stage for e in events]
    spa = next(s for s in events[-1].result.suppliers if s.domain == "spa.ru")
    assert spa.phones == ["+7 343 111-22-33"]


async def test_llm_slots_follow_rank():
    slots = RankedSlots(1)
    order = []

    async def worker(rank: int) -> None:
        async with slots.take(rank):
            order.append(rank)

    async with slots.take(0):
        workers = [asyncio.create_task(worker(rank)) for rank in (3, 1, 2)]
        await asyncio.sleep(0)
    await asyncio.gather(*workers)
    assert order == [1, 2, 3]
