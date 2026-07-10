"""
CelesTrak TLE fetcher.

For each NORAD ID in the curated high-resolution EO list, pull the latest
two-line element set from celestrak.org's gp.php endpoint, cache it on disk
with a 24-hour TTL, and expose it as a dict keyed by NORAD ID.

Primary endpoint:
    https://celestrak.org/NORAD/elements/gp.php?CATNR=<id>&FORMAT=tle

Fallback endpoint (if many per-NORAD calls fail):
    https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle
"""

from __future__ import annotations
import json
import os
import time
import datetime
import warnings
from typing import Optional

import requests

try:
    # Optional — only used to silence the InsecureRequestWarning when the
    # caller deliberately disables certificate validation.
    from urllib3.exceptions import InsecureRequestWarning
    warnings.simplefilter("ignore", InsecureRequestWarning)
except Exception:  # pragma: no cover
    pass

from hires_eo_satellites import HIRES_EO_SATELLITES, BY_NORAD, expected_name_tokens


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "tle_cache_celestrak.json")

CELESTRAK_GP = "https://celestrak.org/NORAD/elements/gp.php"
PER_NORAD_URL = CELESTRAK_GP + "?CATNR={norad}&FORMAT=tle"
GROUP_ACTIVE_URL = CELESTRAK_GP + "?GROUP=active&FORMAT=tle"

CACHE_TTL_SECONDS = 24 * 3600
HTTP_TIMEOUT = 15
USER_AGENT = "ATLAS-SpaceTracker/2.0 (Pakistan Surveillance)"


# ─────────────────────────────────────────────────────────────────────────────
# Disk cache
# ─────────────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[CACHE] Could not read {CACHE_FILE}: {e} — starting fresh")
        return {}


def _atomic_write(path: str, payload: str) -> None:
    """Write to a sibling temp file then rename — never leaves a torn file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save_cache(cache: dict) -> None:
    _atomic_write(CACHE_FILE, json.dumps(cache, indent=2))


def _is_fresh(entry: dict) -> bool:
    fetched_at = entry.get("fetched_at", 0)
    return (time.time() - fetched_at) < CACHE_TTL_SECONDS


# ─────────────────────────────────────────────────────────────────────────────
# Name validation — guard against NORAD-ID typos in the curated list.
# If we ask for NORAD 42063 expecting "CARTOSAT-2D" but CelesTrak says
# "SENTINEL-2B", we reject the entry rather than silently mis-label it.
# ─────────────────────────────────────────────────────────────────────────────
def _name_matches(expected_name: str, actual_name: str) -> bool:
    expected_tokens = expected_name_tokens(expected_name)
    if not expected_tokens:
        return True  # degenerate expected name — don't block
    actual_up = actual_name.upper().replace("-", " ")
    # accept if any non-trivial token from the expected name appears in actual
    for tok in expected_tokens:
        if tok in actual_up:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# TLE parsing — defensive
# ─────────────────────────────────────────────────────────────────────────────

def _parse_tle_block(text: str) -> dict[str, tuple[str, str, str]]:
    """
    Parse a multi-record CelesTrak TLE text response.
    Returns {norad_id: (name, line1, line2)} for every well-formed triplet.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: dict[str, tuple[str, str, str]] = {}
    i = 0
    while i + 2 < len(lines) + 1:
        if i + 2 >= len(lines):
            break
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        if (l1.startswith("1 ") and l2.startswith("2 ")
                and len(l1) >= 69 and len(l2) >= 69):
            try:
                norad = l1[2:7].strip()
                int(norad)  # validate
                out[norad] = (name, l1, l2)
            except ValueError:
                pass
            i += 3
        else:
            i += 1
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Network — single + bulk
# ─────────────────────────────────────────────────────────────────────────────

def _http_get(url: str, session: requests.Session) -> Optional[str]:
    try:
        # verify=False matches the existing project pattern; CelesTrak certs
        # are valid but Windows trust stores under certain Python builds
        # occasionally fail to validate the chain. Log if we ever flip this.
        r = session.get(url, timeout=HTTP_TIMEOUT, verify=False,
                        headers={"User-Agent": USER_AGENT})
        if r.status_code == 200 and len(r.text) > 50:
            return r.text
        print(f"[TLE]   HTTP {r.status_code} for {url}")
    except requests.RequestException as e:
        print(f"[TLE]   network error: {e!s} ({url})")
    return None


