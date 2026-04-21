"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useSupabaseClient } from "@/lib/supabase/client";
import type { PaperTrade } from "@crypto-signals/shared";

const MAX_TRADES = 100;

export function useRealtimeTrades(initial: PaperTrade[]) {
  const { userId } = useAuth();
  const supabase = useSupabaseClient();
  const [trades, setTrades] = useState<PaperTrade[]>(initial);

  useEffect(() => {
    setTrades(initial);
  }, [initial]);

  useEffect(() => {
    if (!userId) return;

    const channel = supabase
      .channel("trades-realtime")
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "paper_trades",
          filter: `user_id=eq.${userId}`,
        },
        (payload) => {
          const row = payload.new as PaperTrade;
          setTrades((prev) => [row, ...prev].slice(0, MAX_TRADES));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [userId, supabase]);

  return trades;
}
