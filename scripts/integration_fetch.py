#!/usr/bin/env python3
"""
Step 5 (Phase 0 integration validation): run all four source scripts
(SEC EDGAR, Federal Register, USAspending, Congress.gov), merge their
per-source CSVs into one unified schema, score data quality per source,
and report API health + Phase 1 recommendations.

This script does not talk to any API directly - it shells out to the four
existing scripts (scripts/sec_edgar_fetch.py, federal_register_fetch.py,
usaspending_fetch.py, congress_fetch.py), each of which writes its own
sample CSV to the repo root, then reads those CSVs back in and normalizes
them into a common "signal" shape.

Prerequisite: run this from the repo root (same convention as the other
four scripts), e.g.  `python scripts/integration_fetch.py`
Congress.gov requires CONGRESS_API_KEY to be set in the environment (see
congress_fetch.py's docstring) - if it's missing, that one source will
fail and be reported in the health section below, but the other three
sources still run and get merged.
"""

import csv
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_CSV = os.path.join(REPO_ROOT, "all_signals_sample.csv")
SUBPROCESS_TIMEOUT = 300  # seconds; Congress source alone can take ~90s (N+1 API calls)

UNIFIED_FIELDS = ["source", "signal_id", "title", "entity", "date", "category", "url", "summary"]
REQUIRED_FIELDS = ["title", "entity", "date", "url"]  # summary is tracked separately (see notes)


def map_sec_row(row):
    cik = (row.get("cik") or "").strip()
    accession = (row.get("accession_number") or "").strip()
    # Verified working format for the underlying filing's document folder
    # (the friendlier "-index.htm" summary page currently returns HTTP 503
    # from SEC even for older filings - confirmed live during planning;
    # this trailing-slash directory listing form returns 200 reliably).
    url = ""
    if cik and accession:
        cik_int = str(int(cik)) if cik.isdigit() else cik
        accession_nodash = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/"

    company = (row.get("company_name") or "").strip()
    form_type = (row.get("form_type") or "").strip()
    title = f"{form_type} - {company}".strip(" -") if (form_type or company) else ""

    return {
        "signal_id": f"SEC-{accession}" if accession else "",
        "title": title,
        "entity": company,
        "date": row.get("filing_date", ""),
        "category": form_type,
        "url": url,
        "summary": "",  # SEC EDGAR CSV has no abstract/summary field at all
    }


def map_federal_register_row(row):
    url = (row.get("url") or "").strip()
    doc_number = ""
    if url:
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            doc_number = parts[-2]  # e.g. .../2026/08/10/2026-16265/slug -> "2026-16265"

    return {
        "signal_id": f"FR-{doc_number}" if doc_number else "",
        "title": row.get("title", ""),
        "entity": row.get("agency_name", ""),
        "date": row.get("publication_date", ""),
        "category": row.get("document_type", ""),
        "url": url,
        "summary": row.get("summary", ""),
    }


def map_usaspending_row(row):
    url = (row.get("url") or "").strip()
    award_id = url.rstrip("/").split("/")[-1] if url else ""

    return {
        "signal_id": f"USA-{award_id}" if award_id else "",
        "title": row.get("title", ""),
        "entity": row.get("agency_name", ""),
        "date": row.get("publication_date", ""),
        "category": row.get("document_type", ""),
        "url": url,
        "summary": row.get("summary", ""),
    }


def map_congress_row(row):
    bill_number = (row.get("bill_number") or "").strip()
    bill_type = bill_number.split(" ")[0] if bill_number else ""
    sponsor = (row.get("sponsor") or "").strip()

    return {
        "signal_id": f"CONGRESS-{bill_number.replace(' ', '')}" if bill_number else "",
        "title": row.get("title", ""),
        "entity": row.get("committee", ""),
        "date": row.get("introduced_date", ""),
        "category": bill_type,
        "url": row.get("url", ""),
        "summary": f"Sponsor: {sponsor}" if sponsor else "",
    }


SOURCES = [
    {
        "name": "SEC_EDGAR",
        "script": "scripts/sec_edgar_fetch.py",
        "csv": "sec_edgar_sample.csv",
        "mapper": map_sec_row,
    },
    {
        "name": "FEDERAL_REGISTER",
        "script": "scripts/federal_register_fetch.py",
        "csv": "federal_register_sample.csv",
        "mapper": map_federal_register_row,
    },
    {
        "name": "USASPENDING",
        "script": "scripts/usaspending_fetch.py",
        "csv": "usaspending_sample.csv",
        "mapper": map_usaspending_row,
    },
    {
        "name": "CONGRESS",
        "script": "scripts/congress_fetch.py",
        "csv": "congress_sample.csv",
        "mapper": map_congress_row,
    },
]


def run_source_script(entry):
    """Run one source script as a subprocess. Never raises - returns a
    health dict so one failing source doesn't stop the others."""
    script_path = os.path.join(REPO_ROOT, entry["script"])
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        duration = time.time() - start
        success = result.returncode == 0
        return {
            "success": success,
            "duration": duration,
            "error_tail": "" if success else (result.stderr or result.stdout)[-400:],
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "duration": time.time() - start,
            "error_tail": f"Timed out after {SUBPROCESS_TIMEOUT}s",
        }
    except OSError as exc:
        return {"success": False, "duration": time.time() - start, "error_tail": str(exc)}


