# Crypto Signals — Architecture

Live crypto trading signal dashboard. Productionizes a 2024 OLS research model by putting it on rails: Python worker polls Coinbase, Logistic Regression inference every 30s, paper-trading simulator per user, Supabase Realtime pushes updates to a Next.js frontend without refresh.

## Data flow

```
Coinbase Exchange (public REST, no auth)
    │  /products/{pair}/ticker   → 5-second price polls
    │  /products/{pair}/candles  → 60-second OHLCV ingest
    │  /products/{pair}/trades   → trade count per bar (reconstructs the old
    │                              project's `count` feature)
    ▼
Python Worker (apps/worker/, Railway)
    - APScheduler AsyncIOScheduler runs six jobs:
        poll_prices (5s), ingest_candles (60s), compute_features (60s),
        infer_and_trade (30s), evaluate_models (1h), refit_models (6h)
    - Idempotent upserts; httpx + tenacity backoff; structlog JSON logs
    ▼
Supabase (Postgres + Realtime + RLS)
    Market data (public read):
        pairs, prices, candles, features, predictions, model_versions,
        model_performance, worker_heartbeats
    User-scoped (RLS on auth.jwt()->>'sub' = user_id):
        user_prefs, portfolios, paper_trades
    Realtime publication (supabase_realtime):
        prices, predictions, paper_trades, portfolios, worker_heartbeats
    ▼
Next.js 16 Frontend (apps/web/, Vercel)
    - Clerk for auth; JWT template `supabase` signs with Supabase's JWT secret
    - useSupabaseClient injects Clerk token as Bearer on every fetch
    - Realtime hooks: use-realtime-prices, -predictions, -trades
    - Pages: / (landing), /dashboard, /portfolio, /model, /settings,
             /sign-in, /sign-up
```

## Why Python (not an Edge Function or Node worker)

The HW4 spec requires "background worker deployed on Railway". The NBA scoreboard reference uses a Supabase Edge Function — elegant but does NOT satisfy this requirement. We run Python on Railway because:

1. `statsmodels.OLS` + `variance_inflation_factor` are native; the bootstrap training script is the pedagogical artifact for this project.
2. `supabase-py` is mature.
3. Railway nixpacks detects `pyproject.toml` automatically.
4. Inference is a dot product anyway — no runtime advantage to TypeScript.

## ML pipeline

Feature engineering happens at two places, intentionally using the same `build_features` function:

1. **One-time bootstrap** (`apps/worker/worker/ml/bootstrap_train.py`): backfills 30 days of candles via Coinbase, computes features, runs Logistic Regression + iterative VIF elimination (drop max-VIF feature when VIF > 10; drop when 5 < VIF ≤ 10 only if val accuracy doesn't degrade by more than `soft_osr2_tolerance`), writes a `model_versions` row with `is_active = TRUE`, emits training artifacts (`artifacts/vif_trace.csv`, coefficient plot, summary report).

2. **Live inference** (`worker/inference.py`): reads latest features row, standardizes with scaler_means/stds from the active model, dot-products coefficients, writes to `predictions`.

3. **Periodic refit** (`worker/ml/refit.py`, every 6h): same code path as bootstrap, but on a rolling 30-day window. Writes a new `model_versions` row; promotes to active only if OSR² > current model's OSR². `refit_complete` log emits the full selected feature list, the VIF drop sequence, and a diff vs the prior active model's features.

The `vif_trace` JSONB column carries the full iteration history — this is what the `/model` page visualizes so the pedagogy is front-facing, not hidden infra.

## VIF tuning

`SOFT_OSR2_TOLERANCE` controls how aggressively the VIF loop drops features in the soft zone (5 < VIF ≤ 10). The default is `0.01` (configured via `Settings.soft_osr2_tolerance`, overridable by env var).

**Why 0.01, not the original 0.005:**

During live operation, `feature_drift_pct` was hitting the 99× clamp on every refit. Investigation (Apr 2026) found the root cause: soft-zone boundary features (`f_momentum_10` VIF≈8, `f_rsi_14` VIF≈5–6) were flipping in and out of the selected feature set across 30-day windows. When a feature flips out, its coefficient signal redistributes onto correlated survivors, producing large apparent drift even when the model's predictive structure is unchanged.

At 0.005, a drop was allowed if it cost <0.5pp val accuracy — a threshold narrow enough that window noise routinely crossed it. At 0.01, a drop requires <1pp cost, which stabilized `f_momentum_10` (consistently dropped on both BTC and ETH) while correctly preserving `f_rsi_14` on BTC (where it contributes genuine signal) and dropping it on ETH (where it is genuinely collinear). ETH dropping `f_rsi_14` and BTC keeping it is expected asset-specific behavior, not instability.

**Hard-zone drops (VIF > 10) are unaffected** — raw price/level features (`f_open`, `f_high`, `f_low`, `f_close`, `f_sma_5`, etc.) always have VIF in the millions and are always eliminated regardless of this setting.

## Auth model

- Web browser → Clerk session → `getToken({ template: "supabase" })` → HS256 JWT
- JWT signed with the Supabase project's JWT secret → Supabase auto-verifies
- RLS policies use `auth.jwt() ->> 'sub'` (Clerk user ID) for user_prefs, portfolios, paper_trades
- The Python worker uses `SUPABASE_SERVICE_ROLE_KEY` and bypasses RLS — it is the trusted system actor that writes on behalf of users

## Deployment

- **Supabase**: project created; apply migrations 001–005 via Supabase MCP; verify Realtime publication; run `get_advisors(type='security')`.
- **Clerk**: create app; add JWT Template `supabase` (HS256) signed with Supabase JWT secret.
- **Railway** (worker): root directory `apps/worker`, nixpacks builds Python 3.12, start command `python -m worker.main`. Paste env vars from `.env.example`.
- **Vercel** (web): root directory `apps/web`, Next.js preset, paste `NEXT_PUBLIC_*` + `CLERK_SECRET_KEY` env vars.

## LLM policy

Zero LLM calls in any hot path. Inference is a dot product. `ENABLE_LLM_FEATURES=false` gates any future CareerOS bridge (user-triggered "explain this prediction" with per-user quotas + caching). Cost discipline is architectural, not aspirational — the lesson from the prior CareerOS project was that agent loops running on a cron bankrupt you.

## Roadmap — next priorities

### 1b. Extend prediction horizon to 15 minutes
Why: 5-minute log returns are near-white-noise. 15-minute returns have more autocorrelation and are more predictable with technical features.

Files: `apps/worker/worker/features.py`, `evaluate.py`
Changes needed:
- `target_logret = log(close.shift(-3) / close)` instead of `shift(-1)`
- `evaluate.py` scoring: match prediction to candle 3 bars ahead
- paper trade engine: hold duration becomes 15 min not 5 min

Expected gain: +3–5pp hit rate, fewer trades, higher precision

### Known optimizer limitations
- BTC cooldown watches `refit_now` specifically — after `lookback_window` cycles it falls back to `refit_now`. Future fix: make cooldown change_type-agnostic.
- ETH model quality problem is separate from optimizer logic — 40.8% win rate suggests feature set isn't capturing ETH signal.

## Disclaimer

Paper-trading simulator. Educational use only. Not investment advice. Footer renders on every page.
