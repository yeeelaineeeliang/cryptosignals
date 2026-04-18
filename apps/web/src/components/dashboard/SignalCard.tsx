"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatLogret, formatRelativeTime } from "@/lib/format";
import type { Pair, Prediction } from "@crypto-signals/shared";

interface SignalCardProps {
  pair: Pair;
  latest: Prediction | undefined;
}

const SIGNAL_STYLES: Record<string, string> = {
  LONG: "bg-green-500/15 text-green-400 border-green-500/30",
  SHORT: "bg-red-500/15 text-red-400 border-red-500/30",
  HOLD: "bg-white/5 text-white/60 border-white/10",
};

export function SignalCard({ pair, latest }: SignalCardProps) {
  const signal = latest?.signal ?? "HOLD";
  const chip = SIGNAL_STYLES[signal] ?? SIGNAL_STYLES.HOLD;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="text-sm font-medium text-muted-foreground">
            {pair.symbol} signal
          </span>
          <Badge className={`${chip} border font-mono`}>{signal}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-mono font-bold">
            {formatLogret(latest?.predicted_logret ?? null)}
          </span>
          <span className="text-xs text-muted-foreground">predicted next bar</span>
        </div>
        <div className="mt-2 text-xs text-muted-foreground">
          {latest ? `Model v${latest.model_version_id} · ${formatRelativeTime(latest.created_at)}` : "No signal yet"}
        </div>
      </CardContent>
    </Card>
  );
}
