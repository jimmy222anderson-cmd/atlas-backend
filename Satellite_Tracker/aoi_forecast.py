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
from forecast_15day import propagate, _solar_elevation_deg, _per_sat_buffer_deg

# Two-phase scan: a cheap COARSE pass locates when a satellite is near the AOI
# (its wide tilt bbox is reliably caught at 2-min steps), then a FINE pass only
# inside those brief windows accurately detects overhead + entry/exit. This is
# as accurate as a pure 15 s scan but a fraction of the SGP4 work — a small AOI's
# overhead pass lasts only ~25 s, so a coarse-only scan would miss it.
COARSE_SEC = 90
FINE_SEC = 15

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


# Drop TLEs older than this — SGP4 drift beyond ~2 weeks makes positions
# untrustworthy, which silently corrupts coverage. (FEAT: TLE freshness guard.)
MAX_TLE_AGE_DAYS = 14.0


def tle_age_days(line1: str, ref: datetime.datetime | None = None) -> float | None:
    """Age (days) of a TLE from its epoch (line1 cols 18-32, YYDDD.dddd)."""
    try:
        yy = int(line1[18:20]); doy = float(line1[20:32])
        yr = 2000 + yy if yy < 57 else 1900 + yy
        epoch = datetime.datetime(yr, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)
        now = ref or datetime.datetime.now(timezone.utc)
        return (now - epoch).total_seconds() / 86400.0
    except Exception:
        return None


