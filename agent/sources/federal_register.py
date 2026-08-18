"""Federal Register source.

Fetches the last DAYS_BACK days of documents for a fixed set of target
agencies (NRC, DOE, Commerce, DoD) and normalizes them to SIGNAL_FIELDS.
Fetch/pagination logic and the row-mapping are carried over unchanged from
Phase 0's scripts/federal_register_fetch.py and
scripts/integration_fetch.py's map_federal_register_row().

Data source: https://www.federalregister.gov/api/v1/documents.json
Public REST API, no API key / auth required.
"""

import time

import requests

from agent.sources.base import Source

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

USER_AGENT = "Political Tracker Research contact@example.com"

FIELDS = ["title", "agencies", "publication_date", "type", "html_url", "abstract"]


def _fetch_page(start_date, end_date, page):
    """Fetch one page of results. Returns the parsed JSON dict, or raises on
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
            print(f"[FEDERAL_REGISTER] Timeout on page {page} (attempt {attempt}/3), retrying...")
            time.sleep(2 * attempt)
            continue
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Network error fetching page {page}: {exc}") from exc

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"[FEDERAL_REGISTER] Rate limited (HTTP 429) on page {page}. Backing off {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            print(f"[FEDERAL_REGISTER] Server error {resp.status_code} on page {page}, retrying...")
            time.sleep(2 * attempt)
            continue

        raise RuntimeError(f"Federal Register API returned HTTP {resp.status_code} on page {page}: {resp.text[:300]}")

    raise RuntimeError(f"Gave up on page {page} after repeated failures.")


def _matched_agency_label(agencies):
    """Given a document's list of agency dicts, return the short label(s)
    (NRC/DOE/Commerce/DoD) for whichever of our target agencies it belongs
    to. A document can match more than one, so join with '; '."""
    labels = []
    for agency in agencies or []:
        slug = agency.get("slug", "")
        if slug in TARGET_AGENCIES:
            labels.append(TARGET_AGENCIES[slug])
    if labels:
        return "; ".join(dict.fromkeys(labels))  # dedupe, keep order
    if agencies:
        return agencies[0].get("name", "Unknown")
    return "Unknown"


def _fetch_documents(start_date, end_date):
    """Fetch pages until we have at least MIN_DOCUMENTS or run out of pages."""
    all_docs = []
    page = 1
    total_pages = None

    while True:
        print(f"[FEDERAL_REGISTER] Fetching page {page} (per_page={PER_PAGE})...")
        data = _fetch_page(start_date, end_date, page)

        if total_pages is None:
            total_pages = data.get("total_pages", 0)

        results = data.get("results", [])
        all_docs.extend(results)

        if not results:
            break
        if len(all_docs) >= MIN_DOCUMENTS:
            break
        if total_pages and page >= total_pages:
            break

        page += 1
        time.sleep(0.25)  # be polite between page requests

    return all_docs


def _map_row(doc):
    url = (doc.get("html_url") or "").strip()
    doc_number = ""
    if url:
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            doc_number = parts[-2]  # e.g. .../2026/08/10/2026-16265/slug -> "2026-16265"

    return {
        "signal_id": f"FR-{doc_number}" if doc_number else "",
        "title": (doc.get("title") or "").strip(),
        "entity": _matched_agency_label(doc.get("agencies")),
        "date": doc.get("publication_date", ""),
        "category": doc.get("type", ""),
        "url": url,
        "summary": (doc.get("abstract") or "").strip(),
    }


class FederalRegisterSource(Source):
    name = "FEDERAL_REGISTER"

    def fetch(self) -> list[dict]:
        import datetime

        end = datetime.date.today()
        start = end - datetime.timedelta(days=DAYS_BACK)

        raw_docs = _fetch_documents(start.isoformat(), end.isoformat())

        signals = []
        for doc in raw_docs:
            signal = _map_row(doc)
            signal["source"] = self.name
            signals.append(signal)
        return signals


if __name__ == "__main__":
    _signals = FederalRegisterSource().fetch()
    print(f"\n{len(_signals)} signals fetched.")
    if _signals:
        print(_signals[0])
