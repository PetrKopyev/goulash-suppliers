import re

ZERO_WIDTH = re.compile("[\u200b-\u200d\u2060\ufeff]")
DOMAIN_LIKE = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+/?", re.IGNORECASE)
TAGLINE = re.compile(r"\s+[—–|-]\s+|:\s")
OPEN_QUOTE = re.compile(r"""(^|[\s(«])["'“„]""")
CLOSE_QUOTE = re.compile(r"""["”“]|'(?=[\s,.]|$)""")
MAX_NAME = 60
RUB = re.compile(r"(\d)\s*(?:руб(?:л[а-я]*)?\.?|р\.|₽)", re.IGNORECASE)
UNIT = re.compile(r"(\d)\s*(кг|гр|г|мл|л|шт)\b\.?", re.IGNORECASE)
PER_UNIT = re.compile(r"₽\s*(?:/\s*|за\s+)(?:1\s+)?(?=\d|кг|г\b|мл|л\b|шт)", re.IGNORECASE)
MONEY_KEYS = ("price", "min_order")


def tidy_name(name: str) -> str:
    name = TAGLINE.split(ZERO_WIDTH.sub("", " ".join(name.split())))[0]
    return CLOSE_QUOTE.sub("»", OPEN_QUOTE.sub(r"\1«", name)).strip(" .,!")


def usable_name(name: str) -> bool:
    return bool(name) and len(name) <= MAX_NAME and not DOMAIN_LIKE.fullmatch(name)


def pick_name(candidates: list[str | None], domain: str) -> str:
    names = (tidy_name(c) for c in candidates if c)
    return next((name for name in names if usable_name(name)), domain)


def format_unit(match: re.Match) -> str:
    unit = match.group(2).lower()
    return f"{match.group(1)} {'г' if unit == 'гр' else unit}"


def format_value(key: str, value: str) -> str:
    value = " ".join(value.split())
    if key not in MONEY_KEYS:
        return value
    value = UNIT.sub(format_unit, RUB.sub(r"\1 ₽", value))
    return PER_UNIT.sub("₽/", value).rstrip(" .")
