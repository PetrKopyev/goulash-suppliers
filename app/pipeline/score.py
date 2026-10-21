import re

from app.pipeline.legal import age_years
from app.pipeline.regions import Region, other_region
from app.schemas import CheckItem, Mark, Supplier

B2B = re.compile(r"\bопт|юридическ|юрлиц|horeca|хорека|ресторан|кафе|b2b|для бизнеса|ндс|дилер", re.IGNORECASE)
NATIONWIDE = re.compile(
    r"по (всей )?(росси|рф)|в регионы|регион\w* (росси|рф)|в любой (город|регион)|транспортн\w* компани", re.IGNORECASE
)
KIND_ORDER = {"producer": 0, "distributor": 1, "unknown": 2, "aggregator": 3}
ACTIVE_STATUSES = {"ACTIVE"}
MARK_ORDER = {"yes": 0, "unknown": 1, "no": 2}


def mentions(text: str, region: Region | None, city: str) -> bool:
    return region.mentioned_in(text) if region else city.lower()[:5] in text.lower()


def delivers_to_city(s: Supplier, region: Region | None, city: str) -> tuple[Mark, str | None]:
    delivery = s.facts.get("delivery")
    terms = " ".join(f"{f.value} {f.quote}" for key, f in s.facts.items() if key in ("delivery", "region"))
    if terms and mentions(terms, region, city):
        return "yes", "доставка или регион работы с городом указаны на сайте"
    if s.address and mentions(s.address, region, city):
        return "yes", f"адрес в городе: {s.address}"
    if s.legal and s.legal.address and mentions(s.legal.address, region, city):
        return "yes", "юрлицо зарегистрировано в регионе"
    if NATIONWIDE.search(terms):
        return "unknown", f"заявлена работа по России — уточнить доставку в {city}"
    if not delivery:
        address = s.address or (s.legal.address if s.legal else None)
        if address and (other := other_region(address, region)):
            return "no", f"адрес в другом регионе ({other.city}), доставка не указана"
    return "unknown", None


def b2b(s: Supplier) -> tuple[Mark, str | None]:
    quotes = " ".join(f.quote for f in s.facts.values())
    if B2B.search(quotes):
        return "yes", "опт или работа с юрлицами в цитатах"
    if s.inn:
        return "yes", f"на сайте указан ИНН {s.inn}"
    return "unknown", None


def legal_active(s: Supplier) -> tuple[Mark, str | None]:
    if not s.legal or not s.legal.status:
        return "unknown", None
    years = age_years(s.legal)
    if s.legal.status not in ACTIVE_STATUSES:
        return "no", f"статус: {s.legal.status}"
    if years is not None and years < 1:
        return "no", "зарегистрировано меньше года назад"
    return "yes", f"действует {int(years)} л." if years is not None else "действует"


def fact_mark(s: Supplier, key: str) -> tuple[Mark, str | None]:
    fact = s.facts.get(key)
    return ("yes", fact.value) if fact else ("unknown", None)


def build_checklist(s: Supplier, region: Region | None, city: str) -> list[CheckItem]:
    items = [
        ("delivers_to_city", f"Доставка в {city}", delivers_to_city(s, region, city)),
        ("b2b", "Работает с юрлицами / опт", b2b(s)),
        ("documents", "Документы на продукцию", fact_mark(s, "documents")),
        ("min_order_known", "Известен минимальный заказ", fact_mark(s, "min_order")),
        ("price_known", "Известна цена", fact_mark(s, "price")),
        ("legal_active", "Юрлицо действует больше года", legal_active(s)),
    ]
    return [CheckItem(key=key, label=label, mark=mark, note=note) for key, label, (mark, note) in items]


WHY = {
    "delivers_to_city": "доставка в город подтверждена",
    "b2b": "работает с юрлицами",
    "documents": "документы указаны",
    "min_order_known": "известен мин. заказ",
    "price_known": "есть цена",
    "legal_active": "юрлицо действует",
}
KIND_RU = {"producer": "производитель", "distributor": "дистрибьютор"}


def why(s: Supplier) -> str:
    parts = [KIND_RU[s.kind]] if s.kind in KIND_RU else []
    parts += [WHY[item.key] for item in s.checklist if item.mark == "yes"]
    if s.phones:
        parts.append("есть телефон")
    text = ", ".join(parts) if parts else "мало данных на сайте — уточнить по телефону"
    return f"{s.confirmed} из 6 подтверждено: {text}"


def apply_score(s: Supplier, region: Region | None, city: str) -> Supplier:
    s.checklist = build_checklist(s, region, city)
    s.confirmed = sum(item.mark == "yes" for item in s.checklist)
    s.why = why(s)
    return s


def sells(s: Supplier) -> str:
    fact = s.facts.get("sells_category")
    return fact.value if fact else "unknown"


def delivery_mark(s: Supplier) -> Mark:
    return next((item.mark for item in s.checklist if item.key == "delivers_to_city"), "unknown")


def rank(suppliers: list[Supplier]) -> list[Supplier]:
    kept = [s for s in suppliers if sells(s) != "no"]
    return sorted(
        kept,
        key=lambda s: (
            MARK_ORDER[delivery_mark(s)],
            -s.confirmed,
            not s.phones,
            KIND_ORDER[s.kind],
            sells(s) != "yes",
        ),
    )
