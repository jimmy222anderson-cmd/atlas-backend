"""
AOI (area-of-interest) coverage forecast — real SGP4 over an ARBITRARY polygon.

The main forecast engine (forecast_15day.py) is hard-wired to the Pakistan
bounding box. This module does the same physics for any polygon the user draws:
for every satellite in the ≤3 m fleet it propagates SGP4 across the forecast
window, tests whether the sub-satellite point falls inside the polygon
("overhead") or within a tilt buffer around it ("tilt-range"), groups
contiguous timesteps into passes, and aggregates each day into the same shape
the dashboard's blind-calendar + charts already render.

Shared by the FastAPI backend (mobile) and the desktop app, so an AOI drawn in
any surface computes identically.
"""
from __future__ import annotations

import datetime
import math
from datetime import timezone, timedelta

# Reuse the exact SGP4 propagation the Pakistan engine uses, so AOI numbers are
# consistent with the main forecast.
from forecast_15day import propagate, STEP_SECONDS

# Tilt buffer around the polygon (an optical sensor can slew off-nadir ~300 km).
# ~2.7° lat / 3.1° lon at ~30°N, matching the Pakistan engine's default.
TILT_BUF_LAT = 2.7
TILT_BUF_LON = 3.1


# ── geometry ────────────────────────────────────────────────────────────────
def point_in_poly(lat: float, lon: float, poly: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon. `poly` = [[lat, lon], ...] (lon = x, lat = y)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        yi, xi = poly[i][0], poly[i][1]
        yj, xj = poly[j][0], poly[j][1]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def poly_bbox(poly: list[list[float]]) -> tuple[float, float, float, float]:
    lats = [p[0] for p in poly]
    lons = [p[1] for p in poly]
    return min(lats), max(lats), min(lons), max(lons)


# ── pass detection over the polygon ──────────────────────────────────────────
def _sat_day_passes(line1: str, line2: str, day: datetime.date,
                    poly: list[list[float]], bbox: tuple) -> list[dict]:
    """All overhead / tilt-range arcs for one satellite over one PKT day."""
    lat_min, lat_max, lon_min, lon_max = bbox
    # PKT day = UTC window shifted back 5 h (same convention as forecast_15day).
    start = (datetime.datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
             - timedelta(hours=5))
    end = start + timedelta(days=1)
    step = timedelta(seconds=STEP_SECONDS)

    passes: list[dict] = []
    in_arc = False
    entry_t = None
    arc_over = False
    max_alt = 0.0

    def _close(t_end):
        nonlocal in_arc, arc_over, max_alt, entry_t
        if entry_t is not None:
            passes.append({
                "entry": entry_t, "exit": t_end,
                "type": "overhead" if arc_over else "tilt-range",
                "max_alt_km": round(max_alt, 1),
            })
        in_arc = False
        arc_over = False
        max_alt = 0.0
        entry_t = None

    t = start
    while t <= end:
        pos = propagate(line1, line2, t)
        if pos is None:
            if in_arc:
                _close(t)
            t += step
            continue
        lat, lon, alt = pos
        in_tilt = (lat_min - TILT_BUF_LAT <= lat <= lat_max + TILT_BUF_LAT and
                   lon_min - TILT_BUF_LON <= lon <= lon_max + TILT_BUF_LON)
        over = point_in_poly(lat, lon, poly) if in_tilt else False
        if in_tilt:
            if not in_arc:
                in_arc = True
                entry_t = t
                arc_over = False
                max_alt = 0.0
            if over:
                arc_over = True
            if alt > max_alt:
                max_alt = alt
            t += step
        elif in_arc:
            _close(t)
            t += step
        else:
            t += step
    if in_arc:
        _close(end)
    return passes


# ── blind-window aggregation (complement of overhead coverage) ───────────────
def _blind_windows(over_intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Given overhead-covered minute intervals in a day (0..1440), return the
    uncovered (blind) minute intervals — the true unobserved gaps."""
    if not over_intervals:
        return [(0, 1440)]
    merged = []
    for s, e in sorted(over_intervals):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    blind = []
    cur = 0
    for s, e in merged:
        if s > cur:
            blind.append((cur, s))
        cur = max(cur, e)
    if cur < 1440:
        blind.append((cur, 1440))
    return blind


def _pkt_min(dt: datetime.datetime) -> int:
    """UTC datetime → minute-of-day in PKT (0..1440)."""
    p = dt + timedelta(hours=5)
    return p.hour * 60 + p.minute


def compute_aoi_forecast(poly: list[list[float]], sats: list[dict],
                         days: int = 15,
                         start_date: datetime.date | None = None) -> dict:
    """
    poly  : [[lat, lon], ...] polygon vertices.
    sats  : [{name, norad, sensor, resolution_m, line1, line2}, ...] (≤3 m fleet).
    Returns a summary shaped like forecast_summary()'s `days` so the existing
    blind-calendar + chart renderers can display it unchanged.
    """
    bbox = poly_bbox(poly)
    if start_date is None:
        start_date = (datetime.datetime.now(timezone.utc) + timedelta(hours=5)).date()

    out_days = []
    for di in range(days):
        day = start_date + timedelta(days=di)
        over_intervals: list[tuple[int, int]] = []   # overhead-covered minutes (both sensors)
        opt_iv, sar_iv = [], []
        opt_cyan, sar_pur = [], []
        sched = []
        n_over = n_tilt = n_opt = n_sar = 0
        seen = set()

        for s in sats:
            try:
                arcs = _sat_day_passes(s["line1"], s["line2"], day, poly, bbox)
            except Exception:
                continue
            is_sar = "SAR" in str(s.get("sensor", "")).upper()
            for a in arcs:
                em = _pkt_min(a["entry"])
                xm = _pkt_min(a["exit"])
                if xm < em:
                    xm = 1440
                is_over = a["type"] == "overhead"
                if is_over:
                    n_over += 1
                    over_intervals.append((em, xm))
                    (sar_iv if is_sar else opt_iv).append((em, xm))
                    (sar_pur if is_sar else opt_cyan).append(em)
                else:
                    n_tilt += 1
                n_sar += 1 if is_sar else 0
                n_opt += 0 if is_sar else 1
                seen.add(s.get("norad"))
                sched.append({
                    "t": em, "e": xm,
                    "p": "O" if is_over else "T",
                    "n": (s.get("name") or "")[:28],
                    "c": s.get("country") or "—",
                    "s": "SAR" if is_sar else "OPT",
                    "r": s.get("resolution_m"),
                })

        blind = _blind_windows(over_intervals)
        blind_min = sum(e - s for s, e in blind)
        longest = max((e - s for s, e in blind), default=0)
        out_days.append({
            "date": day.strftime("%Y-%m-%d"),
            "over": n_over, "tilt": n_tilt,
            "opt": n_opt, "sar": n_sar, "mil": 0,
            "blind_min": blind_min, "longest_gap": longest,
            "sats": len(seen),
            # blind-calendar barcode fields (minutes)
            "opt_windows": _merge_iv(opt_iv), "sar_windows": _merge_iv(sar_iv),
            "opt_cyan": sorted(opt_cyan), "opt_red": [],
            "sar_pur": sorted(sar_pur), "sar_red": [],
            "blind": blind,
            "sched": sorted(sched, key=lambda r: r["t"]),
        })

    return {
        "aoi": poly,
        "generated_at": datetime.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": out_days,
        "satellite_count": len(sats),
    }


def _merge_iv(iv: list[tuple[int, int]]) -> list[list[int]]:
    if not iv:
        return []
    out = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
