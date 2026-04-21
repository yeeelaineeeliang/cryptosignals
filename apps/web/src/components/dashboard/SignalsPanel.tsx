"use client";

import { useMemo } from "react";
import { SignalCard } from "./SignalCard";
import { SignalFeed } from "./SignalFeed";
import { useRealtimePredictions } from "@/hooks/use-realtime-predictions";
import { useUserPrefs } from "@/hooks/use-user-prefs";
import type { Pair, Prediction } from "@crypto-signals/shared";

interface SignalsPanelProps {
  pairs: Pair[];
  initialPredictions: Prediction[];
}

/**
 * Client-side composition of SignalCard (latest per pair) + SignalFeed
 * (rolling list). Uses the realtime predictions stream plus the user's
 * watched-pair preferences to filter noise.
 */
export function SignalsPanel({ pairs, initialPredictions }: SignalsPanelProps) {
  const predictions = useRealtimePredictions(initialPredictions);
  const { prefs } = useUserPrefs();

  const watchedSet = useMemo(
    () => new Set(prefs?.watched_pairs ?? pairs.map((p) => p.symbol)),
    [pairs, prefs?.watched_pairs]
  );
  const watchedPairs = useMemo(
    () => pairs.filter((p) => watchedSet.has(p.symbol)),
    [pairs, watchedSet]
  );

  const latestBySymbol = useMemo(() => {
    const m = new Map<string, Prediction>();
    for (const pred of predictions) {
      if (!m.has(pred.symbol)) m.set(pred.symbol, pred);
    }
    return m;
  }, [predictions]);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
        {watchedPairs.map((pair) => (
          <SignalCard
            key={pair.symbol}
            pair={pair}
            latest={latestBySymbol.get(pair.symbol)}
          />
        ))}
      </div>
      <SignalFeed predictions={predictions} watchedSymbols={watchedSet} />
    </div>
  );
}
