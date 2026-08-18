"use client";

import { SOURCES } from "@/lib/types";

interface FiltersProps {
  minScore: number;
  onMinScoreChange: (value: number) => void;
  source: string;
  onSourceChange: (value: string) => void;
  search: string;
  onSearchChange: (value: string) => void;
}

export default function Filters({
  minScore,
  onMinScoreChange,
  source,
  onSourceChange,
  search,
  onSearchChange,
}: FiltersProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <div>
        <label htmlFor="minScore" className="flex justify-between text-xs text-neutral-400">
          <span>Min score</span>
          <span>{minScore}</span>
        </label>
        <input
          id="minScore"
          type="range"
          min={0}
          max={100}
          step={1}
          value={minScore}
          onChange={(e) => onMinScoreChange(Number(e.target.value))}
          className="mt-1 w-full accent-orange-500"
        />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <select
          aria-label="Source"
          value={source}
          onChange={(e) => onSourceChange(e.target.value)}
          className="rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 sm:w-48"
        >
          <option value="ALL">All sources</option>
          {SOURCES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search title or entity..."
          className="flex-1 rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 placeholder:text-neutral-600"
        />
      </div>
    </div>
  );
}
