import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    city: str
    lr: int
    region: str
    patterns: tuple[str, ...]
    phone_codes: tuple[str, ...]

    def mentioned_in(self, text: str) -> bool:
        low = normalize(text)
        return any(re.search(p, low) for p in self.patterns)

    def city_in(self, text: str) -> bool:
        return bool(re.search(self.patterns[0], normalize(text)))

    def owns_phone(self, phone: str) -> bool:
        return phone_digits(phone).startswith(self.phone_codes)


REGIONS: dict[str, Region] = {
    r.city: r
    for r in [
        Region(
            "Москва",
            213,
            "Московская область",
            (r"\bмоскв", r"\bмосковск", r"\bподмосков", r"\bмск\b", r"\bмкад\b"),
            ("495", "499", "496", "498"),
        ),
        Region(
            "Санкт-Петербург",
            2,
            "Ленинградская область",
            (r"петербург", r"\bспб\b", r"\bпитер", r"ленинградск", r"\bкад\b"),
            ("812", "813"),
        ),
        Region(
            "Екатеринбург",
            54,
            "Свердловская область",
            (r"екатеринбург", r"\bекб\b", r"свердловск", r"\bурфо\b"),
            ("343",),
        ),
        Region("Казань", 43, "Республика Татарстан", (r"\bказан", r"татарстан"), ("843",)),
        Region("Новосибирск", 65, "Новосибирская область", (r"новосибирск",), ("383",)),
        Region("Тюмень", 55, "Тюменская область", (r"\bтюмен",), ("3452",)),
        Region("Челябинск", 56, "Челябинская область", (r"челябинск",), ("351",)),
        Region("Пермь", 50, "Пермский край", (r"\bперм[ьиск]",), ("342",)),
        Region("Уфа", 172, "Республика Башкортостан", (r"\bуф[аеуы]\b", r"башкир", r"башкортостан"), ("347",)),
        Region("Самара", 51, "Самарская область", (r"\bсамар",), ("846",)),
        Region(
            "Нижний Новгород",
            47,
            "Нижегородская область",
            (r"нижн\w* новгород", r"\bн\. ?новгород", r"нижегородск"),
            ("831",),
        ),
        Region("Краснодар", 35, "Краснодарский край", (r"краснодар", r"\bкубан"), ("861",)),
        Region("Ростов-на-Дону", 39, "Ростовская область", (r"ростов[- ]на[- ]дону", r"ростовск"), ("863",)),
        Region("Омск", 66, "Омская область", (r"\bомск",), ("3812",)),
        Region("Красноярск", 62, "Красноярский край", (r"красноярск",), ("391",)),
    ]
}

CITIES = list(REGIONS)

ALIASES = {
    "мск": "Москва",
    "спб": "Санкт-Петербург",
    "питер": "Санкт-Петербург",
    "петербург": "Санкт-Петербург",
    "екб": "Екатеринбург",
    "нн": "Нижний Новгород",
    "нижний": "Нижний Новгород",
    "ростов": "Ростов-на-Дону",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def find_region(city: str) -> Region | None:
    key = normalize(city).replace("г. ", "").strip(" .")
    if key in ALIASES:
        return REGIONS[ALIASES[key]]
    for region in REGIONS.values():
        if normalize(region.city) == key or region.mentioned_in(key):
            return region
    return None


def other_region(text: str, own: Region | None) -> Region | None:
    return next((r for r in REGIONS.values() if r != own and r.mentioned_in(text)), None)


def phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)[1:]


def is_city_phone(phone: str) -> bool:
    digits = phone_digits(phone)
    return digits[:1] in ("3", "4", "8") and not digits.startswith("80")


def phone_region(phone: str) -> Region | None:
    return next((r for r in REGIONS.values() if r.owns_phone(phone)), None)
