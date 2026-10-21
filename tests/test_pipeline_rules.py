import asyncio
import socket
import time

import httpcore
import httpx
import pytest

from app.pipeline import fetch
from app.pipeline.fetch import (
    Page,
    PublicOnlyBackend,
    get,
    is_public_ip,
    parse_html,
    parse_robots,
    resolve_public,
    safe_url,
)
from app.pipeline.regions import REGIONS
from app.pipeline.rules import (
    extract_contacts,
    find_emails,
    find_inns,
    find_phones,
    inn_valid,
)
from app.pipeline.verify import fact_allowed, find_quote, names_category, verify_fact
from tests.test_pipeline_parse import fixture_text


@pytest.mark.parametrize(
    "raw, phone",
    [
        ("+7 (343) 200-10-20", "+7 343 200-10-20"),
        ("8 (343) 200-10-21", "+7 343 200-10-21"),
        ("+7\xa0912\xa0600-70-80", "+7 912 600-70-80"),
        ("тел. 89126007080", "+7 912 600-70-80"),
        ("+7 (3452) 12-34-56", "+7 345 212-34-56"),
        ("(343) 355-44-33", "+7 343 355-44-33"),
        ("8-800-555-35-35", "+7 800 555-35-35"),
        ("+7 (343) 200-10-21\nг. Екатеринбург", "+7 343 200-10-21"),
    ],
)
def test_phone_formats(raw, phone):
    assert find_phones(raw) == [phone]


@pytest.mark.parametrize(
    "text",
    [
        "ИНН 89221234567",
        "Артикул 89221234567",
        "цена 8 900 000 000 руб.",
        "р/с 40702810900000012345",
        "ОГРН 1106670001239",
        "дата 08.10.2026",
        "+7 (777) 123-45-67",
        "1 290 000 руб.",
        "2026-10-08",
        "8 (343) 200-10-21 г",
    ],
)
def test_not_phones(text):
    assert find_phones(text) == []


def test_inn_checksum():
    assert inn_valid("7707083893")
    assert not inn_valid("7707083894")
    assert find_inns("ИНН/КПП 6671012340/667101001, ИНН 1234567890") == ["6671012340"]


def test_inn_inside_longer_number_is_ignored():
    assert find_inns("ИНН 66710123401") == []
    assert find_inns("ИНН 6671012340123") == []


def test_emails_skip_images():
    assert find_emails("pishite: Opt@RybDvor.ru, logo@2x.png, sales@rybdvor.ru.") == [
        "opt@rybdvor.ru",
        "sales@rybdvor.ru",
    ]


def test_regexes_stay_fast_on_hostile_text():
    hostile = "a" * 80_000 + "@" + "b." * 5_000 + "\n" + "+7 " * 10_000
    started = time.monotonic()
    find_emails(hostile)
    find_phones(hostile)
    assert time.monotonic() - started < 1


def test_extract_contacts_from_pages():
    main = parse_html("https://rybdvor.ru/", fixture_text("supplier_main.html"))
    contacts_page = parse_html("https://rybdvor.ru/kontakty/", fixture_text("supplier_contacts.html"))
    contacts = extract_contacts([main, contacts_page], REGIONS["Екатеринбург"].patterns)
    assert contacts.phones[:3] == ["+7 343 200-10-21", "+7 912 600-70-80", "+7 343 355-44-33"]
    assert "+7 343 200-10-20" in contacts.phones
    assert "+7 922 123-45-67" not in contacts.phones
    assert "+7 999 000-00-00" not in contacts.phones
    assert contacts.emails == ["sales@rybdvor.ru", "opt@rybdvor.ru"]
    assert contacts.inn == "6671012340"
    assert contacts.address == "620102, г. Екатеринбург, ул. Посадская, д. 21, оф. 3"


def test_quote_accepted_with_normalization():
    page = parse_html("https://rybdvor.ru/", fixture_text("supplier_main.html"))
    other = Page(url="https://rybdvor.ru/x", text="ничего")
    assert find_quote("Лосось охлаждённый потрошеный 4-5 кг - 1 290 руб./кг", [other, page]) == "https://rybdvor.ru/"
    assert find_quote("«Минимальный заказ — 15 000 рублей.»", [page]) == "https://rybdvor.ru/"
    assert find_quote("Компания «Рыбный двор» ... на Урале с 2010 года", [page]) == "https://rybdvor.ru/"


