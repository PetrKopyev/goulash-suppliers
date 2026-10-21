from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LOCAL_ENV = Path.home() / ".config" / "goulash-suppliers" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(LOCAL_ENV, ROOT / ".env"), extra="ignore")

    yandex_search_api_key: str = ""
    yandex_folder_id: str = ""
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"
    gigachat_concurrency: int = 1
    dadata_api_key: str = ""

    live_search_enabled: bool = True
    live_search_daily_limit: int = 30
    live_search_ip_hourly_limit: int = 3
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    search_budget_seconds: float = 105

    max_domains: int = 20
    llm_domains: int = 18

    yandex_rub_per_request: float = 0.6
    gigachat_rub_per_1k_tokens: float = 0.2


settings = Settings()
