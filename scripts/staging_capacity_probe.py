"""Staging-safe capacity probes using only local synthetic work.

The default command never opens a network connection.  It measures bounded
async work, a semaphore-backed database-pool model, a bounded job queue, and
the bytes present in the local static site.  A local FastAPI ASGI probe is
available behind the explicit ``--local-fastapi`` flag and still does not use
the network or the application lifespan.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Iterable, Optional
from urllib.parse import urlparse


AsyncOperation = Callable[[], Awaitable[Any]]


def _positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_float(value: float, name: str) -> None:
    if not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"{name} must be a finite non-negative number")


@dataclass(frozen=True)
class CapacityConfig:
    """Conservative defaults for a repeatable local probe."""

    request_count: int = 100
    concurrency: int = 8
    synthetic_request_delay_ms: float = 2.0
    pool_size: int = 5
    pool_operations: int = 50
    synthetic_db_delay_ms: float = 10.0
    queue_capacity: int = 20
    queue_jobs: int = 40
    queue_workers: int = 1
    queue_service_ms: float = 10.0
    error_budget_fraction: float = 0.01
    fastapi_p95_budget_ms: float = 250.0
    fastapi_p99_budget_ms: float = 500.0
    db_acquire_p95_budget_ms: float = 150.0
    static_total_budget_bytes: int = 2 * 1024 * 1024
    static_largest_budget_bytes: int = 512 * 1024
    target_url: Optional[str] = None

    def __post_init__(self) -> None:
        for name in (
            "request_count",
            "concurrency",
            "pool_size",
            "pool_operations",
            "queue_capacity",
            "queue_jobs",
            "queue_workers",
            "static_total_budget_bytes",
            "static_largest_budget_bytes",
        ):
            _positive_int(getattr(self, name), name)
        for name in (
            "synthetic_request_delay_ms",
            "synthetic_db_delay_ms",
            "queue_service_ms",
            "fastapi_p95_budget_ms",
            "fastapi_p99_budget_ms",
            "db_acquire_p95_budget_ms",
        ):
            _non_negative_float(getattr(self, name), name)
        if not math.isfinite(float(self.error_budget_fraction)) or not 0 <= self.error_budget_fraction < 1:
            raise ValueError("error_budget_fraction must be in [0, 1)")
        if self.target_url is not None:
            validate_probe_target(self.target_url)


@dataclass(frozen=True)
class LatencyStats:
    total: int
    succeeded: int
    failed: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    max_in_flight: int

    @property
    def error_rate(self) -> float:
        return self.failed / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "error_rate": self.error_rate,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "max_ms": self.max_ms,
            "max_in_flight": self.max_in_flight,
        }


@dataclass(frozen=True)
class PoolProbeStats:
    request_stats: LatencyStats
    acquire_wait_p95_ms: float
    max_in_flight: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "request": self.request_stats.as_dict(),
            "acquire_wait_p95_ms": self.acquire_wait_p95_ms,
            "max_in_flight": self.max_in_flight,
        }


class SyntheticJobQueue:
    """A deliberately bounded queue model with reject-on-overflow semantics."""

    def __init__(self, capacity: int) -> None:
        _positive_int(capacity, "capacity")
        self.capacity = capacity
        self._items: Deque[Any] = deque()
        self.rejected = 0
        self.max_depth = 0

    @property
    def depth(self) -> int:
        return len(self._items)

    def enqueue(self, item: Any) -> bool:
        if self.depth >= self.capacity:
            self.rejected += 1
            return False
        self._items.append(item)
        self.max_depth = max(self.max_depth, self.depth)
        return True

    def dequeue(self) -> Optional[Any]:
        return self._items.popleft() if self._items else None


@dataclass(frozen=True)
class QueueProbeStats:
    capacity: int
    offered: int
    accepted: int
    rejected: int
    completed: int
    max_depth: int
    drain_ms: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StaticInventory:
    root: str
    file_count: int
    total_bytes: int
    largest_path: str
    largest_bytes: int
    excluded_dirs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["excluded_dirs"] = list(self.excluded_dirs)
        return data


def percentile(values: Iterable[float], percentile_value: float) -> float:
    """Return a linearly interpolated percentile without third-party deps."""

    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _latency_stats(
    total: int,
    succeeded: int,
    failed: int,
    latencies_ms: list[float],
    max_in_flight: int,
) -> LatencyStats:
    return LatencyStats(
        total=total,
        succeeded=succeeded,
        failed=failed,
        p50_ms=percentile(latencies_ms, 50),
        p95_ms=percentile(latencies_ms, 95),
        p99_ms=percentile(latencies_ms, 99),
        max_ms=max(latencies_ms, default=0.0),
        max_in_flight=max_in_flight,
    )


async def run_async_probe(
    operation: AsyncOperation,
    *,
    requests: int,
    concurrency: int,
) -> LatencyStats:
    """Run a bounded burst and report tail latency plus failures."""

    _positive_int(requests, "requests")
    _positive_int(concurrency, "concurrency")
    semaphore = asyncio.Semaphore(concurrency)
    latencies_ms: list[float] = []
    succeeded = 0
    failed = 0
    active = 0
    max_in_flight = 0

    async def one() -> None:
        nonlocal succeeded, failed, active, max_in_flight
        started = time.perf_counter()
        async with semaphore:
            active += 1
            max_in_flight = max(max_in_flight, active)
            try:
                await operation()
            except Exception:
                failed += 1
            else:
                succeeded += 1
            finally:
                active -= 1
                latencies_ms.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*(one() for _ in range(requests)))
    return _latency_stats(requests, succeeded, failed, latencies_ms, max_in_flight)


async def run_asgi_probe(app: Any, path: str, *, requests: int, concurrency: int) -> LatencyStats:
    """Probe an ASGI app in-process; no socket, DNS, or external service is used."""

    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - dependency is in requirements-dev
        raise RuntimeError("local ASGI probing requires httpx from requirements-dev.txt") from exc

    request_path = path if path.startswith("/") else f"/{path}"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://synthetic.local") as client:
        async def operation() -> None:
            response = await client.get(request_path)
            response.raise_for_status()

        return await run_async_probe(operation, requests=requests, concurrency=concurrency)


async def run_pool_probe(
    operation: AsyncOperation,
    *,
    operations: int,
    pool_size: int,
) -> PoolProbeStats:
    """Model a bounded asyncpg pool and expose acquire wait separately."""

    _positive_int(operations, "operations")
    _positive_int(pool_size, "pool_size")
    semaphore = asyncio.Semaphore(pool_size)
    latencies_ms: list[float] = []
    acquire_wait_ms: list[float] = []
    succeeded = 0
    failed = 0
    active = 0
    max_in_flight = 0

    async def one() -> None:
        nonlocal succeeded, failed, active, max_in_flight
        started = time.perf_counter()
        wait_started = time.perf_counter()
        async with semaphore:
            acquire_wait_ms.append((time.perf_counter() - wait_started) * 1000)
            active += 1
            max_in_flight = max(max_in_flight, active)
            try:
                await operation()
            except Exception:
                failed += 1
            else:
                succeeded += 1
            finally:
                active -= 1
                latencies_ms.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*(one() for _ in range(operations)))
    request_stats = _latency_stats(operations, succeeded, failed, latencies_ms, max_in_flight)
    return PoolProbeStats(
        request_stats=request_stats,
        acquire_wait_p95_ms=percentile(acquire_wait_ms, 95),
        max_in_flight=max_in_flight,
    )


async def run_queue_probe(
    *,
    capacity: int,
    jobs: int,
    workers: int,
    service_ms: float,
) -> QueueProbeStats:
    """Offer a burst before starting workers, then measure bounded drain."""

    _positive_int(capacity, "capacity")
    _positive_int(jobs, "jobs")
    _positive_int(workers, "workers")
    _non_negative_float(service_ms, "service_ms")
    queue = SyntheticJobQueue(capacity)
    for job_number in range(jobs):
        queue.enqueue(f"synthetic-job-{job_number + 1}")

    completed = 0
    started = time.perf_counter()

    async def worker() -> None:
        nonlocal completed
        while True:
            item = queue.dequeue()
            if item is None:
                return
            await asyncio.sleep(service_ms / 1000)
            completed += 1

    await asyncio.gather(*(worker() for _ in range(workers)))
    return QueueProbeStats(
        capacity=capacity,
        offered=jobs,
        accepted=jobs - queue.rejected,
        rejected=queue.rejected,
        completed=completed,
        max_depth=queue.max_depth,
        drain_ms=(time.perf_counter() - started) * 1000,
    )


def allowed_error_count(total: int, fraction: float) -> int:
    _positive_int(total, "total")
    if not math.isfinite(float(fraction)) or not 0 <= fraction < 1:
        raise ValueError("fraction must be in [0, 1)")
    return math.floor(total * fraction)


def within_error_budget(*, total: int, failed: int, fraction: float) -> bool:
    if failed < 0 or failed > total:
        raise ValueError("failed must be between zero and total")
    return failed <= allowed_error_count(total, fraction)


def inspect_static_assets(
    root: Path,
    *,
    exclude_dirs: tuple[str, ...] = ("library", ".git"),
) -> StaticInventory:
    """Inventory local static files without reading their contents into RAM."""

    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"static root is not a directory: {root}")
    files: list[tuple[str, int]] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in exclude_dirs for part in path.relative_to(root).parts):
            continue
        files.append((path.relative_to(root).as_posix(), path.stat().st_size))
    files.sort(key=lambda item: (-item[1], item[0]))
    largest_path, largest_bytes = files[0] if files else ("", 0)
    return StaticInventory(
        root=root.name,
        file_count=len(files),
        total_bytes=sum(size for _, size in files),
        largest_path=largest_path,
        largest_bytes=largest_bytes,
        excluded_dirs=exclude_dirs,
    )


def static_budget_ok(inventory: StaticInventory, *, total_bytes: int, largest_bytes: int) -> bool:
    _positive_int(total_bytes, "total_bytes")
    _positive_int(largest_bytes, "largest_bytes")
    return inventory.total_bytes <= total_bytes and inventory.largest_bytes <= largest_bytes


def validate_probe_target(url: str, *, allow_staging: bool = False) -> str:
    """Allow loopback by default and a clearly named Render staging host only."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("probe target must be an http(s) URL without credentials")
    if host in {"localhost", "127.0.0.1", "::1"}:
        return url
    if allow_staging and host.endswith(".onrender.com") and "staging" in host:
        return url
    raise ValueError("remote probes require an explicitly allowed *.onrender.com staging host")


