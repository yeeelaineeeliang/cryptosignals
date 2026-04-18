import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatRelativeTime } from "@/lib/format";
import { CoefficientBarChart } from "./CoefficientBarChart";
import { VifTraceChart } from "./VifTraceChart";
import type { ModelVersion } from "@crypto-signals/shared";

interface ModelCardProps {
  model: ModelVersion;
}

interface MetricProps {
  label: string;
  value: number | null;
  precision?: number;
  hint?: string;
}

function Metric({ label, value, precision = 4, hint }: MetricProps) {
  const display =
    value == null || Number.isNaN(value) ? "—" : value.toFixed(precision);
  const tone =
    value == null || Number.isNaN(value)
      ? "text-white/40"
      : value < 0
        ? "text-red-400"
        : value > 0
          ? "text-green-400"
          : "text-white";
  return (
    <div title={hint} className="cursor-help">
      <div className="text-xs font-medium text-white/50">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-bold ${tone}`}>{display}</div>
    </div>
  );
}

export function ModelCard({ model }: ModelCardProps) {
  const droppedFeatures = (model.vif_trace ?? [])
    .filter((e) => e.dropped)
    .map((e) => e.dropped as string);
  const totalCandidates = model.selected_features.length + droppedFeatures.length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between flex-wrap gap-2">
          <span className="text-2xl font-bold">{model.symbol}</span>
          <div className="flex items-center gap-2">
            <Badge className="bg-green-500/15 text-green-400 border border-green-500/30">
              live
            </Badge>
            <span className="text-sm text-white/50">
              {formatRelativeTime(model.trained_at)}
            </span>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-8">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
          <Metric
            label={`uses ${model.selected_features.length} of ${totalCandidates}`}
            value={model.selected_features.length}
            precision={0}
            hint="signals the model uses, out of all candidates considered"
          />
          <Metric
            label="train fit"
            value={model.r_squared}
            hint="R² on training data — how well the model fits the past (0 to 1, higher is better)"
          />
          <Metric
            label="test score"
            value={model.osr2}
            hint="OSR² on unseen data. Negative = worse than always guessing the average."
          />
          <Metric
            label="hit rate"
            value={model.hit_rate}
            hint="how often up/down direction is right. 0.50 = coin flip."
          />
        </div>

        <div>
          <h3 className="text-base font-semibold text-white mb-3">Coefficients</h3>
          <CoefficientBarChart model={model} />
        </div>

        {model.vif_trace && model.vif_trace.length > 1 && (
          <div>
            <div className="flex items-baseline justify-between mb-3">
              <h3 className="text-base font-semibold text-white">
                Trim history
              </h3>
              <div className="flex items-center gap-3 text-xs">
                <span className="flex items-center gap-1.5 text-white/60">
                  <span className="h-2 w-2 rounded-full bg-orange-400" /> overlap
                </span>
                <span className="flex items-center gap-1.5 text-white/60">
                  <span className="h-2 w-2 rounded-full bg-blue-400" /> score
                </span>
              </div>
            </div>
            <VifTraceChart trace={model.vif_trace} />
          </div>
        )}

        {droppedFeatures.length > 0 && (
          <details className="rounded-lg border border-white/10 bg-white/[0.02] p-4">
            <summary className="cursor-pointer text-sm font-semibold text-white/70">
              Dropped signals ({droppedFeatures.length})
            </summary>
            <div className="mt-3 flex flex-wrap gap-1.5 text-xs font-mono">
              {droppedFeatures.map((feat) => (
                <span
                  key={feat}
                  className="rounded border border-white/10 bg-white/5 px-2 py-1 text-white/50"
                >
                  {feat}
                </span>
              ))}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  );
}
