from datetime import date

from app.pipeline.legal import age_years
from app.pipeline.questions import build_questions, build_rfq, category_questions
from app.pipeline.regions import REGIONS
from app.pipeline.score import CHAIN, apply_score, finalize, rank, review
from app.schemas import Fact, LegalInfo, Supplier

EKB = REGIONS["Екатеринбург"]


def supplier(domain: str = "a.ru", **kwargs) -> Supplier:
    return Supplier(
        domain=domain, name=domain, url=f"https://{domain}/", fetched_at="2026-10-21T12:00:00+00:00", **kwargs
    )


def fact(value: str, quote: str) -> Fact:
    return Fact(value=value, quote=quote, url="https://a.ru/")


def marks(s: Supplier) -> dict[str, str]:
    return {item.key: item.mark for item in s.checklist}


def test_full_supplier_confirms_all():
    s = supplier(
        kind="producer",
        phones=["+7 343 200-10-20"],
        facts={
            "delivery": fact("по Екатеринбургу ежедневно", "Доставка по Екатеринбургу ежедневно"),
            "documents": fact("Меркурий", "ветеринарные свидетельства в системе «Меркурий»"),
            "min_order": fact("15 000 ₽", "Минимальный заказ — 15 000 рублей"),
            "price": fact("1 290 ₽/кг", "1 290 руб./кг при заказе от 10 кг"),
            "payment": fact("НДС", "Работаем с юридическими лицами, безналичный расчёт с НДС"),
        },
        legal=LegalInfo(inn="6671012340", status="ACTIVE", registered="2010-06-01", check_url="x"),
    )
    apply_score(s, EKB, "Екатеринбург")
    assert s.confirmed == 6
    assert s.why.startswith("6 из 6 подтверждено: производитель, адрес или телефон в городе")
    assert s.why.endswith("есть телефон")


def test_empty_supplier_is_unknown():
    s = apply_score(supplier(), EKB, "Екатеринбург")
    assert set(marks(s).values()) == {"unknown"}
    assert s.confirmed == 0
    assert "уточнить по телефону" in s.why


def test_other_region_without_delivery_is_no():
    s = apply_score(supplier(address="г. Москва, ул. Тверская, д. 1"), EKB, "Екатеринбург")
    assert marks(s)["delivers_to_city"] == "no"
    s = apply_score(supplier(address="г. Екатеринбург, ул. Ленина, д. 5"), EKB, "Екатеринбург")
    assert marks(s)["delivers_to_city"] == "yes"
    s = apply_score(
        supplier(
            address="г. Москва, ул. Тверская, д. 1",
            facts={"delivery": fact("по России", "Доставка по всей России транспортными компаниями")},
        ),
        EKB,
        "Екатеринбург",
    )
    assert marks(s)["delivers_to_city"] == "unknown"
    assert "уточнить доставку в Екатеринбург" in s.checklist[0].note


def test_b2b_needs_words_not_inn_and_legal_young_or_liquidated():
    s = apply_score(supplier(inn="6671012340"), EKB, "Екатеринбург")
    assert marks(s)["b2b"] == "unknown"
    assert "ИНН на сайте есть" in s.checklist[1].note
    s = apply_score(supplier(inn="6671012340"), EKB, "Екатеринбург", "Отгружаем оптом от 20 кг")
    assert marks(s)["b2b"] == "yes"
    s = apply_score(supplier(facts={"payment": fact("НДС", "Цены с НДС, договор поставки")}), EKB, "Екатеринбург")
    assert marks(s)["b2b"] == "yes"
    assert marks(apply_score(supplier(), EKB, "Екатеринбург", "Оптика и юридический адрес"))["b2b"] == "unknown"
    young = LegalInfo(inn="1", status="ACTIVE", registered=date.today().isoformat(), check_url="x")
    assert marks(apply_score(supplier(legal=young), EKB, "Екатеринбург"))["legal_active"] == "no"
    dead = LegalInfo(inn="1", status="LIQUIDATED", registered="2010-01-01", check_url="x")
    assert marks(apply_score(supplier(legal=dead), EKB, "Екатеринбург"))["legal_active"] == "no"
    assert round(age_years(dead, date(2020, 1, 1))) == 10


