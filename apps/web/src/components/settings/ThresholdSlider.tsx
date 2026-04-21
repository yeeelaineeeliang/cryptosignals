"use client";

import { useUserPrefs } from "@/hooks/use-user-prefs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const STEPS = [0.0005, 0.001, 0.002, 0.003, 0.005, 0.008, 0.01, 0.015, 0.02];

export function ThresholdSlider() {
  const { prefs, loading, update } = useUserPrefs();

  if (loading) return <div className="h-32 rounded-xl bg-muted/30 animate-pulse" />;

  const current = prefs?.signal_threshold ?? 0.002;
  const idx = STEPS.findIndex((s) => s >= current) ?? 2;

  const pct = (current * 100).toFixed(2);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Signal threshold</CardTitle>
        <CardDescription>
          Only trade when the model predicts a log-return at least this large.
          Higher = fewer trades, higher conviction.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-white/50">Min sensitivity</span>
          <span className="text-lg font-bold font-mono text-white">±{pct}%</span>
          <span className="text-sm text-white/50">Max conviction</span>
        </div>
        <input
          type="range"
          min={0}
          max={STEPS.length - 1}
          step={1}
          value={idx < 0 ? 2 : idx}
          onChange={(e) => update({ signal_threshold: STEPS[Number(e.target.value)] })}
          className="w-full accent-white"
        />
        <p className="text-xs text-white/30">
          At ±{pct}%, the model needs to predict a {pct}% move before signalling BUY or SELL.
        </p>
      </CardContent>
    </Card>
  );
}
