"use client";

import { useState } from "react";
import { usePortfolio } from "@/hooks/use-portfolio";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatUSD } from "@/lib/format";

const PRESETS = [1_000, 5_000, 10_000, 25_000, 100_000];

export function CapitalForm() {
  const { portfolio, resetPortfolio } = usePortfolio();
  const [custom, setCustom] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);

  const current = portfolio?.starting_capital ?? 10_000;

  const handleReset = async (amount: number) => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setPending(true);
    await resetPortfolio(amount);
    setPending(false);
    setConfirming(false);
    setCustom("");
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Starting capital</CardTitle>
        <CardDescription>
          Reset your paper portfolio to a fresh starting balance. All positions and trades are wiped.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-white/50">
          Current: <span className="text-white font-mono">{formatUSD(current)}</span>
        </p>

        <div className="flex flex-wrap gap-2">
          {PRESETS.map((amount) => (
            <button
              key={amount}
              type="button"
              onClick={() => handleReset(amount)}
              disabled={pending}
              className="rounded-full border border-white/20 px-4 py-1.5 text-sm font-medium text-white/70 hover:border-white/50 hover:text-white transition-colors disabled:opacity-40"
            >
              {formatUSD(amount)}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <input
            type="number"
            placeholder="Custom amount"
            value={custom}
            onChange={(e) => { setCustom(e.target.value); setConfirming(false); }}
            className="flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-white/20"
          />
          <button
            type="button"
            onClick={() => handleReset(Number(custom))}
            disabled={!custom || Number(custom) <= 0 || pending}
            className="rounded-lg border border-white/20 px-4 py-2 text-sm font-medium text-white/70 hover:border-white/50 hover:text-white transition-colors disabled:opacity-40"
          >
            Set
          </button>
        </div>

        {confirming && (
          <p className="text-sm text-amber-400">
            Click again to confirm — this wipes your positions and trade history.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
