from collections import defaultdict
from functools import cache

from app.config import DATA, settings
from app.pipeline.yandex_search import Hit
from app.schemas import Source

TWO_LEVEL = {"com.ru", "net.ru", "org.ru", "msk.ru", "spb.ru", "ekb.ru", "com.kz"}


@cache
def aggregators() -> frozenset[str]:
    lines = (DATA / "aggregators.txt").read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def is_aggregator(domain: str) -> bool:
    labels = domain.split(".")
    return any(".".join(labels[i:]) in aggregators() for i in range(len(labels) - 1))


def site_key(domain: str) -> str:
    labels = domain.split(".")
    size = 3 if ".".join(labels[-2:]) in TWO_LEVEL else 2
    return ".".join(labels[-size:])


def split_hits(hits: list[Hit]) -> tuple[list[list[Hit]], list[Source]]:
    groups: dict[str, list[Hit]] = defaultdict(list)
    sources: dict[str, Source] = {}
    for hit in hits:
        if not hit.domain:
            continue
        key = site_key(hit.domain)
        if is_aggregator(hit.domain):
            sources.setdefault(key, Source(domain=hit.domain, url=hit.url, title=hit.title))
        else:
            groups[key].append(hit)
    ranked = sorted(groups.values(), key=lambda g: (-len(g), min(h.position for h in g)))
    for group in ranked:
        group.sort(key=lambda h: h.position)
    return ranked[: settings.max_domains], list(sources.values())
