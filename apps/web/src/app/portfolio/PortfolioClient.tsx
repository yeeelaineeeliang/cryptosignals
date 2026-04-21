"use client";

import { usePortfolio } from "@/hooks/use-portfolio";
import { useRealtimeTrades } from "@/hooks/use-realtime-trades";
import { PortfolioSummary } from "@/components/portfolio/PortfolioSummary";
import { EquityCurve } from "@/components/portfolio/EquityCurve";
import { TradeHistoryTable } from "@/components/portfolio/TradeHistoryTable";
import type { PaperTrade, Portfolio } from "@crypto-signals/shared";

interface PortfolioClientProps {
  initialPortfolio: Portfolio | null;
  initialTrades: PaperTrade[];
}

export function PortfolioClient({ initialPortfolio, initialTrades }: PortfolioClientProps) {
  const { portfolio } = usePortfolio();
  const trades = useRealtimeTrades(initialTrades);

  // Prefer live portfolio from realtime hook; fall back to server-fetched
  const livePortfolio = portfolio ?? initialPortfolio;

  return (
    <div className="space-y-6">
      <PortfolioSummary portfolio={livePortfolio} />
      <EquityCurve trades={trades} portfolio={livePortfolio} />
      <TradeHistoryTable trades={trades} />
    </div>
  );
}
