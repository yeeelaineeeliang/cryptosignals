"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";
import type { VifTraceEntry } from "@crypto-signals/shared";

interface VifTraceChartProps {
  trace: VifTraceEntry[];
}

/**
 * Renders the VIF elimination story as a dual-axis line chart.
 *   - left axis: max VIF at each iteration (log scale — it often starts in
 *     the millions because of perfectly collinear price levels)
 *   - right axis: OSR² on the validation fold at each iteration
 *
 * Hover any point to see which feature was dropped on that step.
 */
export function VifTraceChart({ trace }: VifTraceChartProps) {
  const data = trace.map((e) => ({
    iter: e.iter,
    vif_max: e.vif_max === 0 ? 0 : Math.log10(Math.max(1, e.vif_max)), // log10
    osr2: e.osr2,
    hit_rate: e.hit_rate,
    dropped: e.dropped,
  }));

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 40, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
          <XAxis
            dataKey="iter"
            stroke="rgba(255,255,255,0.4)"
            tick={{ fontSize: 11 }}
            label={{
              value: "elimination iteration",
              position: "insideBottom",
              offset: -4,
              fill: "rgba(255,255,255,0.5)",
              fontSize: 11,
            }}
          />
          <YAxis
            yAxisId="left"
            stroke="#f97316"
            tick={{ fontSize: 11 }}
            label={{ value: "log10(max VIF)", angle: -90, position: "insideLeft", fill: "#f97316", fontSize: 11 }}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            stroke="#60a5fa"
            tick={{ fontSize: 11 }}
            label={{ value: "val OSR²", angle: 90, position: "insideRight", fill: "#60a5fa", fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "rgba(20,20,20,0.95)",
              border: "1px solid rgba(255,255,255,0.1)",
              fontSize: 12,
            }}
            labelFormatter={(iter, payload) => {
              const entry = payload?.[0]?.payload;
              return entry?.dropped ? `iter ${iter} — dropped ${entry.dropped}` : `iter ${iter} — start`;
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="vif_max"
            stroke="#f97316"
            strokeWidth={2}
            dot={{ r: 3 }}
            name="log10(max VIF)"
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="osr2"
            stroke="#60a5fa"
            strokeWidth={2}
            dot={{ r: 3 }}
            name="val OSR²"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
