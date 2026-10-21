import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.config import settings
from app.pipeline import fetch, legal
from app.pipeline.cost import Usage
from app.pipeline.extract_llm import FIELDS, Extracted, extract
from app.pipeline.filters import split_hits
from app.pipeline.gigachat import GigaChat, ssl_context
from app.pipeline.queries import build_queries
from app.pipeline.regions import Region, find_region
from app.pipeline.rules import Contacts, extract_contacts
from app.pipeline.score import finalize, review
from app.pipeline.slots import RankedSlots
from app.pipeline.tidy import pick_name
from app.pipeline.verify import normalize, verify_fact
from app.pipeline.yandex_search import Hit, search
from app.schemas import (
    Fact,
    LegalInfo,
    ProgressEvent,
    SearchResult,
    SearchStats,
    Supplier,
)

RUSSIA_LR = 225
MIN_SITE_TEXT = 300

logger = logging.getLogger("suppliers")


class SearchUnavailable(Exception):
    pass


@dataclass
class Candidate:
    hits: list[Hit]
    pages: list[fetch.Page] = field(default_factory=list)
    contacts: Contacts = field(default_factory=Contacts)
    extracted: Extracted | None = None
    legal: LegalInfo | None = None
    rejected: int = 0

    @property
    def domain(self) -> str:
        return self.hits[0].domain

    @property
    def snippet(self) -> str:
        return " … ".join(dict.fromkeys(h.snippet for h in self.hits if h.snippet))[:600]

    @property
    def site_opened(self) -> bool:
        return sum(len(p.text) for p in self.pages) >= MIN_SITE_TEXT

    @property
    def sources(self) -> list[fetch.Page]:
        if self.site_opened:
            return self.pages
        titles = [h.title for h in self.hits if h.title]
        return [fetch.Page(url=self.hits[0].url, text=self.snippet, title=self.hits[0].title, headings=titles)]


@dataclass
class Context:
    category: str
    city: str
    region: Region | None
    sites: httpx.AsyncClient
    api: httpx.AsyncClient
    giga: GigaChat
    fetch_slots: asyncio.Semaphore
    llm_slots: RankedSlots


def stage(name: str, message: str) -> ProgressEvent:
    return ProgressEvent(type="stage", stage=name, message=message)


def verified_facts(c: Candidate) -> dict[str, Fact]:
    if not c.extracted:
        return {}
    facts = {}
    sells = c.extracted.sells_category
    candidates = [("sells_category", sells.value, sells.quote)] if sells.value != "unknown" and sells.quote else []
    candidates += [(key, item.value, item.quote) for key in FIELDS if (item := getattr(c.extracted, key))]
    for key, value, quote in candidates:
        url = verify_fact(key, value, quote, c.sources)
        if url:
            facts[key] = Fact(value=value, quote=quote, url=url)
        else:
            c.rejected += 1
    return facts


def page_text(c: Candidate) -> str:
    return "\n".join([c.snippet, *(p.text for p in c.pages)])


def supplier_name(c: Candidate, category: str) -> str:
    first = c.pages[0] if c.pages else None
    name = c.extracted.name if c.extracted else None
    on_site = name if name and any(normalize(name) in normalize(p.text) for p in c.sources) else None
    return pick_name(
        [
            first.site_name if first else None,
            on_site,
            c.legal.name if c.legal else None,
            first.title if first else c.hits[0].title,
        ],
        c.domain,
        category,
        page_text(c),
    )


