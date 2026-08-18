"""Phase 1 orchestrator: fetch all 4 sources, score, persist to Supabase.

Must be run as a module from the repo root, NOT as a bare script:
    python -m agent.main
(running `python agent/main.py` directly breaks the `agent.sources.*`
imports, since `agent` wouldn't be resolvable as a package from inside its
own directory).

Requires CONGRESS_API_KEY in the environment for the Congress.gov source
(see agent/sources/congress.py). If SUPABASE_URL/SUPABASE_KEY are not set,
the run still fetches and scores everything but skips the DB write with a
clear message - no Supabase project has been created for this repo yet.
If NTFY_TOPIC is not set, push alerts are skipped the same way.
"""

import os

from agent.sources.sec_edgar import SecEdgarSource
from agent.sources.federal_register import FederalRegisterSource
from agent.sources.usaspending import UsaspendingSource
from agent.sources.congress import CongressSource
from agent.scorers.correlation import score_signals
from agent.db.supabase_client import upsert_signals
from agent.alerts.engine import send_ntfy_alert, ALERT_THRESHOLD

SOURCES = [SecEdgarSource(), FederalRegisterSource(), UsaspendingSource(), CongressSource()]


def main():
    all_signals = []

    for source in SOURCES:
        try:
            signals = source.fetch()
            print(f"[{source.name}] fetched {len(signals)} signals")
            all_signals.extend(signals)
        except Exception as exc:  # one bad source shouldn't sink the run
            print(f"[{source.name}] FAILED: {exc}")

    scored = score_signals(all_signals)
    correlated = sum(1 for s in scored if s["score"] > 0)
    print(f"\nScored {len(scored)} signals ({correlated} with correlation > 0)")

    ntfy_topic = os.environ.get("NTFY_TOPIC")
    if ntfy_topic:
        alertable = [s for s in scored if s["score"] >= ALERT_THRESHOLD]
        sent = sum(1 for s in alertable if send_ntfy_alert(s, ntfy_topic))
        print(f"Sent {sent}/{len(alertable)} ntfy alerts (score >= {ALERT_THRESHOLD}).")
    else:
        print("[SKIPPED] NTFY_TOPIC not set - no push alerts sent this run.")

    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
        print("[SKIPPED] SUPABASE_URL/SUPABASE_KEY not set - not writing to Supabase this run.")
        return

    upsert_signals(scored)
    print(f"Wrote {len(scored)} signals to Supabase.")


if __name__ == "__main__":
    main()
