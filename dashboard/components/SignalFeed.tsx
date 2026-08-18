"use client";

import { useCallback, useEffect, useState } from "react";
import { Signal } from "@/lib/types";
import Filters from "./Filters";
import SignalCard from "./SignalCard";

const DEFAULT_MIN_SCORE = 33;

export default function SignalFeed({
  initialSignals,
  initialError,
}: {
  initialSignals: Signal[];
  initialError: string | null;
}) {
  const [signals, setSignals] = useState<Signal[]>(initialSignals);
  const [minScore, setMinScore] = useState(DEFAULT_MIN_SCORE);
  const [source, setSource] = useState("ALL");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(initialError);

  const fetchSignals = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ minScore: String(minScore), source });
      if (search) params.set("search", search);
      const res = await fetch(`/api/signals?${params.toString()}`);
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const data: Signal[] = await res.json();
      setSignals(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load signals");
    } finally {
      setLoading(false);
    }
  }, [minScore, source, search]);

  useEffect(() => {
    // page.tsx already fetched this exact combination server-side on
    // first render, so skip the redundant client round-trip.
    if (minScore === DEFAULT_MIN_SCORE && source === "ALL" && search === "") return;
    const id = setTimeout(fetchSignals, 300);
    return () => clearTimeout(id);
  }, [minScore, source, search, fetchSignals]);

  return (
    <div>
      <Filters
        minScore={minScore}
        onMinScoreChange={setMinScore}
        source={source}
        onSourceChange={setSource}
        search={search}
        onSearchChange={setSearch}
      />

      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      {loading && <p className="mt-3 text-sm text-neutral-500">Loading...</p>}

      <div className="mt-4 flex flex-col gap-3">
        {!loading && signals.length === 0 && (
          <p className="text-sm text-neutral-500">No signals match these filters.</p>
        )}
        {signals.map((signal) => (
          <SignalCard key={signal.signal_id} signal={signal} />
        ))}
      </div>
    </div>
  );
}
