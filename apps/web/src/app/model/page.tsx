import { createPublicSupabaseClient } from "@/lib/supabase/server";
import { ModelCard } from "@/components/model/ModelCard";
import { PipelineDiagram } from "@/components/model/PipelineDiagram";
import { LivePerformancePanel } from "@/components/model/LivePerformancePanel";
import type { ModelPerformance, ModelVersion } from "@crypto-signals/shared";

export const dynamic = "force-dynamic";

export default async function ModelPage() {
  const supabase = createPublicSupabaseClient();

  const [modelsRes, perfRes] = await Promise.all([
    supabase.from("model_versions").select("*").eq("is_active", true).order("symbol"),
    supabase
      .from("model_performance")
      .select("*")
      .order("evaluated_at", { ascending: false })
      .limit(20),
  ]);

  const models = (modelsRes.data ?? []) as ModelVersion[];
  const perfs = (perfRes.data ?? []) as ModelPerformance[];

  // Latest performance per model_version_id
  const latestPerf = new Map<number, ModelPerformance>();
  for (const p of perfs) {
    if (!latestPerf.has(p.model_version_id)) latestPerf.set(p.model_version_id, p);
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 space-y-8">
      <header>
        <h1 className="text-4xl font-extrabold tracking-tight text-white">
          Behind the predictions
        </h1>
        <p className="mt-3 text-base text-white/60">
          The math behind every call. No black boxes.
        </p>
      </header>

      <PipelineDiagram />

      {models.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 p-10 text-center text-white/50">
          No active models yet.
        </div>
      ) : (
        models.map((model) => (
          <div key={model.id} className="space-y-4">
            <ModelCard model={model} />
            <LivePerformancePanel
              model={model}
              perf={latestPerf.get(model.id) ?? null}
            />
          </div>
        ))
      )}
    </div>
  );
}
