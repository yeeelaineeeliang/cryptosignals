"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatUSD } from "@/lib/format";
import type { Portfolio } from "@crypto-signals/shared";

interface PortfolioSummaryProps {
  portfolio: Portfolio | null;
}

export function PortfolioSummary({ portfolio }: PortfolioSummaryProps) {
  if (!portfolio) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-white/40">
          No portfolio yet — trades appear once a signal fires above your threshold.
        </CardContent>
      </Card>
    );
  }

  const equity = portfolio.equity_usd;
  const start = portfolio.starting_capital;
  const pnl = equity - start;
  const pnlPct = start > 0 ? (pnl / start) * 100 : 0;
  const isUp = pnl >= 0;

  const positions = portfolio.positions ?? {};
  const hasPositions = Object.keys(positions).length > 0;

  return (
    <div className="space-y-4">
      {/* Equity summary */}
      <div className="grid grid-cols-3 gap-3">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs font-medium text-white/50 uppercase tracking-wider">Equity</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-white">{formatUSD(equity)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs font-medium text-white/50 uppercase tracking-wider">Cash</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-white">{formatUSD(portfolio.cash_usd)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs font-medium text-white/50 uppercase tracking-wider">Total P&amp;L</CardTitle>
          </CardHeader>
          <CardContent>
            <p className={`text-2xl font-bold ${isUp ? "text-green-400" : "text-red-400"}`}>
              {isUp ? "+" : ""}{formatUSD(pnl)}
            </p>
            <p className={`text-xs mt-0.5 ${isUp ? "text-green-400/70" : "text-red-400/70"}`}>
              {isUp ? "+" : ""}{pnlPct.toFixed(2)}%
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Open positions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold text-white">Open positions</CardTitle>
        </CardHeader>
        <CardContent>
          {!hasPositions ? (
            <p className="text-sm text-white/40">No open positions</p>
          ) : (
            <div className="divide-y divide-white/5">
              {Object.entries(positions).map(([sym, pos]) => (
                <div key={sym} className="grid grid-cols-3 py-3 text-sm">
                  <span className="font-semibold text-white">{sym}</span>
                  <span className="text-white/60 font-mono">{Number(pos.qty).toFixed(6)}</span>
                  <span className="text-right text-white/60 font-mono">
                    avg {formatUSD(Number(pos.avg_cost))}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
