import { getSupabaseServerClient } from "@/lib/supabase/server";
import { Signal } from "@/lib/types";
import SignalFeed from "@/components/SignalFeed";

export const dynamic = "force-dynamic";

export default async function Page() {
  let initialSignals: Signal[] = [];
  let initialError: string | null = null;

  try {
    const { data, error } = await getSupabaseServerClient()
      .from("signals")
      .select("*")
      .gte("relevance_score", 33)
      .order("relevance_score", { ascending: false })
      .limit(100);

    if (error) throw new Error(error.message);
    initialSignals = data ?? [];
  } catch (err) {
    initialError = err instanceof Error ? err.message : "Failed to load signals";
  }

  return (
    <main className="mx-auto min-h-screen max-w-2xl bg-neutral-950 px-4 py-6 text-neutral-100">
      <h1 className="mb-4 text-xl font-bold">Political Tracker</h1>
      <SignalFeed initialSignals={initialSignals} initialError={initialError} />
    </main>
  );
}
