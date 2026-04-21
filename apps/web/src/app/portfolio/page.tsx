import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { createServerSupabaseClient } from "@/lib/supabase/server";
import { PortfolioClient } from "./PortfolioClient";
import type { PaperTrade, Portfolio } from "@crypto-signals/shared";

export const dynamic = "force-dynamic";

export default async function PortfolioPage() {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  const supabase = await createServerSupabaseClient();

  const [portfolioRes, tradesRes] = await Promise.all([
    supabase.from("portfolios").select("*").eq("user_id", userId).maybeSingle(),
    supabase
      .from("paper_trades")
      .select("*")
      .eq("user_id", userId)
      .order("created_at", { ascending: false })
      .limit(100),
  ]);

  return (
    <div className="mx-auto max-w-4xl px-6 py-10 space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Portfolio</h1>
        <p className="mt-1 text-sm text-white/50">
          Paper positions and simulated equity. Not real money.
        </p>
      </div>

      <PortfolioClient
        initialPortfolio={(portfolioRes.data as Portfolio) ?? null}
        initialTrades={(tradesRes.data as PaperTrade[]) ?? []}
      />
    </div>
  );
}
