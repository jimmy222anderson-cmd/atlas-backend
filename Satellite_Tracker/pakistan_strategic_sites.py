"""
Pakistan strategic-site catalog used by the targeting analysis (FEAT-004).

Every entry below comes from PUBLIC-DOMAIN, open-source references — Wikipedia,
public mil-bio articles, satellite-imagery commentary in academic and OSINT
journals, and operator press releases. NO classified, leaked, or speculative
coordinates are included. Where multiple public sources disagree on a few
hundred metres, the airbase's tower or facility centroid from OpenStreetMap
was used.

Schema (per entry):
  name        : the canonical public name
  city        : nearest major city / district (for grouping in reports)
  lat / lon   : decimal degrees, WGS-84
  tier        : 1 = capital + named-by-operator strategic asset
                2 = secondary base / corps HQ / port / nuclear complex
  category    : Air Base | Army HQ / Cantonment | Naval | Nuclear |
                Capital / Govt | Port | Defence Industry | Military Academy
  notes       : public-domain description (one line)
  source      : human-readable provenance (must always be "public / open-source"
                or a named open reference)

Geometry consumer (forecast_15day.py):
  For every satellite-pass arc, compute haversine distance from the satellite's
  sub-point to every site at every timestep. A site is "targeted" by the pass
  if the minimum distance during the arc is <= the satellite's standoff_km.
"""

from __future__ import annotations
import math
from typing import Iterable


