from typing import Literal

from pydantic import BaseModel, Field

Mark = Literal["yes", "no", "unknown"]
Kind = Literal["producer", "distributor", "retail", "aggregator", "unknown"]
Group = Literal["match", "doubtful"]


class Fact(BaseModel):
    value: str
    quote: str
    url: str


class LegalInfo(BaseModel):
    inn: str
    name: str | None = None
    status: str | None = None
    registered: str | None = None
    okved: str | None = None
    okved_name: str | None = None
    address: str | None = None
    check_url: str


class CheckItem(BaseModel):
    key: Literal["delivers_to_city", "b2b", "documents", "min_order_known", "price_known", "legal_active"]
    label: str
    mark: Mark
    note: str | None = None


class Supplier(BaseModel):
    domain: str
    name: str
    url: str
    kind: Kind = "unknown"
    group: Group = "doubtful"
    doubt: str | None = None
    delivery_label: str = "уточнить"
    snippet: str = ""
    site_opened: bool = False
    phones: list[str] = []
    emails: list[str] = []
    address: str | None = None
    inn: str | None = None
    facts: dict[str, Fact] = {}
    legal: LegalInfo | None = None
    checklist: list[CheckItem] = []
    confirmed: int = 0
    why: str = ""
    questions: list[str] = []
    rfq: str = ""
    fetched_at: str


class Source(BaseModel):
    domain: str
    url: str
    title: str


class SearchStats(BaseModel):
    seconds: float = 0
    cost_rub: float = 0
    search_calls: int = 0
    llm_calls: int = 0
    tokens: int = 0
    candidates: int = 0
    suppliers: int = 0
    with_phone: int = 0
    rejected_quotes: int = 0


class SearchResult(BaseModel):
    id: str
    category: str
    city: str
    queries: list[str] = []
    suppliers: list[Supplier] = []
    aggregators: list[Source] = []
    stats: SearchStats = Field(default_factory=SearchStats)
    created_at: str
    is_demo: bool = False


class ProgressEvent(BaseModel):
    type: Literal["stage", "supplier", "done", "error"]
    stage: str | None = None
    message: str | None = None
    supplier: Supplier | None = None
    result: SearchResult | None = None
