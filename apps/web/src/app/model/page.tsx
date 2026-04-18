import { createPublicSupabaseClient } from "@/lib/supabase/server";
import { ModelCard } from "@/components/model/ModelCard";
import { PipelineDiagram } from "@/components/model/PipelineDiagram";
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
        models.map((model) => <ModelCard key={model.id} model={model} />)
      )}
    </div>
  );
}
