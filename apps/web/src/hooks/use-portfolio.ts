"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useSupabaseClient } from "@/lib/supabase/client";
import type { Portfolio } from "@crypto-signals/shared";

export function usePortfolio() {
  const { userId, isSignedIn } = useAuth();
  const supabase = useSupabaseClient();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [loading, setLoading] = useState(true);

  // Initial fetch
  useEffect(() => {
    if (!isSignedIn || !userId) {
      setPortfolio(null);
      setLoading(false);
      return;
    }

    const timer = setTimeout(async () => {
      const { data } = await supabase
        .from("portfolios")
        .select("*")
        .eq("user_id", userId)
        .maybeSingle();
      setPortfolio((data as Portfolio) ?? null);
      setLoading(false);
    }, 100);

    return () => clearTimeout(timer);
  }, [isSignedIn, userId, supabase]);

  // Realtime subscription — worker updates this row on every trade
  useEffect(() => {
    if (!userId) return;

    const channel = supabase
      .channel("portfolio-realtime")
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "portfolios",
          filter: `user_id=eq.${userId}`,
        },
        (payload) => {
          setPortfolio(payload.new as Portfolio);
        }
      )
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "portfolios",
          filter: `user_id=eq.${userId}`,
        },
        (payload) => {
          setPortfolio(payload.new as Portfolio);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [userId, supabase]);

  const resetPortfolio = async (startingCapital: number) => {
    if (!userId) return;
    const { data } = await supabase
      .from("portfolios")
      .upsert({
        user_id: userId,
        starting_capital: startingCapital,
        cash_usd: startingCapital,
        positions: {},
        equity_usd: startingCapital,
        updated_at: new Date().toISOString(),
      })
      .select("*")
      .single();
    if (data) setPortfolio(data as Portfolio);
  };

  return { portfolio, loading, resetPortfolio };
}
