from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles

from starlette.exceptions import HTTPException

from app.web import router, templates

app = FastAPI(title="Поставщики", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")


@app.exception_handler(HTTPException)
async def not_found_page(request: Request, exc: HTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return templates.TemplateResponse(request, "404.html", {"title": "Страница не найдена"}, status_code=404)
    return await http_exception_handler(request, exc)
