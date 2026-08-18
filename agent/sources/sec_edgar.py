"""SEC EDGAR source.

Fetches recent 8-K filings from EDGAR's public real-time filing feed and
normalizes them to SIGNAL_FIELDS. Fetch/parse logic and the URL-construction
quirk (the official "-index.htm" filing page currently 503s, even for older
filings - confirmed live; the trailing-slash directory-listing URL works)
are carried over unchanged from Phase 0's scripts/sec_edgar_fetch.py and
scripts/integration_fetch.py's map_sec_row().

SEC fair-access requirements (https://www.sec.gov/os/webmaster-faq#developers):
  - Requires a descriptive User-Agent with a real contact (name/email).
  - Keep requests under ~10/second (this source only issues two).
"""

import sys
import time
import xml.etree.ElementTree as ET

import requests

from agent.sources.base import Source

USER_AGENT = "Political Tracker Research contact@example.com"
FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


def _build_params(form_type=""):
    return {
        "action": "getcurrent",
        "type": form_type,   # blank = all form types
        "company": "",
        "dateb": "",
        "owner": "include",
        "count": "100",      # last 100 filings
        "output": "atom",
    }


def _fetch_feed(form_type=""):
    """Fetch the latest-filings Atom feed, handling HTTP errors and basic
    rate-limit backoff."""
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    params = _build_params(form_type)

    for attempt in range(1, 4):
        try:
            resp = requests.get(FEED_URL, params=params, headers=headers, timeout=15)
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Network error fetching EDGAR feed: {exc}") from exc

        if resp.status_code == 200:
            return resp.text

        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"[SEC_EDGAR] Rate limited (HTTP 429). Backing off {wait}s (attempt {attempt}/3)...")
            time.sleep(wait)
            continue

        raise RuntimeError(f"EDGAR returned HTTP {resp.status_code}: {resp.reason}")

    raise RuntimeError("Gave up after repeated rate-limit (429) responses.")


def _parse_filings(xml_text):
    """Parse the Atom feed into a list of raw filing dicts."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"Failed to parse EDGAR Atom feed: {exc}") from exc

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


def _map_row(row):
    cik = (row.get("cik") or "").strip()
    accession = (row.get("accession_number") or "").strip()
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
        "summary": "",  # SEC EDGAR has no abstract/summary field at all
    }


class SecEdgarSource(Source):
    name = "SEC_EDGAR"

    def fetch(self) -> list[dict]:
        print(f"[{self.name}] fetching all-types feed...")
        all_filings = _parse_filings(_fetch_feed())

        # The unfiltered feed is dominated by high-volume forms (Form 4,
        # Schedule 13G, etc); 8-Ks are comparatively rare there, so query
        # EDGAR's server-side type filter directly for a real 8-K sample.
        print(f"[{self.name}] fetching type-filtered 8-K feed...")
        eight_ks = _parse_filings(_fetch_feed(form_type="8-K"))
        eight_ks = [f for f in eight_ks if f["form_type"].upper() == "8-K"]

        signals = []
        for row in eight_ks:
            signal = _map_row(row)
            signal["source"] = self.name
            signals.append(signal)
        return signals


if __name__ == "__main__":
    _signals = SecEdgarSource().fetch()
    print(f"\n{len(_signals)} signals fetched.")
    if _signals:
        print(_signals[0])
