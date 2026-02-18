# utils/extractor.py
# Parses raw OCR text from electricity bills to extract:
#   - Total units consumed (kWh)
#   - Final payable amount (₹)
#
# ROOT CAUSE OF "350 returned instead of 2694" BUG:
#   ocr.py's _clean_text() inserts a blank line between EVERY pdfminer line.
#   This doubles the line-index distance between the label and its values.
#
#   Example — Bill 2 (382 units / 2694):
#     line 54: "total amount payable"   ← label
#     line 55: ""                       ← blank (inserted by _clean_text)
#     line 56: "100"                    ← units-col value
#     line 57: ""
#     ...
#     line 84: "350.00"                 ← first charge (30 lines from label)
#     ...
#     line 96: "2694.00"               ← GRAND TOTAL (42 lines from label)
#
#   The old column scan used `for j in range(1, 31)` — a hard limit of 30
#   index steps. With blank lines doubling the distance, the window only
#   reached line 84 ("350.00") and NEVER saw 2694.00 at line 96.
#   Result: last collected value = 350.00 → returned as the amount. WRONG.
#
# FIX:
#   Replace the hard index-step limit with a NON-BLANK LINE COUNTER.
#   Blank lines are skipped entirely (not counted toward the window).
#   The window is now "up to N meaningful content lines ahead", which is
#   consistent regardless of whether _clean_text inserted blanks or not.
#   Both bill layouts now work correctly:
#     - Bill 1 (Vikranth, n-prefixed values): window=30 non-blank → hits 2799.62 ✓
#     - Bill 2 (Sample, bare values + blank gaps): window=30 non-blank → hits 2694.00 ✓

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Sanity bounds
_MIN_UNITS  = 1.0
_MAX_UNITS  = 10_000.0
_MIN_AMOUNT = 10.0
_MAX_AMOUNT = 1_000_000.0

