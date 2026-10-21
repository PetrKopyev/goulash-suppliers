import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.pipeline.filters import is_aggregator
from app.pipeline.legal import age_years
from app.pipeline.questions import build_questions, build_rfq
from app.pipeline.regions import Region, is_city_phone, other_region, phone_digits, phone_region
from app.pipeline.tidy import format_value
from app.pipeline.verify import mentions_category, names_category, offers_category
from app.schemas import CheckItem, Kind, Mark, Source, Supplier

B2B = re.compile(
    r"\bопт(?:ом|ов\w*|у\b|а\b|\b)|юридическ\w* лиц|юрлиц|horeca|хорека|\bhrc\b|для ресторан|ресторанам"
    r"|для (?:кафе|общепита|бизнеса)|\bндс\b|договор\w* поставк|\bb2b\b|дилер",
    re.IGNORECASE,
)
RETAIL = re.compile(
    r"интернет-магазин|в (?:нашем )?магазине|наш магазин|работы магазина|\bлавк|супермаркет|гипермаркет"
    r"|розничн\w* покупател|для частн\w* лиц"
    r"|доставк\w* (?:на дом|до двери|до квартиры|к вашему столу)",
    re.IGNORECASE,
)
CHAIN = re.compile(
    r"сет[ьи] (?:магазинов|супермаркетов|гипермаркетов|продуктовых)|наш\w* (?:супер|гипер)маркет"
    r"|в наших магазинах|в магазинах сети|доставк\w* продуктов на дом"
    r"|торгов\w* сет[ьи]\b|\bТС [«\"]|покупател\w* интернет[- ]магазин",
    re.IGNORECASE,
)
RETAIL_NAME = re.compile(r"^(?:магазин|лавка|гастроном|супермаркет)\b", re.IGNORECASE)
RETAIL_OKVED = "47."
CATALOG = re.compile(
    r"всего \d+ (?:организац|компани)|найдено:? \d+ (?:компани|организац)|в каталоге \d+ компани"
    r"|список (?:производителей|поставщиков|компаний)|представлены поставщики|агрегатор\w* поставщик"
    r"|(?:каталог|справочник)\w* (?:компаний|поставщиков|организаций|предприятий|производителей)"
    r"|где (?:можно )?поесть|\d+ лучших|познакомиться с лучшими|лучшие (?:места|пекарни|рестораны|кафе|заведения)\b"
    r"|ваканси\w+|работа (?:в|пекарем|поваром|продавцом)|зарплат\w+ от \d|резюме",
    re.IGNORECASE,
)
EATERY = re.compile(
    r"наш\w* повар|в ресторане «|\bнаш(?:ем|е)? (?:ресторан|кафе)\b|наш\w* кофейн|забронир\w* стол"
    r"|^(?:ресторан|кафе|бар)\b|наше меню|меню ресторана|доставк\w* (?:еды|блюд) из (?:нашего )?ресторана",
    re.IGNORECASE,
)
NATIONWIDE = re.compile(
    r"по (всей )?(росси|рф)|в регионы|регион\w* (росси|рф)|в любой (город|регион)|транспортн\w* компани"
    r"|\bтк\b|до терминал",
    re.IGNORECASE,
)
TOWN = re.compile(r"(?:^|[\s,])[гГ]\.?\s*([А-ЯЁ][А-ЯЁа-яё]+(?:-[А-ЯЁа-яё]+)*)")
KIND_ORDER = {"producer": 0, "distributor": 1, "unknown": 2, "retail": 3, "aggregator": 4}
GROUP_ORDER = {"match": 0, "doubtful": 1}
ACTIVE_STATUSES = {"ACTIVE"}
MARK_ORDER = {"yes": 0, "unknown": 1, "no": 2}
PLACE_FACTS = ("delivery", "region")


@dataclass
class Delivery:
    mark: Mark
    label: str
    note: str | None = None
    elsewhere: str | None = None


def mentions(text: str, region: Region | None, city: str) -> bool:
    return region.mentioned_in(text) if region else city.lower()[:5] in text.lower()


def place_quotes(s: Supplier) -> str:
    return " ".join(f"{f.value} {f.quote}" for key, f in s.facts.items() if key in PLACE_FACTS)


def addresses(s: Supplier) -> list[str]:
    return [a for a in (s.address, s.legal.address if s.legal else None) if a]


def local_evidence(s: Supplier, region: Region | None, city: str) -> str | None:
    for address in addresses(s):
        if mentions(address, region, city):
            return f"адрес: {address}"
    phone = next((p for p in s.phones if region and region.owns_phone(p)), None)
    return f"городской телефон {phone}" if phone else None


