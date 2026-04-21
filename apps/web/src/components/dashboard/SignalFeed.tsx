"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatLogretPct, formatRelativeTime, signalCopy } from "@/lib/format";
import type { Prediction } from "@crypto-signals/shared";

interface SignalFeedProps {
  predictions: Prediction[];
  watchedSymbols: Set<string>;
}

const TONE = {
  up: "text-green-400",
  down: "text-red-400",
  flat: "text-white/50",
} as const;

export function SignalFeed({ predictions, watchedSymbols }: SignalFeedProps) {
  const filtered = predictions.filter((p) => watchedSymbols.has(p.symbol));
  const show = filtered.slice(0, 15);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-white">Recent calls</CardTitle>
      </CardHeader>
      <CardContent>
        {show.length === 0 ? (
          <div className="py-6 text-center text-sm text-white/40">waiting…</div>
        ) : (
          <div className="divide-y divide-white/5">
            {show.map((p) => {
              const copy = signalCopy(p.signal);
              return (
                <div
                  key={p.id}
                  className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-4 py-3 text-sm"
                >
                  <span className="text-white/40 font-mono text-xs w-12">
                    {formatRelativeTime(p.created_at)}
                  </span>
                  <span className="font-semibold text-white">{p.symbol}</span>
                  <span className={`font-mono ${TONE[copy.tone]}`}>
                    {formatLogretPct(p.predicted_logret)}
                  </span>
                  <span className={`font-bold ${TONE[copy.tone]}`}>
                    {copy.arrow} {copy.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
