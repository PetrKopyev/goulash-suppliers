import asyncio
import sys
from pathlib import Path

from app.pipeline.run import run_search

DEMO = [
    ("salmon-ekb", "лосось охлаждённый", "Екатеринбург"),
    ("nori-rice-ekb", "нори и рис для суши", "Екатеринбург"),
    ("packaging-ekb", "контейнеры для доставки еды", "Екатеринбург"),
    ("tvorog-ekb", "творог фермерский", "Екатеринбург"),
    ("bakery-ekb", "хлеб от местной пекарни", "Екатеринбург"),
    ("chicken-ekb", "куриное филе охлаждённое", "Екатеринбург"),
    ("salmon-kazan", "лосось охлаждённый", "Казань"),
]
OUT = Path(__file__).resolve().parent.parent / "data" / "demo"


async def precompute(slug: str, category: str, city: str) -> None:
    async for event in run_search(category, city):
        if event.type == "done":
            result = event.result.model_copy(update={"is_demo": True})
            (OUT / f"{slug}.json").write_text(result.model_dump_json(indent=1), encoding="utf-8")
            print(f"{slug}: {len(result.suppliers)} поставщиков, {result.stats.seconds:.0f} с, {result.stats.cost_rub:.1f} ₽")
        elif event.type == "error":
            print(f"{slug}: ошибка — {event.message}")


async def main(only: list[str]) -> None:
    for slug, category, city in DEMO:
        if not only or slug in only:
            await precompute(slug, category, city)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