def test_rank_drops_other_category_and_orders():
    off = supplier("off.ru", facts={"sells_category": fact("no", "Продаём только строительные материалы")})
    plain = supplier("plain.ru")
    phone = supplier("phone.ru", phones=["+7 912 200-10-20"])
    producer = supplier("producer.ru", kind="producer", phones=["+7 912 200-10-21"])
    strong = supplier(
        "strong.ru", legal=LegalInfo(inn="6671012340", status="ACTIVE", registered="2010-06-01", check_url="x")
    )
    for s in (off, plain, phone, producer, strong):
        apply_score(s, EKB, "Екатеринбург")
    assert [s.domain for s in rank([off, plain, phone, producer, strong])] == [
        "strong.ru",
        "producer.ru",
        "phone.ru",
        "plain.ru",
    ]


def test_category_questions():
    assert any("Меркури" in q for q in category_questions("Лосось охлаждённый"))
    assert any("Честным знаком" in q for q in category_questions("творог фермерский"))
    assert any("ТР ТС 005" in q for q in category_questions("контейнеры для доставки"))
    assert category_questions("гвозди") == []


def test_questions_by_missing_fields_and_rfq():
    s = apply_score(supplier(facts={"price": fact("1 290 ₽/кг", "1 290 руб./кг")}), EKB, "Екатеринбург")
    s.questions = build_questions(s, "лосось охлаждённый", "Екатеринбург")
    assert "Какой минимальный заказ — сумма или объём?" in s.questions
    assert not any("прайс" in q for q in s.questions)
    assert any("Доставляете в Екатеринбург?" in q for q in s.questions)
    assert any("Меркури" in q for q in s.questions)
    assert len(s.questions) == len(set(s.questions))
    s.rfq = build_rfq(s, "лосось охлаждённый", "Екатеринбург")
    assert "Запрос коммерческого предложения — лосось охлаждённый, поставка в Екатеринбург" in s.rfq
    assert "1. Какой минимальный заказ" in s.rfq


def test_rank_puts_confirmed_delivery_first():
    local = supplier("local.ru", address="г. Екатеринбург, ул. Ленина, д. 5")
    rich = supplier(
        "rich.ru",
        inn="6671012340",
        facts={
            "documents": fact("Меркурий", "ветеринарные свидетельства в системе «Меркурий»"),
            "min_order": fact("15 000 ₽", "Минимальный заказ — 15 000 рублей"),
            "price": fact("1 290 ₽/кг", "1 290 руб./кг"),
        },
        legal=LegalInfo(inn="6671012340", status="ACTIVE", registered="2010-06-01", check_url="x"),
    )
    far = supplier(
        "far.ru",
        address="г. Москва, ул. Тверская, д. 1",
        inn="6671012340",
        facts={"price": fact("1 290 ₽/кг", "1 290 руб./кг")},
    )
    for s in (local, rich, far):
        apply_score(s, EKB, "Екатеринбург")
    assert (local.confirmed, rich.confirmed) == (1, 4)
    assert marks(far)["delivers_to_city"] == "no"
    assert [s.domain for s in rank([far, rich, local])] == ["local.ru", "rich.ru", "far.ru"]


def delivery_of(**kwargs) -> tuple[str, str]:
    s = apply_score(supplier(**kwargs), EKB, "Екатеринбург")
    return s.checklist[0].mark, s.delivery_label


def test_delivery_by_phone_codes_and_address():
    assert delivery_of(phones=["+7 800 100-51-51", "+7 343 370-11-70"]) == ("yes", "да — местный")
    assert delivery_of(legal=LegalInfo(inn="1", address="г Екатеринбург, ул Мира", check_url="x")) == (
        "yes",
        "да — местный",
    )
    assert delivery_of(phones=["+7 495 975-94-31", "+7 903 137-19-91"]) == ("no", "нет — Москва")
    assert delivery_of(phones=["+7 345 220-10-10"]) == ("no", "нет — Тюмень")
    assert delivery_of(phones=["+7 833 220-49-58"]) == ("no", "нет — код 833")
    assert delivery_of(address="г. Якутск, ул. Дзержинского, 42/2") == ("no", "нет — Якутск")
    assert delivery_of(phones=["+7 800 550-41-83", "+7 912 600-70-80"]) == ("unknown", "уточнить")


