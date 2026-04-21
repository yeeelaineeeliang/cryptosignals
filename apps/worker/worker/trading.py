"""Paper-trade engine.

For each new prediction, for every user whose watched_pairs includes the
signal's symbol and whose signal_threshold is satisfied, execute a simulated
trade:

  LONG  → BUY  `position_size_pct` of current cash
  SHORT → SELL the entire existing long position (no short-selling unless
          user.short_enabled is True)

All DB writes use the service-role key so RLS is bypassed — the worker is
the trusted system actor that writes on behalf of users.

Fee model: 5 bps (0.05 %) of notional, debited from cash on buys, from
proceeds on sells. Matches Coinbase Advanced maker fees in round numbers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from supabase import Client

from .config import Settings
from .logging_setup import get_logger

log = get_logger(__name__)

FEE_BPS = 5  # 0.05 % of notional
STARTING_CAPITAL = 10_000.0


async def execute_paper_trades(
    sb: Client,
    prediction: dict,
    settings: Settings,
) -> None:
    """Execute paper trades for every eligible user given a fresh prediction."""
    if not settings.enable_paper_trading:
        return

    symbol: str = prediction["symbol"]
    signal: str = prediction["signal"]
    predicted_logret: float = float(prediction["predicted_logret"])
    price: float = float(prediction["current_price"])
    prediction_id: int = int(prediction["id"])

    if signal == "HOLD":
        return

    try:
        prefs_res = sb.table("user_prefs").select("*").execute()
        for pref in (prefs_res.data or []):
            if symbol not in (pref.get("watched_pairs") or []):
                continue
            threshold = float(pref.get("signal_threshold") or 0.002)
            if abs(predicted_logret) < threshold:
                continue
            if signal == "SHORT" and not pref.get("short_enabled", False):
                continue

            _trade_for_user(sb, pref, symbol, signal, price, prediction_id)

    except Exception as e:  # noqa: BLE001
        log.exception("paper_trade_failed", symbol=symbol, error=str(e))


def _trade_for_user(
    sb: Client,
    pref: dict,
    symbol: str,
    signal: str,
    price: float,
    prediction_id: int,
) -> None:
    user_id: str = pref["user_id"]

    # Fetch or initialize portfolio
    res = (
        sb.table("portfolios")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:
        sb.table("portfolios").insert({
            "user_id": user_id,
            "starting_capital": STARTING_CAPITAL,
            "cash_usd": STARTING_CAPITAL,
            "positions": {},
            "equity_usd": STARTING_CAPITAL,
        }).execute()
        portfolio: dict = {
            "cash_usd": STARTING_CAPITAL,
            "positions": {},
        }
    else:
        portfolio = res.data

    cash = float(portfolio["cash_usd"])
    positions: dict = dict(portfolio.get("positions") or {})
    pos = positions.get(symbol, {"qty": 0.0, "avg_cost": price})
    qty_held = float(pos.get("qty", 0.0))
    position_size_pct = float(pref.get("position_size_pct") or 0.10)

    if signal == "LONG":
        trade_usd = cash * position_size_pct
        if trade_usd < 1.0:
            return
        fee = trade_usd * FEE_BPS / 10_000
        qty_bought = (trade_usd - fee) / price
        new_cash = cash - trade_usd

        # Weighted-average into existing position
        old_notional = qty_held * float(pos.get("avg_cost", price))
        new_qty = qty_held + qty_bought
        new_avg_cost = (old_notional + qty_bought * price) / new_qty if new_qty else price
        positions[symbol] = {"qty": new_qty, "avg_cost": new_avg_cost}

        _insert_trade(sb, user_id, symbol, "BUY", qty_bought, price,
                      trade_usd - fee, fee, prediction_id)
        _update_portfolio(sb, user_id, new_cash, positions)
        log.info("paper_trade_executed", user_id=user_id, symbol=symbol, side="BUY",
                 qty=round(qty_bought, 6), price=price, notional=round(trade_usd - fee, 2))

    elif signal == "SHORT":
        if qty_held <= 0:
            return  # nothing to close
        notional = qty_held * price
        fee = notional * FEE_BPS / 10_000
        proceeds = notional - fee
        new_cash = cash + proceeds
        positions.pop(symbol, None)

        _insert_trade(sb, user_id, symbol, "SELL", qty_held, price,
                      notional - fee, fee, prediction_id)
        _update_portfolio(sb, user_id, new_cash, positions)
        log.info("paper_trade_executed", user_id=user_id, symbol=symbol, side="SELL",
                 qty=round(qty_held, 6), price=price, notional=round(notional - fee, 2))


def _mark_to_market(sb: Client, cash_usd: float, positions: dict) -> float:
    """Recompute equity using latest prices from the prices table."""
    equity = cash_usd
    if not positions:
        return equity
    symbols = list(positions.keys())
    prices_res = (
        sb.table("prices")
        .select("symbol,price")
        .in_("symbol", symbols)
        .execute()
    )
    price_map = {row["symbol"]: float(row["price"]) for row in (prices_res.data or [])}
    for sym, pos in positions.items():
        p = price_map.get(sym, float(pos.get("avg_cost", 0.0)))
        equity += float(pos["qty"]) * p
    return equity


def _insert_trade(
    sb: Client,
    user_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    notional_usd: float,
    fee_usd: float,
    prediction_id: int,
) -> None:
    sb.table("paper_trades").insert({
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "notional_usd": notional_usd,
        "fee_usd": fee_usd,
        "prediction_id": prediction_id,
        "reason": "signal",
    }).execute()


def _update_portfolio(sb: Client, user_id: str, cash_usd: float, positions: dict) -> None:
    equity = _mark_to_market(sb, cash_usd, positions)
    sb.table("portfolios").update({
        "cash_usd": cash_usd,
        "positions": positions,
        "equity_usd": equity,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()
