import logging
import re
from collections.abc import AsyncIterator
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import limits
from app.config import DATA, settings
from app.pipeline.regions import CITIES, find_region
from app.pipeline.run import run_search
from app.schemas import ProgressEvent, SearchResult

DEMO_DIR = DATA / "demo"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DEFAULT_CITY = "Екатеринбург"

logger = logging.getLogger("suppliers")
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
router = APIRouter()


class SearchQuery(BaseModel):
    category: str = ""
    city: str = ""


async def live_left() -> int:
    if not settings.live_search_enabled:
        return 0
    try:
        return await limits.searches_left()
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("Счётчик живых поисков недоступен")
        return 0


@cache
def _demos() -> list[tuple[str, SearchResult]]:
    return [
        (path.stem, SearchResult.model_validate_json(path.read_text(encoding="utf-8")))
        for path in sorted(DEMO_DIR.glob("*.json"))
    ]


def _demo(slug: str) -> SearchResult:
    path = DEMO_DIR / f"{slug}.json"
    if not SLUG_RE.match(slug) or not path.is_file():
        raise HTTPException(404, "Демо не найдено")
    return SearchResult.model_validate_json(path.read_text(encoding="utf-8"))


def _query(category: str, city: str) -> tuple[str, str]:
    category, region = category.strip()[:100], find_region(city)
    if not category or not region:
        raise HTTPException(400, "Нужны категория и город из списка")
    return category, region.city


async def _render(request: Request, name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(
        request, name, {"live_left": await live_left(), "live_limit": settings.live_search_daily_limit, **context}
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse("/static/favicon.svg", status_code=301)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return await _render(
        request,
        "index.html",
        demos=_demos(),
        cities=CITIES,
        default_city=DEFAULT_CITY,
        live_enabled=settings.live_search_enabled,
    )


@router.get("/demo/{slug}", response_class=HTMLResponse)
async def demo(request: Request, slug: str):
    result = _demo(slug)
    return await _render(
        request, "result.html", result=result.model_dump(mode="json"), title=f"{result.category} — {result.city}"
    )


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, category: str = "", city: str = ""):
    if not category.strip():
        return RedirectResponse("/", status_code=303)
    category, city = _query(category, city)
    return await _render(
        request,
        "search.html",
        category=category,
        city=city,
        demos=_demos(),
        live_enabled=settings.live_search_enabled,
        title=f"{category} — {city}",
    )


def _line(event: ProgressEvent) -> str:
    return event.model_dump_json() + "\n"


def _refusal(status: int, message: str) -> StreamingResponse:
    event = ProgressEvent(type="error", stage="limit", message=f"{message} Посмотрите готовые демо.")
    return StreamingResponse(iter([_line(event)]), status_code=status, media_type="application/x-ndjson")


async def _events(category: str, city: str) -> AsyncIterator[str]:
    try:
        async for event in run_search(category, city):
            yield _line(event)
    except Exception:
        logger.exception("Живой поиск прервался: %s, %s", category, city)
        yield _line(
            ProgressEvent(
                type="error", stage="internal", message="Поиск прервался. Попробуйте ещё раз или откройте демо."
            )
        )


def _same_origin(request: Request) -> bool:
    source = request.headers.get("origin") or request.headers.get("referer")
    return bool(source) and urlsplit(source).netloc == request.url.netloc


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or request.client.host


@router.post("/api/search/stream")
async def search_stream(request: Request, query: SearchQuery):
    if not _same_origin(request):
        raise HTTPException(403, "Поиск запускается со страницы сервиса")
    category, city = _query(query.category, query.city)
    if not settings.live_search_enabled:
        return _refusal(429, "Живой поиск сейчас выключен.")
    try:
        refusal = await limits.take_slot(_client_ip(request))
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("Счётчик живых поисков недоступен")
        return _refusal(503, "Не получилось проверить лимит поисков.")
    if refusal:
        return _refusal(429, refusal)
    return StreamingResponse(
        _events(category, city),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/shortlist", response_class=HTMLResponse)
async def shortlist(request: Request):
    return await _render(request, "shortlist.html", title="Шорт-лист")


@router.get("/how", response_class=HTMLResponse)
async def how(request: Request):
    return await _render(request, "how.html", title="Как это работает")


@router.get("/healthz")
async def healthz():
    return {"ok": True, "demos": len(_demos()), "live_left": await live_left()}