def read_source_rows(entry):
    csv_path = os.path.join(REPO_ROOT, entry["csv"])
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def compute_quality(mapped_rows):
    total = len(mapped_rows)
    missing_counts = {field: 0 for field in UNIFIED_FIELDS if field not in ("source",)}
    required_complete = 0
    summary_present = 0

    for row in mapped_rows:
        for field in missing_counts:
            if not (row.get(field) or "").strip():
                missing_counts[field] += 1
        if all((row.get(f) or "").strip() for f in REQUIRED_FIELDS):
            required_complete += 1
        if (row.get("summary") or "").strip():
            summary_present += 1

    return {
        "total": total,
        "required_complete": required_complete,
        "required_complete_pct": (required_complete / total * 100) if total else 0.0,
        "summary_coverage_pct": (summary_present / total * 100) if total else 0.0,
        "missing_counts": missing_counts,
    }


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=UNIFIED_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    print("=== Running Phase 0 source scripts ===\n")

    health = {}
    quality = {}
    all_rows = []

    for entry in SOURCES:
        print(f"[{entry['name']}] running {entry['script']} ...")
        result = run_source_script(entry)
        health[entry["name"]] = result

        if result["success"]:
            print(f"[{entry['name']}] OK ({result['duration']:.1f}s)")
        else:
            print(f"[{entry['name']}] FAILED ({result['duration']:.1f}s): {result['error_tail'].strip()[-200:]}")

        raw_rows = read_source_rows(entry)
        mapped_rows = [entry["mapper"](r) for r in raw_rows]
        for row in mapped_rows:
            row["source"] = entry["name"]
        all_rows.extend(mapped_rows)
        quality[entry["name"]] = compute_quality(mapped_rows)
        print(f"[{entry['name']}] {len(mapped_rows)} rows merged\n")

    write_csv(all_rows, OUTPUT_CSV)

    combined_quality = compute_quality(all_rows)

    print("=== CONSOLIDATED SUMMARY ===\n")

    print("Total signals fetched:")
    for entry in SOURCES:
        print(f"  {entry['name']:18s}: {quality[entry['name']]['total']}")
    print(f"  {'COMBINED':18s}: {len(all_rows)}")
    print(f"\nCSV written to: {OUTPUT_CSV}\n")

    print("Data quality report (% of records with all required fields: title, entity, date, url):")
    for entry in SOURCES:
        q = quality[entry["name"]]
        print(f"  {entry['name']:18s}: {q['required_complete_pct']:5.1f}%  "
              f"(summary/abstract present: {q['summary_coverage_pct']:5.1f}%)")
    print(f"  {'COMBINED':18s}: {combined_quality['required_complete_pct']:5.1f}%\n")

    print("Missing-field breakdown by source:")
    for entry in SOURCES:
        missing = quality[entry["name"]]["missing_counts"]
        nonzero = {k: v for k, v in missing.items() if v > 0}
        if nonzero:
            print(f"  {entry['name']}: " + ", ".join(f"{k}={v}" for k, v in nonzero.items()))
        else:
            print(f"  {entry['name']}: no missing fields")

    print("\nAPI health notes:")
    any_failed = False
    for entry in SOURCES:
        h = health[entry["name"]]
        if h["success"]:
            print(f"  {entry['name']}: OK, completed in {h['duration']:.1f}s")
        else:
            any_failed = True
            print(f"  {entry['name']}: FAILED - {h['error_tail'].strip().splitlines()[-1] if h['error_tail'].strip() else 'unknown error'}")
    if not any_failed:
        print("  No source failures this run.")

    print("\nRecommendations for Phase 1 integration:")
    print("  1. Each source has a different pagination model (SEC: atom feed / no")
    print("     paging needed; Federal Register: page+per_page with total_pages;")
    print("     USAspending: cursor-style page_metadata.hasNext; Congress: offset+limit")
    print("     with no server-side sort). agent/sources/ modules should NOT share a")
    print("     generic paginator - keep per-source pagination logic, as done here.")
    print("  2. Congress.gov is the only source requiring an API key/auth. Phase 1's")
    print("     agent/sources/congress_source.py must read CONGRESS_API_KEY from a")
    print("     secret store (not hardcoded, not committed) - mirror this script's")
    print("     approach. It's also the only source with a documented hard rate limit")
    print("     (5,000 req/hr) - the N+1 per-bill detail calls should be batched or")
    print("     cached if Phase 1 scales beyond a handful of committees.")
    print("  3. 'summary' coverage is inherently uneven: SEC EDGAR has no")
    print("     summary/abstract field at all (0% by design, not a bug), and Federal")
    print("     Register/USAspending abstracts are frequently blank for routine")
    print("     notices. Don't treat blank summary as a data-quality failure in")
    print("     Phase 1 scoring - only title/entity/date/url should gate signal")
    print("     acceptance into the database.")
    print("  4. SEC EDGAR's official '-index.htm' filing-summary URL currently")
    print("     returns HTTP 503 (confirmed live, including for older filings) - use")
    print("     the '.../data/{cik}/{accession_nodash}/' directory-listing URL instead")
    print("     (verified 200), as this script does.")
    print("  5. Unified schema used here (source, signal_id, title, entity, date,")
    print("     category, url, summary) is a reasonable starting point for the")
    print("     Supabase 'signals' table Phase 1 needs to create - signal_id is")
    print("     already unique per source+record and can double as a natural key.")


if __name__ == "__main__":
    main()