# Label keywords — checked in order (most specific first within each function)
_UNITS_LABELS  = ["total units consumed", "units consumed", "energy consumed", "net units"]
_AMOUNT_LABELS = ["total amount payable", "total due", "amount payable", "grand total", "net amount"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_units(text: str) -> Optional[float]:
    """
    Extract total electricity units (kWh) from bill text.

    Handles pdfminer's column-by-column layout where the label and value
    are separated by several lines (meter number, prev/curr readings).

    Strategy:
      1. Find the "total units consumed" label line.
      2. Try to extract a number from the same line (inline layout).
      3. If not found, scan forward counting NON-BLANK lines (up to 15),
         stopping at "description" (start of charge table).
         Collect all valid numbers; return the LAST one.
         pdfminer dumps them as: prev_reading → curr_reading → total_consumed.
         The last is always the correct total.

    The non-blank counter (instead of raw index steps) makes the scan
    robust against _clean_text()'s blank-line interleaving.

    Args:
        text: Cleaned, lowercased bill text from ocr.py.

    Returns:
        Total units as float, or None if not found.
    """
    lines = text.splitlines()

    for i, line in enumerate(lines):
        if "total units consumed" not in line:
            continue

        # ── Mode 1: number on the same line (inline layout) ─────────────────
        m = re.search(r"([\d,]+(?:\.\d+)?)", line)
        if m:
            v = float(m.group(1).replace(",", ""))
            if _MIN_UNITS <= v <= _MAX_UNITS:
                logger.info("Units extracted (inline): %.2f", v)
                return v

        # ── Mode 2: column-layout scan ───────────────────────────────────────
        # Count only NON-BLANK lines toward the window limit so that
        # blank lines inserted by _clean_text() don't shrink the scan range.
        candidates = []
        non_blank_seen = 0

        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()

            if not nxt:
                continue                    # skip blank lines, don't count them

            if "description" in nxt:
                break                       # hit the charge table header → stop

            non_blank_seen += 1
            if non_blank_seen > 15:         # safety cap: 15 real content lines
                break

            m = re.search(r"([\d,]+(?:\.\d+)?)", nxt)
            if m:
                v = float(m.group(1).replace(",", ""))
                if _MIN_UNITS <= v <= _MAX_UNITS:
                    candidates.append(v)

        if candidates:
            # pdfminer dumps: prev_reading, curr_reading, total_consumed → LAST = total
            best = candidates[-1]
            logger.info("Units extracted (column scan): %.2f (last of %d)", best, len(candidates))
            return best

    logger.warning("Could not extract units from text.")
    return None


def extract_amount(text: str) -> Optional[float]:
    """
    Extract the final payable bill amount (₹) from bill text.

    Handles pdfminer's column-by-column layout where the label and grand
    total are separated by many lines (dashes + individual charge rows).
    Also handles _clean_text()'s blank-line interleaving which doubles the
    index distance between label and values.

    Strategy:
      1. Find a payable-amount label line.
      2. Try to extract a number from the same line (inline layout).
         Strip leading non-numeric junk with an anchored ^ sub to preserve
         decimal points inside numbers.
      3. If not found, scan forward counting NON-BLANK lines (up to 30),
         stopping at "due date" or "late payment".
         Collect all standalone numbers; return the LAST one.
         Individual charge rows come before the grand total in the column
         dump, so the last value is always the grand total.

    Args:
        text: Cleaned, lowercased bill text from ocr.py.

    Returns:
        Payable amount as float, or None if not found.
    """
    lines = text.splitlines()

    for i, line in enumerate(lines):
        if not any(lbl in line for lbl in _AMOUNT_LABELS):
            continue

        # ── Mode 1: number on the same line ─────────────────────────────────
        stripped = line
        for lbl in _AMOUNT_LABELS:
            stripped = stripped.replace(lbl, "")
        # Anchored strip: remove only LEADING junk so decimal points in the
        # number itself are never eaten (avoids "2799.62" → "2799 62" bug).
        stripped = re.sub(r"^[\s\-n₹rs\.]+", "", stripped.strip(), flags=re.IGNORECASE)
        nums = re.findall(r"([\d,]+(?:\.\d+)?)", stripped)
        if nums:
            v = float(nums[-1].replace(",", ""))
            if _MIN_AMOUNT <= v <= _MAX_AMOUNT:
                logger.info("Amount extracted (inline): %.2f", v)
                return v

        # ── Mode 2: column-layout scan ───────────────────────────────────────
        # Count only NON-BLANK lines toward the window limit.
        # This is the core fix: blank lines from _clean_text() don't shrink
        # the effective scan range, so we always reach the grand total line
        # even when it's far away (e.g. line 96 when label is at line 54).
        amounts = []
        non_blank_seen = 0

        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()

            if not nxt:
                continue                    # skip blank lines, don't count them

            if "due date" in nxt or "late payment" in nxt:
                break                       # end of amount block → stop

            non_blank_seen += 1
            if non_blank_seen > 30:         # safety cap: 30 real content lines
                break

            # Strip leading currency prefix only (anchored ^)
            cleaned = re.sub(r"^[n₹rs\.\s]+", "", nxt, flags=re.IGNORECASE)
            m = re.fullmatch(r"([\d,]+(?:\.\d+)?)", cleaned)
            if m:
                v = float(m.group(1).replace(",", ""))
                if _MIN_AMOUNT <= v <= _MAX_AMOUNT:
                    amounts.append(v)

        if amounts:
            # Individual charge rows come first, grand total is LAST.
            best = amounts[-1]
            logger.info("Amount extracted (column scan): %.2f (last of %d)", best, len(amounts))
            return best

    logger.warning("Could not extract bill amount from text.")
    return None


def extract_bill_data(text: str) -> dict:
    """
    Convenience wrapper — returns both units and amount from bill text.
    Prints the full cleaned text to stdout so you can verify the exact
    structure pdfminer / Tesseract produced before extraction runs.

    Args:
        text: Cleaned, lowercased OCR/digital text from ocr.py.

    Returns:
        {
            "units":  float | None,   # kWh consumed
            "amount": float | None,   # ₹ payable
        }
    """
    print("\n===== CLEANED TEXT START =====")
    print(text)
    print("===== CLEANED TEXT END =====\n")

    return {
        "units":  extract_units(text),
        "amount": extract_amount(text),
    }