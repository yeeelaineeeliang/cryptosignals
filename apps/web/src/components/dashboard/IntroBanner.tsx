/**
 * Single-line orientation strip. Lean, icon-driven, no paragraph of prose.
 */
export function IntroBanner() {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-sm">
      <Legend dot="bg-green-500" label="▲ Buy" />
      <Legend dot="bg-red-500" label="▼ Sell" />
      <Legend dot="bg-white/40" label="• Wait" />
      <span className="text-white/40">·</span>
      <span className="text-white/60">paper trading only — no real money</span>
    </div>
  );
}

function Legend({ dot, label }: { dot: string; label: string }) {
  return (
    <span className="flex items-center gap-2 text-white/80">
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      <span className="font-semibold">{label}</span>
    </span>
  );
}
