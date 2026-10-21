import json
import logging
import re

from app.pipeline.gigachat import GigaChat

logger = logging.getLogger("suppliers")

PROMPT = """Составь 5 поисковых запросов для Яндекса, чтобы найти поставщиков товара «{category}» \
для ресторанов и магазинов в городе {city}: оптовиков, производителей, дистрибьюторов.
Варианты: «оптом», «поставщик», «производитель», «для ресторанов / HoReCa», синоним или уточнение товара.
Каждый запрос — 3–7 слов, обязательно с названием города. Без кавычек и операторов.
Ответ — только JSON-массив из 5 строк."""


def template_queries(category: str, city: str) -> list[str]:
    return [
        f"{category} оптом {city}",
        f"{category} поставщик {city}",
        f"{category} производитель {city}",
        f"{category} для ресторанов HoReCa {city}",
        f"купить {category} оптом с доставкой {city}",
    ]


def parse_queries(answer: str, city: str) -> list[str]:
    items = json.loads(re.search(r"\[.*\]", answer, re.DOTALL).group(0))
    city_stem = city.lower()[:5]
    queries = []
    for item in items:
        query = re.sub(r"\s+", " ", str(item)).strip(" \"'«»")
        if not query or len(query) > 120:
            continue
        if city_stem not in query.lower():
            query = f"{query} {city}"
        if query.lower() not in (q.lower() for q in queries):
            queries.append(query)
    return queries[:5]


async def build_queries(giga: GigaChat, category: str, city: str) -> list[str]:
    if not giga.enabled:
        return template_queries(category, city)
    try:
        answer = await giga.chat([{"role": "user", "content": PROMPT.format(category=category, city=city)}], 300)
        queries = parse_queries(answer, city)
    except Exception:
        logger.exception("Не удалось расширить запросы через GigaChat")
        return template_queries(category, city)
    return queries if len(queries) >= 3 else template_queries(category, city)
