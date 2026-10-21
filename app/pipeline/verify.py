import re
from collections.abc import Sequence
from functools import cache

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
PLACE_KEYS = ("sells_category", "delivery", "region")
CITY_PICKER = re.compile(r"ваш (город|регион)|выберите (город|регион)")
SEO_HEADING = re.compile(r"купить|\bцен[аы]\b|недорого|^(?!.*(?:достав|привоз|отгруз)).*\bв (г\. ?|городе )?[а-я-]+$")
SEO_WORDS = 8
GENERIC_STEMS = {"дост", "опто", "купи", "цена", "мест", "свеж", "охла", "замо", "ферм", "прои", "пост", "филе"}
STEM_END = re.compile(r"(?:ами|ями|ого|ему|ой|ый|ий|ая|яя|ое|ее|ые|ие|ов|ев|ей|ам|ям|ах|ях|ом|ем|а|я|о|е|ы|и|у|ю|ь)$")
MIN_STEM = 4
RELATED_STEMS = {
    "лосос": (r"\bсемг", r"\bфорел"),
    "семг": (r"\bлосос", r"\bфорел"),
    "курин": (r"\bкуриц", r"\bкур\b", r"\bптиц", r"\bцыпл"),
    "хлеб": (r"\bпекарн", r"\bвыпечк", r"\bбулоч", r"\bбагет", r"\bбатон"),
    "пекарн": (r"\bхлеб", r"\bвыпечк"),
    "контейнер": (r"\bланч[- ]?бокс", r"\bупаковк", r"\bлот(?:ок|к)"),
    "нори": (r"\bводоросл",),
    "рис": (r"\bяпонск\w* рис\b", r"\bрис\w* для роллов"),
    "творог": (r"\bтворож",),
}
COMMERCE = re.compile(r"\bопт|\bкупи|\bцен[аыуе]?\b|каталог|прайс|в наличии")
NEAR = 80


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


def stem(word: str) -> str:
    root = STEM_END.sub("", word)
    return root if len(root) >= MIN_STEM else word


@cache
def category_pattern(category: str) -> re.Pattern | None:
    patterns = set()
    for item in re.split(r",|\bи\b", normalize(category)):
        head, _, purpose = item.partition(" для ")
        for word in re.findall(r"[а-яa-z]{3,}", head):
            if word[:4] in GENERIC_STEMS:
                continue
            root = stem(word)
            if len(root) >= MIN_STEM:
                patterns.add(rf"\b{root}")
            else:
                patterns.add(rf"\b{root}\w* для {re.escape(purpose.strip())}" if purpose.strip() else rf"\b{root}\b")
            patterns.update(RELATED_STEMS.get(root, ()))
    return re.compile("|".join(sorted(patterns))) if patterns else None


def mentions_category(text: str, category: str) -> bool:
    pattern = category_pattern(category)
    return bool(pattern and pattern.search(normalize(text)))


def names_category(quote: str, category: str) -> bool:
    return not category_pattern(category) or mentions_category(quote, category)


def offers_category(text: str, category: str) -> bool:
    pattern = category_pattern(category)
    if not pattern:
        return False
    text = normalize(text)
    return any(
        COMMERCE.search(text[max(0, found.start() - NEAR) : found.end() + NEAR]) for found in pattern.finditer(text)
    )


def is_heading(quote: str, headings: Sequence[str] = ()) -> bool:
    text = normalize(quote).strip(' .,;:!?"-')
    if CITY_PICKER.search(text) or any(text and text in normalize(h) for h in headings):
        return True
    return len(text.split()) <= SEO_WORDS and bool(SEO_HEADING.search(text))


def fact_allowed(key: str, quote: str, headings: Sequence[str] = ()) -> bool:
    if key not in PLACE_KEYS:
        return True
    return not is_heading(quote, headings) and (key == "sells_category" or len(normalize(quote).split()) > 2)


def verify_fact(key: str, value: str, quote: str, pages: list[Page]) -> str | None:
    if not value.strip() or not supports(key, value, quote):
        return None
    headings = [h for page in pages for h in page.headings]
    return find_quote(quote, pages) if fact_allowed(key, quote, headings) else None
