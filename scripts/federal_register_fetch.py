#!/usr/bin/env python3
"""
Fetch recent Federal Register documents for a set of target agencies and
write them to CSV.

Data source
-----------
https://www.federalregister.gov/api/v1/documents.json
Public REST API, no API key / auth required. Full docs:
https://www.federalregister.gov/developers/documentation/api/v1

Key facts used below (verified against the live API):
  - Agencies are filtered server-side via conditions[agencies][]=<slug>,
    e.g. "nuclear-regulatory-commission", "energy-department",
    "commerce-department", "defense-department".
  - Date range is filtered server-side via
    conditions[publication_date][gte]/[lte]=YYYY-MM-DD.
  - fields[]=... lets you request only the fields you need (smaller payload).
  - Pagination is page/per_page (max per_page is 1000); the response
    includes "count" (total matches) and "total_pages".
  - A document can list multiple agencies (a top-level department plus a
    sub-agency, e.g. "Commerce Department" + "International Trade
    Administration"), so agency matching has to check the whole list,
    not just the first entry.
"""

import csv
import sys
import time

import requests

BASE_URL = "https://www.federalregister.gov/api/v1/documents.json"

# Federal Register agency slugs for our target agencies.
# (Looked up via https://www.federalregister.gov/api/v1/agencies.json)
TARGET_AGENCIES = {
    "nuclear-regulatory-commission": "NRC",
    "energy-department": "DOE",
    "commerce-department": "Commerce",
    "defense-department": "DoD",
}

DAYS_BACK = 7
MIN_DOCUMENTS = 50   # fetch at least this many via pagination, if available
PER_PAGE = 100        # documents per page (API max is 1000)
OUTPUT_CSV = "federal_register_sample.csv"

USER_AGENT = "Political Tracker Research contact@example.com"

FIELDS = [
    "title",
    "agencies",
    "publication_date",
    "type",
    "html_url",
    "abstract",
]


def fetch_page(start_date, end_date, page):
    """Fetch one page of results. Returns the parsed JSON dict, or exits on
    unrecoverable errors."""
    params = {
        "conditions[publication_date][gte]": start_date,
        "conditions[publication_date][lte]": end_date,
        "conditions[agencies][]": list(TARGET_AGENCIES.keys()),
        "per_page": PER_PAGE,
        "page": page,
        "order": "newest",
        "fields[]": FIELDS,
    }
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(1, 4):
        try:
            resp = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
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
            f"[ERROR] Federal Register API returned HTTP {resp.status_code} "
            f"on page {page}: {resp.text[:300]}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[ERROR] Gave up on page {page} after repeated failures.", file=sys.stderr)
    sys.exit(1)


def matched_agency_label(agencies):
    """Given a document's list of agency dicts, return the short label(s)
    (NRC/DOE/Commerce/DoD) for whichever of our target agencies it belongs
    to. A document can match more than one (rare, but possible for joint
    notices), so join with '; '."""
    labels = []
    for agency in agencies or []:
        slug = agency.get("slug", "")
        if slug in TARGET_AGENCIES:
            labels.append(TARGET_AGENCIES[slug])
    if labels:
        return "; ".join(dict.fromkeys(labels))  # dedupe, keep order
    # Shouldn't normally happen since we filter server-side, but fall back
    # to whatever the API listed as the primary agency name.
    if agencies:
        return agencies[0].get("name", "Unknown")
    return "Unknown"


def fetch_documents(start_date, end_date):
    """Fetch pages until we have at least MIN_DOCUMENTS or run out of pages."""
    all_docs = []
    page = 1
    total_count = None
    total_pages = None

    while True:
        print(f"Fetching page {page} (per_page={PER_PAGE})...")
        data = fetch_page(start_date, end_date, page)

        if total_count is None:
            total_count = data.get("count", 0)
            total_pages = data.get("total_pages", 0)
            print(f"API reports {total_count} total matching documents across {total_pages} page(s).")

        results = data.get("results", [])
        all_docs.extend(results)
        print(f"  -> got {len(results)} documents this page (running total: {len(all_docs)})")

        if not results:
            break
        if len(all_docs) >= MIN_DOCUMENTS:
            break
        if total_pages and page >= total_pages:
            break

        page += 1
        time.sleep(0.25)  # be polite between page requests

    return all_docs, total_count


def build_rows(raw_docs):
    rows = []
    for doc in raw_docs:
        rows.append(
            {
                "title": doc.get("title", "").strip(),
                "agency_name": matched_agency_label(doc.get("agencies")),
                "publication_date": doc.get("publication_date", ""),
                "document_type": doc.get("type", ""),
                "url": doc.get("html_url", ""),
                "summary": (doc.get("abstract") or "").strip(),
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

    print(f"Fetching Federal Register documents from {start_str} to {end_str}")
    print(f"Target agencies: {', '.join(TARGET_AGENCIES.values())}")

    raw_docs, total_count = fetch_documents(start_str, end_str)
    rows = build_rows(raw_docs)
    write_csv(rows, OUTPUT_CSV)

    breakdown = {label: 0 for label in TARGET_AGENCIES.values()}
    for row in rows:
        for label in row["agency_name"].split("; "):
            if label in breakdown:
                breakdown[label] += 1

    print("\n=== SUMMARY ===")
    print(f"Date range:              {start_str} to {end_str}")
    print(f"Total documents fetched: {len(rows)} (API total available: {total_count})")
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
        print("\nNo documents found in this window for the target agencies.")

    if total_count is not None and len(rows) < min(MIN_DOCUMENTS, total_count):
        print(
            f"[NOTE] Fetched {len(rows)} documents, fewer than the requested minimum of "
            f"{MIN_DOCUMENTS}. This means the target agencies published fewer than "
            f"{MIN_DOCUMENTS} documents combined in the last {DAYS_BACK} days."
        )


if __name__ == "__main__":
    main()
