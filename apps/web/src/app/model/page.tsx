import { createPublicSupabaseClient } from "@/lib/supabase/server";
import { ModelCard } from "@/components/model/ModelCard";
import type { ModelVersion } from "@crypto-signals/shared";

export const dynamic = "force-dynamic";

export default async function ModelPage() {
  const supabase = createPublicSupabaseClient();
  const { data } = await supabase
    .from("model_versions")
    .select("*")
    .eq("is_active", true)
    .order("symbol");
  const models = (data ?? []) as ModelVersion[];

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 space-y-8">
      <div>
        <h1 className="text-4xl font-extrabold tracking-tight text-white">Model</h1>
        <p className="mt-2 text-sm text-white/50 max-w-2xl">
          OLS with iterative VIF elimination. Started with 37 candidate
          features across raw OHLCV, log-transforms, returns, moving-average
          ratios, volatility, momentum, volume flow, calendar, and lagged
          returns. Each active model below is whatever the{" "}
          <code>bootstrap_train</code> script converged to on the training
          window shown.
        </p>
      </div>

      {models.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center text-muted-foreground">
          No active models yet — run{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-foreground">
            python -m worker.ml.bootstrap_train
          </code>{" "}
          to train the first one.
        </div>
      ) : (
        models.map((model) => <ModelCard key={model.id} model={model} />)
      )}
    </div>
  );
}