def test_quote_rejected():
    page = parse_html("https://rybdvor.ru/", fixture_text("supplier_main.html"))
    assert find_quote("Производство сертифицировано по ХАССП", [page]) is None
    assert find_quote("лосось", [page]) is None
    assert find_quote("с 2010 года ... Компания «Рыбный двор»", [page]) is None


def test_quote_parts_must_be_close():
    filler = " ".join(["погода"] * 60)
    page = Page(url="https://a.ru/", text=f"Доставка по Екатеринбургу {filler} ежедневно с 8 до 20")
    assert find_quote("Доставка по Екатеринбургу ... ежедневно с 8 до 20", [page]) is None
    near = Page(url="https://a.ru/", text="Доставка по Екатеринбургу, кроме воскресенья, ежедневно с 8 до 20")
    assert find_quote("Доставка по Екатеринбургу ... ежедневно с 8 до 20", [near]) == "https://a.ru/"


def test_empty_quote_or_value_rejected():
    page = parse_html("https://rybdvor.ru/", fixture_text("supplier_main.html"))
    assert find_quote("", [page]) is None
    assert verify_fact("min_order", "", "Минимальный заказ — 15 000 рублей.", [page]) is None
    assert verify_fact("min_order", "15 000 ₽", "", [page]) is None


@pytest.mark.parametrize(
    "ip, public",
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.0.1", False),
        ("172.16.5.5", False),
        ("169.254.169.254", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("fe80::1", False),
        ("::ffff:127.0.0.1", False),
        ("2a02:6b8::2:242", True),
        ("100.64.0.1", False),
        ("224.0.0.1", False),
        ("::ffff:8.8.8.8", True),
        ("64:ff9b::a00:1", False),
        ("64:ff9b::808:808", True),
        ("2002:7f00:1::", False),
        ("2001:0:4136:e378:8000:63bf:3fff:fdd2", False),
    ],
)
def test_public_ip(ip, public):
    assert is_public_ip(ip) is public


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://localhost:8000/",
        "http://example.com:8080/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://[::1]/",
        "http://[::1/",
        "gopher://x",
    ],
)
def test_unsafe_urls(url):
    assert safe_url(url) is None


def test_safe_url_normalizes_host():
    assert safe_url("https://user@WWW.Rybdvor.RU:443/x?y=1") == "https://www.rybdvor.ru:443/x?y=1"
    assert safe_url("http://96фабрикарыбы.рф/") == "http://xn--96-8kcaeb1cq6cd1b5fb.xn--p1ai/"


def fake_getaddrinfo(monkeypatch, *addresses):
    async def getaddrinfo(host, port, **kwargs):
        if not addresses:
            raise socket.gaierror("no such host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize(
    "addresses, resolved",
    [
        (("93.184.216.34",), "93.184.216.34"),
        (("10.1.2.3",), None),
        (("93.184.216.34", "127.0.0.1"), None),
        ((), None),
    ],
)
async def test_resolve_public(monkeypatch, addresses, resolved):
    fake_getaddrinfo(monkeypatch, *addresses)
    assert await resolve_public("supplier.ru", 443) == resolved


async def test_decimal_ip_is_not_public():
    assert await resolve_public("2130706433", 80) is None


async def test_backend_connects_to_checked_address(monkeypatch):
    fake_getaddrinfo(monkeypatch, "93.184.216.34")
    backend = PublicOnlyBackend()
    connected = []

    async def connect_tcp(host, port, *args):
        connected.append(host)

    monkeypatch.setattr(backend.backend, "connect_tcp", connect_tcp)
    await backend.connect_tcp("supplier.ru", 443)
    assert connected == ["93.184.216.34"]


async def test_backend_refuses_private_address(monkeypatch):
    fake_getaddrinfo(monkeypatch, "10.0.0.7")
    with pytest.raises(httpcore.ConnectError):
        await PublicOnlyBackend().connect_tcp("intranet.supplier.ru", 80)


def html(text: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(text.encode()))


async def fetch_with(handler, url: str = "http://a.ru/"):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await get(client, url)


async def test_redirect_to_private_address_refused():
    def handler(request):
        if request.url.host == "a.ru":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        return html("secret")

    assert await fetch_with(handler) is None


async def test_redirect_loop_stops():
    def handler(request):
        target = "http://b.ru/" if request.url.host == "a.ru" else "http://a.ru/"
        return httpx.Response(302, headers={"location": target})

    assert await fetch_with(handler) is None


async def test_compressed_body_refused():
    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"content-type": "text/html", "content-encoding": "gzip"}, content=b"x")

    assert await fetch_with(handler) is None


