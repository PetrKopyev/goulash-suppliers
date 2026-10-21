import re

from app.pipeline.fetch import Page

QUOTES = str.maketrans({c: '"' for c in "«»“”„‟″'`’‘"} | {c: "-" for c in "‐‑‒–—―−"})
MIN_QUOTE = 8
MIN_PART = 12
MAX_GAP = 200
FIELD_HINTS = {
    "min_order": re.compile(r"мин|\bот\s*\d|заказ|парти|упаков"),
    "price": re.compile(r"руб|₽|\bр\.|цен|стоим"),
    "delivery": re.compile(r"достав|отгруз|самовывоз|привоз|вывоз|курьер"),
    "documents": re.compile(
        r"сертиф|деклар|хассп|haccp|меркури|ветис|ветеринар|честн\w* знак|документ|гост|свидетельств|удостоверени"
    ),
    "payment": re.compile(r"ндс|оплат|безнал|отсроч|расч[её]т|наличн|счет"),
}
NUMBER = re.compile(r"\d+(?:[ \xa0]\d{3})*(?:[.,]\d+)?")


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е").replace("…", "...").translate(QUOTES)
    return re.sub(r"\s+", " ", text).strip()


def quote_parts(quote: str) -> list[str]:
    parts = [p.strip(' .,;:!?"-') for p in normalize(quote).split("...")]
    return [p for p in parts if p]


def follows(text: str, position: int, parts: list[str]) -> bool:
    for part in parts:
        found = text.find(part, position, position + MAX_GAP + len(part))
        if found < 0:
            return False
        position = found + len(part)
    return True


def contains(text: str, parts: list[str]) -> bool:
    first, *rest = parts
    start = text.find(first)
    while start >= 0:
        if follows(text, start + len(first), rest):
            return True
        start = text.find(first, start + 1)
    return False


def find_quote(quote: str, pages: list[Page]) -> str | None:
    parts = quote_parts(quote)
    if not parts or sum(map(len, parts)) < MIN_QUOTE or (len(parts) > 1 and any(len(p) < MIN_PART for p in parts)):
        return None
    return next((page.url for page in pages if contains(normalize(page.text), parts)), None)


def numbers(text: str) -> set[str]:
    return {re.sub(r"[ \xa0]", "", n).replace(",", ".") for n in NUMBER.findall(text)}


def stems(text: str) -> set[str]:
    return {word[:5] for word in re.findall(r"[а-яa-z]{4,}", normalize(text))}


def supports(key: str, value: str, quote: str) -> bool:
    if key == "sells_category":
        return True
    hint = FIELD_HINTS.get(key)
    if hint and not hint.search(normalize(quote)):
        return False
    if not numbers(value) <= numbers(quote):
        return False
    value_stems = stems(value)
    return len(value_stems & stems(quote)) * 2 >= len(value_stems)


def verify_fact(key: str, value: str, quote: str, pages: list[Page]) -> str | None:
    return find_quote(quote, pages) if value.strip() and supports(key, value, quote) else None
