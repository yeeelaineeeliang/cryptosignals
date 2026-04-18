"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatLogret, formatPrice, formatRelativeTime } from "@/lib/format";
import type { Prediction } from "@crypto-signals/shared";

interface SignalFeedProps {
  predictions: Prediction[];
  watchedSymbols: Set<string>;
}

const ROW_SIGNAL_STYLES: Record<string, string> = {
  LONG: "text-green-400",
  SHORT: "text-red-400",
  HOLD: "text-white/50",
};

export function SignalFeed({ predictions, watchedSymbols }: SignalFeedProps) {
  const filtered = predictions.filter((p) => watchedSymbols.has(p.symbol));
  const show = filtered.slice(0, 20);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Recent signals
        </CardTitle>
      </CardHeader>
      <CardContent>
        {show.length === 0 ? (
          <div className="py-6 text-center text-xs text-muted-foreground">
            Waiting for the next prediction… the model runs every 30s.
          </div>
        ) : (
          <div className="divide-y divide-white/5 font-mono text-xs">
            <div className="grid grid-cols-[auto_auto_1fr_auto_auto] items-center gap-3 pb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
              <span>Time</span>
              <span>Symbol</span>
              <span className="text-right">Predicted</span>
              <span className="text-right">Price</span>
              <span className="text-right">Signal</span>
            </div>
            {show.map((p) => (
              <div
                key={p.id}
                className="grid grid-cols-[auto_auto_1fr_auto_auto] items-center gap-3 py-2"
              >
                <span className="text-muted-foreground">
                  {formatRelativeTime(p.created_at)}
                </span>
                <span className="font-semibold">{p.symbol}</span>
                <span className="text-right">
                  {formatLogret(p.predicted_logret)}
                </span>
                <span className="text-right text-muted-foreground">
                  {formatPrice(p.current_price)}
                </span>
                <span
                  className={`text-right font-semibold ${ROW_SIGNAL_STYLES[p.signal] ?? ROW_SIGNAL_STYLES.HOLD}`}
                >
                  {p.signal}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
