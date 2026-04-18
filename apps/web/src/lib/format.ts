// Numeric formatting helpers for crypto prices, returns, and durations.

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const pctFmt = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const pctPlain = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatUSD(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return Math.abs(value) >= 10_000 ? usdCompact.format(value) : usdFmt.format(value);
}

export function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  // Crypto often has sub-cent precision; keep 2 decimals for USD pairs
  return usdFmt.format(value);
}

export function formatPct(value: number | null | undefined, signed = false): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return (signed ? pctFmt : pctPlain).format(value);
}

export function formatLogret(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  // Log-returns are small; show in bps for readability (1 bps = 0.01%)
  return `${(value * 10_000).toFixed(1)} bps`;
}

/**
 * Friendly percentage formatter for tiny log-returns. Designed for users
 * who don't know what "bps" or "log-returns" mean — shows e.g. "+0.04%"
 * or "−0.12%" with a sign and reasonable precision.
 */
export function formatLogretPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const pct = value * 100; // log-return ≈ % return for small moves
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${Math.abs(pct).toFixed(3)}%`;
}

/**
 * Predicted dollar impact of holding `notional` USD through one prediction.
 * Log-returns ≈ percentage returns for small moves, so this is `notional × r`.
 * Returns a string like "+$1.40" or "−$0.65" or "—".
 */
export function formatDollarImpact(
  predictedLogret: number | null | undefined,
  notionalUsd = 10_000,
): string {
  if (predictedLogret == null || !Number.isFinite(predictedLogret)) return "—";
  const dollars = notionalUsd * predictedLogret;
  const abs = Math.abs(dollars);
  const sign = dollars > 0 ? "+" : dollars < 0 ? "−" : "";
  if (abs < 0.01) return `${sign}$${abs.toFixed(3)}`;
  if (abs < 1) return `${sign}$${abs.toFixed(2)}`;
  return `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

/**
 * Translate a SHORT/LONG/HOLD signal into a non-finance label + arrow + tone.
 * For a user who has never traded, "LONG" is meaningless — "Buy" is not.
 */
export function signalCopy(signal: string | null | undefined) {
  switch (signal) {
    case "LONG":
      return { label: "Buy", arrow: "▲", tone: "up" as const, blurb: "Model thinks the price will go up" };
    case "SHORT":
      return { label: "Sell", arrow: "▼", tone: "down" as const, blurb: "Model thinks the price will go down" };
    case "HOLD":
    default:
      return { label: "Wait", arrow: "•", tone: "flat" as const, blurb: "Model isn't confident either way" };
  }
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