STRATEGIC_SITES: list[dict] = [
    # ─── TIER 1 — operator-named in FEAT-004 spec ────────────────────────────
    # Capital + government Red Zone
    {"name": "Islamabad — Red Zone (parliament / govt complex)",
     "city": "Islamabad", "lat": 33.7294, "lon": 73.0931,
     "tier": 1, "category": "Capital / Govt",
     "notes": "Pakistan capital, parliament, presidency, supreme court",
     "source": "Wikipedia: Red Zone (Islamabad)"},

    # General Headquarters — Pakistan Army
    {"name": "GHQ — Pakistan Army HQ (Rawalpindi)",
     "city": "Rawalpindi", "lat": 33.6038, "lon": 73.0473,
     "tier": 1, "category": "Army HQ / Cantonment",
     "notes": "General Headquarters of the Pakistan Army",
     "source": "Wikipedia: General Headquarters (Pakistan)"},

    # Chaklala / PAF Base Nur Khan — co-located with Islamabad-Rawalpindi
    {"name": "PAF Base Nur Khan (Chaklala) — Rawalpindi",
     "city": "Rawalpindi", "lat": 33.6147, "lon": 73.0992,
     "tier": 1, "category": "Air Base",
     "notes": "Transport/VIP airbase, co-located with Islamabad airport area",
     "source": "Wikipedia: PAF Base Nur Khan"},

    # Karachi — Naval HQ
    {"name": "Karachi — PN Naval HQ (Karsaz area)",
     "city": "Karachi", "lat": 24.8888, "lon": 67.0852,
     "tier": 1, "category": "Naval",
     "notes": "Pakistan Navy headquarters region",
     "source": "Wikipedia: Pakistan Navy"},

    # Karachi — Masroor Air Base (PAF main southern airbase)
    {"name": "PAF Base Masroor (Karachi)",
     "city": "Karachi", "lat": 24.8932, "lon": 66.9389,
     "tier": 1, "category": "Air Base",
     "notes": "PAF Southern Air Command, largest PAF base by area",
     "source": "Wikipedia: PAF Base Masroor"},

    # Karachi — PNS Karsaz / naval engineering
    {"name": "PNS Karsaz (Karachi Naval Engineering)",
     "city": "Karachi", "lat": 24.8740, "lon": 67.0928,
     "tier": 1, "category": "Naval",
     "notes": "Naval engineering / shore establishment",
     "source": "Wikipedia: PNS Karsaz"},

    # Lahore Cantonment + PAF Base Walton
    {"name": "Lahore Cantonment",
     "city": "Lahore", "lat": 31.5204, "lon": 74.3587,
     "tier": 1, "category": "Army HQ / Cantonment",
     "notes": "4 Corps HQ; major garrison adjacent to civilian city",
     "source": "Wikipedia: Lahore Cantonment"},

    {"name": "PAF Base Lahore (Walton)",
     "city": "Lahore", "lat": 31.4955, "lon": 74.3543,
     "tier": 1, "category": "Air Base",
     "notes": "Training and secondary operations base",
     "source": "Wikipedia: PAF Base Walton"},

    # Kamra — PAC + Minhas
    {"name": "PAC Kamra / PAF Base Minhas",
     "city": "Kamra (Attock)", "lat": 33.8694, "lon": 72.4019,
     "tier": 1, "category": "Defence Industry",
     "notes": "Pakistan Aeronautical Complex — JF-17 assembly, F-16 MLU, "
              "Mirage rebuild facility, co-located with Minhas airbase",
     "source": "Wikipedia: Pakistan Aeronautical Complex / PAF Base Minhas"},

    # Quetta — Western Air Command / Samungli
    {"name": "Quetta — Samungli Air Base + Cantonment",
     "city": "Quetta", "lat": 30.2510, "lon": 66.9379,
     "tier": 1, "category": "Air Base",
     "notes": "Western Air Command, 12 Corps HQ adjacent",
     "source": "Wikipedia: PAF Base Samungli / Quetta Cantonment"},

    # Sargodha — PAF Base Mushaf (main F-16 base)
    {"name": "PAF Base Mushaf (Sargodha)",
     "city": "Sargodha", "lat": 32.0489, "lon": 72.6717,
     "tier": 1, "category": "Air Base",
     "notes": "Central Air Command, main F-16 operational base",
     "source": "Wikipedia: PAF Base Mushaf"},


    # ─── TIER 2 — other publicly-known strategic facilities ──────────────────
    # Other corps HQs + cantonments
    {"name": "Peshawar — PAF Base + 11 Corps HQ",
     "city": "Peshawar", "lat": 33.9939, "lon": 71.5147,
     "tier": 2, "category": "Air Base",
     "notes": "Northern airbase, 11 Corps HQ adjacent",
     "source": "Wikipedia: PAF Base Peshawar"},

    {"name": "Multan Cantonment (2 Corps HQ)",
     "city": "Multan", "lat": 30.2032, "lon": 71.4181,
     "tier": 2, "category": "Army HQ / Cantonment",
     "notes": "2 Corps Headquarters",
     "source": "Wikipedia: Multan Cantonment"},

    {"name": "Bahawalpur (31 Corps HQ)",
     "city": "Bahawalpur", "lat": 29.3964, "lon": 71.6753,
     "tier": 2, "category": "Army HQ / Cantonment",
     "notes": "31 Corps Headquarters",
     "source": "Wikipedia: XXXI Corps (Pakistan)"},

    {"name": "Gujranwala Cantonment (30 Corps HQ)",
     "city": "Gujranwala", "lat": 32.1877, "lon": 74.1945,
     "tier": 2, "category": "Army HQ / Cantonment",
     "notes": "30 Corps Headquarters",
     "source": "Wikipedia: XXX Corps (Pakistan)"},

    {"name": "Mangla Cantonment (1 Armoured Division)",
     "city": "Mangla", "lat": 33.0833, "lon": 73.6500,
     "tier": 2, "category": "Army HQ / Cantonment",
     "notes": "1 Armoured Division",
     "source": "Wikipedia: Mangla Cantonment"},

    # Military academies + training
    {"name": "PMA Kakul (Pakistan Military Academy)",
     "city": "Abbottabad", "lat": 34.1781, "lon": 73.2419,
     "tier": 2, "category": "Military Academy",
     "notes": "Pakistan Military Academy — officer training",
     "source": "Wikipedia: Pakistan Military Academy"},

    {"name": "PAF Academy Risalpur",
     "city": "Risalpur", "lat": 34.0570, "lon": 71.9740,
     "tier": 2, "category": "Military Academy",
     "notes": "PAF flight training academy",
     "source": "Wikipedia: PAF Academy Asghar Khan"},

    # Defence industry
    {"name": "POF Wah (Pakistan Ordnance Factories)",
     "city": "Wah", "lat": 33.7977, "lon": 72.7159,
     "tier": 2, "category": "Defence Industry",
     "notes": "Largest small-arms / munitions manufacturer in Pakistan",
     "source": "Wikipedia: Pakistan Ordnance Factories"},

    # Nuclear (publicly disclosed sites only)
    {"name": "Khushab Nuclear Complex",
     "city": "Khushab", "lat": 32.0379, "lon": 71.9430,
     "tier": 2, "category": "Nuclear",
     "notes": "Plutonium production reactors (publicly disclosed)",
     "source": "Wikipedia: Khushab Nuclear Complex / academic OSINT"},

    {"name": "Chashma Nuclear Power Complex",
     "city": "Chashma", "lat": 32.3950, "lon": 71.4567,
     "tier": 2, "category": "Nuclear",
     "notes": "Civil nuclear power plants C-1 through C-4",
     "source": "Wikipedia: Chashma Nuclear Power Plant"},

    # Naval — non-Karachi
    {"name": "Jinnah Naval Base (Ormara)",
     "city": "Ormara", "lat": 25.2092, "lon": 64.5870,
     "tier": 2, "category": "Naval",
     "notes": "PN's second-line naval base on Makran coast",
     "source": "Wikipedia: Jinnah Naval Base"},

    {"name": "PNS Siddiq (Turbat) — Pasni Air/Naval area",
     "city": "Pasni", "lat": 25.2904, "lon": 63.4513,
     "tier": 2, "category": "Air Base",
     "notes": "Coastal airfield + naval facility",
     "source": "Wikipedia: Pasni Airport / PNS Siddiq"},

    {"name": "Gwadar Port",
     "city": "Gwadar", "lat": 25.1264, "lon": 62.3290,
     "tier": 2, "category": "Port",
     "notes": "Deep-sea port; strategic CPEC terminus",
     "source": "Wikipedia: Gwadar Port"},

    # Northern high-altitude airbases
    {"name": "PAF Skardu (high-altitude airbase)",
     "city": "Skardu", "lat": 35.3354, "lon": 75.5360,
     "tier": 2, "category": "Air Base",
     "notes": "Forward operating base, high-altitude",
     "source": "Wikipedia: Skardu Airport"},

    {"name": "Gilgit (Air Base / Cantonment)",
     "city": "Gilgit", "lat": 35.9189, "lon": 74.3336,
     "tier": 2, "category": "Air Base",
     "notes": "Northern Areas garrison and airfield",
     "source": "Wikipedia: Gilgit Airport"},
]


