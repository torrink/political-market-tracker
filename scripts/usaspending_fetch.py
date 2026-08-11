#!/usr/bin/env python3
"""
Fetch recent USAspending.gov contract awards for a set of target agencies
and write them to CSV.

Data source
-----------
POST https://api.usaspending.gov/api/v2/search/spending_by_award/
Public REST API, no API key / auth required. Docs:
https://api.usaspending.gov/docs/endpoints

Key facts used below (verified against the live API):
  - Unlike SEC EDGAR / Federal Register, this endpoint takes a JSON POST
    body (filters/fields/page/limit/sort/order), not GET query params.
  - The `sort` field MUST also be present in `fields`, or the API 400s with
    "Sort value 'X' not found in requested fields".
  - `award_type_codes` is required. We use contract codes A/B/C/D (BPA
    call, purchase order, delivery order, definitive contract) since
    NRC/DOE/Commerce/DoD are primarily contract spenders. Grant/loan codes
    (e.g. 02-08) exist for assistance awards but are out of scope here.
  - `time_period.date_type="action_date"` filters to activity within the
    window, but there is no corresponding "Action Date" *output* field for
    contract awards (confirmed via the API's own 400 error, which lists the
    full valid field set). "Last Modified Date" is the closest available
    proxy for recency and is what we sort/display.
  - `filters.agencies` entries OR together: passing all 4 target agencies
    in one request returns a mix of all of them, no need for 4 requests.
  - In USAspending's agency model, all military branches roll up under the
    single toptier "Department of Defense" (Army/Navy/Air Force are
    *subtier* agencies) - one filter entry captures all of DoD.
  - Pagination is cursor-style: page_metadata.hasNext (bool), not a
    total-pages count like the other two APIs.
  - No documented/enforced rate limit observed (no X-RateLimit-* headers).
"""

import csv
import sys
import time

import requests

SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Verified toptier agency names -> short labels used in the CSV/summary.
TARGET_AGENCIES = {
    "Nuclear Regulatory Commission": "NRC",
    "Department of Energy": "DOE",
    "Department of Commerce": "Commerce",
    "Department of Defense": "DoD",
}

# Contract award type codes: A=BPA call, B=Purchase order,
# C=Delivery order, D=Definitive contract.
AWARD_TYPE_CODES = ["A", "B", "C", "D"]

DAYS_BACK = 7
MIN_DOCUMENTS = 50
PAGE_LIMIT = 100       # awards per page (API max for this endpoint)
OUTPUT_CSV = "usaspending_sample.csv"

USER_AGENT = "Political Tracker Research contact@example.com"

FIELDS = [
    "Award ID",
    "Recipient Name",
    "Awarding Agency",
    "Award Amount",
    "Description",
    "Last Modified Date",
    "generated_internal_id",
    "Contract Award Type",
]
SORT_FIELD = "Last Modified Date"


def fetch_page(start_date, end_date, page):
    """Fetch one page of results via POST. Returns the parsed JSON dict, or
    exits on unrecoverable errors."""
    payload = {
        "filters": {
            "time_period": [
                {"start_date": start_date, "end_date": end_date, "date_type": "action_date"}
            ],
            "award_type_codes": AWARD_TYPE_CODES,
            "agencies": [
                {"type": "awarding", "tier": "toptier", "name": name}
                for name in TARGET_AGENCIES
            ],
        },
        "fields": FIELDS,
        "page": page,
        "limit": PAGE_LIMIT,
        "sort": SORT_FIELD,
        "order": "desc",
    }
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}

    for attempt in range(1, 4):
        try:
            resp = requests.post(SEARCH_URL, json=payload, headers=headers, timeout=20)
        except requests.exceptions.Timeout:
            print(f"[WARN] Timeout on page {page} (attempt {attempt}/3), retrying...")
            time.sleep(2 * attempt)
            continue
        except requests.exceptions.RequestException as exc:
            print(f"[ERROR] Network error fetching page {page}: {exc}", file=sys.stderr)
            sys.exit(1)

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"[WARN] Rate limited (HTTP 429) on page {page}. Backing off {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            print(f"[WARN] Server error {resp.status_code} on page {page}, retrying...")
            time.sleep(2 * attempt)
            continue

        print(
            f"[ERROR] USAspending API returned HTTP {resp.status_code} "
            f"on page {page}: {resp.text[:300]}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[ERROR] Gave up on page {page} after repeated failures.", file=sys.stderr)
    sys.exit(1)


