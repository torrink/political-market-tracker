"""Supabase writer for the `signals` table.

Reads SUPABASE_URL / SUPABASE_KEY from the environment (same pattern as
CONGRESS_API_KEY elsewhere in this repo) - never hardcoded.

The live table's actual column names differ from the internal signal dict
produced by agent/scorers/correlation.py (which uses "score"): the table
has "relevance_score" instead, plus "impact_direction" and "sectors"
columns that nothing in the pipeline computes yet. _to_db_row() below does
the rename and fills those two with safe defaults (None / empty list) until
a scorer actually produces them - see the migration note in
supabase/migrations/0001_create_signals_table.sql, which will need updating
to match this live schema.
"""

import os


def get_client():
    from supabase import create_client  # imported lazily so this module is
                                          # importable even before `supabase`
                                          # is installed, as long as get_client()
                                          # itself isn't called

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must both be set in the environment. "
            'PowerShell:  $env:SUPABASE_URL = "https://xxxx.supabase.co"; '
            '$env:SUPABASE_KEY = "your-service-role-or-anon-key"'
        )
    return create_client(url, key)


def _to_db_row(signal: dict) -> dict:
    """Map an internal signal dict (source/signal_id/title/entity/date/
    category/url/summary/score/correlated_sources) to the live `signals`
    table's actual column names."""
    return {
        "signal_id": signal.get("signal_id"),
        "source": signal.get("source"),
        "title": signal.get("title"),
        "entity": signal.get("entity"),
        "date": signal.get("date"),
        "category": signal.get("category"),
        "url": signal.get("url"),
        "summary": signal.get("summary"),
        "relevance_score": signal.get("score", 0),
        "impact_direction": signal.get("impact_direction"),  # not computed yet - defaults to null
        "sectors": signal.get("sectors") or [],               # not computed yet - defaults to []
        "correlated_sources": signal.get("correlated_sources") or [],
    }


def upsert_signals(signals: list[dict]) -> None:
    """Upsert normalized+scored signal dicts into the `signals` table,
    keyed on signal_id so repeated runs are idempotent.

    Deduplicates by signal_id (keeping the first occurrence) before
    sending: Postgres's ON CONFLICT rejects a batch that hits the same
    conflict key twice in one statement, and a source could in principle
    hand back a repeated signal_id even though each source is expected not
    to (see agent/sources/congress.py's own dedupe for the known case)."""
    seen = set()
    rows = []
    for signal in signals:
        signal_id = signal.get("signal_id")
        if signal_id in seen:
            continue
        seen.add(signal_id)
        rows.append(_to_db_row(signal))

    client = get_client()
    client.table("signals").upsert(rows, on_conflict="signal_id").execute()
