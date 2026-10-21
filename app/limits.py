import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx

from app.config import settings

MSK = timezone(timedelta(hours=3))
HOUR = 3600
DAY = 24 * HOUR


class Counter(Protocol):
    async def incr(self, key: str, ttl: int) -> int: ...

    async def get(self, key: str) -> int: ...


class MemoryCounter:
    def __init__(self) -> None:
        self.counts: dict[str, tuple[int, float]] = {}

    async def incr(self, key: str, ttl: int) -> int:
        now = time.time()
        self.counts = {k: v for k, v in self.counts.items() if v[1] > now}
        count, expires = self.counts.get(key, (0, now + ttl))
        self.counts[key] = (count + 1, expires)
        return count + 1

    async def get(self, key: str) -> int:
        count, expires = self.counts.get(key, (0, 0.0))
        return count if expires > time.time() else 0


class UpstashCounter:
    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    async def send(self, path: str, commands: list[list]) -> list:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{self.url}/{path}", headers=self.headers, json=commands)
        response.raise_for_status()
        return [item["result"] for item in response.json()]

    async def incr(self, key: str, ttl: int) -> int:
        count, _ = await self.send("multi-exec", [["INCR", key], ["EXPIRE", key, ttl]])
        return count

    async def get(self, key: str) -> int:
        [count] = await self.send("pipeline", [["GET", key]])
        return int(count or 0)


def make_counter() -> Counter:
    if settings.upstash_redis_rest_url and settings.upstash_redis_rest_token:
        return UpstashCounter(settings.upstash_redis_rest_url, settings.upstash_redis_rest_token)
    return MemoryCounter()


counter = make_counter()


def day_key() -> str:
    return f"live:day:{datetime.now(MSK):%Y-%m-%d}"


def ip_key(ip: str) -> str:
    return f"live:ip:{ip}:{datetime.now(MSK):%Y-%m-%dT%H}"


async def searches_left() -> int:
    return max(settings.live_search_daily_limit - await counter.get(day_key()), 0)


async def take_slot(ip: str) -> str | None:
    if await counter.incr(ip_key(ip), HOUR) > settings.live_search_ip_hourly_limit:
        return "С вашего адреса уже было несколько поисков за этот час."
    if await counter.incr(day_key(), 2 * DAY) > settings.live_search_daily_limit:
        return "Живые поиски на сегодня закончились."
    return None