# Pre-computed convenience: which sites are tier-1
TIER1_SITES: list[dict] = [s for s in STRATEGIC_SITES if s["tier"] == 1]
TIER2_SITES: list[dict] = [s for s in STRATEGIC_SITES if s["tier"] == 2]

# Cities the FEAT-004 spec named explicitly. Used to flag "user-priority"
# targets even when other tier-1 sites are also hit during the same pass.
PRIORITY_CITIES: set[str] = {
    "Islamabad", "Karachi", "Lahore", "Kamra", "Kamra (Attock)",
    "Quetta", "Rawalpindi", "Sargodha",
}


# ── Geometry ────────────────────────────────────────────────────────────────
_EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two (lat, lon) points.

    Flat-earth approximation is wrong at the scales we care about
    (hundreds of km) — haversine keeps the error below 0.5 % anywhere on
    the globe.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def find_targeted_sites(arc_positions: Iterable[tuple],
                        standoff_km: float | None,
                        sites: list[dict] = STRATEGIC_SITES,
                        ) -> list[dict]:
    """For one pass arc, return the list of sites the satellite could image.

    Args:
      arc_positions : iterable of (t, lat, lon, alt_km) tuples — the
                      satellite's sub-points sampled during the arc.
                      Empty list returns [].
      standoff_km   : the satellite's maximum imaging standoff. If None or
                      0, no targeting is computed.
      sites         : strategic-site list. Default is the full catalog.

    Returns:
      List of dicts, sorted by min_dist_km ascending:
        { name, tier, category, city, min_dist_km, closest_t_utc }
      where min_dist_km <= standoff_km. Empty list if no sites in range.
    """
    if not standoff_km or standoff_km <= 0:
        return []
    arc = list(arc_positions)
    if not arc:
        return []

    out: list[dict] = []
    for site in sites:
        slat, slon = site["lat"], site["lon"]
        best_dist = float("inf")
        best_t = None
        for t, lat, lon, _alt in arc:
            d = haversine_km(slat, slon, lat, lon)
            if d < best_dist:
                best_dist = d
                best_t = t
        if best_dist <= standoff_km:
            out.append({
                "name":        site["name"],
                "city":        site["city"],
                "tier":        site["tier"],
                "category":    site["category"],
                "min_dist_km": round(best_dist, 1),
                "closest_t_utc": (best_t.strftime("%Y-%m-%dT%H:%M:%SZ")
                                  if best_t else None),
            })
    # Sort so the closest-approach site comes first (operator scans top-down).
    out.sort(key=lambda s: s["min_dist_km"])
    return out


if __name__ == "__main__":
    # Self-test: print catalog summary
    print(f"Pakistan strategic sites catalog: {len(STRATEGIC_SITES)} entries")
    print(f"  Tier 1: {len(TIER1_SITES)} | Tier 2: {len(TIER2_SITES)}")
    print()
    from collections import Counter
    by_cat = Counter(s["category"] for s in STRATEGIC_SITES)
    for cat, n in by_cat.most_common():
        print(f"  {cat:24s}: {n}")
    print()
    # Sanity: haversine = 0 for same point
    s = STRATEGIC_SITES[0]
    d = haversine_km(s["lat"], s["lon"], s["lat"], s["lon"])
    assert abs(d) < 1e-6, "haversine self-distance must be 0"
    # Sanity: Karachi <-> Islamabad ~ 1100 km
    isb = next(s for s in STRATEGIC_SITES if "Red Zone" in s["name"])
    khi = next(s for s in STRATEGIC_SITES if "Naval HQ" in s["name"])
    d = haversine_km(isb["lat"], isb["lon"], khi["lat"], khi["lon"])
    print(f"Sanity: Islamabad -> Karachi = {d:.0f} km (expected ~1100)")
    assert 1050 <= d <= 1200, "Islamabad-Karachi distance way off"
    print("OK")
