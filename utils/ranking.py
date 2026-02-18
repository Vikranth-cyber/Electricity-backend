# utils/ranking.py
# Extracts the top-N highest-consuming appliances from a breakdown list.
# Sorting is done by percentage contribution (descending), with unit count
# as the tiebreaker.

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

_DEFAULT_TOP_N = 3


def get_top_appliances(breakdown: list[dict], n: int = _DEFAULT_TOP_N) -> list[dict]:
    """
    Return the top-N appliances sorted by percentage contribution (descending).

    Each returned dict has the same shape as a breakdown item plus a
    convenience "rank" field (1 = highest consumer).

    Args:
        breakdown: List of appliance breakdown dicts from calculator.py.
                   Expected keys: name, units, cost, percentage (at minimum).
        n:         How many top appliances to return.  Defaults to 3.

    Returns:
        List of up to n dicts, each annotated with:
            {
                "rank":       int,    # 1-based position
                "name":       str,
                "units":      float,
                "cost":       float,
                "percentage": float,
                # …all other keys from the original breakdown item
            }

        Returns an empty list if breakdown is empty.
    """
    if not breakdown:
        logger.warning("get_top_appliances called with an empty breakdown list.")
        return []

    n = max(1, n)  # guard against n < 1

    sorted_appliances = sorted(
        breakdown,
        key=lambda item: (item.get("percentage", 0.0), item.get("units", 0.0)),
        reverse=True,
    )

    top = []
    for rank, item in enumerate(sorted_appliances[:n], start=1):
        entry = dict(item)     # shallow copy so we don't mutate the original
        entry["rank"] = rank
        top.append(entry)

    return top