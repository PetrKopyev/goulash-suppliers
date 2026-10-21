import argparse
import asyncio
from pathlib import Path

from app.pipeline.run import run_search


async def main(category: str, city: str, out: Path | None) -> None:
    async for event in run_search(category, city):
        if event.type == "stage":
            print(f"[{event.stage}] {event.message}", flush=True)
        elif event.type == "error":
            print(f"[ошибка] {event.message}", flush=True)
        elif event.type == "supplier":
            s = event.supplier
            print(
                f"  + {s.name} ({s.domain}) · {s.confirmed}/6 · {', '.join(s.phones[:2]) or 'без телефона'}", flush=True
            )
        elif event.type == "done":
            stats = event.result.stats
            print(
                f"Готово: {stats.seconds} с · {stats.cost_rub} ₽ · {stats.candidates} кандидатов → "
                f"{stats.suppliers} поставщиков · {stats.with_phone} с телефоном · "
                f"отвергнуто цитат: {stats.rejected_quotes}"
            )
            if out:
                out.write_text(event.result.model_dump_json(indent=2), encoding="utf-8")
                print(f"Сохранено: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Поиск поставщиков по категории и городу")
    parser.add_argument("category")
    parser.add_argument("city")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.category, args.city, args.out))
