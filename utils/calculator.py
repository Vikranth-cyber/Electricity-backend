# utils/calculator.py
from __future__ import annotations
import logging
from typing import Optional
from .tariff import calculate_slab_cost, get_effective_rate, SUPPORTED_STATES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Appliance wattage database
# ---------------------------------------------------------------------------
WATTAGE_DB: dict[str, int] = {

    # ---------------- COOLING ----------------
    "Air Conditioner (Split)":        1450,
    "Air Conditioner (Window)":       1600,
    "Air Cooler":                      180,
    "Refrigerator (Single Door)":      130,
    "Refrigerator (Double Door)":      220,
    "Ceiling Fans":                     70,
    "Table / Pedestal Fan":             60,

    # ---------------- HEATING ----------------
    "Geyser (Water Heater)":          2000,
    "Immersion Heater Rod":           1500,
    "Electric Iron":                  1000,

    # ---------------- KITCHEN ----------------
    "Microwave Oven":                 1200,
    "Mixer Grinder":                   600,
    "Chimney (Kitchen Exhaust)":       140,
    "Dishwasher (Utensil Washer)":    1800,
    "Water Purifier (RO)":              30,
    "Rice Cooker":                     700,

    # ---------------- UTILITY ----------------
    "Washing Machine":                 500,
    "Inverter":                        100,
    "Vacuum Cleaner":                 1200,

    # ---------------- ELECTRONICS ----------------
    "LED TV":                           90,
    "Set-Top Box":                      18,
    "Desktop Computer":                250,
    "WiFi Router":                      12,
    "CCTV System":                      25,

    # ---------------- LIGHTING ----------------
    "LED Bulbs":                        12,
    "Tube Lights":                      40,
}

_DEFAULT_WATTAGE = 100
DEFAULT_HOURS_DB: dict[str, float] = {

    # Continuous devices
    "Refrigerator (Single Door)": 24,
    "Refrigerator (Double Door)": 24,
    "WiFi Router": 24,
    "CCTV System": 24,
    "Inverter": 24,

    # Cooling
    "Air Conditioner (Split)": 6,
    "Air Conditioner (Window)": 6,
    "Ceiling Fans": 8,
    "Table / Pedestal Fan": 6,

    # Kitchen
    "Mixer Grinder": 0.3,
    "Microwave Oven": 0.5,
    "Rice Cooker": 1,
    "Dishwasher (Utensil Washer)": 1,
    "Chimney (Kitchen Exhaust)": 1,
    "Water Purifier (RO)": 2,

    # Heating
    "Geyser (Water Heater)": 1,
    "Electric Iron": 0.5,
    "Immersion Heater Rod": 1,

    # Utility
    "Washing Machine": 1,
    "Vacuum Cleaner": 0.5,

    # Electronics
    "LED TV": 4,
    "Set-Top Box": 6,
    "Desktop Computer": 5,

    # Lighting
    "LED Bulbs": 6,
    "Tube Lights": 6,
}


# ---------------------------------------------------------------------------
# MAIN CALCULATION FUNCTION
# ---------------------------------------------------------------------------

def calculate_breakdown(
    total_units: float,
    total_amount: float,
    appliances: list[dict],
    state: str,
) -> dict:

    if state not in SUPPORTED_STATES:
        raise ValueError(f"Unsupported state '{state}'. Choose from: {SUPPORTED_STATES}")

    if not appliances:
        raise ValueError("Appliance list is empty.")

    # ---------------- STEP 1: RAW ESTIMATION ----------------
    estimated: list[dict] = []

    for item in appliances:
        name = str(item.get("name", "Unknown"))
        quantity = max(1, int(item.get("quantity") or 1))
        hours_raw = item.get("hours_per_day")
        if hours_raw is not None:
            hours = float(hours_raw)
        else:
            hours = DEFAULT_HOURS_DB.get(name, 4.0)

        wattage = WATTAGE_DB.get(name, _DEFAULT_WATTAGE)

        raw_kwh = (wattage * quantity * hours * 30) / 1000.0

        estimated.append({
            "name": name,
            "wattage": wattage,
            "quantity": quantity,
            "hours_per_day": hours,
            "estimated_units": round(raw_kwh, 3),
        })

    total_estimated_kwh = sum(e["estimated_units"] for e in estimated)

    # ---------------- STEP 2: NORMALIZATION SAFETY CHECK ----------------
    normalization_warning: Optional[str] = None

    if total_units > 0 and total_estimated_kwh > 0:
        difference_ratio = abs(total_estimated_kwh - total_units) / total_units

        if difference_ratio > 0.30:
            normalization_warning = (
                "Estimated appliance consumption differs by more than 30% "
                "from actual bill units. Appliance usage inputs may be inaccurate."
            )

    # ---------------- STEP 3: PROPORTIONAL SCALING ----------------
    breakdown: list[dict] = []

    for e in estimated:
        if total_estimated_kwh > 0:
            share = e["estimated_units"] / total_estimated_kwh
        else:
            share = 1.0 / len(estimated)

        scaled_units = round(share * total_units, 3)
        scaled_cost = round(share * total_amount, 2)
        percentage = round(share * 100, 2)

        breakdown.append({
            "name": e["name"],
            "wattage": e["wattage"],
            "quantity": e["quantity"],
            "hours_per_day": round(e["hours_per_day"], 2),
            "estimated_units": e["estimated_units"],
            "units": scaled_units,
            "cost": scaled_cost,
            "percentage": percentage,
        })

    return {
        "breakdown": breakdown,
        "normalization_warning": normalization_warning,
        "estimated_total_kwh": round(total_estimated_kwh, 2),
    }


# ---------------------------------------------------------------------------
# SUMMARY BUILDER
# ---------------------------------------------------------------------------

def build_summary(
    total_units: float,
    total_amount: float,
    state: str,
    breakdown: list[dict],
) -> dict:

    recalculated = calculate_slab_cost(total_units, state)
    eff_rate = get_effective_rate(total_units, state)

    return {
        "total_units": round(total_units, 2),
        "total_amount": round(total_amount, 2),
        "state": state,
        "rate_per_unit": eff_rate,
        "appliances_count": len(breakdown),
        "recalculated_cost": recalculated,
    }