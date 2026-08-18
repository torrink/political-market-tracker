"""Push notification alerts via ntfy.sh for highly-correlated signals.

signal["score"] is the 0-100 cross-source correlation score from
agent/scorers/correlation.py (only ever 0, 33, 67, or 100 - it counts how
many of the other 3 sources also mention the same entity within the
correlation window). It is not a 0-10 relevance/materiality score. Alert
thresholds here are keyed off that scale: 100 = all 3 other sources
correlate (urgent), 67 = 2 other sources correlate (high), below that is
too noisy to page on.
"""

import logging

import requests

logger = logging.getLogger(__name__)

ALERT_THRESHOLD = 67
URGENT_THRESHOLD = 100


def send_ntfy_alert(signal: dict, topic: str) -> bool:
    """Send a push notification via ntfy.sh for a correlated signal."""
    priority = "urgent" if signal["score"] >= URGENT_THRESHOLD else "high"

    try:
        response = requests.post(
            f"https://ntfy.sh/{topic}",
            data=f"{signal['title']} - {signal.get('impact_direction') or 'neutral'}".encode("utf-8"),
            headers={
                "Title": f"{signal['score']}/100 {signal.get('category', 'Signal')}".encode("ascii", "replace"),
                "Priority": priority,
                "Click": signal.get("url") or "https://ntfy.sh",
            },
            timeout=10,
        )
        return response.status_code == 200
    except Exception as exc:
        logger.error(f"ntfy alert failed: {exc}")
        return False
