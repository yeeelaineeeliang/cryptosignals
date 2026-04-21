"""Data ingestion jobs: prices, candles, and feature computation.

Each job is wrapped in broad try/except and logs errors but doesn't raise, so
APScheduler continues ticking even after a transient Coinbase/Supabase hiccup.
Writes go through the service-role client and bypass RLS by design.
"""
from __future__ import annotations

from supabase import Client

from .coinbase import CoinbaseClient
from .config import Settings
from .heartbeat import beat, record_error
from .logging_setup import get_logger

log = get_logger(__name__)


async def poll_prices(cb: CoinbaseClient, sb: Client, settings: Settings) -> None:
    """Poll ticker for each watched pair; UPSERT into `prices`.

    Idempotent: primary key is `symbol`, so a crash-restart just overwrites
    with the fresh tick next time.
    """
    try:
        for symbol in settings.pairs:
            tick = await cb.ticker(symbol)
            sb.table("prices").upsert(
                {
                    "symbol": symbol,
                    "price": tick.price,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "volume_24h": tick.volume_24h,
                    "fetched_at": tick.fetched_at.isoformat(),
                },
                on_conflict="symbol",
            ).execute()
        beat(sb, build_sha=settings.build_sha)
    except Exception as e:  # noqa: BLE001 -- top-level resilience on purpose
        log.exception("poll_prices_failed", error=str(e))
        try:
            record_error(sb, str(e))
        except Exception:
            log.exception("heartbeat_write_failed")


async def ingest_candles(cb: CoinbaseClient, sb: Client, settings: Settings) -> None:
    """Pull recent OHLCV bars for each watched pair; UPSERT into `candles`.

    Coinbase returns ~300 recent bars per request; we simply upsert them all.
    The PRIMARY KEY (symbol, granularity, bucket_start) makes this idempotent,
    so repeated calls silently refresh the still-open bar and re-confirm closed
    bars without duplicating rows.

    `trade_count` is left NULL for now — Coinbase's /trades endpoint doesn't
    expose a time-filtered aggregate, so reconstructing bar-level counts is
    expensive. Features that depend on it are excluded from the v1 feature set;
    see docs/VIF.md.
    """
    try:
        for symbol in settings.pairs:
            bars = await cb.candles(symbol, settings.candle_granularity)
            if not bars:
                continue
            rows = [
                {
                    "symbol": bar.symbol,
                    "bucket_start": bar.bucket_start.isoformat(),
                    "granularity": bar.granularity,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "trade_count": None,
                }
                for bar in bars
            ]
            sb.table("candles").upsert(
                rows,
                on_conflict="symbol,granularity,bucket_start",
            ).execute()
            log.debug("candles_upserted", symbol=symbol, n=len(rows))
    except Exception as e:  # noqa: BLE001
        log.exception("ingest_candles_failed", error=str(e))
