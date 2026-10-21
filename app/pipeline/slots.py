import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class RankedSlots:
    def __init__(self, size: int) -> None:
        self.size = size
        self.busy = 0
        self.waiting: set[int] = set()
        self.changed = asyncio.Condition()

    @asynccontextmanager
    async def take(self, rank: int) -> AsyncIterator[None]:
        async with self.changed:
            self.waiting.add(rank)
            try:
                await self.changed.wait_for(lambda: self.busy < self.size and rank == min(self.waiting))
                self.busy += 1
            finally:
                self.waiting.discard(rank)
                self.changed.notify_all()
        try:
            yield
        finally:
            async with self.changed:
                self.busy -= 1
                self.changed.notify_all()
