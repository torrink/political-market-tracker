#!/usr/bin/env python3
"""
Fetch bills currently "in committee" at three target House committees
(Armed Services, Appropriations, Energy and Commerce) from the Congress.gov
API and write them to CSV.

Data source
-----------
https://api.congress.gov/v3/  (Library of Congress)
Docs: https://github.com/LibraryOfCongress/api.congress.gov/

UNLIKE the SEC EDGAR / Federal Register / USAspending scripts in this repo,
this API REQUIRES a free API key. Sign up (instant, email-based) at:
    https://api.congress.gov/sign-up/
Then set it as an environment variable before running this script:
    PowerShell:  $env:CONGRESS_API_KEY = "your-key-here"
The key is never hardcoded here and is not written to the CSV/output.

Key facts used below (verified against the live API):
  - Auth: pass the key as a query param `api_key=...` (also supported via an
    `X-Api-Key` header, but the query param is simpler and confirmed working).
  - Documented rate limit: 5,000 requests/hour per key (per the API's own
    GitHub docs repo).
  - There is NO query param to filter the top-level bill list by committee.
    Instead, use the per-committee endpoint:
      GET /v3/committee/{congress}/{chamber}/{committeeCode}/bills
    which lists bills referred to that committee (bill number/type +
    referral actionDate only - no title/sponsor/status).
  - That endpoint's `sort` param is accepted but silently ignored - results
    are always in ascending chronological order by referral date. To get the
    MOST RECENT referrals without paging through everything, fetch the
    total `count` first (limit=1), then request with
    `offset = max(0, count - N)` to land on the last N (most recent) items.
  - Bill *detail* (title, sponsors, introducedDate, latestAction,
    legislationUrl) requires a separate call per bill:
      GET /v3/bill/{congress}/{billType}/{billNumber}
  - The v3 API has NO discrete bill-status field (no "In Committee" /
    "Passed House" enum like GovTrack provides). Status must be inferred
    from `latestAction.text`. This script uses a keyword heuristic (see
    `is_in_committee()`) - documented as an approximation, not a source of
    truth, in the summary output.
"""

import csv
import os
import sys
import time

import requests

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
MIN_DOCUMENTS = 50               # target minimum "in committee" bills, combined
OUTPUT_CSV = "congress_sample.csv"

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


def get_current_congress():
    """Congress numbers increment every 2 years starting Jan 3 of odd years;
    the 118th Congress began 2023-01-03. This is an approximation (doesn't
    special-case the Jan 1-2 handover of odd years) - the API has no
    "current congress" lookup endpoint to query this directly."""
    import datetime

    year = datetime.date.today().year
    return 118 + (year - 2023) // 2


def api_get(path, params=None):
    """GET a Congress.gov API endpoint, injecting the API key and handling
    errors/timeouts/rate limits gracefully."""
    api_key = os.environ.get("CONGRESS_API_KEY")
    if not api_key:
        print(
            "[ERROR] CONGRESS_API_KEY environment variable is not set.\n"
            "        Sign up for a free key at https://api.congress.gov/sign-up/ "
            "and set it with:\n"
            '        PowerShell:  $env:CONGRESS_API_KEY = "your-key-here"',
            file=sys.stderr,
        )
        sys.exit(1)

    params = dict(params or {})
    params["api_key"] = api_key
    params["format"] = "json"
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(1, 4):
        try:
            resp = requests.get(f"{BASE_URL}{path}", params=params, headers=headers, timeout=15)
        except requests.exceptions.Timeout:
            print(f"[WARN] Timeout on {path} (attempt {attempt}/3), retrying...")
            time.sleep(2 * attempt)
            continue
        except requests.exceptions.RequestException as exc:
            print(f"[ERROR] Network error fetching {path}: {exc}", file=sys.stderr)
            sys.exit(1)

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 403:
            print(
                f"[ERROR] HTTP 403 on {path}: {resp.text[:300]}\n"
                "        Check that CONGRESS_API_KEY is a valid key.",
                file=sys.stderr,
            )
            sys.exit(1)

        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"[WARN] Rate limited (HTTP 429) on {path}. Backing off {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            print(f"[WARN] Server error {resp.status_code} on {path}, retrying...")
            time.sleep(2 * attempt)
            continue

        print(f"[ERROR] HTTP {resp.status_code} on {path}: {resp.text[:300]}", file=sys.stderr)
        sys.exit(1)

    print(f"[ERROR] Gave up on {path} after repeated failures.", file=sys.stderr)
    sys.exit(1)


