import asyncio
import ssl
import time
import uuid
from pathlib import Path

import certifi
import httpx

from app.config import settings
from app.pipeline.cost import Usage

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
RUSSIAN_CA = Path(__file__).with_name("russian_trusted_ca.pem")


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(RUSSIAN_CA)
    return ctx


_token: tuple[str, float] | None = None
_token_lock = asyncio.Lock()


class GigaChat:
    def __init__(self, client: httpx.AsyncClient, usage: Usage):
        self.client = client
        self.usage = usage
        self.slots = asyncio.Semaphore(settings.gigachat_concurrency)

    @property
    def enabled(self) -> bool:
        return bool(settings.gigachat_auth_key)

    async def _token(self) -> str:
        global _token
        async with _token_lock:
            if _token and _token[1] > time.time() + 60:
                return _token[0]
            response = await self.client.post(
                OAUTH_URL,
                headers={
                    "Authorization": f"Basic {settings.gigachat_auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": settings.gigachat_scope},
            )
            response.raise_for_status()
            body = response.json()
            _token = (body["access_token"], body["expires_at"] / 1000)
            return _token[0]

    async def chat(self, messages: list[dict], max_tokens: int = 700) -> str:
        token = await self._token()
        async with self.slots:
            for attempt in range(3):
                response = await self.client.post(
                    CHAT_URL,
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "model": settings.gigachat_model,
                        "messages": messages,
                        "temperature": 0.01,
                        "max_tokens": max_tokens,
                    },
                    timeout=30,
                )
                if response.status_code != 429:
                    break
                await asyncio.sleep(1 + attempt)
        response.raise_for_status()
        body = response.json()
        self.usage.llm_calls += 1
        self.usage.tokens += body["usage"]["total_tokens"]
        return body["choices"][0]["message"]["content"]