def _budget_status(stats: LatencyStats, config: CapacityConfig) -> dict[str, Any]:
    return {
        "p95_ms": stats.p95_ms,
        "p99_ms": stats.p99_ms,
        "p95_budget_ms": config.fastapi_p95_budget_ms,
        "p99_budget_ms": config.fastapi_p99_budget_ms,
        "error_budget_fraction": config.error_budget_fraction,
        "passed": (
            stats.p95_ms <= config.fastapi_p95_budget_ms
            and stats.p99_ms <= config.fastapi_p99_budget_ms
            and within_error_budget(
                total=stats.total,
                failed=stats.failed,
                fraction=config.error_budget_fraction,
            )
        ),
    }


async def run_synthetic_baseline(web_root: Path, config: CapacityConfig = CapacityConfig()) -> dict[str, Any]:
    """Return a JSON-ready local baseline with no production or staging traffic."""

    async def synthetic_request() -> None:
        await asyncio.sleep(config.synthetic_request_delay_ms / 1000)

    async def synthetic_db_operation() -> None:
        await asyncio.sleep(config.synthetic_db_delay_ms / 1000)

    fastapi_stats = await run_async_probe(
        synthetic_request,
        requests=config.request_count,
        concurrency=config.concurrency,
    )
    pool_stats = await run_pool_probe(
        synthetic_db_operation,
        operations=config.pool_operations,
        pool_size=config.pool_size,
    )
    queue_stats = await run_queue_probe(
        capacity=config.queue_capacity,
        jobs=config.queue_jobs,
        workers=config.queue_workers,
        service_ms=config.queue_service_ms,
    )
    static_inventory = inspect_static_assets(web_root)
    static_passed = static_budget_ok(
        static_inventory,
        total_bytes=config.static_total_budget_bytes,
        largest_bytes=config.static_largest_budget_bytes,
    )
    pool_passed = (
        pool_stats.acquire_wait_p95_ms <= config.db_acquire_p95_budget_ms
        and pool_stats.request_stats.failed == 0
    )
    fastapi_budget = _budget_status(fastapi_stats, config)
    return {
        "schema_version": 1,
        "generated_at": date.today().isoformat(),
        "scope": "local_synthetic",
        "production_contacted": False,
        "staging_contacted": False,
        "config": asdict(config),
        "fastapi": {
            "probe": "synthetic_async_operation",
            "stats": fastapi_stats.as_dict(),
            "budget": fastapi_budget,
        },
        "db_pool": {
            "probe": "synthetic_semaphore_pool",
            "pool_size": config.pool_size,
            "stats": pool_stats.as_dict(),
            "acquire_wait_p95_budget_ms": config.db_acquire_p95_budget_ms,
            "passed": pool_passed,
        },
        "queue": {
            "probe": "synthetic_bounded_burst",
            "overflow_policy": "reject",
            "stats": queue_stats.as_dict(),
            "bounded": queue_stats.max_depth <= config.queue_capacity,
        },
        "static": {
            "inventory": static_inventory.as_dict(),
            "total_budget_bytes": config.static_total_budget_bytes,
            "largest_budget_bytes": config.static_largest_budget_bytes,
            "passed": static_passed,
        },
        "declared_contracts": {
            "upload_max_bytes": 20 * 1024 * 1024,
            "storage_timeout_seconds": 8,
            "geocoder_requests_per_session_per_hour": 5,
            "geocoder_timeout_default_seconds": 5,
            "geocoder_timeout_bounds_seconds": [1, 15],
            "render_plan": "free_web_service_with_possible_sleep",
            "cdn_status": "not_configured_in_render_yaml",
        },
        "overall": {
            "passed": bool(fastapi_budget["passed"] and pool_passed and static_passed),
            "verdict": "SHIP" if fastapi_budget["passed"] and pool_passed and static_passed else "FIX",
        },
        "not_assessed": [
            "staging cold-start/wake latency",
            "staging PostgreSQL connection saturation",
            "reverse-geocoder provider quota and latency",
            "static response cache headers and CDN edge hit ratio",
            "production error rate or user traffic",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--web-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "web",
        help="local static site root (default: repository web/)",
    )
    parser.add_argument("--output", type=Path, help="write the JSON baseline to this local path")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--pool-size", type=int, default=5)
    parser.add_argument("--queue-capacity", type=int, default=20)
    parser.add_argument("--queue-jobs", type=int, default=40)
    parser.add_argument(
        "--local-fastapi",
        action="store_true",
        help="also probe backend.app.main.app through an in-process ASGI transport",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="return exit code 1 when a local budget is exceeded",
    )
    return parser


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    config = CapacityConfig(
        request_count=args.requests,
        concurrency=args.concurrency,
        pool_size=args.pool_size,
        queue_capacity=args.queue_capacity,
        queue_jobs=args.queue_jobs,
    )
    result = await run_synthetic_baseline(args.web_root, config)
    if args.local_fastapi:
        repo_root = str(Path(__file__).resolve().parents[1])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from backend.app.main import app

        stats = await run_asgi_probe(
            app,
            "/health/live",
            requests=config.request_count,
            concurrency=config.concurrency,
        )
        result["fastapi"] = {
            "probe": "local_in_process_asgi:/health/live",
            "stats": stats.as_dict(),
            "budget": _budget_status(stats, config),
        }
        result["overall"]["passed"] = bool(
            result["fastapi"]["budget"]["passed"]
            and result["db_pool"]["passed"]
            and result["static"]["passed"]
        )
        result["overall"]["verdict"] = "SHIP" if result["overall"]["passed"] else "FIX"
    return result


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    result = asyncio.run(_run_cli(args))
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 1 if args.check and not result["overall"]["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
