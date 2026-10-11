"""Admission control: bounded queues, shared-resource concurrency, reservations,
uncertain-occupancy holds, and per-backend circuit breakers.

Feasibility checks are non-reserving. A reservation is acquired atomically
(backend slot + pool slot) immediately before dispatch and released when the
upstream call completes. If completion cannot be confirmed (client
disconnected mid-stream), the reservation is kept as *uncertain* for a bounded
hold period, because an HTTP disconnect does not prove the backend stopped.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from ..config import AdmissionConfig, BackendConfig, ResourcePool
from ..registry import Deployment


@dataclass
class _Slot:
    limit: int
    max_queue: int
    queue_timeout_s: float
    active: int = 0
    waiting: int = 0
    uncertain: int = 0
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    @property
    def used(self) -> int:
        return self.active + self.uncertain


@dataclass
class Circuit:
    threshold: int
    cooldown_s: float
    failures: int = 0
    opened_at: float | None = None

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at >= self.cooldown_s:
            return False  # half-open: allow a probe request
        return True

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.time()

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None


class Reservation:
    def __init__(self, admission: Admission, slots: list[_Slot], dep_id: str) -> None:
        self._adm = admission
        self._slots = slots
        self.dep_id = dep_id
        self._released = False
        self.acquired_at = time.monotonic()

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        for s in self._slots:
            async with s.cond:
                s.active = max(0, s.active - 1)
                s.cond.notify_all()

    async def mark_uncertain(self) -> None:
        """Convert this reservation into an uncertain-occupancy hold for a bounded time."""
        if self._released:
            return
        self._released = True
        hold = self._adm.cfg.uncertain_hold_s
        for s in self._slots:
            async with s.cond:
                s.active = max(0, s.active - 1)
                s.uncertain += 1
        self._adm.uncertain_events += 1

        async def _expire() -> None:
            await asyncio.sleep(hold)
            for s in self._slots:
                async with s.cond:
                    s.uncertain = max(0, s.uncertain - 1)
                    s.cond.notify_all()

        task = asyncio.create_task(_expire())
        self._adm._tasks.add(task)
        task.add_done_callback(self._adm._tasks.discard)


class Admission:
    def __init__(self, cfg: AdmissionConfig, pools: list[ResourcePool], backends: list[BackendConfig]) -> None:
        self.cfg = cfg
        self._pools: dict[str, _Slot] = {
            p.id: _Slot(p.max_concurrent, p.max_queue, p.queue_timeout_s) for p in pools
        }
        self._backends: dict[str, _Slot] = {
            b.id: _Slot(b.max_concurrent, cfg.max_queue, cfg.queue_timeout_s) for b in backends
        }
        self._circuits: dict[str, Circuit] = {
            b.id: Circuit(b.circuit_failure_threshold, b.circuit_cooldown_s) for b in backends
        }
        self._tasks: set[asyncio.Task] = set()
        self.uncertain_events = 0
        self.rejected_queue_full = 0
        self.queue_timeouts = 0

    def _slots_for(self, dep: Deployment) -> list[_Slot]:
        slots: list[_Slot] = []
        b = self._backends.get(dep.backend_id)
        if b:
            slots.append(b)
        if dep.resource_pool and dep.resource_pool in self._pools:
            slots.append(self._pools[dep.resource_pool])
        return slots

    def circuit(self, backend_id: str) -> Circuit | None:
        return self._circuits.get(backend_id)

    def feasibility(self, dep: Deployment) -> str | None:
        """Non-reserving check; returns a blocker string or None."""
        c = self._circuits.get(dep.backend_id)
        if c and c.is_open():
            return f"circuit open for backend {dep.backend_id} after {c.failures} consecutive failures"
        for s in self._slots_for(dep):
            if s.used >= s.limit and s.waiting >= s.max_queue:
                return "admission queue full for this deployment's resource pool/backend"
        return None

    async def acquire(self, dep: Deployment, timeout: float | None = None) -> Reservation:
        slots = self._slots_for(dep)
        acquired: list[_Slot] = []
        try:
            for s in slots:
                t = timeout if timeout is not None else s.queue_timeout_s
                await self._acquire_one(s, t)
                acquired.append(s)
        except BaseException:
            for s in acquired:
                async with s.cond:
                    s.active = max(0, s.active - 1)
                    s.cond.notify_all()
            raise
        return Reservation(self, acquired, dep.id)

    async def _acquire_one(self, s: _Slot, timeout: float) -> None:
        async with s.cond:
            if s.used >= s.limit:
                if s.waiting >= s.max_queue:
                    self.rejected_queue_full += 1
                    raise AdmissionRejected("admission queue full", status=429)
                s.waiting += 1
                try:
                    deadline = time.monotonic() + timeout
                    while s.used >= s.limit:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            self.queue_timeouts += 1
                            raise AdmissionRejected("admission queue timeout", status=503)
                        try:
                            await asyncio.wait_for(s.cond.wait(), timeout=remaining)
                        except asyncio.TimeoutError:
                            self.queue_timeouts += 1
                            raise AdmissionRejected("admission queue timeout", status=503)
                finally:
                    s.waiting -= 1
            s.active += 1

    def stats(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for k, s in {**{f"backend:{k}": v for k, v in self._backends.items()}, **{f"pool:{k}": v for k, v in self._pools.items()}}.items():
            out[k] = {"limit": s.limit, "active": s.active, "waiting": s.waiting, "uncertain": s.uncertain}
        return out


class AdmissionRejected(Exception):
    def __init__(self, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
