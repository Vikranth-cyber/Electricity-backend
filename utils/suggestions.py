# utils/suggestions.py
# Top-3 priority based energy saving suggestion engine (React icon ready)

from __future__ import annotations
from typing import List, Dict

_HEAVY_WATTAGE_THRESHOLD = 1000
_DOMINANT_SHARE_THRESHOLD = 30.0
_AC_HIGH_HOURS = 8.0
_HEAT_HIGH_HOURS = 2.0


def generate_suggestions(
    breakdown: List[Dict],
    total_units: float,
) -> List[Dict]:
    """
    Returns exactly 3 high-impact suggestions.
    Each suggestion:
        {
            "title": str,
            "description": str,
            "icon": str   # react-icons name
        }
    """

    suggestions = []

    if not breakdown:
        return [
            {
                "title": "Add Appliance Data",
                "description": "Enter all major appliances for accurate savings recommendations.",
                "icon": "HiOutlineClipboardList"
            },
            {
                "title": "Upgrade to 5-Star Appliances",
                "description": "BEE 5-star rated appliances reduce power consumption by up to 30%.",
                "icon": "HiOutlineSparkles"
            },
            {
                "title": "Eliminate Standby Power",
                "description": "Switch off devices at the socket to avoid hidden standby losses.",
                "icon": "HiOutlinePower"
            }
        ]

    scored_suggestions = []

    heavy_total_pct = 0.0
    always_on_count = 0

    for item in breakdown:
        name = str(item.get("name", "")).lower()
        percentage = float(item.get("percentage", 0.0))
        wattage = int(item.get("wattage", 0))
        hours = float(item.get("hours_per_day", 0.0))
        display_name = item.get("name", "Appliance")

        # 1. Dominant appliance
        if percentage > _DOMINANT_SHARE_THRESHOLD:
            scored_suggestions.append({
                "score": percentage,
                "title": f"Reduce {display_name} Usage",
                "description": f"{display_name} contributes {percentage:.1f}% of your bill. Reducing usage by 1–2 hours daily can significantly lower costs.",
                "icon": "HiOutlineBolt"
            })

        # 2. AC optimization
        if "air conditioner" in name and hours >= _AC_HIGH_HOURS:
            scored_suggestions.append({
                "score": 85,
                "title": "Optimize AC Temperature",
                "description": "Set AC temperature between 24–26°C and use timers to reduce cooling costs by up to 20%.",
                "icon": "HiOutlineSnowflake"
            })

        # 3. Heating appliance control
        if any(h in name for h in ["geyser", "immersion heater", "electric iron"]) and hours >= _HEAT_HIGH_HOURS:
            scored_suggestions.append({
                "score": 75,
                "title": f"Control {display_name} Usage",
                "description": "Reducing daily heating time by 30 minutes can noticeably cut electricity expenses.",
                "icon": "HiOutlineFire"
            })

        # 4. Heavy appliance accumulation
        if wattage >= _HEAVY_WATTAGE_THRESHOLD:
            heavy_total_pct += percentage

        # 5. Always-on detection
        if any(x in name for x in [
            "refrigerator", "wifi", "router", "inverter",
            "cctv", "set-top box", "water purifier"
        ]):
            always_on_count += 1

    # Heavy appliances dominate
    if heavy_total_pct > 50:
        scored_suggestions.append({
            "score": heavy_total_pct,
            "title": "Upgrade Heavy Appliances",
            "description": f"High-wattage appliances contribute {heavy_total_pct:.0f}% of your usage. Switching to 5-star rated models improves efficiency.",
            "icon": "HiOutlineSparkles"
        })

    # Many always-on appliances
    if always_on_count >= 2:
        scored_suggestions.append({
            "score": 60,
            "title": "Reduce Standby Consumption",
            "description": "Multiple always-on devices increase base load. Use smart plugs or turn devices off when not needed.",
            "icon": "HiOutlinePower"
        })

    # High total consumption
    if total_units > 300:
        scored_suggestions.append({
            "score": 90,
            "title": "High Monthly Consumption",
            "description": f"Your consumption is {total_units:.0f} kWh. Consider an energy audit or load balancing to reduce peak usage.",
            "icon": "HiOutlineChartBar"
        })

    elif total_units > 150:
        scored_suggestions.append({
            "score": 50,
            "title": "Improve Lighting Efficiency",
            "description": "Switch fully to LED lighting and maximize natural daylight to reduce lighting costs significantly.",
            "icon": "HiOutlineLightBulb"
        })

    # Universal fallback (low priority)
    scored_suggestions.append({
        "score": 10,
        "title": "General Energy Optimization",
        "description": "Use energy-efficient appliances and avoid unnecessary usage during peak hours.",
        "icon": "HiOutlineLeaf"
    })

    # Sort by impact score (descending)
    scored_suggestions.sort(key=lambda x: x["score"], reverse=True)

    # Return ONLY top 3
    return scored_suggestions[:3]
