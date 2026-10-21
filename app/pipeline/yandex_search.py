import base64
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.pipeline.cost import Usage

SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/search"


@dataclass
class Hit:
    url: str
    domain: str
    title: str
    snippet: str
    position: int
    query: str = ""


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if "xn--" in host:
        try:
            return host.encode("ascii").decode("idna")
        except UnicodeError:
            return host
    return host


def _text(node: ET.Element | None) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def parse_response(body: dict, query: str = "") -> list[Hit]:
    root = ET.fromstring(base64.b64decode(body["rawData"]))
    error = root.find(".//response/error")
    if error is not None:
        raise RuntimeError(f"Yandex Search: {_text(error)}")
    hits = []
    for position, doc in enumerate(root.iter("doc"), start=1):
        url = _text(doc.find("url"))
        passages = [_text(p) for p in doc.iter("passage")]
        snippet = " … ".join(p for p in passages if p) or _text(doc.find("headline"))
        hits.append(Hit(url, host_of(url), _text(doc.find("title")), snippet, position, query))
    return hits


async def search(client: httpx.AsyncClient, query: str, lr: int, usage: Usage) -> list[Hit]:
    usage.search_calls += 1
    response = await client.post(
        SEARCH_URL,
        headers={"Authorization": f"Api-Key {settings.yandex_search_api_key}"},
        json={
            "query": {"searchType": "SEARCH_TYPE_RU", "queryText": query},
            "folderId": settings.yandex_folder_id,
            "region": str(lr),
            "responseFormat": "FORMAT_XML",
            "groupSpec": {"groupMode": "GROUP_MODE_DEEP", "groupsOnPage": "20", "docsInGroup": "1"},
        },
        timeout=20,
    )
    response.raise_for_status()
    return parse_response(response.json(), query)