def address_town(address: str, region: Region | None) -> str | None:
    match = TOWN.search(address)
    if match:
        return match.group(1).capitalize() if match.group(1).isupper() else match.group(1)
    other = other_region(address, region)
    return other.city if other else None


def phone_town(phone: str) -> str:
    other = phone_region(phone)
    return other.city if other else f"код {phone_digits(phone)[:3]}"


def elsewhere(s: Supplier, region: Region, listing: str = "") -> list[str]:
    towns = [address_town(a, region) for a in addresses(s)]
    towns += [phone_town(p) for p in s.phones if is_city_phone(p)]
    quoted = other_region(place_quotes(s), region)
    listed = None if region.mentioned_in(listing) else other_region(listing, region)
    towns += [r.city for r in (quoted, listed) if r]
    return list(dict.fromkeys(t for t in towns if t))


def delivery(s: Supplier, region: Region | None, city: str, listing: str = "") -> Delivery:
    if where := local_evidence(s, region, city):
        return Delivery("yes", "да — местный", where)
    quotes = place_quotes(s)
    if quotes and mentions(quotes, region, city):
        scope = "по городу" if not region or region.city_in(quotes) else "по области"
        return Delivery("yes", f"да — доставка {scope}", "доставка или регион работы с городом указаны на сайте")
    if not region:
        return Delivery("unknown", "уточнить")
    towns = elsewhere(s, region, listing)
    if NATIONWIDE.search(quotes):
        return Delivery(
            "unknown",
            "уточнить (через ТК)",
            f"заявлена отправка по России — уточнить доставку в {city}",
            towns[0] if towns else None,
        )
    if towns:
        return Delivery(
            "no", f"нет — {towns[0]}", f"адрес и телефоны: {', '.join(towns)}; доставки в {city} на сайте нет"
        )
    return Delivery("unknown", "уточнить")


def b2b_words(text: str) -> str | None:
    found = B2B.search(text)
    if not found:
        return None
    tail = re.match(r"\w*", text[found.end() :]).group(0)
    return (found.group(0) + tail).lower()


def b2b(s: Supplier, text: str) -> tuple[Mark, str | None]:
    if words := b2b_words(" ".join(f.quote for f in s.facts.values())) or b2b_words(text):
        return "yes", f"на сайте: «{words}»"
    return "unknown", "ИНН на сайте есть, но про опт и юрлиц ни слова" if s.inn else None


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


def build_checklist(
    s: Supplier, region: Region | None, city: str, text: str = "", listing: str = ""
) -> list[CheckItem]:
    route = delivery(s, region, city, listing)
    s.delivery_label = route.label
    items = [
        ("delivers_to_city", f"Доставка в {city}", (route.mark, route.note)),
        ("b2b", "Работает с юрлицами / опт", b2b(s, text)),
        ("documents", "Документы на продукцию", fact_mark(s, "documents")),
        ("min_order_known", "Известен минимальный заказ", fact_mark(s, "min_order")),
        ("price_known", "Известна цена", fact_mark(s, "price")),
        ("legal_active", "Юрлицо действует больше года", legal_active(s)),
    ]
    return [CheckItem(key=key, label=label, mark=mark, note=note) for key, label, (mark, note) in items]


WHY = {
    "b2b": "работает с юрлицами",
    "documents": "документы указаны",
    "min_order_known": "известен мин. заказ",
    "price_known": "есть цена",
    "legal_active": "юрлицо действует",
}
WHY_DELIVERY = {
    "да — местный": "адрес или телефон в городе",
    "да — доставка по городу": "доставка по городу",
    "да — доставка по области": "доставка по области",
}
KIND_RU = {"producer": "производитель", "distributor": "дистрибьютор"}


def why(s: Supplier) -> str:
    parts = [KIND_RU[s.kind]] if s.kind in KIND_RU else []
    parts += [
        WHY_DELIVERY.get(s.delivery_label, "") if item.key == "delivers_to_city" else WHY[item.key]
        for item in s.checklist
        if item.mark == "yes"
    ]
    if s.phones:
        parts.append("есть телефон")
    text = ", ".join(parts) if parts else "мало данных на сайте — уточнить по телефону"
    return f"{s.confirmed} из 6 подтверждено: {text}"


def apply_score(s: Supplier, region: Region | None, city: str, text: str = "", listing: str = "") -> Supplier:
    s.checklist = build_checklist(s, region, city, text, listing)
    s.confirmed = sum(item.mark == "yes" for item in s.checklist)
    s.why = why(s)
    return s


