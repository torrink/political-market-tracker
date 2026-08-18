"""Cross-source correlation scorer.

A signal scores higher when the same entity is independently touched by
multiple sources within a short time window - e.g. a company or agency
shows up in both a Federal Register notice and a USAspending contract the
same week. This is a v1 heuristic, not a materiality/relevance model: it
only measures "how many other independent data streams are talking about
the same entity right now."
"""

import datetime
import re

CORRELATION_WINDOW_DAYS = 14
TOTAL_SOURCES = 4

_SUFFIX_RE = re.compile(
    r"\b(INC|LLC|LTD|CO|CORP|CORPORATION|COMPANY|THE)\b\.?", re.IGNORECASE
)
_PUNCT_RE = re.compile(r"[^A-Z0-9 ]")

# Federal Register, USAspending, and Congress all use coarse government
# labels (agency short names / committee names) as their "entity" field by
# construction (Phase 0 deliberately pre-filtered all 3 to the same 4
# agencies). Two signals both being "about Commerce" is true by definition,
# not a real correlation - so exact-equality matches on these generic
# labels are excluded. Substring mentions of something MORE specific (a
# company name showing up in a bill's text, say) still count normally.
_GENERIC_ENTITY_LABELS = {
    "NRC", "DOE", "COMMERCE", "DOD",
    "ARMED SERVICES", "APPROPRIATIONS", "ENERGY AND COMMERCE",
}


def normalize_entity(name: str) -> str:
    """Uppercase, strip punctuation and common legal-entity suffixes, and
    collapse whitespace, so e.g. 'Acme, LLC' and 'THE ACME COMPANY' both
    normalize to 'ACME'."""
    if not name:
        return ""
    text = name.upper()
    text = _SUFFIX_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def _parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.date.fromisoformat(date_str[:10])
    except ValueError:
        return None


def score_signals(signals: list[dict]) -> list[dict]:
    """Mutates and returns `signals`, adding two fields to each dict:
      - "score": int 0-100, round(100 * distinct_correlated_source_count / (TOTAL_SOURCES - 1))
      - "correlated_sources": list[str], the distinct OTHER sources that
        mention this signal's entity within CORRELATION_WINDOW_DAYS days
        (matched either by exact normalized-entity equality, or by the
        normalized entity appearing as a substring inside the other
        signal's title+summary text).
    """
    parsed = [
        (sig, normalize_entity(sig.get("entity", "")), _parse_date(sig.get("date", "")))
        for sig in signals
    ]

    for i, (sig, norm_i, date_i) in enumerate(parsed):
        correlated = set()

        if norm_i and date_i:
            for j, (other, norm_j, date_j) in enumerate(parsed):
                if i == j or other["source"] == sig["source"]:
                    continue
                if not date_j:
                    continue
                if abs((date_i - date_j).days) > CORRELATION_WINDOW_DAYS:
                    continue

                if norm_i in _GENERIC_ENTITY_LABELS:
                    continue  # both matched-by-construction and mentioned-everywhere - not informative

                text_j = f"{other.get('title', '')} {other.get('summary', '')}".upper()
                exact_match = norm_i == norm_j
                # \b word boundaries prevent false positives like "UR ENERGY"
                # (from "UR-Energy Inc") matching inside "...OUR ENERGY..."
                # (from "Defending Our Energy Act") - "OUR" contains "UR"
                # as a plain substring, but not as a word-bounded match.
                mention_match = len(norm_i) >= 4 and re.search(
                    r"\b" + re.escape(norm_i) + r"\b", text_j
                )

                if exact_match or mention_match:
                    correlated.add(other["source"])

        sig["correlated_sources"] = sorted(correlated)
        sig["score"] = round(100 * len(correlated) / (TOTAL_SOURCES - 1)) if correlated else 0

    return signals
