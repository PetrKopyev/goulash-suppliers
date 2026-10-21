import asyncio
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
from app.pipeline.questions import build_questions, build_rfq
from app.pipeline.regions import Region, find_region
from app.pipeline.rules import Contacts, extract_contacts
from app.pipeline.score import apply_score, rank
from app.pipeline.verify import normalize, verify_fact
from app.pipeline.yandex_search import Hit, search
from app.schemas import Fact, LegalInfo, ProgressEvent, SearchResult, SearchStats, Source, Supplier

RUSSIA_LR = 225
MIN_SITE_TEXT = 300


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
        return [fetch.Page(url=self.hits[0].url, text=self.snippet, title=self.hits[0].title)]


@dataclass
class Context:
    category: str
    city: str
    region: Region | None
    sites: httpx.AsyncClient
    api: httpx.AsyncClient
    giga: GigaChat
    fetch_slots: asyncio.Semaphore


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


def supplier_name(c: Candidate) -> str:
    first = c.pages[0] if c.pages else None
    if first and first.site_name and len(first.site_name) <= 40:
        return first.site_name
    name = c.extracted.name if c.extracted else None
    if name and len(name) <= 60 and any(normalize(name) in normalize(p.text) for p in c.sources):
        return name
    if c.legal and c.legal.name:
        return c.legal.name
    return c.domain


def build_supplier(c: Candidate, ctx: Context) -> Supplier:
    s = Supplier(
        domain=c.domain,
        name=supplier_name(c),
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
    apply_score(s, ctx.region, ctx.city)
    s.questions = build_questions(s, ctx.category, ctx.city)
    s.rfq = build_rfq(s, ctx.category, ctx.city)
    return s


async def lookup_legal(c: Candidate, ctx: Context) -> None:
    if c.contacts.inn:
        try:
            c.legal = await legal.lookup(ctx.api, c.contacts.inn)
        except httpx.HTTPError:
            c.legal = LegalInfo(inn=c.contacts.inn, check_url=legal.check_url(c.contacts.inn))


async def run_llm(c: Candidate, ctx: Context) -> None:
    try:
        c.extracted = await extract(ctx.giga, c.sources, ctx.category, ctx.city)
    except httpx.HTTPError:
        c.extracted = None


async def process(c: Candidate, ctx: Context, use_llm: bool) -> Candidate:
    try:
        await fetch.fetch_site(ctx.sites, c.hits[0].url, ctx.fetch_slots, c.pages)
        patterns = ctx.region.patterns if ctx.region else ()
        c.contacts = extract_contacts(c.sources, patterns)
        jobs = [lookup_legal(c, ctx)]
        if use_llm and ctx.giga.enabled:
            jobs.append(run_llm(c, ctx))
        await asyncio.gather(*jobs)
    except Exception:
        pass
    return c


async def search_all(ctx: Context, queries: list[str], usage: Usage) -> list[Hit]:
    lr = ctx.region.lr if ctx.region else RUSSIA_LR
    results = await asyncio.gather(*(search(ctx.api, q, lr, usage) for q in queries), return_exceptions=True)
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
            verify=tls,
            timeout=fetch.TIMEOUT,
            headers={"User-Agent": fetch.USER_AGENT, "Accept-Language": "ru"},
            limits=httpx.Limits(max_connections=16),
        ) as sites,
    ):
        ctx = Context(category, city, region, sites, api, GigaChat(api, usage), asyncio.Semaphore(8))

        yield stage("queries", "Составляю поисковые запросы")
        result.queries = await build_queries(ctx.giga, category, city)
        yield stage("search", "Ищу в Яндексе: " + "; ".join(result.queries))
        hits = await search_all(ctx, result.queries, usage)
        if not hits:
            yield ProgressEvent(type="error", message="Поиск не вернул результатов — попробуйте другую формулировку")
        groups, result.aggregators = split_hits(hits)
        candidates = [Candidate(hits=g) for g in groups]
        yield stage(
            "sites",
            f"Нашлось {len(candidates)} сайтов поставщиков, отсеяно агрегаторов и маркетплейсов: "
            f"{len(result.aggregators)}. Открываю сайты и читаю условия",
        )

        tasks = {asyncio.create_task(process(c, ctx, i < settings.llm_domains)): c for i, c in enumerate(candidates)}
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
                supplier = build_supplier(tasks[task], ctx)
                suppliers[supplier.domain] = supplier

    ordered = [suppliers[c.domain] for c in candidates if c.domain in suppliers]
    result.aggregators += [Source(domain=s.domain, url=s.url, title=s.name) for s in ordered if s.kind == "aggregator"]
    result.suppliers = rank([s for s in ordered if s.kind != "aggregator"])
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