def build_supplier(c: Candidate, ctx: Context) -> Supplier:
    s = Supplier(
        domain=c.domain,
        name=supplier_name(c, ctx.category),
        url=c.hits[0].url,
        kind=c.extracted.kind if c.extracted else "unknown",
        snippet=c.snippet,
        site_opened=c.site_opened,
        phones=c.contacts.phones,
        emails=c.contacts.emails,
        address=c.contacts.address,
        inn=c.contacts.inn,
        facts=verified_facts(c),
        legal=c.legal,
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    headings = [*(h.title for h in c.hits), *(h for p in c.pages for h in p.headings)]
    return review(s, ctx.category, ctx.region, ctx.city, page_text(c), headings)


async def lookup_legal(c: Candidate, ctx: Context) -> None:
    if c.contacts.inn:
        try:
            c.legal = await legal.lookup(ctx.api, c.contacts.inn)
        except httpx.HTTPError:
            c.legal = LegalInfo(inn=c.contacts.inn, check_url=legal.check_url(c.contacts.inn))


async def run_llm(c: Candidate, ctx: Context, position: int) -> None:
    async with ctx.llm_slots.take(position):
        c.extracted = await extract(ctx.giga, c.sources, ctx.category, ctx.city)


async def find_contacts(c: Candidate, ctx: Context) -> None:
    patterns = ctx.region.patterns if ctx.region else ()
    c.contacts = await asyncio.to_thread(extract_contacts, c.sources, patterns)


async def process(c: Candidate, ctx: Context, position: int) -> Candidate:
    try:
        await fetch.fetch_site(ctx.sites, c.hits[0].url, ctx.fetch_slots, c.pages)
        await find_contacts(c, ctx)
    except Exception:
        logger.exception("Не удалось прочитать сайт %s", c.domain)
        return c
    jobs = [lookup_legal(c, ctx)]
    if position < settings.llm_domains and ctx.giga.enabled:
        jobs.append(run_llm(c, ctx, position))
    for error in await asyncio.gather(*jobs, return_exceptions=True):
        if error:
            logger.error("Не удалось дополнить данные по %s", c.domain, exc_info=error)
    return c


async def search_all(ctx: Context, queries: list[str], usage: Usage) -> list[Hit]:
    lr = ctx.region.lr if ctx.region else RUSSIA_LR
    results = await asyncio.gather(*(search(ctx.api, q, lr, usage) for q in queries), return_exceptions=True)
    errors = [result for result in results if isinstance(result, BaseException)]
    for error in errors:
        logger.error("Яндекс Поиск вернул ошибку", exc_info=error)
    if len(errors) == len(results):
        raise SearchUnavailable
    return [hit for result in results if isinstance(result, list) for hit in result]


async def run_search(category: str, city: str) -> AsyncIterator[ProgressEvent]:
    started = time.monotonic()
    deadline = started + settings.search_budget_seconds
    region = find_region(city)
    city = region.city if region else city.strip()
    category = " ".join(category.split())
    usage = Usage()
    result = SearchResult(
        id=uuid.uuid4().hex[:12],
        category=category,
        city=city,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    tls = ssl_context()
    async with (
        httpx.AsyncClient(verify=tls, timeout=20) as api,
        httpx.AsyncClient(
            transport=fetch.PublicOnlyTransport(tls, max_connections=16),
            timeout=fetch.TIMEOUT,
            headers={"User-Agent": fetch.USER_AGENT, "Accept-Language": "ru"},
        ) as sites,
    ):
        ctx = Context(
            category,
            city,
            region,
            sites,
            api,
            GigaChat(api, usage),
            asyncio.Semaphore(8),
            RankedSlots(settings.gigachat_concurrency),
        )

        yield stage("queries", "Составляю поисковые запросы")
        result.queries = await build_queries(ctx.giga, category, city)
        yield stage("search", "Ищу в Яндексе: " + "; ".join(result.queries))
        try:
            hits = await search_all(ctx, result.queries, usage)
        except SearchUnavailable:
            hits = []
            yield ProgressEvent(
                type="error",
                stage="unavailable",
                message="Поиск временно недоступен — попробуйте позже или откройте демо",
            )
        else:
            if not hits:
                yield ProgressEvent(
                    type="error", message="Поиск не вернул результатов — попробуйте другую формулировку"
                )
        groups, result.aggregators = split_hits(hits)
        candidates = [Candidate(hits=g) for g in groups]
        yield stage(
            "sites",
            f"Нашлось {len(candidates)} сайтов поставщиков, отсеяно агрегаторов и маркетплейсов: "
            f"{len(result.aggregators)}. Открываю сайты и читаю условия",
        )

        tasks = {asyncio.create_task(process(c, ctx, i)): c for i, c in enumerate(candidates)}
        suppliers: dict[str, Supplier] = {}
        pending = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, timeout=max(0.0, deadline - time.monotonic()), return_when=asyncio.FIRST_COMPLETED
                )
                if not done:
                    break
                for task in done:
                    supplier = build_supplier(task.result(), ctx)
                    suppliers[supplier.domain] = supplier
                    if supplier.kind != "aggregator":
                        yield ProgressEvent(type="supplier", supplier=supplier)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        if pending:
            yield stage("timeout", f"Время вышло: {len(pending)} сайтов не дочитаны, показываю что успел")
            for task in pending:
                await find_contacts(tasks[task], ctx)
                supplier = build_supplier(tasks[task], ctx)
                suppliers[supplier.domain] = supplier

    ordered = [suppliers[c.domain] for c in candidates if c.domain in suppliers]
    result.suppliers, catalogs = finalize(ordered)
    result.aggregators += catalogs
    result.stats = SearchStats(
        seconds=round(time.monotonic() - started, 1),
        cost_rub=usage.cost_rub,
        search_calls=usage.search_calls,
        llm_calls=usage.llm_calls,
        tokens=usage.tokens,
        candidates=len(candidates),
        suppliers=len(result.suppliers),
        with_phone=sum(bool(s.phones) for s in result.suppliers),
        rejected_quotes=sum(c.rejected for c in candidates),
    )
    yield ProgressEvent(type="done", result=result)
