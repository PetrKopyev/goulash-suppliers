import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    city: str
    lr: int
    region: str
    patterns: tuple[str, ...]

    def mentioned_in(self, text: str) -> bool:
        low = normalize(text)
        return any(re.search(p, low) for p in self.patterns)


REGIONS: dict[str, Region] = {
    r.city: r
    for r in [
        Region("Москва", 213, "Московская область", (r"\bмоскв", r"\bмосковск", r"\bподмосков", r"\bмск\b")),
        Region("Санкт-Петербург", 2, "Ленинградская область", (r"петербург", r"\bспб\b", r"\bпитер", r"ленинградск")),
        Region("Екатеринбург", 54, "Свердловская область", (r"екатеринбург", r"\bекб\b", r"свердловск", r"\bурфо\b")),
        Region("Казань", 43, "Республика Татарстан", (r"\bказан", r"татарстан")),
        Region("Новосибирск", 65, "Новосибирская область", (r"новосибирск",)),
        Region("Тюмень", 55, "Тюменская область", (r"\bтюмен",)),
        Region("Челябинск", 56, "Челябинская область", (r"челябинск",)),
        Region("Пермь", 50, "Пермский край", (r"\bперм[ьиск]",)),
        Region("Уфа", 172, "Республика Башкортостан", (r"\bуф[аеуы]\b", r"башкир", r"башкортостан")),
        Region("Самара", 51, "Самарская область", (r"\bсамар",)),
        Region(
            "Нижний Новгород", 47, "Нижегородская область", (r"нижн\w* новгород", r"\bн\. ?новгород", r"нижегородск")
        ),
        Region("Краснодар", 35, "Краснодарский край", (r"краснодар", r"\bкубан")),
        Region("Ростов-на-Дону", 39, "Ростовская область", (r"ростов[- ]на[- ]дону", r"ростовск")),
        Region("Омск", 66, "Омская область", (r"\bомск",)),
        Region("Красноярск", 62, "Красноярский край", (r"красноярск",)),
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
