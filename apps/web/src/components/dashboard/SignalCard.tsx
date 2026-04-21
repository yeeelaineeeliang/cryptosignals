"use client";

import { Card, CardContent } from "@/components/ui/card";
import {
  formatDollarImpact,
  formatLogretPct,
  formatRelativeTime,
  signalCopy,
} from "@/lib/format";
import type { Pair, Prediction } from "@crypto-signals/shared";

interface SignalCardProps {
  pair: Pair;
  latest: Prediction | undefined;
}

const NOTIONAL = 10_000; // $10k hypothetical position — easy to scale mentally

const BG = {
  up: "bg-green-500/10 border-green-500/30",
  down: "bg-red-500/10 border-red-500/30",
  flat: "bg-white/5 border-white/10",
} as const;

const TEXT = {
  up: "text-green-400",
  down: "text-red-400",
  flat: "text-white/60",
} as const;

export function SignalCard({ pair, latest }: SignalCardProps) {
  const copy = signalCopy(latest?.signal);

  return (
    <Card className={`border ${BG[copy.tone]}`}>
      <CardContent className="py-5">
        <div className="flex items-baseline justify-between mb-3">
          <span className="text-base font-semibold text-white">{pair.display_name}</span>
          <span className={`text-lg font-bold ${TEXT[copy.tone]}`}>
            {copy.arrow} {copy.label}
          </span>
        </div>

        <div className={`text-4xl font-mono font-bold ${TEXT[copy.tone]}`}>
          {formatLogretPct(latest?.predicted_logret ?? null)}
        </div>

        {latest && (
          <div className="mt-2 text-sm text-white/60">
            {formatDollarImpact(latest.predicted_logret, NOTIONAL)} on a{" "}
            <span className="text-white/80">$10k</span> position
          </div>
        )}

        <div className="mt-2 text-xs text-white/40">
          {latest ? `updated ${formatRelativeTime(latest.created_at)}` : "waiting…"}
        </div>
      </CardContent>
    </Card>
  );
}
