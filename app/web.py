import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import DATA, settings
from app.pipeline.regions import CITIES, find_region
from app.schemas import ProgressEvent, SearchResult

DEMO_DIR = DATA / "demo"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MSK = timezone(timedelta(hours=3))

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
router = APIRouter()

_live_counter: dict[str, int] = {}


def _today() -> str:
    return datetime.now(MSK).date().isoformat()


def live_left() -> int:
    if not settings.live_search_enabled:
        return 0
    return max(settings.live_search_daily_limit - _live_counter.get(_today(), 0), 0)


def _take_live_slot() -> bool:
    if live_left() <= 0:
        return False
    day = _today()
    count = _live_counter.get(day, 0) + 1
    _live_counter.clear()
    _live_counter[day] = count
    return True


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


def _render(request: Request, name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"live_left": live_left(), "live_limit": settings.live_search_daily_limit, **context})


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _render(request, "index.html", demos=_demos(), cities=CITIES, live_enabled=settings.live_search_enabled)


@router.get("/demo/{slug}", response_class=HTMLResponse)
def demo(request: Request, slug: str):
    result = _demo(slug)
    return _render(request, "result.html", result=result.model_dump(mode="json"), title=f"{result.category} — {result.city}")


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, category: str = "", city: str = ""):
    category, city = _query(category, city)
    return _render(
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


async def _events(category: str, city: str) -> AsyncIterator[str]:
    from app.pipeline.run import run_search

    try:
        async for event in run_search(category, city):
            yield _line(event)
    except Exception:
        yield _line(ProgressEvent(type="error", stage="internal", message="Поиск прервался. Попробуйте ещё раз или откройте демо."))


@router.get("/api/search/stream")
def search_stream(category: str = "", city: str = ""):
    category, city = _query(category, city)
    if not _take_live_slot():
        message = "Живой поиск сейчас выключен." if not settings.live_search_enabled else "Живые поиски на сегодня закончились."
        event = ProgressEvent(type="error", stage="limit", message=message + " Посмотрите готовые демо.")
        return StreamingResponse(iter([_line(event)]), status_code=429, media_type="application/x-ndjson")
    return StreamingResponse(
        _events(category, city),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/shortlist", response_class=HTMLResponse)
def shortlist(request: Request):
    return _render(request, "shortlist.html", title="Шорт-лист")


@router.get("/how", response_class=HTMLResponse)
def how(request: Request):
    return _render(request, "how.html", title="Как это работает")


@router.get("/healthz")
def healthz():
    return {"ok": True, "demos": len(list(DEMO_DIR.glob("*.json"))), "live_left": live_left()}
