import json
from functools import cache

from app.config import DATA
from app.schemas import Supplier


@cache
def category_rules() -> list[dict]:
    return json.loads((DATA / "category_rules.json").read_text(encoding="utf-8"))


def category_questions(category: str) -> list[str]:
    low = f"{category.lower().replace('ё', 'е')} "
    return [q for rule in category_rules() if any(m in low for m in rule["match"]) for q in rule["questions"]]


def field_questions(s: Supplier, city: str) -> list[str]:
    marks = {item.key: item.mark for item in s.checklist}
    questions = []
    if "min_order" not in s.facts:
        questions.append("Какой минимальный заказ — сумма или объём?")
    if marks.get("delivers_to_city") != "yes":
        questions.append(f"Доставляете в {city}? По каким дням и в какое время, сколько стоит доставка?")
    else:
        questions.append(f"Какой график доставки в {city} и до скольких принимаете заявку?")
    if "price" not in s.facts:
        questions.append("Пришлите актуальный прайс для HoReCa.")
    if "payment" not in s.facts:
        questions.append("Работаете с НДС? Возможна ли отсрочка платежа и на сколько дней?")
    if "documents" not in s.facts:
        questions.append("Какие документы прикладываете к поставке?")
    questions.append("Можно получить образцы перед первой поставкой?")
    return questions


def build_questions(s: Supplier, category: str, city: str) -> list[str]:
    return list(dict.fromkeys(field_questions(s, city) + category_questions(category)))


def build_rfq(s: Supplier, category: str, city: str) -> str:
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(s.questions, start=1))
    return (
        f"Тема: Запрос коммерческого предложения — {category}, поставка в {city}\n\n"
        f"Здравствуйте!\n\n"
        f"Мы подбираем поставщика: {category} с регулярной поставкой в {city} "
        f"(рестораны и доставка). Нашли вашу компанию на сайте {s.domain}.\n"
        f"Просим прислать коммерческое предложение и прайс для HoReCa и ответить на вопросы:\n\n"
        f"{numbered}\n\n"
        f"Ориентировочный объём: ___ в неделю. Удобно получить ответ на эту почту или по телефону ___.\n\n"
        f"С уважением,\n___"
    )
