from dataclasses import dataclass

from app.config import settings


@dataclass
class Usage:
    search_calls: int = 0
    llm_calls: int = 0
    tokens: int = 0

    @property
    def cost_rub(self) -> float:
        search = self.search_calls * settings.yandex_rub_per_request
        llm = self.tokens / 1000 * settings.gigachat_rub_per_1k_tokens
        return round(search + llm, 2)
