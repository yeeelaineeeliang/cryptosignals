# Phase 2 — Live OLS Trading Signal: Methodology, Architecture, Results

## What this project is — for humans, not engineers

**Crypto Signals is a live, transparent dashboard that watches Bitcoin and Ethereum prices in real time, runs a statistical model on every new bar, and tells you what the data thinks the next 5 minutes will look like — up, down, or unclear — and shows every line of math behind that opinion.** You sign up, pick which coins to watch, set a paper-trading budget, and watch a simulated portfolio grow or shrink based on the model's calls. No real money is ever at risk; nothing is locked behind a paywall; nothing is opaque.

### The problem it addresses

Anyone who has ever opened a crypto exchange app knows the feeling: green numbers, red numbers, a chart, a buy button — and zero help making the call. The two most common ways people resolve this end badly:

1. **Vibes-based trading**: scroll Twitter, see a confident take, buy or sell on instinct. Most retail traders lose money this way; the data is overwhelming.
2. **Paid black-box "AI" tools**: subscribe to something promising signals from a "proprietary algorithm." You see a buy/sell arrow but no reasoning. When the model is wrong (and it will be) you have no way to know whether to trust the next signal.

Both fail for the same reason: **the trader can't see the model's reasoning, so they can't calibrate trust.** When the signal works they over-trust; when it fails they over-distrust. Either way they're flying blind.

### What Crypto Signals does differently

Three things, in plain English:

1. **It shows you the model's actual prediction in real time** — "BTC predicted to move +2.3 bps in the next 5 minutes, signal: LONG" — updated every 30 seconds without you refreshing.
2. **It exposes every coefficient and every assumption.** The `/model` page lists exactly which 15 features the model uses, what each one's weight is, and which features it considered but rejected (and why). You can read the math the same way you'd read a recipe.
3. **It lets you paper-trade** — run a simulated portfolio for weeks against live signals, with no money at risk, to find out whether following the model would actually have made money before deciding whether to trust it with real capital.

### Who could actually use this

Three real personas:

- **A grad student who wants to learn ML in a domain they care about.** Read the `/model` page during your morning coffee, watch the coefficients drift over weeks, see how a model trained on one regime degrades when the market shifts. This is what a quant analyst does day one on the job.
- **A retail crypto holder considering becoming an active trader.** Run the paper portfolio for a month before risking real money. If the simulated equity curve is flat or down, the model has no edge and you've saved yourself a real loss. If it's up, you've learned what the model's good and bad market conditions look like.
- **An interview candidate.** Show this dashboard to a fintech / data science interviewer and walk through how it works. The system demonstrates: production ML deployment, real-time infrastructure, honest reporting of negative results, and the gap between research and live performance — all things hiring managers probe for.

### How it actually helps you

