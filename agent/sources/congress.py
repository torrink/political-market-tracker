"""Congress.gov source.

Fetches bills currently "in committee" at three target House committees
(Armed Services, Appropriations, Energy and Commerce) and normalizes them
to SIGNAL_FIELDS. Fetch/pagination logic and the row-mapping are carried
over unchanged from Phase 0's scripts/congress_fetch.py and
scripts/integration_fetch.py's map_congress_row().

Data source: https://api.congress.gov/v3/ (Library of Congress)
Docs: https://github.com/LibraryOfCongress/api.congress.gov/

UNLIKE the other three sources, this API REQUIRES a free API key. Sign up
(instant, email-based) at https://api.congress.gov/sign-up/, then set it as
an environment variable before running:
    PowerShell:  $env:CONGRESS_API_KEY = "your-key-here"
The key is read from the environment only - never hardcoded, never written
to any output.

Key quirks (verified against the live API - see Phase 0 script history):
  - Documented rate limit: 5,000 requests/hour per key.
  - No query param filters the top-level bill list by committee; use
    GET /v3/committee/{congress}/{chamber}/{committeeCode}/bills instead
    (bill number/type + referral date only - no title/sponsor/status).
  - That endpoint's `sort` param is silently ignored (always ascending by
    referral date); use offset = count - N to get the most recent N.
  - Bill detail (title, sponsors, introducedDate, latestAction,
    legislationUrl) requires a separate call per bill.
  - No discrete bill-status field exists; "in committee" is inferred from
    latestAction.text via a keyword heuristic (is_in_committee below) -
    an approximation, not a source of truth.
"""

import os
import time

import requests

from agent.sources.base import Source

BASE_URL = "https://api.congress.gov/v3"
USER_AGENT = "Political Tracker Research contact@example.com"

# House committee system codes (looked up via /v3/committee/119/house).
TARGET_COMMITTEES = {
    "hsas00": "Armed Services",
    "hsap00": "Appropriations",
    "hsif00": "Energy and Commerce",
}
CHAMBER = "house"

RAW_SAMPLE_PER_COMMITTEE = 60   # recent committee-referrals to inspect per committee

# Phrases in `latestAction.text` indicating a bill has moved PAST simple
# committee referral (passed a chamber, reported out, enacted, etc). If any
# of these appear, we do not count the bill as "in committee" even though it
# was referred to one of our target committees at some point.
ADVANCED_STAGE_KEYWORDS = [
    "passed",
    "reported",
    "placed on the union calendar",
    "placed on calendar",
    "ordered to be reported",
    "discharged",
    "agreed to",
    "became public law",
    "vetoed",
    "signed by president",
    "presented to president",
    "received in the senate",
    "motion to reconsider",
    "failed of passage",
    "resolving differences",
    "conference",
]


def _get_current_congress():
    """Congress numbers increment every 2 years starting Jan 3 of odd years;
    the 118th Congress began 2023-01-03. This is an approximation (doesn't
    special-case the Jan 1-2 handover of odd years) - the API has no
    "current congress" lookup endpoint to query this directly."""
    import datetime

    year = datetime.date.today().year
    return 118 + (year - 2023) // 2


def _api_get(path, params=None):
    """GET a Congress.gov API endpoint, injecting the API key and handling
    errors/timeouts/rate limits gracefully."""
    api_key = os.environ.get("CONGRESS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CONGRESS_API_KEY environment variable is not set. Sign up for a "
            "free key at https://api.congress.gov/sign-up/ and set it with: "
            'PowerShell:  $env:CONGRESS_API_KEY = "your-key-here"'
        )

    params = dict(params or {})
    params["api_key"] = api_key
    params["format"] = "json"
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(1, 4):
        try:
            resp = requests.get(f"{BASE_URL}{path}", params=params, headers=headers, timeout=15)
        except requests.exceptions.Timeout:
            print(f"[CONGRESS] Timeout on {path} (attempt {attempt}/3), retrying...")
            time.sleep(2 * attempt)
            continue
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Network error fetching {path}: {exc}") from exc

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 403:
            raise RuntimeError(f"HTTP 403 on {path}: {resp.text[:300]} - check that CONGRESS_API_KEY is valid.")

        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"[CONGRESS] Rate limited (HTTP 429) on {path}. Backing off {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            print(f"[CONGRESS] Server error {resp.status_code} on {path}, retrying...")
            time.sleep(2 * attempt)
            continue

        raise RuntimeError(f"HTTP {resp.status_code} on {path}: {resp.text[:300]}")

    raise RuntimeError(f"Gave up on {path} after repeated failures.")


