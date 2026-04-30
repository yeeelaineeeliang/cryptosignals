# Crypto Signals

Live crypto trading signal dashboard — Logistic Regression model with iterative VIF feature selection, per-user paper trading, and real-time performance tracking.

**Live URLs:**
- Web: *coming soon (Vercel)*
- Worker: *coming soon (Railway)*

## Architecture

```
Coinbase Exchange API (public, no auth)
   ↓  (prices every 5s / OHLCV candles every 60s)
Python Worker on Railway (apps/worker/)
   ↓  (LR inference every 30s · paper-trade engine per user
       evaluate + optimize every 60m · refit every 6h)
Supabase (Postgres + Realtime + RLS)
   ↓  (postgres_changes subscriptions)
Next.js on Vercel (apps/web/) with Clerk auth
```

## ML pipeline

1. **Bootstrap** (`bootstrap_train.py`): one-time backfill of 30 days of candles, builds features, trains Logistic Regression with iterative VIF elimination (hard threshold configurable via `VIF_HARD_THRESHOLD`, default 10), writes `model_versions` row with `is_active=TRUE`.
2. **Live inference** (`inference.py`): reads latest candles, builds features, dot-products the active model's coefficients, writes to `predictions`. 15-minute prediction horizon (3-bar cumulative log-return).
3. **Periodic refit** (`ml/refit.py`, every 6h): same feature + training pipeline on a rolling 30-day window. Promotes to active only if new OSR² beats current model.
4. **Optimizer loop** (`ml/optimize.py` + `ml/analyze.py`, every 60m): reads recent `model_performance` rows, applies a priority-ordered rule set (signal_threshold advisory → refit_now → lookback_window escalation), logs plans to `optimization_history` with before/after metrics.

## Project layout

```
apps/
├── web/      Next.js + Tailwind + shadcn + Clerk
└── worker/   Python 3.12 + APScheduler + statsmodels
packages/
└── shared/   TypeScript types
supabase/
└── migrations/   SQL migrations (apply via Supabase MCP)
```

## Quickstart

### 1. Supabase

Create a project at supabase.com. Apply migrations in order via the Supabase MCP:

```
001_pairs_and_market_data.sql
002_models_and_predictions.sql
003_user_scoped.sql
004_rls_and_realtime.sql
005_seed.sql
```

### 2. Clerk

Create an app at clerk.com. In JWT Templates, create a template named `supabase` (HS256) signed with your Supabase project's JWT secret.

### 3. Worker (local)

```bash
cd apps/worker
uv sync                              # or: pip install -e .
cp .env.example .env                 # fill in SUPABASE_* and SERVICE_ROLE_KEY
python -m worker.ml.bootstrap_train  # ONCE: backfill + train initial model
python -m worker.main                # start the live loop
```

### 4. Web (local)

```bash
cd apps/web
pnpm install
cp .env.example .env.local      # fill in Clerk + Supabase anon key
pnpm dev
```

## Deployment

- **Worker → Railway**: connect GitHub, root directory `apps/worker`, set env vars from `.env.example`, start command `python -m worker.main`.
- **Web → Vercel**: connect GitHub, root directory `apps/web`, set env vars, framework preset Next.js.

## Disclaimer

Paper-trading simulator. Educational use only. Not investment advice. Not affiliated with Coinbase.