- **Calibrate trust through transparency.** When a "buy" signal fires, you can see: this came from coefficients trained on N days of history, the model has a 53% hit rate on similar setups historically, and right now the magnitude is small (so it's a weak signal, not a strong one). That's actionable. A paid black-box tool can't give you any of that.
- **Learn without losing money.** Paper trading turns "should I have bought BTC last week?" from a regret loop into a reproducible experiment. You can test ten strategies in a month for free.
- **Build a real portfolio piece.** The codebase is fully open at github.com/yeeelaineeeliang/cryptosignals. Contribute a feature, fork it for your own asset class, or use it as a reference for how to deploy a multi-service ML system.

### What it's NOT

To be clear, because regulators care: this is **not** a brokerage, **not** investment advice, **not** affiliated with Coinbase, and **not** a tool that will make you money. The disclaimer renders on every page. It is an educational tool — like a flight simulator for trading. The point is to understand the system, not to print free money.

---

## How it works — the technical pitch

> I took my 2024 OLS crypto research project — which lived as backtest-only Jupyter notebooks — and put it on rails. Phase 2 turns it into a live system: a Python worker on Railway pulls Coinbase data every minute, regenerates ~37 engineered features each tick, runs an OLS model trained with iterative VIF elimination, and writes a prediction every 30 seconds. The Next.js dashboard subscribes to predictions via Supabase Realtime and shows them as they arrive. Every coefficient and every elimination step is exposed on the `/model` page — there are no black boxes.

---

## 1. What Phase 2 actually does

Phase 1 (already shipped) was the data plumbing: poll Coinbase ticker, write `prices`, push to the frontend via Supabase Realtime, let users choose which pairs to watch. No ML.

Phase 2 adds the ML layer on top, with **three new responsibilities** for the worker and **two new surfaces** in the frontend:

| New thing | Where | Cadence |
|---|---|---|
| Candle ingestion (5-min OHLCV bars) | `worker/ingest.py::ingest_candles` | every 60s |
| Feature engineering pipeline (37 candidates) | `worker/features.py::build_features` | on demand |
| Bootstrap training (one-time, pedagogical) | `worker/ml/bootstrap_train.py` | once per refit |
| Live OLS inference | `worker/inference.py::infer_and_record` | every 30s |
| `SignalsPanel` (LONG/SHORT/HOLD card + rolling feed) | `apps/web/.../dashboard/SignalsPanel.tsx` | realtime |
| `/model` page (coefficient chart + VIF elimination trace) | `apps/web/.../app/model/page.tsx` | dynamic SSR |

The data flow stitches together:

```
Coinbase /candles ──► worker.ingest_candles ──► Supabase.candles
                                                       │
                                                       ▼
                          worker.features.build_features (≈37 features)
                                                       │
              ┌────────────────────────────────────────┤
              │                                        │
              ▼                                        ▼
    worker.ml.bootstrap_train               worker.inference.infer_and_record
    (offline, runs once)                    (live, every 30s)
              │                                        │
              ▼                                        ▼
    Supabase.model_versions                 Supabase.predictions
    (is_active = TRUE row)                            │
              │                                        │
              └────────► loaded each tick by inference │
                                                       ▼
                              postgres_changes (Supabase Realtime)
                                                       │
                                                       ▼
                           Next.js useRealtimePredictions hook
                                                       │
                                                       ▼
                           SignalCard / SignalFeed re-render
```

**Cost in production**: Railway worker $0/mo (free tier), Supabase ~50 MB after a month, Vercel hobby tier, **zero LLM tokens** in any hot path. Inference is a dot product.

---

## 2. The ML methodology — OLS + iterative VIF elimination

### Why OLS for crypto?

Two reasons that aren't "I had it lying around":

1. **VIF only makes sense for OLS.** The diagnostic this project is built around — the variance inflation factor — measures how much OLS coefficient *variance* is inflated by collinearity. For a tree-based model or a neural net, VIF is meaningless: the model doesn't care if two features carry overlapping information. So if the project's pedagogical goal is "learn VIF properly," OLS is the only fit.
2. **Linear models are the right baseline before complexity.** OLS gives you a coefficient per feature, an R², an F-statistic, and standard errors. You can read every decision the model makes. If a more complex model can't beat OLS by a clean margin, you should not deploy the complexity. Most quant desks run linear baselines for exactly this reason.

It's also dirt-cheap to serve: inference is `intercept + Σ(coefficient × standardized_feature)` — a single dot product. No GPU, no library bloat.

### What the model predicts

The target is the **log return of the next bar**:

```
target_t = log(close_{t+1} / close_t)
```

Log returns are stationary (their distribution doesn't drift across price regimes) and additive across time. A model trained on BTC at $30k and one trained at $100k can use the same coefficients because log returns mean the same thing in both regimes. The original 2024 project used `(high + low) / 2` of the next bar — a level target, which is non-stationary and inflated R² for the wrong reason. Phase 2 fixes that.

### The pipeline at a glance

```
candles ──► build_features(df)  ──► train_with_vif(features)  ──► persisted model
                                            │
                                            ├── chronological 70/15/15 split
                                            ├── z-score using train-fold stats
                                            ├── compute VIF
                                            ├── decision: drop / keep / stop
                                            ├── refit OLS
                                            └── loop until stop conditions
```

Live inference uses the *same* `build_features` function (training/serving parity), loads the persisted scaler stats and coefficients, standardizes, and dot-products.

---

## 3. The VIF deep-dive (this is what an interviewer will probe)

### What multicollinearity is

Two features carry overlapping information. For OHLCV this is structural and extreme:

- `open`, `high`, `low`, `close` are mechanically constrained: `low ≤ open, close ≤ high`.
- On low-volatility bars all four are nearly identical floats.
- `volume` and `trade_count` move together.
- `sma_5` and `sma_20` are both anchored near `close`.

### Why it hurts OLS specifically

The OLS coefficient covariance is `σ²(XᵀX)⁻¹`. If two columns of `X` are nearly linearly dependent, `XᵀX` is near-singular, so its inverse explodes. Three observable consequences:

1. **Coefficient instability** — sign flips across resamples or after one-row changes.
2. **Inflated standard errors** — t-statistics collapse toward zero; individually significant features look insignificant.
3. **Interpretability dies** — you can't say "this feature matters" because the coefficient is unstable.

The forecast itself is still accurate *in the same regime*, but you lose the things that make OLS valuable in the first place.

### What VIF measures

For predictor `j`, regress `xⱼ` on every other predictor; call the auxiliary R² `Rⱼ²`. Then:

```
VIF_j = 1 / (1 - Rⱼ²)
```

| VIF | Rⱼ² | Read as |
|---|---|---|
| 1 | 0% | perfectly orthogonal — every coefficient stands alone |
| 5 | 80% | yellow flag |
| 10 | 90% | red flag — conventional drop threshold |
| ∞ | 100% | perfect collinearity (linearly dependent column) |

In code (`worker/ml/train.py:88`):

```python
def _compute_vif(x: pd.DataFrame) -> dict[str, float]:
    with_const = sm.add_constant(x, has_constant="add")
    vals = with_const.values
    return {
        col: float(variance_inflation_factor(vals, i + 1))
        for i, col in enumerate(x.columns)
    }
```

The `+1` matters — it skips the intercept, which always has a high "VIF" by construction and isn't a feature.

### The elimination loop

`train_with_vif` is a deterministic procedure (`worker/ml/train.py:158`):

```
1. fit standardizer on TRAIN fold only; transform val and test with those stats
2. compute VIF on standardized X
3. fit OLS; record train R², val OSR², val hit rate, val RMSE
4. decide:
     if max VIF > 10        → drop unconditionally
     elif 5 < max VIF ≤ 10  → drop iff val OSR² doesn't degrade by > 0.005
     else                   → STOP
5. also stop if removing any further feature would cost > 0.01 OSR², or fewer than 3 features remain
6. emit: selected_features, coefficients, scaler stats, vif_trace, metrics
```

The "soft zone" is where engineering judgment lives. Pure VIF would drop anything > 5. Pure OOS performance would never drop anything that helps. The two-rule decision tree balances them: be aggressive when collinearity is severe, conservative when it's mild and the feature is doing real work.

### What gets recorded

Each iteration appends a `vif_trace` entry:

```json
{
  "iter": 8,
  "dropped": "f_open",
  "vif_max": 11905.25,
  "r2": 0.1872,
  "osr2": -0.7206,
  "hit_rate": 0.4889,
  "rmse": 0.000743,
  "remaining_features": [...]
}
```

This trace is the artifact the `/model` page renders. The pedagogy is *visible*, not buried.

---

## 4. Feature engineering — 37 candidates across 9 groups

The pool is intentionally large so VIF has real work to do. The original 2024 project started with 9 features and converged to 2 — that's so few that VIF barely demonstrated anything. Here we start at 37 and the elimination tells a story.

| Group | Features | Why include |
|---|---|---|
| A. Raw OHLCV | open, high, low, close, volume | baseline; lets VIF demonstrate the pathology of level features |
| B. Log transforms | log1p(volume), log(close) | tame heavy-tailed distributions |
| C. Returns / bar shape | ret, logret, range_pct, body_pct, wick_upper_pct, wick_lower_pct | stationary; scale-invariant across price regimes |
| D. MA / ratios | sma_5, sma_20, sma_50, ema_12, ema_26, close/sma_20, sma_5/sma_20 | trend-following effects in crypto are real intraday |
| E. Volatility | vol_20, vol_50, atr14_proxy, vol_20/vol_50 | high-vol regimes have different return distributions |
| F. Momentum / oscillators | rsi_14, momentum_10, momentum_50, macd_hist | mean-reversion at extremes; trend persistence |
| G. Volume flow | vol_z_20, volume_change | volume surges often precede directional moves |
| H. Calendar | hour_sin, hour_cos, dow_sin, dow_cos | crypto trades 24/7 but liquidity is diurnal |
| I. Lags | logret_lag_1, logret_lag_3, logret_lag_12 | AR(p) effects in short-horizon returns |

**Why sin/cos for calendar instead of one-hot**: 24 dummies for hour bloats the feature matrix; sin/cos preserves cyclic structure (hour 23 is close to hour 0), uses only 2 columns per period, and avoids an arbitrary reference category.

**What we deliberately dropped**: `count`-dependent features (`count_z_20`, `volume_per_trade`). Coinbase's REST API doesn't expose bar-level trade counts cheaply, and reconstructing them by paging `/trades` would be I/O-expensive without much signal payoff. Documented in `docs/VIF.md` and `worker/features.py`.

### The look-ahead invariant

This is the #1 financial-ML interview question. We enforce it everywhere:

- All rolling windows are **trailing-only**: `close.rolling(20)`, never `close.rolling(20, center=True)`.
- Standardization fits on **training data only**: `_standardize` returns scaler stats that the val/test folds use unchanged.
- The target is the *only* forward-looking column: `log(close.shift(-1) / close)`. The last row's target is NaN and is dropped before training.
- No feature uses bar `t+1` data to predict bar `t+1`'s return.

Look-ahead bias is invisible in the metrics — a leaky model has fantastic OSR² in training and gets destroyed live. The structure of `build_features` is the defense.

---

## 5. The training procedure end-to-end

Run it locally with:

```bash
cd apps/worker
uv run python -m worker.ml.bootstrap_train
```

What it does, top to bottom:

1. **Load candles** from Supabase (paginated, all available history)
2. **Build features** — drops the warmup rows (first ~50 bars where 50-bar rolling stats are NaN) and the last row (no target)
3. **Chronological 70/15/15 split** — never shuffle. Splits by time index.
4. **Standardize on train** — fit z-score scaler on train only; transform val/test with those stats. Saves the means and stds.
5. **Iterate VIF elimination** — print each iteration: dropped feature, max VIF after, train R², val OSR², val hit rate, val RMSE.
6. **Refit on train+val** with the surviving features.
7. **Score on test** — touch the held-out tail exactly once. Report final OSR², hit rate, RMSE.
8. **Persist** — INSERT a new `model_versions` row with `is_active = TRUE`, demote any previous active model atomically.
9. **Write artifacts** — `artifacts/vif_trace__btc_usd.csv`, `summary__btc_usd.md`, `coefficients__btc_usd.csv` for the writeup.

The `/model` page reads `vif_trace` JSONB straight from `model_versions` and renders the elimination as a dual-axis line chart.

---

## 6. Live inference

```python
# worker/inference.py
async def infer_and_record(sb, settings):
    for symbol in settings.pairs:
        model = load_active(sb, symbol, granularity, "v1")  # SELECT
        candles = _fetch_recent_candles(sb, symbol, granularity, 120)  # SELECT
        feats = build_features(candles)                                # same fn as training
        latest = feats.iloc[-1]
        prediction = intercept + sum(
            coefs[f] * (latest[f] - means[f]) / stds[f]
            for f in selected_features
        )
        signal = "LONG" if prediction > 1e-5 else "SHORT" if prediction < -1e-5 else "HOLD"
        sb.table("predictions").insert({...}).execute()                # INSERT
```

Three notes:

- **Training/serving parity** comes from sharing one `build_features` function. If we fork the feature engineering into a different language for inference, parity drift is the most likely production bug. We took the simpler path.
- **Model cache is implicit** — we re-`SELECT model_versions WHERE is_active` every tick. It's one row, ~5 KB, takes <50ms. Pre-optimizing this would be a mistake before there's a real bottleneck.
- **No paper trading yet** — Phase 2 just persists predictions. The trading engine that translates signals to per-user positions is Phase 3.

The Supabase Realtime publication on the `predictions` table delivers each new INSERT to every subscribed client. The Next.js hook `useRealtimePredictions` keeps the latest 50 in memory and re-renders the SignalCard / SignalFeed.

---

## 7. How to read the dashboard

### `/dashboard`

- **Top: PriceTicker grid** — one card per watched pair. Price flashes green/red on each update. The "Updated 3s ago" stamp is the worker heartbeat lag.
- **Bottom-left: SignalCard** — current model prediction per pair. The chip color is the signal:
  - **LONG** (green) — model predicts up by more than the HOLD threshold (≈0.1 bp)
  - **SHORT** (red) — model predicts down
  - **HOLD** (gray) — magnitude too small to act on
  - The number underneath is the predicted next-bar log return in basis points.
- **Bottom-right: SignalFeed** — rolling list of the last 20 predictions (filtered by your watched pairs). Watch it grow without refresh — that's Realtime working.

### `/model`

This is the page interviewers will ask about.

- **Per-pair card** — one for BTC-USD, one for ETH-USD.
- **Metric strip**:
  - `features kept` — 15 for BTC, 18 for ETH (started at 37)
  - `train R²` — fraction of in-sample variance the model explains
  - `test OSR²` — out-of-sample R² vs the train-mean baseline. **Negative means worse than predicting the mean** — a real, honest signal that our model isn't yet beating the baseline at this data scale.
  - `test hit rate` — direction accuracy. 0.50 = coin flip.
  - `test RMSE` — root mean squared error in log-return space. 0.0007 ≈ 7 bps typical residual.
- **Coefficient bar chart** — final surviving features sorted by coefficient. Red bars = negative impact on next-bar return; blue = positive. The biggest bars are the model's strongest convictions.
- **VIF elimination dual-axis chart** — orange line is `log10(max VIF)` collapsing from millions (perfect collinearity at the start) to ~3 (well under the 5 threshold) over 22 iterations. Blue line is val OSR² oscillating along the way. Hover any iteration to see which feature was dropped.
- **Dropped-by-VIF chip cloud** — the elimination history as a wall of feature names. You can read the story: `f_dow_sin` first (perfectly collinear with `f_dow_cos` because the first few days of data are all weekdays, making one of them constant), then `f_high`, `f_low`, `f_close`, `f_open` (all collinear with each other), then `f_ema_12`, `f_ema_26`, `f_sma_5`, `f_sma_20` (all dominated by `close`), then the soft-zone judgment calls.

---

## 8. Results from the first run

Honest numbers, no spin.

| Pair | Features kept | Train R² | Test OSR² | Test hit rate | Test RMSE |
|---|---|---|---|---|---|
| BTC-USD | 15 / 37 | 0.071 | **−0.076** | **0.533** | 0.000738 |
| ETH-USD | 18 / 37 | 0.107 | **−0.109** | **0.533** | 0.001068 |

What this means in plain English:

- **OSR² is negative** for both pairs. The model is *worse than* simply predicting the train-set mean log return on held-out data. With only ~300 bars of 5-minute history at training time (about 25 hours), this is not surprising — every quant text says you need months to years of bars at this granularity to fit a model that beats the mean.
- **Hit rate is 53.3%** — slightly above coin-flip. With only 45 test bars, the standard error on a hit-rate estimate is ~7%, so 53.3% is statistically indistinguishable from 50%. It is *not* evidence the model has alpha. It is also not evidence it doesn't.
- **The architecture works regardless of the alpha.** The end-to-end pipeline — backfill, feature, train, serve, persist, render — is what Phase 2 is demonstrating. The numbers will improve as Railway accumulates more candles overnight (we'll have 2-3 days of training data by morning).

The honest framing for interviews: *"This model isn't yet beating naive baselines because of the data scale, and the OSR² confirms it. The valuable artifact isn't the alpha — it's the system around the model: training/serving parity, VIF elimination as a first-class deliverable, and the gap between backtest and live, which I'll be measuring as more data accumulates."*

---

## 9. Decision register — what we picked, what we considered

### Worker stack: Python on Railway (vs Node Edge Function)

**Picked**: Python 3.12 + APScheduler + uv + Dockerfile, deployed on Railway.
**Considered**: Supabase Edge Function (Deno/TypeScript) — which is what the NBA scoreboard reference uses.
**Why Python won**: HW4 spec literally requires "background worker deployed on Railway." Edge Functions don't satisfy it. Beyond that, `statsmodels.OLS` and `variance_inflation_factor` are native and battle-tested in Python; porting VIF to TypeScript would be a long detour for no benefit.

### Build system: Dockerfile (vs nixpacks default)

**Picked**: Custom Dockerfile + `uv sync --frozen --no-dev`.
**Considered**: Railway's nixpacks default Python builder.
**Why Dockerfile won**: Three failed Railway deploys taught me nixpacks copies `pyproject.toml` *before* the source, then runs `pip install .`, which fails because setuptools can't find the `worker/` package directory. Dockerfile gives precise control over copy order. `uv sync` is also 5x faster than pip and uses the lockfile for reproducibility.

### Inference deployment: dot-product in worker (vs separate ML service)

**Picked**: Inference happens inside the same Python worker.
**Considered**: A separate FastAPI ML service that the worker calls; serving the model from a TypeScript Edge Function with coefficients exported to JSON.
**Why same worker**: OLS inference is a 15-element dot product. The cost of standing up a separate service is hundreds of times the cost of the inference itself. Same-worker also means no network hop, no RPC schema, no staleness between model registry and serving.

### Feature persistence: NOT writing a `features` table (vs persisting features per bar)

**Picked**: Compute features on demand at training time and inference time.
**Considered**: A `compute_features` job that writes a `features` row per bar.
**Why on-demand won**: Storage cost (37 floats × 350 bars per day per pair × 2 pairs ≈ 26k floats per day, all redundant with `candles`). More importantly: stale-feature risk. If we change the feature set, persisted rows become incorrect for live inference. Computing fresh from `candles` is the correct invariant. The `features` table in the schema stays for future work.

### Target: log-returns (vs the original midpoint target)

**Picked**: `log(close_{t+1} / close_t)`.
**Considered**: `(high_{t+1} + low_{t+1}) / 2` — the original 2024 target.
**Why log-returns won**: Stationary, scale-invariant, additive. The midpoint is a level: a model trained at $30k BTC has different coefficients than one trained at $100k. Log returns mean the same thing in both regimes, which is why every quant paper uses them.

### Train/val/test split: chronological 70/15/15 (vs random k-fold)

**Picked**: Strict time-ordered split.
**Considered**: Sklearn's `train_test_split` with `shuffle=True` (the wrong way) or k-fold.
**Why chronological won**: Random shuffling lets bar 9:00am end up in train while bar 10:00am ends up in test — the model sees the future to predict the past. K-fold has the same problem. This is the single most common ML mistake in finance, and the one an interviewer will probe first.

### VIF threshold: hybrid (drop>10 unconditional, 5–10 conditional on OSR²)

**Picked**: Two-rule decision tree.
**Considered**: Single threshold (drop > 5 always, or drop > 10 always).
**Why hybrid won**: Pure VIF > 5 is too aggressive — it drops features that have mild collinearity but are doing real predictive work. Pure VIF > 10 is too lax — it leaves features in that destabilize coefficients. The hybrid encodes the engineering judgment: "be aggressive when collinearity is severe; let OOS performance arbitrate when it's mild."

### Realtime delivery: Supabase postgres_changes (vs Server-Sent Events / a websocket service)

**Picked**: Supabase Realtime piggybacks on Postgres logical replication.
**Considered**: Custom websocket layer; SSE; client polling.
**Why Supabase Realtime won**: Free, works through HTTPS, native to our DB, no extra infra. The frontend's `useRealtimePredictions` hook is 35 lines.

### Frontend charts: Recharts (vs D3, vs ECharts, vs Chart.js)

**Picked**: Recharts.
**Considered**: D3 (too low-level for a 2-week build), ECharts (heavier bundle, more features than needed), Chart.js (less React-friendly).
**Why Recharts won**: React-first, well-typed, bundle <50KB, dual-axis charts native. The VIF trace chart is 70 lines.

---

## 10. Tool selection — quick reference

| Tool | Used for | Why |
|---|---|---|
| **statsmodels** | OLS + VIF | Has the canonical `variance_inflation_factor`; produces a complete summary; battle-tested |
| **pandas** | Feature engineering | Time-indexed rolling windows are first-class |
| **APScheduler (AsyncIOScheduler)** | Worker job scheduling | Async-native; coalescing prevents overlapping runs |
| **httpx + tenacity** | Coinbase HTTP | Async, easy retry/backoff |
| **uv** | Python packaging | 5–10x faster than pip; lockfile-driven; replaces venv too |
| **structlog** | JSON logs | Railway captures stdout; structured logs are greppable |
| **Supabase Realtime** | Push to frontend | Free, no infra, native to our DB |
| **Recharts** | Coefficient + VIF charts | React-native, dual-axis support |
| **Clerk** | Auth | NBA reference uses it; JWT template integrates with Supabase RLS in 1 step |
| **Railway** | Worker hosting | Long-running process support; nixpacks/Docker support; free tier |
| **Vercel** | Web hosting | Next.js-native; generous free tier |

---

## 11. What's next (Phase 3 and beyond)

The architecture is designed for these to drop in cleanly:

- **`evaluate_models` job** (every 60 min) — backfill `realized_logret` and `hit` on prediction rows where the next bar has closed. Compute rolling hit rate + confusion matrix → `model_performance`. **This is what produces the backtest-vs-live divergence number** — the metric every quant interviewer asks about.
- **Refit cycle** (every 6h) — same code path as bootstrap on a rolling 30-day window. Inserts a new `model_versions` row, demotes the old one. Lets us watch coefficients drift as crypto regime shifts.
- **Paper trading engine** (Phase 3) — translate signals into per-user position changes. `paper_trades` and `portfolios` tables already exist. Uses user prefs (threshold, position size %).
- **Equity curve UI** (Phase 3) — Recharts area chart of portfolio equity over time per user.
- **Model performance UI** — confusion matrix component, hit rate sparkline, **backtest-vs-live Sharpe panel** (the single highest-signal artifact for fintech interviews).

---

## 12. Interview-defense quick reference

When asked these questions, here are the answers:

- *"Why OLS?"* → "VIF is meaningful for OLS specifically — it measures coefficient variance inflation. For a tree or NN, VIF doesn't apply. The pedagogical goal is VIF mastery, so OLS is the only fit. Plus inference is a dot product — no GPU needed."
- *"What does negative OSR² mean?"* → "Worse than predicting the train-set mean. Honest result for ~300 bars of training data. The valuable artifact is the system around the model, not yet the alpha."
- *"Why these features?"* → "Stationary derivatives instead of raw OHLCV levels. Coefficients keep meaning across price regimes. Started at 37 to give VIF real work; the elimination story is on `/model`."
- *"Why threshold 5 and 10?"* → "Conservative two-rule. >10 drops unconditionally because that level of collinearity destabilizes coefficients. 5–10 is the soft zone — drop only if OOS performance doesn't degrade by more than 0.005 OSR²."
- *"Why time-based split?"* → "Random shuffle leaks the future. K-fold on time series measures interpolation, not forecasting. Chronological 70/15/15, touch test exactly once at the end."
- *"Where can the model fail?"* → "Regime shift — if vol structure changes mid-window, coefficients become stale. Mitigated by 6h refits on a rolling window. Also limited training data right now; OSR² will improve as candles accumulate."
- *"What's the gap between backtest and live?"* → "I'm measuring it as we speak. Predictions get backfilled with realized returns by the `evaluate_models` job — gap will surface on the `/model` page within a week. That gap is the most honest credibility metric in quant; if I can show it transparently, it's worth more than overstated alpha."
- *"How would you scale this to 1000 pairs?"* → "Three changes: (1) Coinbase rate limit becomes the bottleneck — switch from polling per pair to websocket subscription. (2) Inference is still a dot product per pair, fine on one worker. (3) Realtime channel count would explode — collapse to one channel with a pair filter applied client-side."
- *"What's the LLM angle?"* → "There isn't one in the hot path, by design. Feature flag `ENABLE_LLM_FEATURES` is wired in for a future user-triggered 'explain this prediction' feature, with per-user quotas and result caching. The lesson from my prior project (CareerOS) was that LLM agents on a cron bankrupt you; here LLMs only fire on user intent."

---

## 13. Repository pointers

If an interviewer wants to read code, here's the order I'd send them:

1. **`docs/VIF.md`** — the conceptual framing
2. **`apps/worker/worker/features.py`** — feature engineering (the canonical pipeline)
3. **`apps/worker/worker/ml/train.py`** — the elimination loop
4. **`apps/worker/worker/ml/bootstrap_train.py`** — the pedagogical training script
5. **`apps/worker/worker/inference.py`** — live serving
6. **`apps/web/src/app/model/page.tsx`** + **`components/model/`** — the visualization layer
7. **`CLAUDE.md`** — full architecture overview
8. **`PHASE2_REPORT.md`** — this document

---

*Last updated: end of Phase 2 build.*
