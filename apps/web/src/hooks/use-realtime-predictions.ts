"use client";

import { useEffect, useState } from "react";
import { useSupabaseClient } from "@/lib/supabase/client";
import type { Prediction } from "@crypto-signals/shared";

const MAX_PREDICTIONS = 50;

/**
 * Subscribe to INSERT events on `predictions` and keep a rolling list of
 * the latest N (newest first). Same pattern as use-realtime-prices but the
 * predictions table is append-only so we only watch inserts, not updates.
 */
export function useRealtimePredictions(initial: Prediction[]) {
  const supabase = useSupabaseClient();
  const [rows, setRows] = useState<Prediction[]>(initial);

  useEffect(() => {
    setRows(initial);
  }, [initial]);

  useEffect(() => {
    const channel = supabase
      .channel("predictions-realtime")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "predictions" },
        (payload) => {
          const row = payload.new as Prediction;
          setRows((prev) => {
            const next = [row, ...prev];
            return next.slice(0, MAX_PREDICTIONS);
          });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return rows;
}
