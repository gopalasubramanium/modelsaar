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
from collections.abc import Callable
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
    # Memory budget (pools only). holders counts active+uncertain reservations per deployment so
    # a deployment's weights are counted once however many requests it serves concurrently.
    memory_gb: float | None = None
    memory_margin_gb: float = 0.0
    unknown_memory_policy: str = "allow"
    holders: dict[str, int] = field(default_factory=dict)
    # Weights assumed resident after a dispatch completed: a request slot is released when the
    # response ends, but the model's weights stay loaded in the runtime. The assumption is kept
    # (conservatively counted against the budget) until a residency observation reconciles it or
    # the pool's assumed_residency_ttl_s expires. dep_id -> monotonic time of the last completion.
    assumed_resident: dict[str, float] = field(default_factory=dict)
    assumed_residency_ttl_s: float | None = None

    @property
    def used(self) -> int:
        return self.active + self.uncertain

    def hold(self, dep_id: str) -> None:
        self.holders[dep_id] = self.holders.get(dep_id, 0) + 1

    def unhold(self, dep_id: str, assume_resident: bool = True) -> None:
        n = self.holders.get(dep_id, 0) - 1
        if n <= 0:
            self.holders.pop(dep_id, None)
            if self.memory_gb is not None and assume_resident:
                # The slot is free; the weights are not. Keep them counted until reconciled.
                self.assumed_resident[dep_id] = time.monotonic()
        else:
            self.holders[dep_id] = n

    def assumed(self) -> set[str]:
        """Deployments whose weights are assumed resident (TTL applied)."""
        if self.assumed_residency_ttl_s is not None:
            cutoff = time.monotonic() - self.assumed_residency_ttl_s
            for k in [k for k, t in self.assumed_resident.items() if t < cutoff]:
                self.assumed_resident.pop(k, None)
        return set(self.assumed_resident)


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

    async def release(self, *, submitted: bool = True) -> None:
        """Free the slot. ``submitted=False`` means no work ever reached the runtime (the connection
        was refused before the request was sent), so nothing could have loaded: the weights are not
        assumed resident. Any outcome where loading or computation may have started keeps the
        conservative assumption."""
        if self._released:
            return
        self._released = True
        for s in self._slots:
            async with s.cond:
                s.active = max(0, s.active - 1)
                s.unhold(self.dep_id, assume_resident=submitted)
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
                    s.unhold(self.dep_id)  # the hold counted the weights until now
                    s.cond.notify_all()

        task = asyncio.create_task(_expire())
        self._adm._tasks.add(task)
        task.add_done_callback(self._adm._tasks.discard)


