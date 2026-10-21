from datetime import UTC, date, datetime

import httpx

from app.config import settings
from app.schemas import LegalInfo

DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"


def check_url(inn: str) -> str:
    return f"https://www.rusprofile.ru/search?query={inn}"


def parse_party(inn: str, body: dict) -> LegalInfo:
    if not body.get("suggestions"):
        return LegalInfo(inn=inn, check_url=check_url(inn))
    item = body["suggestions"][0]
    data = item["data"]
    state = data.get("state") or {}
    registered = state.get("registration_date")
    main_okved = next((o for o in data.get("okveds") or [] if o.get("main")), {})
    return LegalInfo(
        inn=inn,
        name=(data.get("name") or {}).get("short_with_opf") or item.get("value"),
        status=state.get("status"),
        registered=datetime.fromtimestamp(registered / 1000, UTC).date().isoformat() if registered else None,
        okved=data.get("okved"),
        okved_name=main_okved.get("name"),
        address=(data.get("address") or {}).get("value"),
        check_url=check_url(inn),
    )


async def lookup(client: httpx.AsyncClient, inn: str) -> LegalInfo:
    if not settings.dadata_api_key:
        return LegalInfo(inn=inn, check_url=check_url(inn))
    response = await client.post(
        DADATA_URL,
        headers={"Authorization": f"Token {settings.dadata_api_key}"},
        json={"query": inn, "count": 1},
        timeout=8,
    )
    response.raise_for_status()
    return parse_party(inn, response.json())


def age_years(legal: LegalInfo, today: date | None = None) -> float | None:
    if not legal.registered:
        return None
    return ((today or date.today()) - date.fromisoformat(legal.registered)).days / 365.25
