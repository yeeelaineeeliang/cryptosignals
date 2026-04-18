import { createPublicSupabaseClient } from "@/lib/supabase/server";
import { PriceTickerGrid } from "@/components/dashboard/PriceTickerGrid";
import { SignalsPanel } from "@/components/dashboard/SignalsPanel";
import type { Pair, Prediction, Price } from "@crypto-signals/shared";

export const dynamic = "force-dynamic";

async function DashboardData() {
  const supabase = createPublicSupabaseClient();

  const [pairsRes, pricesRes, predictionsRes] = await Promise.all([
    supabase.from("pairs").select("*").eq("is_active", true).order("display_name"),
    supabase.from("prices").select("*"),
    supabase
      .from("predictions")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(50),
  ]);

  const pairs = (pairsRes.data ?? []) as Pair[];
  const prices = (pricesRes.data ?? []) as Price[];
  const predictions = (predictionsRes.data ?? []) as Prediction[];

  return (
    <div className="space-y-8">
      <PriceTickerGrid pairs={pairs} initialPrices={prices} />
      <SignalsPanel pairs={pairs} initialPredictions={predictions} />
    </div>
  );
}

export default async function DashboardPage() {
  const now = new Date().toLocaleString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-4xl font-extrabold tracking-tight text-white">
            Dashboard
          </h1>
          <div className="flex items-center gap-1.5 rounded-full bg-green-500/10 px-2.5 py-1">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-green-500" />
            </span>
            <span className="text-[11px] font-semibold text-green-400 uppercase tracking-wider">
              Live
            </span>
          </div>
        </div>
        <p className="text-lg text-white/40">{now}</p>
      </div>

      <DashboardData />
    </div>
  );
}
