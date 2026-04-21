# Demo Video Script — Crypto Signals, HW4

Total: ~2:30 at conversational pace. Read this once, then talk naturally. The HW4 spec explicitly says "Informal — no slides, no script," so use this as a rough map, not a teleprompter.

---

## 🎬 Opening (10s)

> "Hey, Elaine here. For HW4 I built Crypto Signals — a live paper-trading dashboard that polls Coinbase every 5 seconds and pushes updates to every user's browser in real-time. Let me walk through it."

---

## 🖥️ Show it live (60s)

> "Here's the landing page." *[show cryptosignals-gray.vercel.app/]*
>
> "I'll sign up with Google — new user, never seen this site before." *[click Sign Up → Google → land on dashboard]*
>
> "Here's the dashboard. Two cards — BTC and ETH. Watch the prices. Every 5 seconds they refresh without me doing anything. See the cards flash green when the price ticks up? That's Supabase Realtime pushing changes through a WebSocket."
>
> "Now let me show personalization. I'll go to Settings…" *[click Settings]* "I have both BTC and ETH watched. Let me toggle BTC off" *[toggle]* "and back to the dashboard — BTC is gone, just ETH now. That preference is saved to my user account. Every user gets their own view."

---

## 🧩 Architecture (45s)

> "Three services talking to each other. Let me show you the backend."
>
> *[Open Railway logs]* "This is Railway running a Python worker. Every 5 seconds it polls Coinbase, computes a heartbeat, and upserts prices into Supabase. I can see it right here."
>
> *[Open Supabase table editor]* "And here's the Supabase side. The `prices` table is being written to in real-time by the worker. The frontend subscribes to this table via `postgres_changes` — that's how the dashboard stays live."
>
> *[Open GitHub repo briefly]* "It's a pnpm monorepo — `apps/web` is Next.js on Vercel, `apps/worker` is Python 3.12 on Railway, with shared TypeScript types. Full Row-Level Security on user preferences so no one can read anyone else's data."

---

## 💥 What broke + Phase 2 (30s)

> "One thing I'm proud of — the story behind this project. I had a 2024 research project training OLS regressions on BTC and ETH with VIF feature selection. It was a notebook with backtest results. For this class I'm productionizing it."
>
> "Phase 1 — what you just saw — is the data infrastructure. Phase 2 adds the ML layer: candle ingestion, feature engineering from scratch, live predictions, and paper trading. That's what I'm building next."
>
> "Biggest debugging moment: Railway's nixpacks kept running `pip install .` which failed because setuptools couldn't find my `worker` package directory before the source was copied. Took four commits and a Dockerfile to fully resolve."

---

## 🎁 Wrap (5s)

> "Repo's at github.com/yeeelaineeeliang/cryptosignals. Live URL is cryptosignals-gray.vercel.app. Thanks!"

---

## Filming tips

- Record with Loom or macOS `Cmd+Shift+5` → Screen Recording with mic.
- Browser at 1280×720, text zoomed to 110% so it's legible.
- Don't re-record if you stumble — spec says informal.
- Export as MP4, drop in Slack `#tuesday-night` or `#wednesday-night`.
- Remember to grab the Slack message link (hover → 3-dot menu → Copy link) for the submission.