def _fetch_per_norad(norad_id: str, session: requests.Session
                    ) -> Optional[tuple[str, str, str]]:
    text = _http_get(PER_NORAD_URL.format(norad=norad_id), session)
    if not text:
        return None
    parsed = _parse_tle_block(text)
    return parsed.get(norad_id)


def _fetch_active_bulk(session: requests.Session
                      ) -> dict[str, tuple[str, str, str]]:
    print("[TLE] Falling back to GROUP=active bulk pull...")
    text = _http_get(GROUP_ACTIVE_URL, session)
    if not text:
        return {}
    return _parse_tle_block(text)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_hires_eo_tles(force_refresh: bool = False) -> dict[str, dict]:
    """
    Return a dict keyed by NORAD ID:
      {
        "44804": {
            "name": "CARTOSAT-3", "norad_id": "44804",
            "line1": "...", "line2": "...",
            "country": "India", "operator": "ISRO", ...
            "fetched_at": 1715520000,
        }, ...
      }

    Strategy:
      1. Load disk cache.
      2. For each NORAD in HIRES_EO_SATELLITES:
           - If cached < 24h old and not force_refresh: use cache.
           - Else: HTTP GET per-NORAD.
      3. If > 30% of NORAD lookups failed: pull the active group bulk and
         backfill missing entries.
      4. Persist updated cache.
      5. Stale (>24h) entries still served if the network is unavailable,
         flagged with `stale=true`.
    """
    print(f"[TLE] Loading TLEs for {len(HIRES_EO_SATELLITES)} curated EO satellites...")
    cache = _load_cache()
    session = requests.Session()

    # Fast connectivity probe — a GET to CelesTrak's ISS canary (NORAD 25544).
    # If it fails we skip the per-NORAD loop entirely (50 sats × 15s timeout =
    # 12+ min hang otherwise) and serve cached TLEs regardless of age. ISS is
    # small, always present, and the cheapest reachability test.
    #
    # Timeout bumped from 3s -> 10s because CelesTrak occasionally responds
    # slowly under load; a 3-sec window was failing for users on slower or
    # high-latency connections and silently dropping any newly-added NORAD
    # that didn't already have a cache entry (e.g. fresh catalog additions).
    # We retry the probe twice before giving up.
    celestrak_down = False
    probe_err = None
    for _attempt in range(2):
        try:
            probe = session.get(
                PER_NORAD_URL.format(norad="25544"),
                timeout=(10, 10), verify=False,
                headers={"User-Agent": USER_AGENT},
            )
            if probe.status_code != 200 or len(probe.text) < 50:
                raise requests.RequestException(f"probe HTTP {probe.status_code}")
            celestrak_down = False
            probe_err = None
            break
        except requests.RequestException as e:
            probe_err = e
            celestrak_down = True
    if celestrak_down:
        print(f"[TLE] CelesTrak unreachable ({probe_err!s}) — serving cached TLEs of any age.")

    fresh_hits = 0
    fetched = 0
    failed: list[str] = []

    for sat in HIRES_EO_SATELLITES:
        nid = str(sat.norad_id)
        entry = cache.get(nid)

        # CelesTrak down → don't even try to fetch (would waste 15s/sat). Use
        # cache at any age; mark cache-misses as failed and move on.
        if celestrak_down:
            if entry:
                fresh_hits += 1
            else:
                failed.append(nid)
                print(f"[TLE]   [!] {sat.name:<28s} ({nid}) — no cache, CelesTrak down")
            continue

        if entry and _is_fresh(entry) and not force_refresh:
            fresh_hits += 1
            continue

        triplet = _fetch_per_norad(nid, session)
        if triplet and not _name_matches(sat.name, triplet[0]):
            print(f"[TLE]   [!] {sat.name:<28s} ({nid}) — NORAD points to "
                  f"'{triplet[0]}' — rejecting (NORAD ID needs audit)")
            triplet = None
        if triplet:
            name, l1, l2 = triplet
            cache[nid] = {
                "name":         name,
                "norad_id":     nid,
                "line1":        l1,
                "line2":        l2,
                "country":      sat.country,
                "operator":     sat.operator,
                "sensor":       sat.sensor,
                "resolution_m": sat.resolution_m,
                "notes":        sat.notes,
                "fetched_at":   time.time(),
                "stale":        False,
            }
            fetched += 1
            print(f"[TLE]   [+] {sat.name:<28s} ({nid}) — {sat.country}")
        else:
            failed.append(nid)
            print(f"[TLE]   [!] {sat.name:<28s} ({nid}) — fetch failed")

    # Bulk fallback if too many individual misses
    if failed and len(failed) >= max(1, int(0.3 * len(HIRES_EO_SATELLITES))):
        bulk = _fetch_active_bulk(session)
        for nid in list(failed):
            triplet = bulk.get(nid)
            if not triplet:
                continue
            if not _name_matches(BY_NORAD[nid].name, triplet[0]):
                print(f"[TLE]   [!] bulk says {nid} = '{triplet[0]}' — rejected")
                continue
            name, l1, l2 = triplet
            sat = BY_NORAD[nid]
            cache[nid] = {
                "name":         name,
                "norad_id":     nid,
                "line1":        l1,
                "line2":        l2,
                "country":      sat.country,
                "operator":     sat.operator,
                "sensor":       sat.sensor,
                "resolution_m": sat.resolution_m,
                "notes":        sat.notes,
                "fetched_at":   time.time(),
                "stale":        False,
            }
            failed.remove(nid)
            print(f"[TLE]   [+] bulk-resolved {sat.name} ({nid})")

    # ── Supplemental analyst source for WITHHELD sats (Israeli Ofeq/TecSAR) ──
    # CelesTrak/Space-Track never publish these, so they always land in `failed`.
    # Fill them from the bundled+refreshed McCants analyst elements. Flagged
    # source="analyst" / stale-ish so the UI can badge lower confidence.
    try:
        from supplemental_tle import supplemental_tles, SUPPLEMENTAL_SOURCE
        supp = supplemental_tles()
        for nid in list(failed):
            if nid in supp and nid in BY_NORAD:
                nm, l1, l2 = supp[nid]
                sat = BY_NORAD[nid]
                cache[nid] = {
                    "name":         nm,
                    "norad_id":     nid,
                    "line1":        l1,
                    "line2":        l2,
                    "country":      sat.country,
                    "operator":     sat.operator,
                    "sensor":       sat.sensor,
                    "resolution_m": sat.resolution_m,
                    "notes":        sat.notes,
                    "fetched_at":   time.time(),
                    "stale":        False,
                    "source":       SUPPLEMENTAL_SOURCE,
                }
                failed.remove(nid)
                print(f"[TLE]   [+] {sat.name:<28s} ({nid}) — {SUPPLEMENTAL_SOURCE}")
    except Exception as e:
        print(f"[TLE]   supplemental source unavailable: {type(e).__name__}: {e}")

    # Mark anything we couldn't refresh as stale (but keep serving from cache)
    for nid in failed:
        if nid in cache:
            cache[nid]["stale"] = True

    _save_cache(cache)

    print(f"[TLE] cache: {fresh_hits} fresh hits, {fetched} newly fetched, "
          f"{len(failed)} failed")

    # Return only the curated subset
    out: dict[str, dict] = {}
    for sat in HIRES_EO_SATELLITES:
        nid = str(sat.norad_id)
        if nid in cache and cache[nid].get("line1") and cache[nid].get("line2"):
            out[nid] = cache[nid]
    print(f"[TLE] usable TLEs: {len(out)} / {len(HIRES_EO_SATELLITES)}")
    return out


if __name__ == "__main__":
    tles = fetch_hires_eo_tles()
    indian = [t for t in tles.values() if t["country"] == "India"]
    print(f"\nLoaded {len(tles)} TLEs.")
    print(f"Indian satellites: {len(indian)}")
    for t in indian:
        print(f"  - {t['name']} ({t['norad_id']}) — {t['sensor']} {t['resolution_m']} m")
