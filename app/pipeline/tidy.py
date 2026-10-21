import re
from itertools import pairwise

from app.pipeline.verify import mentions_category

ZERO_WIDTH = re.compile("[\u200b-\u200d\u2060\ufeff]")
DOMAIN_LIKE = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+/?", re.IGNORECASE)
TAGLINE = re.compile(r"\s+[—–|-]\s+|:\s")
OPEN_QUOTE = re.compile(r"""(^|[\s(«])["'“„]""")
CLOSE_QUOTE = re.compile(r"""["”“]|'(?=[\s,.]|$)""")
MAX_NAME = 60
SHORT_NAME = 35
DESCRIPTION = re.compile(r"[,%]|\bопт(?:ом|ов\w*)?\b|\bкупи|\bцен[аыуе]?\b|\bдля\b|недорог|каталог", re.IGNORECASE)
NOT_A_NAME = re.compile(
    r"проверка безопасности|страница не найдена|access denied|just a moment|^главная\b", re.IGNORECASE
)
LEGAL_FORM = re.compile(r"(?:ООО|АО|ПАО|ЗАО|ОАО|ИП)\b")
WORD = re.compile(r"[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*")
LATIN = str.maketrans(
    dict(zip("абвгдезиклмнопрстуф", "abvgdeziklmnoprstuf", strict=True))
    | {"ё": "e", "ж": "zh", "й": "y", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ы": "y", "э": "e"}
    | {"ю": "yu", "я": "ya", "ъ": "", "ь": ""}
)
SOUNDS = (("shch", "sch"), ("kh", "h"), ("ck", "k"), ("x", "ks"), ("w", "v"), ("q", "k"), ("ph", "f"), ("j", "y"))
VOWELS = "aeiouy"
MIN_BRAND = 4
CYRILLIC_VOWELS = "аеёиоуыэюя"
CYRILLIC_VOWEL = {"a": "а", "e": "е", "i": "и", "o": "о", "u": "у", "y": "ы"}
RUB = re.compile(r"(\d)\s*(?:руб(?:л[а-я]*)?\.?|р\.|₽)", re.IGNORECASE)
UNIT = re.compile(r"(\d)\s*(кг|гр|г|мл|л|шт)\b\.?", re.IGNORECASE)
PER_UNIT = re.compile(r"₽\s*(?:/\s*|за\s+)(?:1\s+)?(?=\d|кг|г\b|мл|л\b|шт)", re.IGNORECASE)
MONEY_KEYS = ("price", "min_order")


def tidy_name(name: str) -> str:
    name = TAGLINE.split(ZERO_WIDTH.sub("", " ".join(name.split())))[0]
    return CLOSE_QUOTE.sub("»", OPEN_QUOTE.sub(r"\1«", name)).strip(" .,!")


def usable_name(name: str) -> bool:
    return bool(name) and len(name) <= MAX_NAME and not DOMAIN_LIKE.fullmatch(name)


def looks_like_product(name: str, category: str) -> bool:
    if len(name) > SHORT_NAME or DESCRIPTION.search(name):
        return True
    return "«" not in name and mentions_category(name.split()[0], category)


def sound_key(text: str) -> str:
    key = text.lower().translate(LATIN)
    for spelling, sound in SOUNDS:
        key = key.replace(spelling, sound)
    return re.sub(r"c(?!h)", "k", re.sub(r"[^a-z]", "", key))


def brand_span(span: str, key: str) -> str:
    tail = key[len(key.rstrip(VOWELS)) :]
    if sound_key(span) != key and tail in CYRILLIC_VOWEL and span[-1].lower() in CYRILLIC_VOWELS:
        span = span.rstrip(CYRILLIC_VOWELS + CYRILLIC_VOWELS.upper()) + CYRILLIC_VOWEL[tail]
    return span[0].upper() + span[1:]


def domain_label(domain: str) -> str:
    labels = domain.split(".")
    return labels[-2] if len(labels) > 1 else labels[0]


def domain_brand(domain: str, text: str) -> str | None:
    key = sound_key(domain_label(domain))
    root = key.rstrip(VOWELS)
    words = WORD.findall(text) if len(root) >= MIN_BRAND else []
    for span in (*words, *map(" ".join, pairwise(words))):
        if sound_key(span).rstrip(VOWELS) == root:
            return brand_span(span, key)
    return None


def pick_name(candidates: list[str | None], domain: str, category: str = "", text: str = "") -> str:
    names = [n for n in (tidy_name(c) for c in candidates if c) if usable_name(n) and not NOT_A_NAME.search(n)]
    good = (n for n in names if not looks_like_product(n, category))
    legal = (n for n in names if LEGAL_FORM.match(n))
    label = domain_label(domain)
    return next(good, None) or domain_brand(domain, text) or next(legal, None) or label[0].upper() + label[1:]


def format_unit(match: re.Match) -> str:
    unit = match.group(2).lower()
    return f"{match.group(1)} {'г' if unit == 'гр' else unit}"


def format_value(key: str, value: str) -> str:
    value = " ".join(value.split())
    if key not in MONEY_KEYS:
        return value
    value = UNIT.sub(format_unit, RUB.sub(r"\1 ₽", value))
    return PER_UNIT.sub("₽/", value).rstrip(" .")
