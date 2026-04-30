# Crypto Signals Worker

Python 3.12 long-running process deployed on Railway. Polls Coinbase, upserts into Supabase, runs Logistic Regression inference, simulates per-user paper trades, and auto-optimizes model parameters.

## Local development

```bash
# install (uv is fastest; pip also works)
uv sync                   # or: pip install -e .

# env
cp .env.example .env
# fill in SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY from the Supabase dashboard

# one-time bootstrap: backfill 30 days of candles, train initial model
python -m worker.ml.bootstrap_train

# live loop
python -m worker.main
```

## What the scheduler does

| Job | Interval | Action |
|---|---|---|
| `poll_prices` | 5s | Coinbase ticker → `prices` UPSERT + heartbeat |
| `ingest_candles` | 60s | Coinbase candles → `candles` UPSERT |
| `infer_and_record` | 30s | LR inference → `predictions` + per-user paper trades |
| `evaluate_then_optimize` | 60m | Backfill realized returns + metrics → `model_performance`; rule-based optimizer → `optimization_history` |
| `refit_models` | 6h | Logistic Regression + VIF prune on rolling 30-day window → new `model_versions` row if OSR² improves |

## Key env vars

| Variable | Default | Description |
|---|---|---|
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | — | Service-role key (bypasses RLS) |
| `WATCHED_PAIRS` | `BTC-USD,ETH-USD` | Comma-separated pairs |
| `CANDLE_GRANULARITY` | `300` | Bar size in seconds |
| `VIF_HARD_THRESHOLD` | `10` | Hard VIF cutoff for feature elimination |
| `SOFT_OSR2_TOLERANCE` | `0.01` | Max val-accuracy cost allowed for soft-zone VIF drops |
| `ROLLING_TRAIN_DAYS` | `30` | Lookback window for periodic refits |
| `ENABLE_PAPER_TRADING` | `true` | Toggle paper-trade engine |

## Deployment (Railway)

1. Push repo to GitHub.
2. railway.app → New Project → Deploy from GitHub.
3. Root directory: `apps/worker`.
4. Variables tab → paste every key from `.env.example`.
5. Deploy. Watch logs for the first `worker_starting` line.

## Files

```
worker/
├── main.py              entrypoint — APScheduler setup
├── config.py            env → typed Settings (pydantic-settings)
├── logging_setup.py     structured JSON logs via structlog
├── supabase_client.py   service-role client factory
├── http_client.py       httpx + tenacity retry client
├── coinbase.py          ticker / candles REST wrappers
├── scheduler.py         APScheduler job registration helper
├── heartbeat.py         worker_heartbeats writer
├── ingest.py            poll_prices + ingest_candles jobs
├── features.py          feature engineering (37 features, v1 set)
├── inference.py         load active model, predict, write predictions
├── trading.py           paper-trade engine (BUY/SELL simulation)
└── ml/
    ├── train.py             Logistic Regression + iterative VIF elimination
    ├── refit.py             refit_models job (rolling window)
    ├── evaluate.py          evaluate_then_optimize — scoring half
    ├── optimize.py          evaluate_then_optimize — action half
    ├── analyze.py           rule-based optimizer: reads perf, returns OptimizationPlan
    ├── persistence.py       model_versions read/write helpers
    ├── metrics.py           hit_rate, confusion matrix, Sharpe, max drawdown
    └── bootstrap_train.py   one-time cold-start training script
```