def get_committee_bill_count(congress, code):
    data = api_get(f"/committee/{congress}/{CHAMBER}/{code}/bills", {"limit": 1})
    return data.get("pagination", {}).get("count", 0)


def fetch_recent_committee_referrals(congress, code, sample_size):
    """Return the most recent `sample_size` (bill_type, bill_number) pairs
    referred to this committee, using the offset trick described in the
    module docstring (the endpoint is always ascending-chronological)."""
    total = get_committee_bill_count(congress, code)
    if total == 0:
        return []

    offset = max(0, total - sample_size)
    data = api_get(
        f"/committee/{congress}/{CHAMBER}/{code}/bills",
        {"limit": sample_size, "offset": offset},
    )
    entries = data.get("committee-bills", {}).get("bills", [])
    return [(b["type"], b["number"]) for b in entries]


def fetch_bill_detail(congress, bill_type, bill_number):
    data = api_get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}")
    return data.get("bill", {})


def is_in_committee(latest_action_text):
    text = (latest_action_text or "").lower()
    if any(kw in text for kw in ADVANCED_STAGE_KEYWORDS):
        return False
    return "committee" in text or "referred" in text


def build_row(bill_detail, committee_label):
    sponsors = bill_detail.get("sponsors") or []
    sponsor = sponsors[0].get("fullName", "Unknown") if sponsors else "Unknown"

    return {
        "bill_number": f"{bill_detail.get('type', '')} {bill_detail.get('number', '')}".strip(),
        "title": bill_detail.get("title", ""),
        "introduced_date": bill_detail.get("introducedDate", ""),
        "sponsor": sponsor,
        "committee": committee_label,
        "url": bill_detail.get("legislationUrl", ""),
    }


def write_csv(rows, path):
    fieldnames = ["bill_number", "title", "introduced_date", "sponsor", "committee", "url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    congress = get_current_congress()
    print(f"Fetching bills from the {congress}th Congress, filtered to committees: "
          f"{', '.join(TARGET_COMMITTEES.values())}")
    print("Status filter: 'In Committee' (heuristic - see script docstring)\n")

    rows = []
    breakdown = {label: 0 for label in TARGET_COMMITTEES.values()}
    considered = 0
    skipped_advanced = 0

    for code, label in TARGET_COMMITTEES.items():
        print(f"Committee: {label} ({code})")
        referrals = fetch_recent_committee_referrals(congress, code, RAW_SAMPLE_PER_COMMITTEE)
        print(f"  -> inspecting {len(referrals)} most recent referrals for detail/status...")

        for bill_type, bill_number in referrals:
            considered += 1
            detail = fetch_bill_detail(congress, bill_type, bill_number)
            latest_action_text = detail.get("latestAction", {}).get("text", "")

            if is_in_committee(latest_action_text):
                rows.append(build_row(detail, label))
                breakdown[label] += 1
            else:
                skipped_advanced += 1

            time.sleep(0.1)  # be polite between per-bill detail calls

        print(f"  -> {breakdown[label]} currently 'in committee' so far")

    write_csv(rows, OUTPUT_CSV)

    print("\n=== SUMMARY ===")
    print(f"Congress:                {congress}th")
    print(f"Bills inspected:         {considered}")
    print(f"Bills 'in committee':    {len(rows)}")
    print(f"Bills skipped (advanced past committee): {skipped_advanced}")
    print("Breakdown by committee:")
    for label, cnt in breakdown.items():
        print(f"  {label:20s}: {cnt}")
    print(f"CSV written to:          {OUTPUT_CSV}")

    if rows:
        print("\nSample of first 5 bills:")
        for row in rows[:5]:
            print(f"  bill_number:      {row['bill_number']}")
            print(f"  title:            {row['title']}")
            print(f"  introduced_date:  {row['introduced_date']}")
            print(f"  sponsor:          {row['sponsor']}")
            print(f"  committee:        {row['committee']}")
            print(f"  url:              {row['url']}")
            print()
    else:
        print("\nNo bills found matching the 'in committee' filter.")

    if len(rows) < MIN_DOCUMENTS:
        print(
            f"[NOTE] Only found {len(rows)} bills 'in committee', below the target of "
            f"{MIN_DOCUMENTS}. Increase RAW_SAMPLE_PER_COMMITTEE to inspect more referrals "
            f"per committee if you need a larger sample."
        )
    print(
        "[NOTE] Congress.gov's v3 API has no explicit bill-status field; the "
        "'in committee' classification above is a heuristic based on latestAction "
        "text and may misclassify edge cases."
    )


if __name__ == "__main__":
    main()