# ── pass detection over the polygon ──────────────────────────────────────────
def _sat_day_passes(line1: str, line2: str, day: datetime.date,
                    poly: list[list[float]], bbox: tuple,
                    buf_lat: float = TILT_BUF_LAT,
                    buf_lon: float = TILT_BUF_LON) -> list[dict]:
    """All overhead / tilt-range arcs for one satellite over one PKT day.
    buf_lat/buf_lon = THIS satellite's tilt standoff in degrees, so a sat that
    can slew 500 km off-nadir covers the AOI from 500 km away."""
    lat_min, lat_max, lon_min, lon_max = bbox
    tb_lat0, tb_lat1 = lat_min - buf_lat, lat_max + buf_lat
    tb_lon0, tb_lon1 = lon_min - buf_lon, lon_max + buf_lon
    # PKT day = UTC window shifted back 5 h (same convention as forecast_15day).
    start = (datetime.datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
             - timedelta(hours=5))
    end = start + timedelta(days=1)

    def _in_tilt(lat, lon):
        return tb_lat0 <= lat <= tb_lat1 and tb_lon0 <= lon <= tb_lon1

    # ── Phase 1: coarse scan → candidate near-AOI windows ────────────────────
    coarse = timedelta(seconds=COARSE_SEC)
    hits = []
    t = start
    while t <= end:
        pos = propagate(line1, line2, t)
        if pos and _in_tilt(pos[0], pos[1]):
            hits.append(t)
        t += coarse
    if not hits:
        return []
    ranges = []
    for w in hits:
        s, e = w - coarse, w + coarse
        if ranges and s <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], e))
        else:
            ranges.append((s, e))

    # ── Phase 2: fine scan inside each window → accurate arcs ────────────────
    fine = timedelta(seconds=FINE_SEC)
    passes: list[dict] = []
    for rs, re in ranges:
        in_arc = False
        entry_t = None
        arc_over = False
        max_alt = 0.0
        t = max(rs, start)
        rend = min(re, end)
        while t <= rend:
            pos = propagate(line1, line2, t)
            if pos is None:
                t += fine
                continue
            lat, lon, alt = pos
            if _in_tilt(lat, lon):
                if not in_arc:
                    in_arc, entry_t, arc_over, max_alt = True, t, False, 0.0
                if point_in_poly(lat, lon, poly):
                    arc_over = True
                if alt > max_alt:
                    max_alt = alt
            elif in_arc:
                passes.append({"entry": entry_t, "exit": t,
                               "type": "overhead" if arc_over else "tilt-range",
                               "max_alt_km": round(max_alt, 1)})
                in_arc = False
            t += fine
        if in_arc:
            passes.append({"entry": entry_t, "exit": rend,
                           "type": "overhead" if arc_over else "tilt-range",
                           "max_alt_km": round(max_alt, 1)})
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
    # AOI centroid — used for the daylight test (optical can't image in the dark).
    c_lat = sum(p[0] for p in poly) / len(poly)
    c_lon = sum(p[1] for p in poly) / len(poly)
    if start_date is None:
        start_date = (datetime.datetime.now(timezone.utc) + timedelta(hours=5)).date()

    # TLE freshness guard: drop satellites whose TLE is too old to trust (SGP4
    # drift), so stale elements don't quietly corrupt the coverage numbers.
    _ages = []
    _fresh = []
    _stale_dropped = 0
    for s in sats:
        age = tle_age_days(str(s.get("line1", "")))
        if age is not None:
            _ages.append(age)
            if age > MAX_TLE_AGE_DAYS:
                _stale_dropped += 1
                continue
        _fresh.append(s)
    sats = _fresh
    _median_age = round(sorted(_ages)[len(_ages) // 2], 1) if _ages else None

    # Per-satellite tilt buffer (its standoff_km → degrees). A high-tilt sat can
    # image the AOI from far off its ground track (e.g. 500 km).
    buf_map = {}
    for s in sats:
        try:
            buf_map[s.get("norad")] = _per_sat_buffer_deg(s.get("norad"))
        except Exception:
            buf_map[s.get("norad")] = (TILT_BUF_LAT, TILT_BUF_LON)
    max_buf_lat = max((b[0] for b in buf_map.values()), default=TILT_BUF_LAT)

    # Inclination cull: a satellite of inclination i only reaches latitudes up to
    # ±(i if i<=90 else 180-i). If it can't reach the AOI's nearest-equator edge
    # even with the LARGEST tilt standoff, its coverage never touches — skip it.
    aoi_min_abs_lat = min(abs(bbox[0]), abs(bbox[1])) - max_buf_lat
    fleet = []
    for s in sats:
        try:
            inc = float(str(s["line2"])[8:16])
            reach = inc if inc <= 90 else (180.0 - inc)
            if reach + 1.0 < aoi_min_abs_lat:
                continue
        except Exception:
            pass  # unparsable → keep it (safer than dropping)
        fleet.append(s)
    sats = fleet

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
            _bl, _bo = buf_map.get(s.get("norad"), (TILT_BUF_LAT, TILT_BUF_LON))
            try:
                arcs = _sat_day_passes(s["line1"], s["line2"], day, poly, bbox, _bl, _bo)
            except Exception:
                continue
            is_sar = "SAR" in str(s.get("sensor", "")).upper()
            for a in arcs:
                em = _pkt_min(a["entry"])
                xm = _pkt_min(a["exit"])
                if xm < em:
                    xm = 1440
                # Daylight filter (matches the main forecast): OPTICAL sensors can
                # only image in sunlight, so drop optical passes whose midpoint is
                # after dark. SAR (radar) images day AND night — always kept.
                if not is_sar:
                    mid = a["entry"] + (a["exit"] - a["entry"]) / 2
                    if _solar_elevation_deg(c_lat, c_lon, mid) <= 0.0:
                        continue
                is_over = a["type"] == "overhead"
                if is_over:
                    n_over += 1
                else:
                    n_tilt += 1
                n_sar += 1 if is_sar else 0
                n_opt += 0 if is_sar else 1
                # EVERY kept pass (overhead OR tilt-range) is a coverage window —
                # the satellite can image the AOI, so it counts against blind time,
                # exactly like the Pakistan forecast.
                over_intervals.append((em, xm))
                (sar_iv if is_sar else opt_iv).append((em, xm))
                (sar_pur if is_sar else opt_cyan).append(em)
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
        "engine": "aoi-v4-tle-fresh",              # version marker to confirm deploy
        "generated_at": datetime.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": out_days,
        "satellite_count": len(sats),
        "tle_median_age_days": _median_age,
        "tle_stale_dropped": _stale_dropped,
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
