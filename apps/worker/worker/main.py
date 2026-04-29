"""Worker entrypoint.

Phase 1: polls Coinbase ticker every N seconds → UPSERT `prices` → update heartbeat.
Later phases add candles, feature engineering, OLS inference, paper trading,
model refit, and performance evaluation.
"""
from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from .coinbase import CoinbaseClient
from .config import Settings
from .http_client import make_http_client
from .inference import infer_and_record
from .ingest import ingest_candles, poll_prices
from .logging_setup import get_logger, setup_logging
from .ml.evaluate import evaluate_predictions
from .ml.optimize import analyze_and_optimize
from .ml.refit import refit_models
from .scheduler import add_interval
from .supabase_client import make_supabase


async def run() -> None:
    load_dotenv()
    settings = Settings()
    setup_logging(settings.log_level)
    log = get_logger(__name__)

    log.info(
        "worker_starting",
        pairs=settings.pairs,
        granularity=settings.candle_granularity,
        build_sha=settings.build_sha or None,
    )

    sb = make_supabase(settings)
    http = make_http_client()
    cb = CoinbaseClient(http, settings.coinbase_base_url)

    scheduler = AsyncIOScheduler()

    async def _poll_prices() -> None:
        await poll_prices(cb, sb, settings)

    async def _ingest_candles() -> None:
        await ingest_candles(cb, sb, settings)

    async def _infer_and_record() -> None:
        await infer_and_record(sb, settings)

    async def _refit_models() -> None:
        await refit_models(sb, settings)

    async def _evaluate_then_optimize() -> None:
        # analyze_and_optimize must read the model_performance row that
        # evaluate_predictions just wrote.  Running them as a single chained
        # job guarantees ordering — registering them as two independent
        # 60-minute jobs causes analyze_and_optimize to misfire on every cycle
        # because evaluate's synchronous supabase-py calls block the asyncio
        # event loop past the 30s misfire_grace_time window.
        await evaluate_predictions(sb, settings)
        await analyze_and_optimize(sb, settings)

    add_interval(
        scheduler,
        "poll_prices",
        _poll_prices,
        seconds=settings.poll_interval_seconds,
    )
    add_interval(
        scheduler,
        "ingest_candles",
        _ingest_candles,
        seconds=settings.candle_interval_seconds,
    )
    add_interval(
        scheduler,
        "infer_and_record",
        _infer_and_record,
        seconds=settings.inference_interval_seconds,
    )
    add_interval(
        scheduler,
        "evaluate_then_optimize",
        _evaluate_then_optimize,
        minutes=settings.evaluate_interval_minutes,
    )
    add_interval(
        scheduler,
        "refit_models",
        _refit_models,
        hours=settings.refit_interval_hours,
    )

    scheduler.start()
    log.info("scheduler_started", jobs=[j.id for j in scheduler.get_jobs()])

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    try:
        await stop.wait()
    finally:
        log.info("worker_stopping")
        scheduler.shutdown(wait=False)
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(run())