def test_delivery_by_quotes():
    by_city = fact("по Екатеринбургу", "Доставка по Екатеринбургу ежедневно")
    assert delivery_of(phones=["+7 495 975-94-31"], facts={"delivery": by_city}) == ("yes", "да — доставка по городу")
    by_area = fact("УрФО", "доставка замороженных полуфабрикатов по всей территории УрФО")
    assert delivery_of(facts={"region": by_area}) == ("yes", "да — доставка по области")
    moscow = fact("Москва и МО", "Доставка по Москве в пределах МКАД на следующий день")
    assert delivery_of(facts={"delivery": moscow}) == ("no", "нет — Москва")
    nationwide = fact("по России", "Отправляем во все регионы России транспортными компаниями")
    assert delivery_of(facts={"delivery": nationwide}) == ("unknown", "уточнить (через ТК)")
    assert delivery_of(address="г. Москва, ул. Тверская, д. 1", facts={"delivery": nationwide}) == (
        "unknown",
        "уточнить (через ТК)",
    )


SELLS = fact("yes", "Поставляем охлаждённый лосось в рестораны")


def reviewed(text: str = "", **kwargs) -> Supplier:
    return review(supplier(**kwargs), "лосось охлаждённый", EKB, "Екатеринбург", text)


def test_groups_and_doubts():
    local = reviewed(phones=["+7 343 200-10-20"], facts={"sells_category": SELLS})
    assert (local.group, local.doubt) == ("match", None)
    unsure = reviewed(phones=["+7 912 200-10-20"], facts={"sells_category": SELLS})
    assert (unsure.group, unsure.delivery_label) == ("doubtful", "уточнить")
    assert unsure.doubt.startswith("не нашли, возят ли")
    far = reviewed(phones=["+7 495 975-94-31"], facts={"sells_category": SELLS})
    assert (far.group, far.doubt) == ("doubtful", "другой регион: Москва")
    tk = reviewed(
        address="г. Москва, ул. Тверская, д. 1",
        facts={
            "sells_category": SELLS,
            "delivery": fact("по России", "Доставка по всей России транспортными компаниями"),
        },
    )
    assert tk.group == "doubtful"
    assert tk.doubt.startswith("другой регион: Москва — только отправка")
    unproven = reviewed(phones=["+7 343 200-10-20"])
    assert unproven.doubt == "не подтверждено, что продают лосось охлаждённый"
    vague = fact("yes", "Живая и охлаждённая рыба, раки, икра")
    assert reviewed(phones=["+7 343 200-10-20"], facts={"sells_category": vague}).group == "doubtful"
    named = reviewed("Лосось атлантический 2-3 кг", phones=["+7 343 200-10-20"], facts={"sells_category": vague})
    assert named.group == "match"
    priced = reviewed(phones=["+7 343 200-10-20"], facts={"price": fact("950 ₽", "Цена Лосось (СЕМГА) 950 р.")})
    assert priced.group == "match"
    assert (
        reviewed("Для ресторанов и кафе", phones=["+7 343 200-10-20"]).checklist[1].note == "на сайте: «для ресторанов»"
    )


def test_category_proven_by_name_title_trade_text_or_snippet():
    local = {"phones": ["+7 343 200-10-20"]}
    named = supplier(**local)
    named.name = "Лосось Урала"
    assert review(named, "лосось охлаждённый", EKB, "Екатеринбург").group == "match"
    assert review(supplier(**local), "лосось охлаждённый", EKB, "Екатеринбург", "", ["Лосось оптом"]).group == "match"
    assert reviewed("О компании\nОхлаждённый лосось — цена за кг", **local).group == "match"
    assert reviewed(snippet="Лосось атлантический, Чили", **local).group == "match"
    assert reviewed("Лосось полезен. " + "Омега-3 укрепляет сосуды и сердце. " * 5 + "Опт", **local).group == "doubtful"


def test_title_does_not_prove_delivery():
    titled = review(
        supplier(phones=["+7 495 975-94-31"]),
        "лосось охлаждённый",
        EKB,
        "Екатеринбург",
        "",
        ["Лосось охлаждённый с доставкой по Екатеринбургу"],
    )
    assert (titled.group, titled.delivery_label) == ("doubtful", "нет — Москва")


