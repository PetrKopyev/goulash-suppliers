import sys
from pathlib import Path

from app.pipeline.regions import find_region
from app.pipeline.score import finalize, review
from app.pipeline.tidy import pick_name
from app.pipeline.verify import fact_allowed
from app.schemas import SearchResult, Supplier

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def rescore_supplier(s: Supplier, category: str, city: str) -> tuple[Supplier, int]:
    facts = {key: fact for key, fact in s.facts.items() if fact_allowed(key, fact.quote)}
    # текста страниц в демо нет: берём то, что живой прогон уже нашёл на сайте — слова про опт и подтверждённый товар
    b2b_seen = [item.note or "" for item in s.checklist if item.key == "b2b" and item.mark == "yes"]
    text = "\n".join([s.snippet, *b2b_seen, *(fact.quote for fact in facts.values())])
    name = pick_name([s.name, s.legal.name if s.legal else None], s.domain, category, text)
    rescored = s.model_copy(update={"facts": facts, "name": name})
    headings = [s.name, *([category] if s.group == "match" else [])]
    return review(rescored, category, find_region(city), city, text, headings), len(s.facts) - len(facts)


def rescore(result: SearchResult) -> SearchResult:
    rescored = [rescore_supplier(s, result.category, result.city) for s in result.suppliers]
    suppliers, catalogs = finalize([s for s, _ in rescored])
    known = {source.domain for source in result.aggregators}
    stats = result.stats.model_copy(
        update={
            "suppliers": len(suppliers),
            "with_phone": sum(bool(s.phones) for s in suppliers),
            "rejected_quotes": result.stats.rejected_quotes + sum(rejected for _, rejected in rescored),
        }
    )
    return result.model_copy(
        update={
            "suppliers": suppliers,
            "aggregators": result.aggregators + [c for c in catalogs if c.domain not in known],
            "stats": stats,
        }
    )


def report(slug: str, result: SearchResult) -> None:
    match = [s for s in result.suppliers if s.group == "match"]
    print(f"\n{slug}: подходят {len(match)}, под вопросом {len(result.suppliers) - len(match)}")
    for s in result.suppliers:
        mark = "+" if s.group == "match" else "?"
        reason = f" · {s.doubt}" if s.doubt else ""
        print(f"  {mark} {s.name} ({s.domain}) · {s.delivery_label} · {s.confirmed} из 6{reason}")


def main(write: bool) -> None:
    for path in sorted(DEMO_DIR.glob("*.json")):
        result = rescore(SearchResult.model_validate_json(path.read_text(encoding="utf-8")))
        report(path.stem, result)
        if write:
            path.write_text(result.model_dump_json(indent=1), encoding="utf-8")


if __name__ == "__main__":
    main("--write" in sys.argv[1:])
