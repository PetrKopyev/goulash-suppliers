import json
from pathlib import Path

from app.config import settings
from app.pipeline.extract_llm import parse_answer, select_text
from app.pipeline.fetch import Page, parse_html, pick_subpages
from app.pipeline.filters import is_aggregator, split_hits
from app.pipeline.legal import parse_party
from app.pipeline.queries import parse_queries, template_queries
from app.pipeline.regions import find_region
from app.pipeline.yandex_search import Hit, host_of, parse_response

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_yandex_response():
    hits = parse_response(json.loads(fixture_text("yandex_search_response.json")))
    assert len(hits) == 20
    assert hits[0].domain == "opt.defagroup.com"
    assert hits[0].title == "Defa group – оптовая продажа рыбы и морепродуктов"
    assert "Екатеринбург и Свердловская область" in hits[0].snippet
    assert hits[1].domain == "molprodukt-ekb.ru"
    assert hits[7].domain == "96фабрикарыбы.рф" or hits[7].domain.endswith(".рф")
    assert [h.position for h in hits] == list(range(1, 21))


def test_aggregators_filtered_and_ranked(monkeypatch):
    monkeypatch.setattr(settings, "max_domains", 15)
    hits = parse_response(json.loads(fixture_text("yandex_search_response.json")))
    more = [
        Hit("https://rybkaopt.ru/contacts", "rybkaopt.ru", "Рыбка", "", 3),
        Hit("https://ekb.pulscen.ru/x", "ekb.pulscen.ru", "Пульс", "", 1),
    ]
    groups, sources = split_hits(hits + more)
    domains = {s.domain for s in sources}
    assert {"avito.ru", "online.metro-cc.ru", "lenta.com", "ozon.ru", "ekb.pulscen.ru"} <= domains
    assert all(not is_aggregator(g[0].domain) for g in groups)
    assert len(groups) == settings.max_domains
    assert groups[0][0].domain == "rybkaopt.ru"
    assert len({g[0].domain for g in groups}) == len(groups)


def test_is_aggregator_matches_subdomains_only():
    assert is_aggregator("market.yandex.ru")
    assert is_aggregator("spb.flagma.ru")
    assert not is_aggregator("notavito.ru")
    assert not is_aggregator("rybkaopt.ru")


def test_aggregator_host_ignores_www_and_case():
    assert host_of("https://WWW.Avito.RU/ekaterinburg") == "avito.ru"
    assert is_aggregator(host_of("https://Market.Yandex.ru/x"))


def test_subdomains_of_site_builders_stay_apart():
    hits = [
        Hit("https://fish.tilda.ws/", "fish.tilda.ws", "Рыба", "", 1),
        Hit("https://meat.tilda.ws/", "meat.tilda.ws", "Мясо", "", 2),
    ]
    groups, _ = split_hits(hits)
    assert [g[0].domain for g in groups] == ["fish.tilda.ws", "meat.tilda.ws"]


def test_find_region():
    assert find_region("екб").lr == 54
    assert find_region("г. Екатеринбург").city == "Екатеринбург"
    assert find_region("Питер").lr == 2
    assert find_region("Нижний Новгород").lr == 47
    assert find_region("Томск") is None
    assert find_region("Омск").lr == 66


def test_parse_queries_adds_city_and_dedups():
    answer = 'Вот запросы: ["лосось оптом Екатеринбург", "Лосось оптом Екатеринбург", "семга поставщик", "лосось HoReCa Екатеринбург"]'
    assert parse_queries(answer, "Екатеринбург") == [
        "лосось оптом Екатеринбург",
        "семга поставщик Екатеринбург",
        "лосось HoReCa Екатеринбург",
    ]
    assert all("Тюмень" in q for q in template_queries("рис", "Тюмень"))


def test_parse_html_text_links_and_contacts():
    page = parse_html("https://rybdvor.ru/", fixture_text("supplier_main.html"))
    assert page.site_name == "Рыбный двор"
    assert "window.dataLayer" not in page.text
    assert "Минимальный заказ — 15 000 рублей." in page.text
    assert page.tel_links == ["+73432001020"]
    assert page.mail_links == ["opt@rybdvor.ru"]
    assert pick_subpages(page, 2) == ["https://rybdvor.ru/kontakty/", "https://rybdvor.ru/dostavka/"]


def test_js_page_has_no_text():
    page = parse_html("https://spa.ru/", fixture_text("supplier_js.html"))
    assert len(page.text) < 50


def test_parse_gigachat_answer():
    body = json.loads(fixture_text("gigachat_extract.json"))
    extracted = parse_answer(body["choices"][0]["message"]["content"])
    assert extracted.kind == "distributor"
    assert extracted.sells_category.value == "yes"
    assert extracted.min_order.value == "15 000 ₽"
    assert extracted.region is None


def test_parse_answer_drops_empty_and_bad_kind():
    extracted = parse_answer(
        '{"kind": "farm", "price": {"value": 100, "quote": "100 руб"}, "delivery": {"value": "", "quote": "x"}}'
    )
    assert extracted.kind == "unknown"
    assert extracted.price.value == "100"
    assert extracted.delivery is None


def test_select_text_respects_budget_and_keeps_keywords():
    filler = "\n".join(f"строка про погоду {i}" for i in range(2000))
    page = Page(url="https://a.ru/", text=filler + "\nМинимальный заказ 5 кг лосося\n" + filler)
    text = select_text([page], "лосось", budget=3000)
    assert len(text) <= 3000
    assert "Минимальный заказ 5 кг лосося" in text


def test_select_text_skips_lines_with_keyword_inside_words():
    page = Page(url="https://a.ru/", text="Минск и минуты\nКомментарии к городу\nОтвет на вопрос\nЦена 100 ₽")
    body = select_text([page], "рис").split("…\n", 1)[1]
    assert body == "Ответ на вопрос\nЦена 100 ₽"


def test_parse_dadata_party():
    legal = parse_party("6671012340", json.loads(fixture_text("dadata_party.json")))
    assert legal.status == "ACTIVE"
    assert legal.registered == "2010-06-01"
    assert legal.okved == "46.38.1"
    assert legal.okved_name.startswith("Торговля оптовая рыбой")
    assert "rusprofile.ru" in legal.check_url
    assert parse_party("6671012340", {"suggestions": []}).status is None


def test_parse_answer_accepts_flat_strings():
    extracted = parse_answer(
        '{"kind": "distributor", "sells_category": "yes", "delivery": "доставка по Екатеринбургу", "price": null}'
    )
    assert extracted.sells_category.value == "yes"
    assert extracted.sells_category.quote is None
    assert extracted.delivery.quote == "доставка по Екатеринбургу"
    assert extracted.price is None
