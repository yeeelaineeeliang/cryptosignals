"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatUSD } from "@/lib/format";
import type { PaperTrade, Portfolio } from "@crypto-signals/shared";

interface EquityCurveProps {
  trades: PaperTrade[];
  portfolio: Portfolio | null;
}

interface DataPoint {
  time: string;
  equity: number;
}

function buildCurve(trades: PaperTrade[], portfolio: Portfolio | null): DataPoint[] {
  if (!portfolio) return [];
  const start = portfolio.starting_capital;

  // Walk trades in chronological order; track running cash
  const sorted = [...trades].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );

  const points: DataPoint[] = [{ time: "Start", equity: start }];
  let cash = start;

  for (const t of sorted) {
    if (t.side === "BUY") {
      cash -= t.notional_usd + t.fee_usd;
    } else {
      cash += t.notional_usd - t.fee_usd;
    }
    const label = new Date(t.created_at).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
    // Use cash as equity proxy at trade time (positions valued at trade price)
    const positionValue = t.side === "BUY" ? t.notional_usd : 0;
    points.push({ time: label, equity: cash + positionValue });
  }

  // Append current live equity
  if (portfolio && sorted.length > 0) {
    points.push({ time: "Now", equity: portfolio.equity_usd });
  }

  return points;
}

export function EquityCurve({ trades, portfolio }: EquityCurveProps) {
  const data = buildCurve(trades, portfolio);
  const start = portfolio?.starting_capital ?? 10_000;
  const current = portfolio?.equity_usd ?? start;
  const isUp = current >= start;

  if (data.length < 2) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold text-white">Equity curve</CardTitle>
        </CardHeader>
        <CardContent className="py-8 text-center text-sm text-white/40">
          Waiting for first trade…
        </CardContent>
      </Card>
    );
  }

  const color = isUp ? "#4ade80" : "#f87171";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-white">Equity curve</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.25} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis
              dataKey="time"
              tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
              tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              formatter={(v: number) => [formatUSD(v), "Equity"]}
              contentStyle={{
                background: "#0f172a",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "rgba(255,255,255,0.5)" }}
            />
            <Area
              type="monotone"
              dataKey="equity"
              stroke={color}
              strokeWidth={2}
              fill="url(#equityGrad)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
