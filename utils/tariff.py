# utils/tariff.py
# Slab-based electricity tariff rates (₹ per unit) for supported Indian states.
# Each slab defines an upper boundary (upto) and the rate applied within that band.
# upto=None means "all remaining units" (the final/open-ended slab).

TARIFF_RATES = {
    "Telangana": {
        "slabs": [
            {"upto": 100,  "rate": 3.40},
            {"upto": 200,  "rate": 4.80},
            {"upto": 300,  "rate": 7.70},
            {"upto": 400,  "rate": 9.00},
            {"upto": None, "rate": 9.50},
        ]
    },
    "Andhra Pradesh": {
        "slabs": [
            {"upto": 75,   "rate": 1.45},
            {"upto": 125,  "rate": 2.60},
            {"upto": 225,  "rate": 3.60},
            {"upto": 400,  "rate": 6.90},
            {"upto": None, "rate": 7.90},
        ]
    },
    "Karnataka": {
        "slabs": [
            {"upto": 100,  "rate": 3.75},
            {"upto": 200,  "rate": 5.20},
            {"upto": 300,  "rate": 6.75},
            {"upto": 500,  "rate": 7.80},
            {"upto": None, "rate": 8.90},
        ]
    },
    "Tamil Nadu": {
        "slabs": [
            {"upto": 100,  "rate": 2.25},
            {"upto": 200,  "rate": 4.50},
            {"upto": 400,  "rate": 6.00},
            {"upto": 500,  "rate": 8.00},
            {"upto": None, "rate": 9.00},
        ]
    },
}

SUPPORTED_STATES = list(TARIFF_RATES.keys())


def calculate_slab_cost(units: float, state: str) -> float:
    """
    Calculate the electricity bill using progressive slab pricing.

    Each band of units is charged at its own rate; only units that
    fall within a slab are charged at that slab's rate (non-cumulative
    flat-rate per slab, not a marginal-rate system).

    Args:
        units: Total units consumed (kWh) – must be >= 0.
        state: One of the SUPPORTED_STATES strings.

    Returns:
        Total bill amount (₹), rounded to 2 decimal places.

    Raises:
        ValueError: If the state is not in TARIFF_RATES.
        ValueError: If units is negative.
    """
    if state not in TARIFF_RATES:
        raise ValueError(
            f"State '{state}' is not supported. "
            f"Supported states: {', '.join(SUPPORTED_STATES)}"
        )

    if units < 0:
        raise ValueError("Units consumed cannot be negative.")

    slabs = TARIFF_RATES[state]["slabs"]
    remaining = float(units)
    previous_limit = 0.0
    total_cost = 0.0

    for slab in slabs:
        if remaining <= 0:
            break

        limit = slab["upto"]
        rate = slab["rate"]

        if limit is None:
            # Open-ended final slab: charge all remaining units
            total_cost += remaining * rate
            remaining = 0.0
            break

        slab_capacity = limit - previous_limit          # width of this band
        units_in_slab = min(remaining, slab_capacity)   # how many fall here
        total_cost += units_in_slab * rate
        remaining -= units_in_slab
        previous_limit = float(limit)

    return round(total_cost, 2)


def get_effective_rate(units: float, state: str) -> float:
    """
    Returns the effective (average) rate per unit for a given consumption.

    Useful for per-appliance cost attribution when distributing a known
    total bill across appliances proportionally.

    Args:
        units: Total units consumed.
        state: State name.

    Returns:
        Average ₹/unit, rounded to 4 decimal places.
    """
    if units <= 0:
        return 0.0
    total = calculate_slab_cost(units, state)
    return round(total / units, 4)