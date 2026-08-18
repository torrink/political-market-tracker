import { Signal } from "@/lib/types";
import { formatRelativeTime, scoreBadgeClasses } from "@/lib/format";

export default function SignalCard({ signal }: { signal: Signal }) {
  return (
    <article className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="flex items-start justify-between gap-3">
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${scoreBadgeClasses(
            signal.relevance_score
          )}`}
        >
          {signal.relevance_score}
        </span>
        <span className="text-xs text-neutral-500">{formatRelativeTime(signal.date)}</span>
      </div>

      <h2 className="mt-2 line-clamp-2 font-bold text-neutral-100">{signal.title}</h2>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {signal.category && (
          <span className="rounded-full bg-blue-500/20 px-2 py-0.5 text-xs text-blue-400 ring-1 ring-blue-500/40">
            {signal.category}
          </span>
        )}
        {signal.entity && <span className="text-xs text-neutral-400">{signal.entity}</span>}
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-neutral-800 pt-2">
        <span className="text-xs font-medium text-neutral-500">{signal.source}</span>
        <a
          href={signal.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Open source"
          className="text-neutral-500 hover:text-neutral-300"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
            <path d="M12.75 3a.75.75 0 0 1 .75-.75h3.5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0V4.81l-6.22 6.22a.75.75 0 1 1-1.06-1.06L15.19 3.75h-1.69a.75.75 0 0 1-.75-.75Z" />
            <path d="M4.25 4.5a.75.75 0 0 0-.75.75v10.5c0 .414.336.75.75.75h10.5a.75.75 0 0 0 .75-.75v-4.5a.75.75 0 0 1 1.5 0v4.5a2.25 2.25 0 0 1-2.25 2.25H4.25A2.25 2.25 0 0 1 2 15.75V5.25A2.25 2.25 0 0 1 4.25 3h4.5a.75.75 0 0 1 0 1.5h-4.5Z" />
          </svg>
        </a>
      </div>
    </article>
  );
}
