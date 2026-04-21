"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ModelPerformance, ModelVersion } from "@crypto-signals/shared";

interface LivePerformancePanelProps {
  model: ModelVersion;
  perf: ModelPerformance | null;
}

function Cell({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="text-center">
      <p className="text-xs text-white/40 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-white/30 mt-0.5">{sub}</p>}
    </div>
  );
}

function ConfusionMatrix({ tp, fp, tn, fn }: { tp: number; fp: number; tn: number; fn: number }) {
  const total = tp + fp + tn + fn || 1;
  const cells = [
    { label: "True Long", value: tp, color: "bg-green-500/20 text-green-400" },
    { label: "False Long", value: fp, color: "bg-red-500/10 text-red-400/70" },
    { label: "False Short", value: fn, color: "bg-red-500/10 text-red-400/70" },
    { label: "True Short", value: tn, color: "bg-green-500/20 text-green-400" },
  ];

  return (
    <div>
      <p className="text-xs text-white/40 uppercase tracking-wider mb-2">Confusion matrix (live)</p>
      <div className="grid grid-cols-2 gap-1 w-48">
        {cells.map((c) => (
          <div key={c.label} className={`rounded-lg p-3 ${c.color}`}>
            <p className="text-xs text-current/60">{c.label}</p>
            <p className="text-lg font-bold">{c.value}</p>
            <p className="text-xs opacity-60">{((c.value / total) * 100).toFixed(0)}%</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function LivePerformancePanel({ model, perf }: LivePerformancePanelProps) {
  const testHit = model.hit_rate != null ? `${(model.hit_rate * 100).toFixed(1)}%` : "—";
  const liveHit = perf?.hit_rate != null ? `${(perf.hit_rate * 100).toFixed(1)}%` : "—";

  const gap =
    model.hit_rate != null && perf?.hit_rate != null
      ? ((model.hit_rate - perf.hit_rate) * 100).toFixed(1)
      : null;

  const gapTag =
    gap == null
      ? null
      : Math.abs(Number(gap)) <= 3
        ? { label: "honest", color: "text-green-400" }
        : Number(gap) > 8
          ? { label: "overfit", color: "text-red-400" }
          : Number(gap) > 3
            ? { label: "mild overfit", color: "text-amber-400" }
            : { label: "regime luck", color: "text-blue-400" };

  const confusion = perf?.confusion;
  const n = confusion ? Object.values(confusion).reduce((a, b) => a + b, 0) : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-white">
          Backtest vs live — {model.symbol}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-8 items-start">
          {/* Hit rate comparison */}
          <div className="flex gap-6">
            <Cell label="Test hit rate" value={testHit} sub="held-out set" />
            <div className="flex items-center pt-6 text-white/20 text-xl">→</div>
            <Cell
              label="Live hit rate"
              value={liveHit}
              sub={n > 0 ? `n=${n} predictions` : "no live data yet"}
            />
            {gap != null && (
              <div className="flex flex-col items-center pt-4">
                <p className="text-xs text-white/40 uppercase tracking-wider mb-1">Gap</p>
                <p className={`text-lg font-bold ${gapTag?.color}`}>
                  {Number(gap) > 0 ? "+" : ""}{gap} pp
                </p>
                {gapTag && (
                  <p className={`text-xs font-medium ${gapTag.color}`}>{gapTag.label}</p>
                )}
              </div>
            )}
          </div>

          {/* Confusion matrix */}
          {confusion && n > 0 && (
            <ConfusionMatrix
              tp={confusion.tp}
              fp={confusion.fp}
              tn={confusion.tn}
              fn={confusion.fn}
            />
          )}
        </div>

        {!perf && (
          <p className="text-sm text-white/30 mt-4">
            Live metrics appear after the first evaluation cycle (runs hourly).
          </p>
        )}
      </CardContent>
    </Card>
  );
}
