"""USAspending.gov source.

Fetches the last DAYS_BACK days of contract awards for a fixed set of
target agencies (NRC, DOE, Commerce, DoD) and normalizes them to
SIGNAL_FIELDS. Fetch/pagination logic and the row-mapping are carried over
unchanged from Phase 0's scripts/usaspending_fetch.py and
scripts/integration_fetch.py's map_usaspending_row().

Data source: POST https://api.usaspending.gov/api/v2/search/spending_by_award/
Public REST API, no API key / auth required.

Key quirks (verified against the live API - see Phase 0 script history):
  - JSON POST body (filters/fields/page/limit/sort/order), not GET params.
  - `sort` field must also be present in `fields`, or the API 400s.
  - `award_type_codes` is required; we use contract codes A/B/C/D.
  - No "Action Date" output field exists; "Last Modified Date" is the
    closest proxy for recency and is what we sort/display.
  - `filters.agencies` entries OR together in one request.
  - Pagination is cursor-style: page_metadata.hasNext (bool).
"""

import time

import requests

from agent.sources.base import Source

SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Verified toptier agency names -> short labels.
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


def _fetch_page(start_date, end_date, page):
    """Fetch one page of results via POST. Returns the parsed JSON dict, or
    raises on unrecoverable errors."""
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
            print(f"[USASPENDING] Timeout on page {page} (attempt {attempt}/3), retrying...")
            time.sleep(2 * attempt)
            continue
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Network error fetching page {page}: {exc}") from exc

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"[USASPENDING] Rate limited (HTTP 429) on page {page}. Backing off {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            print(f"[USASPENDING] Server error {resp.status_code} on page {page}, retrying...")
            time.sleep(2 * attempt)
            continue

        raise RuntimeError(f"USAspending API returned HTTP {resp.status_code} on page {page}: {resp.text[:300]}")

    raise RuntimeError(f"Gave up on page {page} after repeated failures.")


def _fetch_awards(start_date, end_date):
    """Fetch pages until we have at least MIN_DOCUMENTS or run out of pages."""
    all_awards = []
    page = 1

    while True:
        print(f"[USASPENDING] Fetching page {page} (limit={PAGE_LIMIT})...")
        data = _fetch_page(start_date, end_date, page)

        results = data.get("results", [])
        all_awards.extend(results)

        page_metadata = data.get("page_metadata", {})
        has_next = page_metadata.get("hasNext", False)

        if not results or not has_next:
            break
        if len(all_awards) >= MIN_DOCUMENTS:
            break

        page += 1
        time.sleep(0.25)  # be polite between page requests

    return all_awards


def _agency_label(awarding_agency):
    return TARGET_AGENCIES.get(awarding_agency, awarding_agency or "Unknown")


def _map_row(award):
    recipient = (award.get("Recipient Name") or "").strip()
    description = (award.get("Description") or "").strip()
    title = f"{recipient} - {description}" if recipient and description else (description or recipient or "Untitled award")

    internal_id = award.get("generated_internal_id", "")
    url = f"https://www.usaspending.gov/award/{internal_id}" if internal_id else ""

    return {
        "signal_id": f"USA-{internal_id}" if internal_id else "",
        "title": title,
        "entity": _agency_label(award.get("Awarding Agency")),
        "date": award.get("Last Modified Date", ""),
        "category": award.get("Contract Award Type", ""),
        "url": url,
        "summary": description,
    }


class UsaspendingSource(Source):
    name = "USASPENDING"

    def fetch(self) -> list[dict]:
        import datetime

        end = datetime.date.today()
        start = end - datetime.timedelta(days=DAYS_BACK)

        raw_awards = _fetch_awards(start.isoformat(), end.isoformat())

        signals = []
        for award in raw_awards:
            signal = _map_row(award)
            signal["source"] = self.name
            signals.append(signal)
        return signals


if __name__ == "__main__":
    _signals = UsaspendingSource().fetch()
    print(f"\n{len(_signals)} signals fetched.")
    if _signals:
        print(_signals[0])