class Admission:
    def __init__(self, cfg: AdmissionConfig, pools: list[ResourcePool], backends: list[BackendConfig]) -> None:
        self.cfg = cfg
        self._pools: dict[str, _Slot] = {
            p.id: _Slot(
                p.max_concurrent,
                p.max_queue,
                p.queue_timeout_s,
                memory_gb=p.memory_gb,
                memory_margin_gb=p.memory_margin_gb,
                unknown_memory_policy=p.unknown_memory_policy,
                assumed_residency_ttl_s=p.assumed_residency_ttl_s,
            )
            for p in pools
        }
        # Set by the router: deployments sharing a pool (for resident-weight accounting).
        self.pool_members: Callable[[str], list[Deployment]] = lambda pool_id: []
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
        return self.memory_blocker(dep)

    # ---------------------------------------------------------------- #
    # Memory budget
    # ---------------------------------------------------------------- #
    def memory_view(self, dep: Deployment) -> dict | None:
        """What the pool budget would look like with ``dep`` dispatched. None when the pool has no
        memory budget. Estimates are weights-only (provenance on each deployment); KV/workspace
        and runtime overhead are covered only by memory_margin_gb. Unified memory is counted once
        per pool; a deployment is counted once however many requests it serves."""
        pool_id = dep.resource_pool
        s = self._pools.get(pool_id) if pool_id else None
        if s is None or s.memory_gb is None:
            return None
        members = {d.id: d for d in self.pool_members(pool_id)}
        members.setdefault(dep.id, dep)
        # Counted once each: active/uncertain holders, the candidate, members observed loaded, and
        # members assumed resident since their last completion (not yet reconciled by an observation).
        counted: set[str] = set(s.holders) | {dep.id} | {d.id for d in members.values() if d.loaded} | (s.assumed() & set(members))
        total = 0.0
        unknown: list[str] = []
        for did in sorted(counted):
            d = members.get(did)
            est = d.memory_gb_estimate if d else None
            if est is None:
                unknown.append(did)
            else:
                total += est
        return {
            "pool": pool_id,
            "memory_gb": s.memory_gb,
            "margin_gb": s.memory_margin_gb,
            "counted": sorted(counted),
            "assumed_resident": sorted(s.assumed() & set(members)),
            "estimated_gb": round(total, 2),
            "unknown": unknown,
            "policy_unknown": s.unknown_memory_policy,
            # With unknown_memory_policy=reject an unknown member anywhere in the count blocks admission:
            # a resident or reserved model of unknown size makes the whole budget unverifiable.
            "fits": total + s.memory_margin_gb <= s.memory_gb and not (unknown and s.unknown_memory_policy == "reject"),
        }

    def memory_blocker(self, dep: Deployment) -> str | None:
        v = self.memory_view(dep)
        if v is None:
            return None
        if dep.memory_gb_estimate is None and v["policy_unknown"] == "reject":
            return (
                f"memory estimate unknown for {dep.id} and pool {v['pool']} has unknown_memory_policy=reject "
                f"(declare memory_gb_estimate under backends[].models or deployments[] overrides)"
            )
        if v["unknown"] and v["policy_unknown"] == "reject":
            return (
                f"memory estimate unknown for {', '.join(v['unknown'])} already counted in pool {v['pool']} "
                f"(resident or reserved) and the pool has unknown_memory_policy=reject; the budget cannot be verified "
                "(declare memory_gb_estimate for every member or unload the unknown model)"
            )
        if not v["fits"]:
            return (
                f"memory budget: pool {v['pool']} memory_gb={v['memory_gb']} < resident+reserved estimate "
                f"{v['estimated_gb']} GB + margin {v['margin_gb']} GB (counted: {', '.join(v['counted'])}; "
                f"{dep.id} estimate {dep.memory_gb_estimate} GB from {dep.memory_estimate_provenance or 'unknown'}"
                f"{'; unknown: ' + ', '.join(v['unknown']) if v['unknown'] else ''})"
            )
        return None

    def reconcile_residency(self, deployments: list[Deployment], observed_backends: set[str]) -> None:
        """Apply a residency observation. For every backend in ``observed_backends`` the registry's
        ``loaded`` flags are the truth, so assumptions about its deployments are dropped (a model the
        runtime reports loaded is counted through ``loaded``; one it reports unloaded is no longer
        counted). Deployments of backends that cannot report residency keep their assumption."""
        by_id = {d.id: d for d in deployments}
        for s in self._pools.values():
            for did in list(s.assumed_resident):
                d = by_id.get(did)
                if d is None or d.backend_id in observed_backends:
                    s.assumed_resident.pop(did, None)

    async def acquire(self, dep: Deployment, timeout: float | None = None) -> Reservation:
        slots = self._slots_for(dep)
        acquired: list[_Slot] = []
        try:
            for s in slots:
                t = timeout if timeout is not None else s.queue_timeout_s
                await self._acquire_one(s, t)
                acquired.append(s)
            # Atomic with the slot: the memory check runs after the pool slot is held, so two
            # concurrent admissions cannot both pass against the same free budget.
            why = self.memory_blocker(dep)
            if why:
                raise AdmissionRejected(why, status=503)
            for s in acquired:
                s.hold(dep.id)
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
            if k.startswith("pool:") and s.memory_gb is not None:
                members = {d.id: d for d in self.pool_members(k[5:])}
                reserved = sum((members[d].memory_gb_estimate or 0.0) for d in s.holders if d in members)
                out[k].update(
                    {
                        "memory_gb": s.memory_gb,
                        "memory_margin_gb": s.memory_margin_gb,
                        "memory_reserved_gb": round(reserved, 2),
                        "memory_holders": sorted(s.holders),
                        "memory_assumed_resident": sorted(s.assumed() & set(members)),
                        "unknown_memory_policy": s.unknown_memory_policy,
                    }
                )
        return out


class AdmissionRejected(Exception):
    def __init__(self, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