async def test_body_cut_to_limit(monkeypatch):
    monkeypatch.setattr(fetch, "MAX_BYTES", 1000)
    url, text = await fetch_with(lambda request: html("я" * 5000))
    assert url == "http://a.ru/"
    assert len(text.encode()) <= 1000


def test_fact_value_numbers_must_be_in_quote():
    page = parse_html("https://rybdvor.ru/", fixture_text("supplier_main.html"))
    assert verify_fact("min_order", "15 000 ₽", "Минимальный заказ — 15 000 рублей.", [page]) == "https://rybdvor.ru/"
    assert verify_fact("min_order", "1 упаковка", "Минимальный заказ — 15 000 рублей.", [page]) is None
    assert verify_fact(
        "documents",
        "ветсвидетельства, Меркурий",
        "сопровождается ветеринарными свидетельствами в системе «Меркурий»",
        [page],
    )
    assert verify_fact("min_order", "4 кг", "Лосось охлаждённый потрошёный 4-5 кг", [page]) is None
    assert verify_fact("region", "Москва, Краснодар", "Компания «Рыбный двор» — дистрибьютор рыбы", [page]) is None
    assert verify_fact("sells_category", "yes", "Поставляем охлаждённый лосось (Мурманск, Фареры)", [page]) == (
        "https://rybdvor.ru/"
    )
    assert verify_fact("delivery", "по Екатеринбургу и области, самовывоз", "Доставка и оплата", [page]) is None


def test_robots_rules():
    robots = parse_robots(
        "User-agent: Yandex\nDisallow: /\n\nUser-agent: *\nDisallow: /?\nDisallow: /*?yclid\nDisallow: /order/\nAllow: /order/info$\n"
    )
    assert robots.allows("https://a.ru/")
    assert robots.allows("https://a.ru/kontakty/")
    assert not robots.allows("https://a.ru/?page=2")
    assert not robots.allows("https://a.ru/catalog?yclid=1")
    assert not robots.allows("https://a.ru/order/new")
    assert robots.allows("https://a.ru/order/info")
    assert not parse_robots("User-agent: *\nDisallow: /").allows("https://a.ru/x")
    assert parse_robots("User-agent: *\nDisallow: /\n\nUser-agent: GoulashSuppliersBot\nDisallow:\n").allows(
        "https://a.ru/x"
    )
    assert parse_robots("").allows("https://a.ru/x")


def test_robots_wildcards_are_linear():
    robots = parse_robots("User-agent: *\nDisallow: /" + "*a" * 200 + "*b$\nDisallow: /*.pdf$\n")
    started = time.monotonic()
    assert robots.allows("https://a.ru/" + "a" * 5000)
    assert time.monotonic() - started < 1
    assert not robots.allows("https://a.ru/files/price.pdf")
    assert robots.allows("https://a.ru/files/price.pdf?v=2")


def test_heading_quote_does_not_prove_place_or_category():
    page = parse_html("https://rybdvor.ru/", fixture_text("supplier_main.html"))
    assert page.headings == ["Рыбный двор — лосось и форель оптом в Екатеринбурге", "Охлаждённый лосось оптом"]
    assert verify_fact("sells_category", "yes", "Охлаждённый лосось оптом", [page]) is None
    assert verify_fact("min_order", "15 000 ₽", "Минимальный заказ — 15 000 рублей.", [page])
    assert not fact_allowed("sells_category", "Лосось в Екатеринбурге — купить с доставкой")
    assert not fact_allowed("region", "Куриное филе оптом в городе Екатеринбург")
    assert not fact_allowed("region", "Ваш город: Екатеринбург")
    assert not fact_allowed("region", "Екатеринбург")
    assert fact_allowed("delivery", "Опт, брендирование, быстрая доставка в Екатеринбурге.")
    assert fact_allowed("delivery", "Доставка по Екатеринбургу")
    assert fact_allowed("price", "Лосось в Екатеринбурге — купить с доставкой")


def test_quote_must_name_category():
    assert names_category("Охлажденная рыба Семга охлажденная: 5-6 кг", "лосось охлаждённый")
    assert not names_category("живая и охлаждённая рыба, раки, икра", "лосось охлаждённый")
    assert names_category("Рис для суши и роллов", "нори и рис для суши")
    assert not names_category("Доставка еды... Производства", "контейнеры для доставки еды")
    assert names_category("Упаковка для HoReCa и Delivery", "контейнеры для доставки еды")
    assert names_category("мясо птицы оптом", "куриное филе охлаждённое")