def test_other_city_in_snippet_or_title_without_local_signs():
    spb = reviewed(snippet="Оптовая база: лосось охлаждённый оптом, Санкт-Петербург", facts={"sells_category": SELLS})
    assert (spb.delivery_label, spb.doubt) == ("нет — Санкт-Петербург", "другой регион: Санкт-Петербург")
    kad = review(supplier(), "лосось охлаждённый", EKB, "Екатеринбург", "", ["Лосось с доставкой в пределах КАД"])
    assert kad.delivery_label == "нет — Санкт-Петербург"
    both = reviewed(snippet="Лосось оптом: склады в Москве и Екатеринбурге")
    assert both.delivery_label == "уточнить"
    local = reviewed(snippet="Лосось оптом, доставка по Москве", phones=["+7 343 200-10-20"])
    assert (local.delivery_label, local.group) == ("да — местный", "match")


def test_store_chain_is_retail_despite_corporate_page():
    chain = reviewed("Сеть супермаркетов. Юридическим лицам", snippet="Лосось кусок охлажденный")
    assert (chain.kind, chain.doubt) == ("retail", "розничный магазин")


def test_explicit_no_needs_absent_category():
    no = fact("no", "Мы продаём только говядину и свинину")
    off = reviewed("Говядина оптом", facts={"sells_category": no})
    assert off.facts["sells_category"].value == "no"
    assert rank([off]) == []
    sold = reviewed("Говядина и лосось оптом", phones=["+7 343 200-10-20"], facts={"sells_category": no})
    assert (sold.group, "sells_category" in sold.facts, rank([sold])) == ("match", False, [sold])


def test_eateries_and_guides_are_not_suppliers():
    cafe = reviewed(snippet="Лосось, приготовленный руками наших поваров", phones=["+7 343 200-10-20"])
    assert (cafe.group, cafe.doubt) == ("doubtful", "ресторан или кафе, а не поставщик")
    menu = reviewed("Наше меню: тартар из лосося", phones=["+7 343 200-10-20"])
    assert menu.doubt == "ресторан или кафе, а не поставщик"
    horeca = reviewed("Лосось оптом для ресторанов и кафе", phones=["+7 343 200-10-20"])
    assert (horeca.group, horeca.doubt) == ("match", None)
    guide = reviewed("Узнай лучшие места, где можно поесть лосось в Екатеринбурге")
    assert guide.kind == "aggregator"


def test_retail_without_wholesale_is_doubtful():
    shop = reviewed(
        "Интернет-магазин рыбы с доставкой на дом", phones=["+7 343 200-10-20"], facts={"sells_category": SELLS}
    )
    assert (shop.kind, shop.group, shop.doubt) == ("retail", "doubtful", "розничный магазин")
    retail_okved = LegalInfo(inn="1", okved="47.23", check_url="x")
    assert reviewed(legal=retail_okved, facts={"sells_category": SELLS}).kind == "retail"
    wholesale = reviewed(
        "Интернет-магазин. Продаём оптом и в розницу", kind="distributor", facts={"sells_category": SELLS}
    )
    assert wholesale.kind == "distributor"


def test_catalogs_go_to_aggregators_and_names_follow_inn():
    catalog = reviewed("Хлебобулочные изделия в Екатеринбурге. Всего 556 организаций.", domain="places.ru")
    listed = reviewed(domain="postavshikov.net")
    first = reviewed(domain="a.ru", inn="6671012340", phones=["+7 343 200-10-20"], facts={"sells_category": SELLS})
    first.name = "Рыбный двор"
    second = reviewed(domain="b.ru", inn="6671012340")
    second.name = "ООО «РЫБНЫЙ ДВОР»"
    suppliers, sources = finalize([catalog, listed, second, first])
    assert [s.domain for s in sources] == ["places.ru", "postavshikov.net"]
    assert [(s.domain, s.name) for s in suppliers] == [("a.ru", "Рыбный двор")]


def test_values_are_formatted():
    s = reviewed(facts={"price": fact("640 Руб. за 1 кг.", "640 Руб. за 1 кг."), "payment": fact("НДС ", "с НДС")})
    assert s.facts["price"].value == "640 ₽/кг"
    assert s.facts["payment"].value == "НДС"


def test_retail_chain_by_trade_network_marker():
    assert CHAIN.search('Юридическим лицам Напишите нам ТС "Яблоко" Каталог')
    assert CHAIN.search("Покупатель интернет магазина и ООО «Десерт»")
    assert not CHAIN.search("Оптовые поставки для ресторанов и торговых точек")
