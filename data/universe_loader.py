"""Loader and entity-matcher for the political-tracker company universe
(data/universe.csv).

match_entity() is deliberately whole-phrase, word-boundary matching, not
plain substring: "Ur-Energy Inc" (ticker URG) must not match inside text
like "Defending Our Energy Act" - "our" contains "ur" as a plain substring
but not as a word-bounded match. Same requirement as
agent/scorers/correlation.py's normalize_entity() on the agent side.
"""

import csv
import functools
import os
import re

UNIVERSE_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe.csv")


def load_universe(path=UNIVERSE_CSV):
    """Return data/universe.csv as a list of dicts, one per company.
    `aliases` is split into a list on "|"; every other field stays a string
    (including cik/uei, which may be blank)."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["aliases"] = [a.strip() for a in row["aliases"].split("|") if a.strip()]
    return rows


@functools.lru_cache(maxsize=None)
def _compiled_patterns(path):
    patterns = []
    for row in load_universe(path):
        names = [row["company_name"], *row["aliases"]]
        names = sorted({n for n in names if n}, key=len, reverse=True)
        if not names:
            continue
        alternation = "|".join(re.escape(name) for name in names)
        pattern = re.compile(r"\b(?:" + alternation + r")\b", re.IGNORECASE)
        patterns.append((row["ticker"], pattern))
    return tuple(patterns)


def match_entity(text, path=UNIVERSE_CSV):
    """Return the list of tickers whose company_name or any alias appears in
    `text` as a whole, word-boundary-anchored phrase (case-insensitive)."""
    return [ticker for ticker, pattern in _compiled_patterns(path) if pattern.search(text)]
