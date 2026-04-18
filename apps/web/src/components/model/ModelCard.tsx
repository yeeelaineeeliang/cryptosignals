import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatRelativeTime } from "@/lib/format";
import { CoefficientBarChart } from "./CoefficientBarChart";
import { VifTraceChart } from "./VifTraceChart";
import type { ModelVersion } from "@crypto-signals/shared";

interface ModelCardProps {
  model: ModelVersion;
}

function metricChip(label: string, value: number | null, precision = 4) {
  if (value == null || Number.isNaN(value)) {
    return (
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="font-mono text-base text-muted-foreground">—</div>
      </div>
    );
  }
  const display = value.toFixed(precision);
  const tone = value < 0 ? "text-red-400" : value > 0 ? "text-green-400" : "text-foreground";
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`font-mono text-base ${tone}`}>{display}</div>
    </div>
  );
}

export function ModelCard({ model }: ModelCardProps) {
  const droppedFeatures = (model.vif_trace ?? [])
    .filter((e) => e.dropped)
    .map((e) => e.dropped as string);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between flex-wrap gap-2">
          <span className="text-xl font-bold">{model.symbol}</span>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-mono text-[10px]">v{model.id}</Badge>
            <Badge className="bg-green-500/15 text-green-400 border border-green-500/30 text-[10px]">
              active
            </Badge>
            <span className="text-[11px] text-muted-foreground">
              trained {formatRelativeTime(model.trained_at)}
            </span>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
          {metricChip("features kept", model.selected_features.length, 0)}
          {metricChip("train R²", model.r_squared)}
          {metricChip("test OSR²", model.osr2)}
          {metricChip("test hit rate", model.hit_rate)}
          {metricChip("test RMSE", model.rmse, 6)}
        </div>

        <div>
          <h3 className="text-sm font-semibold text-white mb-2">Coefficients (final model)</h3>
          <CoefficientBarChart model={model} />
        </div>

        {model.vif_trace && model.vif_trace.length > 1 && (
          <div>
            <h3 className="text-sm font-semibold text-white mb-2">
              VIF elimination trace ({model.vif_trace.length} iterations)
            </h3>
            <VifTraceChart trace={model.vif_trace} />
          </div>
        )}

        {droppedFeatures.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-white mb-2">
              Dropped by VIF ({droppedFeatures.length})
            </h3>
            <div className="flex flex-wrap gap-1.5 text-[11px] font-mono">
              {droppedFeatures.map((feat) => (
                <span
                  key={feat}
                  className="rounded border border-white/10 bg-muted/30 px-2 py-0.5 text-muted-foreground"
                >
                  {feat}
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