def _get_committee_bill_count(congress, code):
    data = _api_get(f"/committee/{congress}/{CHAMBER}/{code}/bills", {"limit": 1})
    return data.get("pagination", {}).get("count", 0)


def _fetch_recent_committee_referrals(congress, code, sample_size):
    """Return the most recent `sample_size` (bill_type, bill_number) pairs
    referred to this committee, using the offset trick described in the
    module docstring (the endpoint is always ascending-chronological)."""
    total = _get_committee_bill_count(congress, code)
    if total == 0:
        return []

    offset = max(0, total - sample_size)
    data = _api_get(
        f"/committee/{congress}/{CHAMBER}/{code}/bills",
        {"limit": sample_size, "offset": offset},
    )
    entries = data.get("committee-bills", {}).get("bills", [])
    return [(b["type"], b["number"]) for b in entries]


def _fetch_bill_detail(congress, bill_type, bill_number):
    data = _api_get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}")
    return data.get("bill", {})


def _is_in_committee(latest_action_text):
    text = (latest_action_text or "").lower()
    if any(kw in text for kw in ADVANCED_STAGE_KEYWORDS):
        return False
    return "committee" in text or "referred" in text


def _map_row(bill_detail, committee_labels):
    sponsors = bill_detail.get("sponsors") or []
    sponsor = sponsors[0].get("fullName", "Unknown") if sponsors else "Unknown"
    bill_number = f"{bill_detail.get('type', '')} {bill_detail.get('number', '')}".strip()
    bill_type = bill_number.split(" ")[0] if bill_number else ""

    return {
        "signal_id": f"CONGRESS-{bill_number.replace(' ', '')}" if bill_number else "",
        "title": bill_detail.get("title", ""),
        "entity": "; ".join(committee_labels),
        "date": bill_detail.get("introducedDate", ""),
        "category": bill_type,
        "url": bill_detail.get("legislationUrl", ""),
        "summary": f"Sponsor: {sponsor}" if sponsor else "",
    }


class CongressSource(Source):
    name = "CONGRESS"

    def fetch(self) -> list[dict]:
        congress = _get_current_congress()
        # Bills are often jointly referred to multiple committees (e.g. a
        # defense-adjacent bill going to both Armed Services and Energy and
        # Commerce). Track by bill key so a jointly-referred bill produces
        # ONE signal with a combined entity, not duplicate signal_ids -
        # Postgres's upsert rejects a batch that hits the same conflict key
        # twice. Also avoids re-fetching bill detail for the same bill.
        bills = {}  # bill_key -> {"detail": dict, "committees": [label, ...]}

        for code, label in TARGET_COMMITTEES.items():
            print(f"[{self.name}] Committee: {label} ({code})")
            referrals = _fetch_recent_committee_referrals(congress, code, RAW_SAMPLE_PER_COMMITTEE)
            print(f"[{self.name}]   -> inspecting {len(referrals)} most recent referrals for detail/status...")

            for bill_type, bill_number in referrals:
                bill_key = (bill_type, bill_number)

                if bill_key in bills:
                    bills[bill_key]["committees"].append(label)
                    continue

                detail = _fetch_bill_detail(congress, bill_type, bill_number)
                latest_action_text = detail.get("latestAction", {}).get("text", "")

                if _is_in_committee(latest_action_text):
                    bills[bill_key] = {"detail": detail, "committees": [label]}

                time.sleep(0.1)  # be polite between per-bill detail calls

        signals = []
        for entry in bills.values():
            signal = _map_row(entry["detail"], entry["committees"])
            signal["source"] = self.name
            signals.append(signal)
        return signals


if __name__ == "__main__":
    _signals = CongressSource().fetch()
    print(f"\n{len(_signals)} signals fetched.")
    if _signals:
        print(_signals[0])
