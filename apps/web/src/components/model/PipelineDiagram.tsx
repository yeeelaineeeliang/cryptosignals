import { Fragment } from "react";

/**
 * Visual pipeline of how the model is built.
 * 5 mini-cards in a row with arrows; minimal text per card.
 */
export function PipelineDiagram() {
  const steps = [
    { icon: "📊", label: "Coinbase candles", sub: "5-min OHLCV" },
    { icon: "🔧", label: "37 signals", sub: "engineered" },
    { icon: "📅", label: "Time split 70/15/15", sub: "train · val · test" },
    { icon: "✂️", label: "VIF prune", sub: "drop redundant" },
    { icon: "🚀", label: "Live every 30s", sub: "predict · serve" },
  ];

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
      <h3 className="mb-4 text-sm font-semibold text-white/70">
        How a model gets built
      </h3>
      <div className="flex flex-wrap items-stretch gap-2">
        {steps.map((step, i) => (
          <Fragment key={step.label}>
            <div className="flex-1 min-w-[140px] rounded-lg border border-white/10 bg-white/5 px-3 py-3 text-center">
              <div className="text-2xl">{step.icon}</div>
              <div className="mt-1.5 text-sm font-semibold text-white">
                {step.label}
              </div>
              <div className="text-xs text-white/40">{step.sub}</div>
            </div>
            {i < steps.length - 1 && (
              <div
                className="hidden self-center text-white/30 sm:block"
                aria-hidden
              >
                →
              </div>
            )}
          </Fragment>
        ))}
      </div>
    </div>
  );
}
