import { createPublicSupabaseClient } from "@/lib/supabase/server";
import { PairPicker } from "@/components/settings/PairPicker";
import { ThresholdSlider } from "@/components/settings/ThresholdSlider";
import { CapitalForm } from "@/components/settings/CapitalForm";
import type { Pair } from "@crypto-signals/shared";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const supabase = createPublicSupabaseClient();
  const { data } = await supabase
    .from("pairs")
    .select("*")
    .eq("is_active", true)
    .order("display_name");
  const pairs = (data ?? []) as Pair[];

  return (
    <div className="mx-auto max-w-3xl px-6 py-10 space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Settings</h1>
        <p className="mt-1 text-sm text-white/50">
          Preferences saved per user. Worker picks them up on the next inference tick.
        </p>
      </div>

      <PairPicker pairs={pairs} />
      <ThresholdSlider />
      <CapitalForm />
    </div>
  );
}
