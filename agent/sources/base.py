"""Base contract for all signal sources.

Every source's fetch() does both the API call AND the normalization step
in one shot, returning plain dicts shaped exactly like SIGNAL_FIELDS. This
is the same unified schema validated end-to-end in Phase 0's
scripts/integration_fetch.py (there called UNIFIED_FIELDS).
"""

from abc import ABC, abstractmethod

SIGNAL_FIELDS = ["source", "signal_id", "title", "entity", "date", "category", "url", "summary"]


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self) -> list[dict]:
        """Fetch and normalize this source's data. Returns a list of dicts
        with exactly the keys in SIGNAL_FIELDS (source is filled in by the
        caller/subclass, not left for agent/main.py to add)."""
        raise NotImplementedError
