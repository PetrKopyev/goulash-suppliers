import pytest

from app.pipeline.fetch import Page, is_public_ip, is_safe_url, parse_html, parse_robots
from app.pipeline.regions import REGIONS
from app.pipeline.rules import extract_contacts, find_emails, find_inns, find_phones, inn_valid
from app.pipeline.verify import find_quote, verify_fact
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
    ],
)
def test_not_phones(text):
    assert find_phones(text) == []


def test_inn_checksum():
    assert inn_valid("7707083893")
    assert not inn_valid("7707083894")
    assert find_inns("ИНН/КПП 6671012340/667101001, ИНН 1234567890") == ["6671012340"]


def test_emails_skip_images():
    assert find_emails("pishite: Opt@RybDvor.ru, logo@2x.png, sales@rybdvor.ru.") == [
        "opt@rybdvor.ru",
        "sales@rybdvor.ru",
    ]


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
    assert contacts.ogrn == "1106670001239"
    assert contacts.address == "620102, г. Екатеринбург, ул. Посадская, д. 21, оф. 3"
    assert contacts.address_url == "https://rybdvor.ru/"


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
        "http://127.0.0.1/",
        "http://[::1]/",
        "gopher://x",
    ],
)
async def test_unsafe_urls(url):
    assert not await is_safe_url(url)


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
    assert verify_fact("sells_category", "yes", "Охлаждённый лосось оптом", [page]) == "https://rybdvor.ru/"
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