def sells(s: Supplier) -> str:
    fact = s.facts.get("sells_category")
    return fact.value if fact else "unknown"


def sells_confirmed(s: Supplier, category: str, text: str, headings: Sequence[str] = ()) -> bool:
    fact, price = s.facts.get("sells_category"), s.facts.get("price")
    if price and names_category(price.quote, category):
        return True
    if fact and fact.value == "yes" and (names_category(fact.quote, category) or mentions_category(text, category)):
        return True
    shown = [s.name, s.legal.name if s.legal else None, s.snippet, *headings]
    return any(mentions_category(t, category) for t in shown if t) or offers_category(text, category)


def check(s: Supplier, key: str) -> CheckItem | None:
    return next((item for item in s.checklist if item.key == key), None)


def delivery_mark(s: Supplier) -> Mark:
    item = check(s, "delivers_to_city")
    return item.mark if item else "unknown"


def detect_kind(s: Supplier, text: str) -> Kind:
    blob = " ".join([s.name, text, *(f.quote for f in s.facts.values())])
    if s.kind == "aggregator" or is_aggregator(s.domain) or CATALOG.search(blob):
        return "aggregator"
    okved = s.legal.okved if s.legal and s.legal.okved else ""
    retail = s.kind == "retail" or RETAIL.search(blob) or RETAIL_NAME.search(s.name) or okved.startswith(RETAIL_OKVED)
    if CHAIN.search(blob) or (retail and b2b(s, text)[0] != "yes"):
        return "retail"
    return "unknown" if s.kind == "retail" else s.kind


def doubt(
    s: Supplier, region: Region | None, city: str, category: str, text: str, sold: bool, listing: str = ""
) -> str | None:
    route = delivery(s, region, city, listing)
    if route.mark == "no":
        return f"другой регион: {route.label.removeprefix('нет — ')}"
    if route.elsewhere:
        return f"другой регион: {route.elsewhere} — только отправка транспортной компанией"
    if s.kind == "retail":
        return "розничный магазин"
    if EATERY.search(f"{s.name} {s.snippet} {text}"):
        return "ресторан или кафе, а не поставщик"
    if not sold:
        return f"не подтверждено, что продают {category}"
    if route.mark != "yes":
        return f"не нашли, возят ли в {city}: нет местного адреса, телефона или условий доставки"
    return None


def review(
    s: Supplier, category: str, region: Region | None, city: str, text: str = "", headings: Sequence[str] = ()
) -> Supplier:
    s.facts = {key: fact.model_copy(update={"value": format_value(key, fact.value)}) for key, fact in s.facts.items()}
    sold = sells_confirmed(s, category, text, headings)
    if sold and sells(s) == "no":
        del s.facts["sells_category"]
    s.kind = detect_kind(s, text)
    listing = " ".join([s.snippet, *headings])
    apply_score(s, region, city, text, listing)
    s.doubt = doubt(s, region, city, category, text, sold, listing)
    s.group = "doubtful" if s.doubt else "match"
    s.questions = build_questions(s, category, city)
    s.rfq = build_rfq(s, category, city)
    return s


def rank(suppliers: list[Supplier]) -> list[Supplier]:
    kept = [s for s in suppliers if sells(s) != "no"]
    return sorted(
        kept,
        key=lambda s: (
            GROUP_ORDER[s.group],
            MARK_ORDER[delivery_mark(s)],
            -s.confirmed,
            not s.phones,
            KIND_ORDER[s.kind],
            sells(s) != "yes",
        ),
    )


def same_company(a: Supplier, b: Supplier) -> bool:
    inn_a = a.inn or (a.legal.inn if a.legal else None)
    inn_b = b.inn or (b.legal.inn if b.legal else None)
    return bool(inn_a and inn_a == inn_b) or bool(set(a.phones) & set(b.phones))


def dedupe(ranked: list[Supplier]) -> list[Supplier]:
    kept: list[Supplier] = []
    for s in ranked:
        if not any(same_company(s, k) for k in kept):
            kept.append(s)
    return kept


def finalize(suppliers: list[Supplier]) -> tuple[list[Supplier], list[Source]]:
    catalogs = [Source(domain=s.domain, url=s.url, title=s.name) for s in suppliers if s.kind == "aggregator"]
    ranked = dedupe(rank([s for s in suppliers if s.kind != "aggregator"]))
    names: dict[str, str] = {}
    for s in ranked:
        inn = s.inn or (s.legal.inn if s.legal else None)
        if inn:
            s.name = names.setdefault(inn, s.name)
    return ranked, catalogs
