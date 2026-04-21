"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatUSD, formatRelativeTime } from "@/lib/format";
import type { PaperTrade } from "@crypto-signals/shared";

interface TradeHistoryTableProps {
  trades: PaperTrade[];
}

export function TradeHistoryTable({ trades }: TradeHistoryTableProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-white">Trade history</CardTitle>
      </CardHeader>
      <CardContent>
        {trades.length === 0 ? (
          <p className="text-sm text-white/40 py-4 text-center">No trades yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-white/30 text-xs uppercase tracking-wider">
                  <th className="pb-2 text-left">Time</th>
                  <th className="pb-2 text-left">Pair</th>
                  <th className="pb-2 text-left">Side</th>
                  <th className="pb-2 text-right">Qty</th>
                  <th className="pb-2 text-right">Price</th>
                  <th className="pb-2 text-right">Notional</th>
                  <th className="pb-2 text-right">Fee</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {trades.slice(0, 50).map((t) => (
                  <tr key={t.id} className="group">
                    <td className="py-2.5 text-white/40 font-mono text-xs">
                      {formatRelativeTime(t.created_at)}
                    </td>
                    <td className="py-2.5 font-semibold text-white">{t.symbol}</td>
                    <td className="py-2.5">
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs font-bold ${
                          t.side === "BUY"
                            ? "bg-green-500/15 text-green-400"
                            : "bg-red-500/15 text-red-400"
                        }`}
                      >
                        {t.side}
                      </span>
                    </td>
                    <td className="py-2.5 text-right font-mono text-white/70">
                      {Number(t.qty).toFixed(6)}
                    </td>
                    <td className="py-2.5 text-right font-mono text-white/70">
                      {formatUSD(t.price)}
                    </td>
                    <td className="py-2.5 text-right font-mono text-white/70">
                      {formatUSD(t.notional_usd)}
                    </td>
                    <td className="py-2.5 text-right font-mono text-white/40 text-xs">
                      {formatUSD(t.fee_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
