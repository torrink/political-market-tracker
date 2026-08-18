export function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "unknown";

  const then = new Date(dateStr).getTime();
  if (Number.isNaN(then)) return "unknown";

  const diffMs = Date.now() - then;
  const diffMinutes = Math.round(diffMs / 60_000);
  const diffHours = Math.round(diffMs / 3_600_000);
  const diffDays = Math.round(diffMs / 86_400_000);

  if (diffMinutes < 1) return "just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

// score is 0/33/67/100 (cross-source correlation count), not a 0-10 scale -
// see agent/scorers/correlation.py.
export function scoreBadgeClasses(score: number): string {
  if (score >= 100) return "bg-red-500/20 text-red-400 ring-1 ring-red-500/40";
  if (score >= 67) return "bg-orange-500/20 text-orange-400 ring-1 ring-orange-500/40";
  if (score >= 33) return "bg-yellow-500/20 text-yellow-400 ring-1 ring-yellow-500/40";
  return "bg-neutral-500/20 text-neutral-400 ring-1 ring-neutral-500/40";
}
