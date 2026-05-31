"""Background task supervisor.

Runs registered periodic coroutines as asyncio tasks. Each tick re-reads its
interval and enabled flag from the runtime settings store, so the schedule can be
changed from the dashboard without a restart.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from voidswitch.core.logging import get_logger
from voidswitch.services import settings_store

log = get_logger("tasks")

TickFn = Callable[[], Awaitable[None]]


@dataclass
class PeriodicTask:
    name: str
    tick: TickFn
    interval_key: str
    enabled_key: str | None = None
    min_interval: int = 15
    last_run: dt.datetime | None = field(default=None)
    last_error: str | None = field(default=None)
    runs: int = 0


class TaskManager:
    def __init__(self) -> None:
        self._tasks: list[PeriodicTask] = []
        self._handles: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()

    def register(self, task: PeriodicTask) -> None:
        self._tasks.append(task)

    def start(self) -> None:
        self._stopping.clear()
        for task in self._tasks:
            self._handles.append(asyncio.create_task(self._run(task), name=f"task:{task.name}"))
        log.info("tasks_started", count=len(self._handles))

    async def stop(self) -> None:
        self._stopping.set()
        for handle in self._handles:
            handle.cancel()
        for handle in self._handles:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await handle
        self._handles.clear()
        log.info("tasks_stopped")

    def status(self) -> list[dict[str, object]]:
        return [
            {
                "name": t.name,
                "interval_seconds": settings_store.get_int(t.interval_key, t.min_interval),
                "enabled": settings_store.get_bool(t.enabled_key, True) if t.enabled_key else True,
                "runs": t.runs,
                "last_run": t.last_run.isoformat() if t.last_run else None,
                "last_error": t.last_error,
            }
            for t in self._tasks
        ]

    async def _run(self, task: PeriodicTask) -> None:
        # Small initial stagger so tasks don't all fire at boot.
        await self._sleep(5)
        while not self._stopping.is_set():
            enabled = settings_store.get_bool(task.enabled_key, True) if task.enabled_key else True
            if enabled:
                try:
                    await task.tick()
                    task.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    task.last_error = str(exc)
                    log.warning("task_tick_failed", task=task.name, error=str(exc))
                task.runs += 1
                task.last_run = dt.datetime.now(dt.UTC)
            interval = max(task.min_interval, settings_store.get_int(task.interval_key, 120))
            await self._sleep(interval)

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
