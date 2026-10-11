"""One LISTEN connection per API process, fanning wake-ups out to SSE subscribers.

Notifications only say "run X has new events"; subscribers always read the events from the
table. A lost notification (listener reconnecting, server restart) therefore delays an event
until the subscriber's next timed re-check but can never drop or reorder it.
"""

import asyncio
import contextlib
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable

import psycopg

from querycure.core.logging import get_logger
from querycure.events.types import NOTIFY_CHANNEL

Connect = Callable[[], Awaitable[psycopg.AsyncConnection]]

RECONNECT_DELAY_SECONDS = 1.0

log = get_logger(__name__)


class Subscription:
    def __init__(self, hub: "EventHub", run_id: uuid.UUID) -> None:
        self._hub = hub
        self.run_id = run_id
        self._event = asyncio.Event()

    def wake(self) -> None:
        self._event.set()

    async def wait(self, seconds: float) -> bool:
        """True when woken by a notification, False after `seconds` without one."""
        try:
            async with asyncio.timeout(seconds):
                await self._event.wait()
        except TimeoutError:
            return False
        self._event.clear()
        return True

    def close(self) -> None:
        self._hub.unsubscribe(self)


class EventHub:
    def __init__(self, connect: Connect) -> None:
        self._connect = connect
        self._subscribers: dict[uuid.UUID, set[Subscription]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None
        self.listening = asyncio.Event()

    def subscribe(self, run_id: uuid.UUID) -> Subscription:
        if self._task is None:
            self._task = asyncio.create_task(self._listen())
        sub = Subscription(self, run_id)
        self._subscribers[run_id].add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        subs = self._subscribers.get(sub.run_id)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                del self._subscribers[sub.run_id]

    def _wake(self, run_id: uuid.UUID | None) -> None:
        targets = (
            [s for subs in self._subscribers.values() for s in subs]
            if run_id is None
            else list(self._subscribers.get(run_id, ()))
        )
        for sub in targets:
            sub.wake()

    async def _listen(self) -> None:
        while True:
            try:
                conn = await self._connect()
                try:
                    await conn.execute(f"LISTEN {NOTIFY_CHANNEL}")
                    self.listening.set()
                    # Anything committed while we were not listening is picked up on re-read.
                    self._wake(None)
                    async for note in conn.notifies():
                        try:
                            self._wake(uuid.UUID(note.payload))
                        except ValueError:
                            log.warning("event_notify_bad_payload")
                finally:
                    self.listening.clear()
                    await conn.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("event_listener_disconnected", exc_info=True)
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