def fetch_awards(start_date, end_date):
    """Fetch pages until we have at least MIN_DOCUMENTS or run out of pages."""
    all_awards = []
    page = 1

    while True:
        print(f"Fetching page {page} (limit={PAGE_LIMIT})...")
        data = fetch_page(start_date, end_date, page)

        results = data.get("results", [])
        all_awards.extend(results)
        print(f"  -> got {len(results)} awards this page (running total: {len(all_awards)})")

        page_metadata = data.get("page_metadata", {})
        has_next = page_metadata.get("hasNext", False)

        if not results or not has_next:
            break
        if len(all_awards) >= MIN_DOCUMENTS:
            break

        page += 1
        time.sleep(0.25)  # be polite between page requests

    return all_awards


def agency_label(awarding_agency):
    return TARGET_AGENCIES.get(awarding_agency, awarding_agency or "Unknown")


def build_rows(raw_awards):
    rows = []
    for award in raw_awards:
        recipient = (award.get("Recipient Name") or "").strip()
        description = (award.get("Description") or "").strip()
        title = f"{recipient} - {description}" if recipient and description else (description or recipient or "Untitled award")

        internal_id = award.get("generated_internal_id", "")
        url = f"https://www.usaspending.gov/award/{internal_id}" if internal_id else ""

        rows.append(
            {
                "title": title,
                "agency_name": agency_label(award.get("Awarding Agency")),
                "publication_date": award.get("Last Modified Date", ""),
                "document_type": award.get("Contract Award Type", ""),
                "url": url,
                "summary": description,
            }
        )
    return rows


def write_csv(rows, path):
    fieldnames = ["title", "agency_name", "publication_date", "document_type", "url", "summary"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    import datetime

    end = datetime.date.today()
    start = end - datetime.timedelta(days=DAYS_BACK)
    start_str, end_str = start.isoformat(), end.isoformat()

    print(f"Fetching USAspending.gov contract awards from {start_str} to {end_str}")
    print(f"Target agencies: {', '.join(TARGET_AGENCIES.values())}")

    raw_awards = fetch_awards(start_str, end_str)
    rows = build_rows(raw_awards)
    write_csv(rows, OUTPUT_CSV)

    breakdown = {label: 0 for label in TARGET_AGENCIES.values()}
    for row in rows:
        if row["agency_name"] in breakdown:
            breakdown[row["agency_name"]] += 1

    print("\n=== SUMMARY ===")
    print(f"Date range:              {start_str} to {end_str}")
    print(f"Total documents fetched: {len(rows)}")
    print("Breakdown by agency:")
    for label, cnt in breakdown.items():
        print(f"  {label:10s}: {cnt}")
    print(f"CSV written to:          {OUTPUT_CSV}")

    if rows:
        print("\nSample of first 5 documents:")
        for row in rows[:5]:
            print(f"  title:             {row['title']}")
            print(f"  agency_name:       {row['agency_name']}")
            print(f"  publication_date:  {row['publication_date']}")
            print(f"  document_type:     {row['document_type']}")
            print(f"  url:               {row['url']}")
            summary = row["summary"]
            print(f"  summary:           {summary[:200]}{'...' if len(summary) > 200 else ''}")
            print()
    else:
        print("\nNo awards found in this window for the target agencies.")

    if len(rows) < MIN_DOCUMENTS:
        print(
            f"[NOTE] Fetched {len(rows)} documents, fewer than the requested minimum of "
            f"{MIN_DOCUMENTS}. This means the target agencies had fewer than "
            f"{MIN_DOCUMENTS} contract actions combined in the last {DAYS_BACK} days, "
            f"or pagination was exhausted (hasNext=False)."
        )


if __name__ == "__main__":
    main()
