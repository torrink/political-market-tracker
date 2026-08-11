#!/usr/bin/env python3
"""
Fetch the most recent SEC EDGAR filings and extract 8-K entries to CSV.

Data source note
-----------------
SEC EDGAR does not expose a single "give me the last N filings across every
company" endpoint under data.sec.gov. The Company Facts / Submissions APIs
under data.sec.gov are per-company only (you must already know a CIK), so
they can't be used to sample "the last 100 filings" system-wide.

The actual public, no-key endpoint for "latest filings across all filers" is
EDGAR's real-time filing feed:

    https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom

That's what this script uses. It's still plain REST/HTTP, needs no API key,
and is fetched with `requests` exactly like data.sec.gov would be.

SEC fair-access requirements (https://www.sec.gov/os/webmaster-faq#developers):
  - You MUST send a descriptive User-Agent with a real contact (name/email).
  - Keep requests under ~10/second (this script only issues one).
"""

import csv
import sys
import time
import xml.etree.ElementTree as ET

import requests

# SEC requires a descriptive User-Agent identifying you / your organization.
# Replace with your real name/company and a valid contact email before running.
USER_AGENT = "Political Tracker Research contact@example.com"

FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"


def build_params(form_type=""):
    return {
        "action": "getcurrent",
        "type": form_type,   # blank = all form types
        "company": "",
        "dateb": "",
        "owner": "include",
        "count": "100",      # last 100 filings
        "output": "atom",
    }

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
OUTPUT_CSV = "sec_edgar_sample.csv"


def fetch_feed(form_type=""):
    """Fetch the latest-filings Atom feed, handling HTTP errors and basic
    rate-limit backoff."""
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    params = build_params(form_type)

    for attempt in range(1, 4):
        try:
            resp = requests.get(FEED_URL, params=params, headers=headers, timeout=15)
        except requests.exceptions.RequestException as exc:
            print(f"[ERROR] Network error fetching EDGAR feed: {exc}", file=sys.stderr)
            sys.exit(1)

        if resp.status_code == 200:
            return resp.text

        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"[WARN] Rate limited (HTTP 429). Backing off {wait}s (attempt {attempt}/3)...")
            time.sleep(wait)
            continue

        print(f"[ERROR] EDGAR returned HTTP {resp.status_code}: {resp.reason}", file=sys.stderr)
        sys.exit(1)

    print("[ERROR] Gave up after repeated rate-limit (429) responses.", file=sys.stderr)
    sys.exit(1)


def parse_filings(xml_text):
    """Parse the Atom feed into a list of filing dicts."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        print(f"[ERROR] Failed to parse EDGAR Atom feed: {exc}", file=sys.stderr)
        sys.exit(1)

    filings = []
    for entry in root.findall("a:entry", ATOM_NS):
        title_el = entry.find("a:title", ATOM_NS)
        updated_el = entry.find("a:updated", ATOM_NS)
        id_el = entry.find("a:id", ATOM_NS)

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        updated = updated_el.text.strip() if updated_el is not None and updated_el.text else ""
        entry_id = id_el.text.strip() if id_el is not None and id_el.text else ""

        # Title format: "8-K - COMPANY NAME (0001234567) (Filer)"
        form_type, company_name, cik = "", "", ""
        if " - " in title:
            form_type, rest = title.split(" - ", 1)
            form_type = form_type.strip()
            if "(" in rest:
                name_part, paren_part = rest.split("(", 1)
                company_name = name_part.strip()
                cik_digits = "".join(ch for ch in paren_part.split(")")[0] if ch.isdigit())
                cik = cik_digits
            else:
                company_name = rest.strip()

        # id format: "urn:tag:sec.gov,2008:accession-number=0001234567-25-000123"
        accession_number = ""
        if "accession-number=" in entry_id:
            accession_number = entry_id.split("accession-number=", 1)[1].strip()

        filing_date = updated.split("T")[0] if "T" in updated else updated

        if not (company_name or cik or accession_number):
            continue  # skip malformed entries rather than fail the whole run

        filings.append(
            {
                "company_name": company_name,
                "cik": cik,
                "accession_number": accession_number,
                "filing_date": filing_date,
                "form_type": form_type,
            }
        )

    return filings


def write_csv(rows, path):
    fieldnames = ["company_name", "cik", "accession_number", "filing_date", "form_type"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    count = build_params()["count"]

    print(f"Fetching last {count} SEC EDGAR filings (all form types)...")
    all_filings = parse_filings(fetch_feed())

    eight_ks_in_sample = [f for f in all_filings if f["form_type"].upper() == "8-K"]

    # EDGAR's unfiltered "latest filings" window is dominated by high-volume
    # forms (Form 4, Schedule 13G, etc). 8-Ks are comparatively rare, so a
    # 100-filing all-type window frequently contains zero of them. To produce
    # a real, useful 8-K sample we also query EDGAR's server-side type filter
    # directly (type=8-K), which is the correct way to pull 8-Ks specifically.
    print(f"Fetching last {count} SEC EDGAR 8-K filings (type-filtered)...")
    eight_ks = parse_filings(fetch_feed(form_type="8-K"))
    eight_ks = [f for f in eight_ks if f["form_type"].upper() == "8-K"]

    write_csv(eight_ks, OUTPUT_CSV)

    print("\n=== SUMMARY ===")
    print(f"Total filings fetched (all types):     {len(all_filings)}")
    print(f"  of which 8-K in that same window:    {len(eight_ks_in_sample)}")
    print(f"8-K filings found (type-filtered pull): {len(eight_ks)}")
    print(f"CSV written to:                         {OUTPUT_CSV}")

    if not eight_ks:
        print("\nNo 8-K filings were present in this sample window.")
    else:
        print("\nSample of up to 5 8-K entries:")
        for row in eight_ks[:5]:
            print(
                f"  company_name={row['company_name']!r} "
                f"cik={row['cik']!r} "
                f"accession_number={row['accession_number']!r} "
                f"filing_date={row['filing_date']!r} "
                f"form_type={row['form_type']!r}"
            )

    if len(all_filings) < int(count):
        print(
            f"\n[NOTE] All-types feed returned only {len(all_filings)} of the "
            f"requested {count} entries — this is normal if EDGAR has had "
            f"fewer filings than that recently, or entries were skipped as malformed."
        )


if __name__ == "__main__":
    main()
