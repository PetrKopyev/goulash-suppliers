from datetime import date

from app.pipeline.legal import age_years
from app.pipeline.questions import build_questions, build_rfq, category_questions
from app.pipeline.regions import REGIONS
from app.pipeline.score import apply_score, rank
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
    assert s.why.startswith("6 из 6 подтверждено: производитель, доставка в город подтверждена")
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


def test_b2b_from_inn_and_legal_young_or_liquidated():
    s = apply_score(supplier(inn="6671012340"), EKB, "Екатеринбург")
    assert marks(s)["b2b"] == "yes"
    young = LegalInfo(inn="1", status="ACTIVE", registered=date.today().isoformat(), check_url="x")
    assert marks(apply_score(supplier(legal=young), EKB, "Екатеринбург"))["legal_active"] == "no"
    dead = LegalInfo(inn="1", status="LIQUIDATED", registered="2010-01-01", check_url="x")
    assert marks(apply_score(supplier(legal=dead), EKB, "Екатеринбург"))["legal_active"] == "no"
    assert round(age_years(dead, date(2020, 1, 1))) == 10


def test_rank_drops_other_category_and_orders():
    off = supplier("off.ru", facts={"sells_category": fact("no", "Продаём только строительные материалы")})
    plain = supplier("plain.ru")
    phone = supplier("phone.ru", phones=["+7 343 200-10-20"])
    producer = supplier("producer.ru", kind="producer", phones=["+7 343 200-10-21"])
    strong = supplier("strong.ru", inn="6671012340")
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
