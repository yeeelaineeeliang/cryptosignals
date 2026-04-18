"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ModelVersion } from "@crypto-signals/shared";

interface CoefficientBarChartProps {
  model: ModelVersion;
}

/**
 * Horizontal-style bar chart of surviving coefficients (excluding const).
 * Bars left of zero = negative coef, right of zero = positive.
 * Mirrors the intent of `coefplot` from the old Final Product.py.
 */
export function CoefficientBarChart({ model }: CoefficientBarChartProps) {
  const data = Object.entries(model.coefficients)
    .filter(([k]) => k !== "const")
    .map(([feature, coef]) => ({ feature, coef }))
    .sort((a, b) => a.coef - b.coef);

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 22)}>
        <BarChart data={data} layout="vertical" margin={{ left: 80, right: 24, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
          <XAxis type="number" stroke="rgba(255,255,255,0.4)" tick={{ fontSize: 11 }} />
          <YAxis
            type="category"
            dataKey="feature"
            stroke="rgba(255,255,255,0.4)"
            tick={{ fontSize: 10, fontFamily: "ui-monospace, monospace" }}
            width={140}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "rgba(20,20,20,0.95)",
              border: "1px solid rgba(255,255,255,0.1)",
              fontSize: 12,
            }}
            formatter={(v: number) => v.toExponential(3)}
          />
          <ReferenceLine x={0} stroke="rgba(255,255,255,0.3)" />
          <Bar dataKey="coef" fill="#60a5fa" radius={[0, 2, 2, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
