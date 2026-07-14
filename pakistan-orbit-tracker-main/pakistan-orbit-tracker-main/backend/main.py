from enum import Enum
from math import sqrt
import os
import re
import sys
import time
import json
from datetime import datetime, timezone, timedelta
import math
from functools import lru_cache

import httpx
from fastapi import FastAPI, HTTPException, Query, Header, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sgp4.api import Satrec, jday


TLE_TTL = 2 * 60 * 60  # 2 hours — matches mirror update cadence

# GitHub mirror of CelesTrak — updated automatically via GitHub Actions
# https://github.com/satvisorcom/satvisor-data
MIRROR_BASE = "https://raw.githubusercontent.com/satvisorcom/satvisor-data/master/celestrak/tle/"


class Category(str, Enum):
    stations  = "stations"
    starlink  = "starlink"
    oneweb    = "oneweb"
    gps_ops   = "gps-ops"
    glo_ops   = "glo-ops"
    galileo   = "galileo"
    beidou    = "beidou"
    weather   = "weather"
    noaa      = "noaa"
    goes      = "goes"
    resource  = "resource"
    sarsat    = "sarsat"
    radar     = "radar"
    military  = "military"
    science   = "science"
    geo       = "geo"
    iridium   = "iridium-NEXT"
    intelsat  = "intelsat"
    tdrss     = "tdrss"
    analyst   = "analyst"
    active    = "active"


CATEGORY_META = {
    Category.stations:  {"label": "Space Stations (ISS/CSS)", "slug": "stations",     "max": 50},
    Category.starlink:  {"label": "Starlink",                  "slug": "starlink",     "max": 7000},
    Category.oneweb:    {"label": "OneWeb",                    "slug": "oneweb",       "max": 700},
    Category.gps_ops:   {"label": "GPS Operational",           "slug": "gps-ops",      "max": 50},
    Category.glo_ops:   {"label": "GLONASS",                   "slug": "glo-ops",      "max": 50},
    Category.galileo:   {"label": "Galileo",                   "slug": "galileo",      "max": 50},
    Category.beidou:    {"label": "BeiDou",                    "slug": "beidou",       "max": 60},
    Category.weather:   {"label": "Weather (NOAA)",            "slug": "weather",      "max": 80},
    Category.noaa:      {"label": "NOAA",                      "slug": "noaa",         "max": 20},
    Category.goes:      {"label": "GOES",                      "slug": "goes",         "max": 20},
    Category.resource:  {"label": "Earth Observation",         "slug": "resource",     "max": 200},
    Category.sarsat:    {"label": "SAR / SARSAT",              "slug": "sarsat",       "max": 100},
    Category.radar:     {"label": "Radar",                     "slug": "radar",        "max": 50},
    Category.military:  {"label": "Military / Recon",          "slug": "military",     "max": 100},
    Category.science:   {"label": "Science",                   "slug": "science",      "max": 100},
    Category.geo:       {"label": "Geostationary",             "slug": "geo",          "max": 600},
    Category.iridium:   {"label": "Iridium NEXT",              "slug": "iridium-NEXT", "max": 100},
    Category.intelsat:  {"label": "Intelsat",                  "slug": "intelsat",     "max": 60},
    Category.tdrss:     {"label": "TDRSS",                     "slug": "tdrss",        "max": 30},
    Category.analyst:   {"label": "Analyst",                   "slug": "analyst",      "max": 300},
    Category.active:    {"label": "Active (all)",              "slug": "active",       "max": 15000},
}

# In-memory TLE cache: category -> {fetched_at, text}
tle_cache: dict[Category, dict] = {}

app = FastAPI(title="Pakistan Orbit Tracker Backend")
# Backend runs on 127.0.0.1 and is only consumed by the local Vite dev server
# (port 8080) or its preview port (5173). Locking origins prevents any other
# page in the browser from probing the backend.
app.add_middleware(
    CORSMiddleware,
    # allow_credentials is False, so a wildcard is safe. The mobile app's tracker
    # (Capacitor origins https://localhost / capacitor://localhost) fetches the
    # public position/TLE data cross-origin, so we allow any origin here.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],   # GET (tracker/positions) + POST (mobile on-demand recompute)
    allow_headers=["*"],
)


# ── TLE fetching ──────────────────────────────────────────────────────────────

async def fetch_tle(category: Category) -> str:
    slug = CATEGORY_META[category]["slug"]
    url = MIRROR_BASE + slug + ".tle"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "pakistan-orbit-tracker/1.0"})
        r.raise_for_status()
        text = r.text.strip()
        if len(text) < 100:
            raise ValueError(f"TLE response too short ({len(text)} bytes)")
        return text


async def get_tle_text(category: Category) -> str:
    now_ts = time.time()
    cached = tle_cache.get(category)
    if cached and now_ts - cached["fetched_at"] < TLE_TTL:
        return cached["text"]
    try:
        text = await fetch_tle(category)
        tle_cache[category] = {"fetched_at": now_ts, "text": text}
        return text
    except Exception as exc:
        if cached:
            return cached["text"]  # serve stale on failure
        raise HTTPException(502, detail=f"Failed to fetch TLE: {exc}") from exc


def parse_records(text: str, max_count: int) -> list[tuple[str, str, str]]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    records: list[tuple[str, str, str]] = []
    for i in range(0, len(lines) - 2, 3):
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            records.append((name, l1, l2))
        if len(records) >= max_count:
            break
    return records


# ── SGP4 propagation ──────────────────────────────────────────────────────────

def propagate_now(name: str, line1: str, line2: str) -> dict | None:
    try:
        sat = Satrec.twoline2rv(line1, line2)
        now = datetime.now(timezone.utc)
        jd, fr = jday(now.year, now.month, now.day,
                      now.hour, now.minute, now.second + now.microsecond / 1e6)
        e, r, v = sat.sgp4(jd, fr)
        if e != 0 or not r:
            return None

        x, y, z = r
        vx, vy, vz = v

        # GMST (radians)
        jd_ut1 = jd + fr
        gmst_deg = (280.46061837 + 360.98564736629 * (jd_ut1 - 2451545.0)) % 360
        gmst_rad = math.radians(gmst_deg)

        # ECI → geodetic (WGS84 iterative)
        lon_rad = math.atan2(y, x) - gmst_rad
        lon_deg = (math.degrees(lon_rad) + 180) % 360 - 180

        a = 6378.137
        f = 1 / 298.257223563
        e2 = 2 * f - f * f
        p = math.sqrt(x * x + y * y)
        lat_rad = math.atan2(z, p * (1 - e2))
        for _ in range(5):
            sin_lat = math.sin(lat_rad)
            N = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
            lat_rad = math.atan2(z + e2 * N * sin_lat, p)

        lat_deg = math.degrees(lat_rad)
        sin_lat = math.sin(lat_rad)
        cos_lat = math.cos(lat_rad)
        N = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
        alt_km = (p / cos_lat - N) if abs(cos_lat) > 1e-6 else (abs(z) / abs(sin_lat) - N * (1 - e2))

        return {
            "name": name,
            "lat": round(lat_deg, 4),
            "lon": round(lon_deg, 4),
            "altKm": round(alt_km, 2),
            "velocityKms": round(sqrt(vx*vx + vy*vy + vz*vz), 4),
        }
    except Exception:
        return None


# ── endpoints ─────────────────────────────────────────────────────────────────

# Country code → full name
COUNTRY_NAMES: dict[str, str] = {
    "US": "United States", "RU": "Russia", "CN": "China", "GB": "United Kingdom",
    "FR": "France", "DE": "Germany", "JP": "Japan", "IN": "India",
    "CA": "Canada", "AU": "Australia", "IT": "Italy", "ES": "Spain",
    "KR": "South Korea", "IL": "Israel", "BR": "Brazil", "AE": "UAE",
    "SA": "Saudi Arabia", "PK": "Pakistan", "BD": "Bangladesh", "TH": "Thailand",
    "MX": "Mexico", "AR": "Argentina", "ZA": "South Africa", "NG": "Nigeria",
    "EG": "Egypt", "TR": "Turkey", "UA": "Ukraine", "SE": "Sweden",
    "NO": "Norway", "NL": "Netherlands", "BE": "Belgium", "CH": "Switzerland",
    "AT": "Austria", "PL": "Poland", "CZ": "Czech Republic", "FI": "Finland",
    "DK": "Denmark", "PT": "Portugal", "GR": "Greece", "HU": "Hungary",
    "LU": "Luxembourg", "SG": "Singapore", "MY": "Malaysia", "ID": "Indonesia",
    "PH": "Philippines", "VN": "Vietnam", "NZ": "New Zealand", "IR": "Iran",
    "IQ": "Iraq", "QA": "Qatar", "KW": "Kuwait", "OM": "Oman",
    "TW": "Taiwan", "HK": "Hong Kong", "TH": "Thailand", "LK": "Sri Lanka",
    "MM": "Myanmar", "KZ": "Kazakhstan", "UZ": "Uzbekistan", "AZ": "Azerbaijan",
    "GE": "Georgia", "AM": "Armenia", "BY": "Belarus", "MD": "Moldova",
    "RS": "Serbia", "HR": "Croatia", "SI": "Slovenia", "SK": "Slovakia",
    "RO": "Romania", "BG": "Bulgaria", "LT": "Lithuania", "LV": "Latvia",
    "EE": "Estonia", "IS": "Iceland", "IE": "Ireland", "CY": "Cyprus",
    "MT": "Malta", "AL": "Albania", "MK": "North Macedonia", "BA": "Bosnia",
    "ME": "Montenegro", "XK": "Kosovo", "LI": "Liechtenstein", "MC": "Monaco",
    "SM": "San Marino", "VA": "Vatican", "AD": "Andorra",
    "INT": "International", "ESA": "European Space Agency",
}

# Known patterns for satellites not in SatNOGS catalog.
# Match order matters — most specific first, generic last.
NAME_PATTERNS: list[tuple[str, dict]] = [
    # ── Broadband / Internet constellations ────────────────────────────────
    ("STARLINK",  {"operator": "SpaceX",            "country": "US",  "country_name": "United States",         "purpose": "Broadband Internet Constellation",     "source": "SpaceX",            "destination": "Global Internet Coverage"}),
    ("KUIPER",    {"operator": "Amazon",            "country": "US",  "country_name": "United States",         "purpose": "Broadband Internet Constellation",     "source": "Amazon",            "destination": "Global Internet Coverage"}),
    ("ONEWEB",    {"operator": "Eutelsat OneWeb",   "country": "GB",  "country_name": "United Kingdom",        "purpose": "Broadband Internet Constellation",     "source": "Eutelsat OneWeb",   "destination": "Global Internet Coverage (LEO)"}),
    ("IRIDIUM",   {"operator": "Iridium Communications", "country": "US", "country_name": "United States",     "purpose": "Voice / Data Communications",          "source": "Iridium",           "destination": "Global Mobile Comms (LEO)"}),
    ("GLOBALSTAR",{"operator": "Globalstar Inc.",    "country": "US",  "country_name": "United States",         "purpose": "Voice / Data Communications",          "source": "Globalstar",        "destination": "LEO Comms"}),
    ("ORBCOMM",   {"operator": "Orbcomm",            "country": "US",  "country_name": "United States",         "purpose": "M2M / IoT Communications",             "source": "Orbcomm",           "destination": "LEO Data Network"}),

    # ── Navigation (GNSS) ──────────────────────────────────────────────────
    ("GPS",       {"operator": "US Space Force",     "country": "US",  "country_name": "United States",         "purpose": "Navigation & Positioning (GPS)",       "source": "US Space Force",    "destination": "Global Navigation (MEO)"}),
    ("NAVSTAR",   {"operator": "US Space Force",     "country": "US",  "country_name": "United States",         "purpose": "Navigation & Positioning (GPS)",       "source": "US Space Force",    "destination": "Global Navigation (MEO)"}),
    ("GLONASS",   {"operator": "Roscosmos",          "country": "RU",  "country_name": "Russia",                "purpose": "Navigation & Positioning (GLONASS)",   "source": "Roscosmos",         "destination": "Global Navigation (MEO)"}),
    ("GALILEO",   {"operator": "European GNSS Agency","country": "ESA","country_name": "European Union",        "purpose": "Navigation & Positioning (Galileo)",   "source": "ESA / EUSPA",       "destination": "Global Navigation (MEO)"}),
    ("BEIDOU",    {"operator": "CNSA / CASC",        "country": "CN",  "country_name": "China",                 "purpose": "Navigation & Positioning (BeiDou)",    "source": "CNSA",              "destination": "Global Navigation"}),
    ("COMPASS",   {"operator": "CNSA / CASC",        "country": "CN",  "country_name": "China",                 "purpose": "Navigation & Positioning (BeiDou)",    "source": "CNSA",              "destination": "Global Navigation"}),
    ("QZS",       {"operator": "JAXA / Cabinet Office Japan", "country": "JP", "country_name": "Japan",         "purpose": "Regional Navigation (QZSS)",           "source": "JAXA",              "destination": "Asia-Oceania Navigation"}),
    ("IRNSS",     {"operator": "ISRO",               "country": "IN",  "country_name": "India",                 "purpose": "Regional Navigation (NavIC)",          "source": "ISRO",              "destination": "Indian Subcontinent Navigation"}),
    ("NVS",       {"operator": "ISRO",               "country": "IN",  "country_name": "India",                 "purpose": "Regional Navigation (NavIC)",          "source": "ISRO",              "destination": "Indian Subcontinent Navigation"}),

    # ── Weather ────────────────────────────────────────────────────────────
    ("NOAA",      {"operator": "NOAA / NASA",        "country": "US",  "country_name": "United States",         "purpose": "Weather & Earth Observation",          "source": "NOAA",              "destination": "Global Weather Monitoring"}),
    ("GOES",      {"operator": "NOAA",               "country": "US",  "country_name": "United States",         "purpose": "Geostationary Weather",                "source": "NOAA",              "destination": "Americas Weather Coverage"}),
    ("METEOR",    {"operator": "Roscosmos",          "country": "RU",  "country_name": "Russia",                "purpose": "Weather Observation",                  "source": "Roscosmos",         "destination": "Global Weather Monitoring"}),
    ("METOP",     {"operator": "EUMETSAT / ESA",     "country": "ESA", "country_name": "European Space Agency", "purpose": "Polar-orbiting Meteorology",           "source": "ESA / EUMETSAT",    "destination": "Global Weather Monitoring"}),
    ("HIMAWARI",  {"operator": "JMA",                "country": "JP",  "country_name": "Japan",                 "purpose": "Geostationary Weather",                "source": "JMA",               "destination": "Asia-Pacific Weather"}),
    ("FY-",       {"operator": "CMA / CNSA",         "country": "CN",  "country_name": "China",                 "purpose": "Meteorology (Fengyun)",                "source": "CMA",               "destination": "Global Weather Monitoring"}),
    ("FENGYUN",   {"operator": "CMA / CNSA",         "country": "CN",  "country_name": "China",                 "purpose": "Meteorology (Fengyun)",                "source": "CMA",               "destination": "Global Weather Monitoring"}),
    ("INSAT",     {"operator": "ISRO",               "country": "IN",  "country_name": "India",                 "purpose": "Weather & Communications",             "source": "ISRO",              "destination": "Indian Region"}),

    # ── Earth Observation ──────────────────────────────────────────────────
    ("LANDSAT",   {"operator": "USGS / NASA",        "country": "US",  "country_name": "United States",         "purpose": "Land Imaging",                         "source": "USGS",              "destination": "Earth Observation (SSO)"}),
    ("SENTINEL",  {"operator": "ESA / Copernicus",   "country": "ESA", "country_name": "European Space Agency", "purpose": "Earth Observation (Copernicus)",       "source": "ESA",               "destination": "Earth Observation"}),
    ("WORLDVIEW", {"operator": "Maxar Technologies", "country": "US",  "country_name": "United States",         "purpose": "Commercial High-Res Imaging",          "source": "Maxar",             "destination": "Commercial Earth Observation"}),
    ("GEOEYE",    {"operator": "Maxar Technologies", "country": "US",  "country_name": "United States",         "purpose": "Commercial High-Res Imaging",          "source": "Maxar",             "destination": "Commercial Earth Observation"}),
    ("QUICKBIRD", {"operator": "Maxar Technologies", "country": "US",  "country_name": "United States",         "purpose": "Commercial High-Res Imaging",          "source": "Maxar",             "destination": "Commercial Earth Observation"}),
    ("IKONOS",    {"operator": "Maxar Technologies", "country": "US",  "country_name": "United States",         "purpose": "Commercial High-Res Imaging",          "source": "Maxar",             "destination": "Commercial Earth Observation"}),
    ("PLANET",    {"operator": "Planet Labs",        "country": "US",  "country_name": "United States",         "purpose": "Daily Earth Imaging (Dove)",           "source": "Planet Labs",       "destination": "Commercial Earth Observation"}),
    ("DOVE",      {"operator": "Planet Labs",        "country": "US",  "country_name": "United States",         "purpose": "Daily Earth Imaging",                  "source": "Planet Labs",       "destination": "Commercial Earth Observation"}),
    ("SKYSAT",    {"operator": "Planet Labs",        "country": "US",  "country_name": "United States",         "purpose": "Commercial High-Res Imaging",          "source": "Planet Labs",       "destination": "Commercial Earth Observation"}),
    ("ICEYE",     {"operator": "ICEYE",              "country": "FI",  "country_name": "Finland",               "purpose": "Commercial SAR Imaging",               "source": "ICEYE",             "destination": "Commercial SAR Constellation"}),
    ("CAPELLA",   {"operator": "Capella Space",      "country": "US",  "country_name": "United States",         "purpose": "Commercial SAR Imaging",               "source": "Capella Space",     "destination": "Commercial SAR Constellation"}),
    ("CARTOSAT",  {"operator": "ISRO",               "country": "IN",  "country_name": "India",                 "purpose": "Cartography & High-Res Imaging",       "source": "ISRO",              "destination": "Earth Observation"}),
    ("RESOURCESAT",{"operator": "ISRO",              "country": "IN",  "country_name": "India",                 "purpose": "Natural Resources Monitoring",         "source": "ISRO",              "destination": "Earth Observation"}),
    ("RISAT",     {"operator": "ISRO",               "country": "IN",  "country_name": "India",                 "purpose": "Radar / SAR Imaging",                  "source": "ISRO",              "destination": "Earth Observation (SAR)"}),
    ("EMISAT",    {"operator": "ISRO / DRDO",        "country": "IN",  "country_name": "India",                 "purpose": "Electronic Intelligence (ELINT)",      "source": "DRDO",              "destination": "Signal Intelligence"}),
    ("HYSIS",     {"operator": "ISRO",               "country": "IN",  "country_name": "India",                 "purpose": "Hyperspectral Imaging",                "source": "ISRO",              "destination": "Earth Observation"}),
    ("GSAT",      {"operator": "ISRO",               "country": "IN",  "country_name": "India",                 "purpose": "Communications / Broadcast",           "source": "ISRO",              "destination": "Indian Region (GEO)"}),
    ("OCEANSAT",  {"operator": "ISRO",               "country": "IN",  "country_name": "India",                 "purpose": "Ocean Color & Sea State",              "source": "ISRO",              "destination": "Ocean Monitoring"}),
    ("GAOFEN",    {"operator": "CNSA",               "country": "CN",  "country_name": "China",                 "purpose": "High-Res Earth Observation",           "source": "CNSA",              "destination": "Earth Observation"}),
    ("ZIYUAN",    {"operator": "CNSA",               "country": "CN",  "country_name": "China",                 "purpose": "Civilian Earth Observation",           "source": "CNSA",              "destination": "Earth Observation"}),
    ("HAIYANG",   {"operator": "CNSA",               "country": "CN",  "country_name": "China",                 "purpose": "Ocean Monitoring",                     "source": "CNSA",              "destination": "Ocean Observation"}),
    ("TERRA",     {"operator": "NASA",               "country": "US",  "country_name": "United States",         "purpose": "Earth System Science (EOS)",           "source": "NASA",              "destination": "Earth Observation (SSO)"}),
    ("AQUA",      {"operator": "NASA",               "country": "US",  "country_name": "United States",         "purpose": "Water Cycle Observation (EOS)",        "source": "NASA",              "destination": "Earth Observation (SSO)"}),
    ("AURA",      {"operator": "NASA",               "country": "US",  "country_name": "United States",         "purpose": "Atmospheric Composition (EOS)",        "source": "NASA",              "destination": "Earth Observation (SSO)"}),
    ("MODIS",     {"operator": "NASA",               "country": "US",  "country_name": "United States",         "purpose": "Spectroradiometer Imaging",            "source": "NASA",              "destination": "Earth Observation"}),

    # ── Military / Reconnaissance ──────────────────────────────────────────
    ("OFEK",      {"operator": "IAI / Israeli MoD",  "country": "IL",  "country_name": "Israel",                "purpose": "Reconnaissance",                       "source": "Israeli MoD",       "destination": "Military Earth Observation"}),
    ("OFEQ",      {"operator": "IAI / Israeli MoD",  "country": "IL",  "country_name": "Israel",                "purpose": "Reconnaissance",                       "source": "Israeli MoD",       "destination": "Military Earth Observation"}),
    ("TECSAR",    {"operator": "IAI / Israeli MoD",  "country": "IL",  "country_name": "Israel",                "purpose": "Radar Reconnaissance (SAR)",           "source": "Israeli MoD",       "destination": "Military SAR"}),
    ("EROS",      {"operator": "ImageSat International","country":"IL","country_name": "Israel",                "purpose": "Commercial Reconnaissance",            "source": "ImageSat",          "destination": "Commercial Earth Observation"}),
    ("KH-",       {"operator": "NRO",                "country": "US",  "country_name": "United States",         "purpose": "Optical Reconnaissance (KH)",          "source": "NRO",               "destination": "Military Earth Observation"}),
    ("USA-",      {"operator": "US DoD / NRO",       "country": "US",  "country_name": "United States",         "purpose": "Classified Military",                  "source": "US DoD",            "destination": "Military"}),
    ("YAOGAN",    {"operator": "PLA / CNSA",         "country": "CN",  "country_name": "China",                 "purpose": "Reconnaissance",                       "source": "PLA",               "destination": "Military Earth Observation"}),
    ("LACROSSE",  {"operator": "NRO",                "country": "US",  "country_name": "United States",         "purpose": "Radar Reconnaissance",                 "source": "NRO",               "destination": "Military SAR"}),
    ("RADARSAT",  {"operator": "CSA / MDA",          "country": "CA",  "country_name": "Canada",                "purpose": "Radar Earth Observation",              "source": "CSA",               "destination": "Earth Observation (SAR)"}),
    ("COSMOS",    {"operator": "Roscosmos / VKS",    "country": "RU",  "country_name": "Russia",                "purpose": "Military / Multi-purpose",             "source": "Russian MoD",       "destination": "Military"}),
    ("DMSP",      {"operator": "US Space Force",     "country": "US",  "country_name": "United States",         "purpose": "Military Weather",                     "source": "US DoD",            "destination": "Global Military Weather"}),

    # ── Curated high-res imaging / SAR fleet ───────────────────────────────
    # These satellites also appear in CelesTrak's resource / active groups.
    # Name-matched here so they enrich correctly even when their NORAD is
    # not in the per-NORAD catalog (avoids "Unknown / Scientific Research").
    ("COSMO-SKYMED", {"operator": "ASI / Italian MoD","country": "IT", "country_name": "Italy",                 "purpose": "Military SAR Reconnaissance",          "source": "ASI / Italian MoD", "destination": "Military SAR"}),
    ("CSG-",      {"operator": "ASI / Italian MoD",  "country": "IT",  "country_name": "Italy",                 "purpose": "Military SAR Reconnaissance (2nd gen)","source": "ASI / Italian MoD", "destination": "Military SAR"}),
    ("TERRASAR",  {"operator": "DLR / Airbus",       "country": "DE",  "country_name": "Germany",               "purpose": "SAR Earth Observation",                "source": "DLR",               "destination": "Earth Observation (SAR)"}),
    ("TANDEM-X",  {"operator": "DLR / Airbus",       "country": "DE",  "country_name": "Germany",               "purpose": "SAR Earth Observation",                "source": "DLR",               "destination": "Earth Observation (SAR)"}),
    ("PAZ",       {"operator": "Hisdesat",           "country": "ES",  "country_name": "Spain",                 "purpose": "Military SAR Reconnaissance",          "source": "Hisdesat",          "destination": "Military SAR"}),
    ("KOMPSAT",   {"operator": "KARI",               "country": "KR",  "country_name": "South Korea",           "purpose": "High-Res Earth Observation",           "source": "KARI",              "destination": "Earth Observation"}),
    ("ALOS",      {"operator": "JAXA",               "country": "JP",  "country_name": "Japan",                 "purpose": "SAR Earth Observation",                "source": "JAXA",              "destination": "Earth Observation (SAR)"}),
    ("DEIMOS",    {"operator": "Deimos Imaging",     "country": "ES",  "country_name": "Spain",                 "purpose": "Commercial Earth Observation",         "source": "Deimos Imaging",    "destination": "Commercial Earth Observation"}),
    ("PLEIADES",  {"operator": "Airbus DS / CNES",   "country": "FR",  "country_name": "France",                "purpose": "High-Res Optical Imaging",             "source": "Airbus DS",         "destination": "Earth Observation"}),
    ("WORLDVIEW", {"operator": "Maxar",              "country": "US",  "country_name": "United States",         "purpose": "Commercial High-Res Imaging",          "source": "Maxar",             "destination": "Commercial Earth Observation"}),
    ("GEOEYE",    {"operator": "Maxar",              "country": "US",  "country_name": "United States",         "purpose": "Commercial High-Res Imaging",          "source": "Maxar",             "destination": "Commercial Earth Observation"}),
    ("GAOFEN",    {"operator": "CNSA",               "country": "CN",  "country_name": "China",                 "purpose": "High-Res Earth Observation",           "source": "CNSA",              "destination": "Earth Observation"}),
    ("SENTINEL",  {"operator": "ESA / Copernicus",   "country": "EU",  "country_name": "European Union",        "purpose": "Earth Observation (Copernicus)",       "source": "ESA",               "destination": "Earth Observation"}),

    # ── Geostationary Communications ───────────────────────────────────────
    ("INTELSAT",  {"operator": "Intelsat",           "country": "US",  "country_name": "United States",         "purpose": "Geostationary Communications",         "source": "Intelsat",          "destination": "GEO Comms"}),
    ("EUTELSAT",  {"operator": "Eutelsat",           "country": "FR",  "country_name": "France",                "purpose": "Geostationary Communications",         "source": "Eutelsat",          "destination": "GEO Comms"}),
    ("HOTBIRD",   {"operator": "Eutelsat",           "country": "FR",  "country_name": "France",                "purpose": "Geostationary Broadcast",              "source": "Eutelsat",          "destination": "GEO Comms"}),
    ("INMARSAT",  {"operator": "Inmarsat",           "country": "GB",  "country_name": "United Kingdom",        "purpose": "Geostationary Mobile Comms",           "source": "Inmarsat",          "destination": "GEO Comms"}),
    ("ASTRA",     {"operator": "SES",                "country": "LU",  "country_name": "Luxembourg",            "purpose": "Geostationary Broadcast",              "source": "SES",               "destination": "GEO Comms"}),
    ("SES-",      {"operator": "SES",                "country": "LU",  "country_name": "Luxembourg",            "purpose": "Geostationary Communications",         "source": "SES",               "destination": "GEO Comms"}),
    ("TELSTAR",   {"operator": "Telesat",            "country": "CA",  "country_name": "Canada",                "purpose": "Geostationary Communications",         "source": "Telesat",           "destination": "GEO Comms"}),
    ("ANIK",      {"operator": "Telesat",            "country": "CA",  "country_name": "Canada",                "purpose": "Geostationary Communications",         "source": "Telesat",           "destination": "GEO Comms"}),
    ("BSAT",      {"operator": "B-SAT Corporation",  "country": "JP",  "country_name": "Japan",                 "purpose": "Geostationary Broadcast",              "source": "B-SAT",             "destination": "Japan Broadcast (GEO)"}),
    ("PAKSAT",    {"operator": "SUPARCO",            "country": "PK",  "country_name": "Pakistan",              "purpose": "Geostationary Communications",         "source": "SUPARCO",           "destination": "Pakistan GEO Comms"}),
    ("BADR",      {"operator": "Arabsat",            "country": "SA",  "country_name": "Saudi Arabia",          "purpose": "Geostationary Broadcast",              "source": "Arabsat",           "destination": "MENA Region (GEO)"}),
    ("NILESAT",   {"operator": "Nilesat",            "country": "EG",  "country_name": "Egypt",                 "purpose": "Geostationary Broadcast",              "source": "Nilesat",           "destination": "MENA Region (GEO)"}),
    ("YAMAL",     {"operator": "Gazprom Space Systems","country": "RU","country_name": "Russia",                "purpose": "Geostationary Communications",         "source": "Gazprom",           "destination": "Russia GEO Comms"}),
    ("EXPRESS",   {"operator": "RSCC",               "country": "RU",  "country_name": "Russia",                "purpose": "Geostationary Communications",         "source": "RSCC",              "destination": "Russia GEO Comms"}),
    ("CHINASAT",  {"operator": "China Satcom",       "country": "CN",  "country_name": "China",                 "purpose": "Geostationary Communications",         "source": "China Satcom",      "destination": "China GEO Comms"}),
    ("APSTAR",    {"operator": "APT Satellite",      "country": "HK",  "country_name": "Hong Kong",             "purpose": "Geostationary Communications",         "source": "APT Satellite",     "destination": "Asia-Pacific GEO"}),
    ("THAICOM",   {"operator": "Thaicom",            "country": "TH",  "country_name": "Thailand",              "purpose": "Geostationary Communications",         "source": "Thaicom",           "destination": "Asia-Pacific GEO"}),
    ("MEASAT",    {"operator": "MEASAT",             "country": "MY",  "country_name": "Malaysia",              "purpose": "Geostationary Communications",         "source": "MEASAT",            "destination": "Asia-Pacific GEO"}),
    ("KOREASAT",  {"operator": "KT SAT",             "country": "KR",  "country_name": "South Korea",           "purpose": "Geostationary Communications",         "source": "KT SAT",            "destination": "Asia-Pacific GEO"}),

    # ── Space Stations / Crewed / Cargo ────────────────────────────────────
    ("ISS",       {"operator": "NASA / Roscosmos / ESA / JAXA / CSA", "country": "INT", "country_name": "International", "purpose": "Crewed Space Station",   "source": "Multi-national",    "destination": "Low Earth Orbit Research"}),
    ("TIANGONG",  {"operator": "CMSA",               "country": "CN",  "country_name": "China",                 "purpose": "Crewed Space Station",                 "source": "CMSA",              "destination": "Low Earth Orbit Research"}),
    ("CSS",       {"operator": "CMSA",               "country": "CN",  "country_name": "China",                 "purpose": "Space Station Module",                 "source": "CMSA",              "destination": "Low Earth Orbit Research"}),
    ("SOYUZ",     {"operator": "Roscosmos",          "country": "RU",  "country_name": "Russia",                "purpose": "Crewed Transport",                     "source": "Roscosmos",         "destination": "ISS / LEO"}),
    ("PROGRESS",  {"operator": "Roscosmos",          "country": "RU",  "country_name": "Russia",                "purpose": "Cargo Resupply",                       "source": "Roscosmos",         "destination": "ISS"}),
    ("CYGNUS",    {"operator": "Northrop Grumman",   "country": "US",  "country_name": "United States",         "purpose": "Cargo Resupply",                       "source": "Northrop Grumman",  "destination": "ISS"}),
    ("DRAGON",    {"operator": "SpaceX / NASA",      "country": "US",  "country_name": "United States",         "purpose": "Crewed / Cargo Transport",             "source": "SpaceX",            "destination": "ISS"}),
    ("SHENZHOU",  {"operator": "CMSA",               "country": "CN",  "country_name": "China",                 "purpose": "Crewed Transport",                     "source": "CMSA",              "destination": "Tiangong"}),
    ("TIANZHOU",  {"operator": "CMSA",               "country": "CN",  "country_name": "China",                 "purpose": "Cargo Resupply",                       "source": "CMSA",              "destination": "Tiangong"}),

    # ── Science / Research ─────────────────────────────────────────────────
    ("HUBBLE",    {"operator": "NASA / ESA",         "country": "US",  "country_name": "United States",         "purpose": "Space Telescope (Optical)",            "source": "NASA",              "destination": "Astronomy"}),
    ("JWST",      {"operator": "NASA / ESA / CSA",   "country": "US",  "country_name": "United States",         "purpose": "Space Telescope (Infrared)",           "source": "NASA",              "destination": "Sun-Earth L2"}),
    ("CHANDRA",   {"operator": "NASA",               "country": "US",  "country_name": "United States",         "purpose": "X-Ray Space Telescope",                "source": "NASA",              "destination": "Astronomy"}),
    ("SWIFT",     {"operator": "NASA",               "country": "US",  "country_name": "United States",         "purpose": "Gamma-Ray Burst Observatory",          "source": "NASA",              "destination": "Astronomy"}),
    ("FERMI",     {"operator": "NASA",               "country": "US",  "country_name": "United States",         "purpose": "Gamma-Ray Space Telescope",            "source": "NASA",              "destination": "Astronomy"}),

    # ── Ham / Amateur radio ────────────────────────────────────────────────
    ("AO-",       {"operator": "AMSAT",              "country": "INT", "country_name": "International",         "purpose": "Amateur Radio",                        "source": "AMSAT",             "destination": "Amateur Radio"}),
    ("FO-",       {"operator": "JARL",               "country": "JP",  "country_name": "Japan",                 "purpose": "Amateur Radio",                        "source": "JARL",              "destination": "Amateur Radio"}),
    ("SO-",       {"operator": "AMSAT",              "country": "INT", "country_name": "International",         "purpose": "Amateur Radio",                        "source": "AMSAT",             "destination": "Amateur Radio"}),

    # ── Modern military / intelligence / SDA & USSF programs ───────────────
    # These names started flying 2020+ and are missing from older SatNOGS dumps.
    ("PRAETORIAN", {"operator": "US Space Force / USSF",      "country": "US",  "country_name": "United States",  "purpose": "Space Domain Awareness / SSA",       "source": "US Space Force",     "destination": "Space Domain Awareness"}),
    ("USSF-",      {"operator": "US Space Force",             "country": "US",  "country_name": "United States",  "purpose": "Classified Military",                 "source": "US Space Force",     "destination": "Military"}),
    ("NROL-",      {"operator": "NRO",                        "country": "US",  "country_name": "United States",  "purpose": "Classified Reconnaissance",           "source": "NRO",                "destination": "Military Reconnaissance"}),
    ("VICTUS",     {"operator": "US Space Force / SSC",       "country": "US",  "country_name": "United States",  "purpose": "Tactically Responsive Space",         "source": "US Space Force",     "destination": "Military"}),
    ("SDA-T",      {"operator": "Space Development Agency",   "country": "US",  "country_name": "United States",  "purpose": "Tranche Tracking / Transport Layer",  "source": "SDA",                "destination": "Proliferated LEO Constellation"}),
    ("TRANSPORT",  {"operator": "Space Development Agency",   "country": "US",  "country_name": "United States",  "purpose": "Tactical Comms Constellation",        "source": "SDA",                "destination": "Proliferated LEO Constellation"}),
    ("TRACKING",   {"operator": "Space Development Agency",   "country": "US",  "country_name": "United States",  "purpose": "Missile Warning / Tracking",          "source": "SDA",                "destination": "Proliferated LEO Constellation"}),
    ("SBIRS",      {"operator": "US Space Force",             "country": "US",  "country_name": "United States",  "purpose": "Missile Warning (SBIRS)",             "source": "US Space Force",     "destination": "Strategic Surveillance"}),
    ("STP-SAT",    {"operator": "DoD Space Test Program",     "country": "US",  "country_name": "United States",  "purpose": "Military Technology Demonstration",   "source": "US DoD",             "destination": "Military Research"}),

    # ── Modern commercial constellations (post-2018) ──────────────────────
    ("BLACKSKY",   {"operator": "BlackSky Technology",        "country": "US",  "country_name": "United States",  "purpose": "Commercial High-Res Imaging",         "source": "BlackSky",           "destination": "Commercial Earth Observation"}),
    ("HAWKEYE",    {"operator": "HawkEye 360",                "country": "US",  "country_name": "United States",  "purpose": "RF Geolocation",                      "source": "HawkEye 360",        "destination": "Commercial SIGINT"}),
    ("HAWK-",      {"operator": "HawkEye 360",                "country": "US",  "country_name": "United States",  "purpose": "RF Geolocation",                      "source": "HawkEye 360",        "destination": "Commercial SIGINT"}),
    ("LEMUR-",     {"operator": "Spire Global",               "country": "US",  "country_name": "United States",  "purpose": "AIS / Weather / RF Sensing",          "source": "Spire Global",       "destination": "Commercial Data Network"}),
    ("SPIRE",      {"operator": "Spire Global",               "country": "US",  "country_name": "United States",  "purpose": "AIS / Weather / RF Sensing",          "source": "Spire Global",       "destination": "Commercial Data Network"}),
    ("FLOCK",      {"operator": "Planet Labs",                "country": "US",  "country_name": "United States",  "purpose": "Daily Earth Imaging (Dove)",          "source": "Planet Labs",        "destination": "Commercial Earth Observation"}),
    ("SUPERDOVE",  {"operator": "Planet Labs",                "country": "US",  "country_name": "United States",  "purpose": "Daily Earth Imaging",                 "source": "Planet Labs",        "destination": "Commercial Earth Observation"}),
    ("BLUEBIRD",   {"operator": "AST SpaceMobile",            "country": "US",  "country_name": "United States",  "purpose": "Direct-to-Phone Broadband",           "source": "AST SpaceMobile",    "destination": "Cellular Constellation"}),
    ("BLUEWALKER", {"operator": "AST SpaceMobile",            "country": "US",  "country_name": "United States",  "purpose": "Direct-to-Phone Broadband (Prototype)","source": "AST SpaceMobile",   "destination": "Cellular Constellation"}),
    ("JILIN",      {"operator": "Chang Guang Satellite",      "country": "CN",  "country_name": "China",          "purpose": "Commercial High-Res Imaging",         "source": "Chang Guang",        "destination": "Commercial Earth Observation"}),
    ("YUNHAI",     {"operator": "CASC",                       "country": "CN",  "country_name": "China",          "purpose": "Atmospheric Observation / Recon",     "source": "CASC",               "destination": "Earth Observation"}),
    ("GUOWANG",    {"operator": "China SatNet",               "country": "CN",  "country_name": "China",          "purpose": "Broadband Internet Constellation",    "source": "China SatNet",       "destination": "Global Internet Coverage"}),
    ("QIANFAN",    {"operator": "Shanghai Spacecom (SSST)",   "country": "CN",  "country_name": "China",          "purpose": "Broadband Internet Constellation",    "source": "SSST",               "destination": "Global Internet Coverage"}),
    ("STARSHIELD", {"operator": "SpaceX / NRO",               "country": "US",  "country_name": "United States",  "purpose": "Military Reconnaissance Constellation","source": "NRO / SpaceX",      "destination": "Military Reconnaissance"}),
    ("YAM-",       {"operator": "Loft Orbital",               "country": "US",  "country_name": "United States",  "purpose": "Satellite-as-a-Service Hosted Payload","source": "Loft Orbital",      "destination": "Multi-Payload LEO"}),
    ("VARDA",      {"operator": "Varda Space Industries",     "country": "US",  "country_name": "United States",  "purpose": "In-Space Manufacturing",              "source": "Varda",              "destination": "Microgravity Production"}),
    ("BANDWAGON",  {"operator": "SpaceX (Rideshare)",         "country": "INT", "country_name": "International",  "purpose": "Rideshare Payload",                   "source": "SpaceX Rideshare",   "destination": "Various (Rideshare)"}),
    ("TRANSPORTER",{"operator": "SpaceX (Rideshare)",         "country": "INT", "country_name": "International",  "purpose": "Rideshare Payload",                   "source": "SpaceX Rideshare",   "destination": "Various (Rideshare)"}),
    ("O3B",        {"operator": "SES O3b",                    "country": "LU",  "country_name": "Luxembourg",     "purpose": "MEO Broadband Communications",        "source": "SES",                "destination": "MEO Comms"}),
    ("MPOWER",     {"operator": "SES O3b mPOWER",             "country": "LU",  "country_name": "Luxembourg",     "purpose": "MEO Broadband Communications",        "source": "SES",                "destination": "MEO Comms"}),
    ("KINEIS",     {"operator": "Kineis (CLS)",               "country": "FR",  "country_name": "France",         "purpose": "IoT Constellation (Argos)",           "source": "Kineis",             "destination": "Global IoT Network"}),
    ("ELSA-",      {"operator": "Astroscale",                 "country": "JP",  "country_name": "Japan",          "purpose": "Active Debris Removal Demo",          "source": "Astroscale",         "destination": "On-Orbit Servicing"}),
    ("CLEARSPACE", {"operator": "ClearSpace",                 "country": "CH",  "country_name": "Switzerland",    "purpose": "Active Debris Removal",               "source": "ClearSpace",         "destination": "On-Orbit Servicing"}),

    # ── Specific identifier prefixes that signal classified/unidentified ──
    ("OBJECT",     {"operator": "Unknown (Unidentified Object)","country": "??","country_name": "Unidentified",   "purpose": "Unidentified Object",                 "source": "Catalog placeholder","destination": "Unknown"}),
    ("TBA-",       {"operator": "Unknown (To Be Assigned)",   "country": "??", "country_name": "Unassigned",      "purpose": "Newly Catalogued (TBA)",              "source": "Catalog placeholder","destination": "Unknown"}),
]

# SatNOGS catalog cache
_satnogs_catalog: dict | None = None
_catalog_fetched_at: float = 0
CATALOG_TTL = 24 * 3600  # refresh daily

async def get_satnogs_catalog() -> dict:
    global _satnogs_catalog, _catalog_fetched_at
    now = time.time()
    if _satnogs_catalog and now - _catalog_fetched_at < CATALOG_TTL:
        return _satnogs_catalog
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                "https://raw.githubusercontent.com/satvisorcom/satvisor-data/master/catalog/satnogs.json"
            )
            r.raise_for_status()
            _satnogs_catalog = r.json()
            _catalog_fetched_at = now
    except Exception:
        if _satnogs_catalog:
            return _satnogs_catalog
        _satnogs_catalog = {}
    return _satnogs_catalog


def _parse_intl_designator(line1: str) -> dict:
    """Extract launch year + launch number from TLE line 1 columns 10-17.

    Format: 'YYNNNAAA' where YY is 2-digit year (00-56 = 2000-2056, 57-99 =
    1957-1999 per NORAD convention), NNN is launch # in that year, AAA is
    the piece letter(s) within that launch. Returns
      {launch_year, launch_num, intl_designator}
    or {} if the line is too short to parse.
    """
    if not line1 or len(line1) < 17:
        return {}
    chunk = line1[9:17].strip()
    if len(chunk) < 5:
        return {}
    try:
        yy = int(chunk[:2])
        full_year = 2000 + yy if yy <= 56 else 1900 + yy
        num = int(chunk[2:5])
        piece = chunk[5:].strip() or ""
        return {
            "launch_year": full_year,
            "launch_num":  num,
            "intl_designator": f"{full_year}-{num:03d}{piece}",
        }
    except (ValueError, TypeError):
        return {}


def _find_tle_lines_for_norad(norad: str) -> tuple[str, str, str] | None:
    """Search all cached TLE blocks (per-category mirror cache + per-NORAD
    hires-eo cache) for a NORAD ID. Returns (name, line1, line2) or None.
    """
    # Per-NORAD hi-res EO cache: dict[norad -> {line1, line2}]
    cached = _hires_eo_tle_cache.get(norad)
    if cached:
        sat = _HIRES_EO_BY_NORAD.get(norad)
        nm = sat["name"] if sat else norad
        return (nm, cached["line1"], cached["line2"])
    # Category bulk cache
    for cat_cache in tle_cache.values():
        lines = [l.strip() for l in cat_cache["text"].splitlines() if l.strip()]
        for i in range(0, len(lines) - 2, 3):
            if (lines[i+1].startswith("1 ")
                    and lines[i+1][2:7].strip() == norad):
                return (lines[i], lines[i+1], lines[i+2])
    return None


def build_metadata(norad: str, name: str, catalog: dict) -> dict:
    """Build full satellite metadata from catalog + name pattern matching."""
    meta: dict = {"norad": norad, "name": name}

    # Pre-compute TLE-derived launch year. Even when SatNOGS or pattern match
    # gives us most of the data, the intl designator is a reliable anchor.
    tle = _find_tle_lines_for_norad(norad)
    intl = _parse_intl_designator(tle[1]) if tle else {}

    # 1. Try SatNOGS catalog first
    entry = catalog.get(norad)
    if entry:
        sat = entry.get("sat", [])
        if len(sat) >= 9:
            cc_raw = sat[5] or ""
            ccs = [c.strip() for c in cc_raw.split(",") if c.strip()]
            country_names = ", ".join(COUNTRY_NAMES.get(c, c) for c in ccs)
            meta.update({
                "operator":     sat[6] or "Unknown",
                "country":      cc_raw,
                "country_name": country_names or "Unknown",
                "status":       sat[3] or "unknown",
                "launch_date":  sat[4],
                "image":        f"https://db.satnogs.org/media/{sat[7]}" if sat[7] else None,
                "website":      sat[8],
                "purpose":      _infer_purpose(name),
                "source":       country_names or "Unknown",
                "destination":  _infer_destination(name),
                "catalog_source": "SatNOGS / CelesTrak",
                "intl_designator": intl.get("intl_designator"),
            })
            return meta

    # 2. Fall back to name pattern matching
    name_up = name.upper()
    for pattern, info in NAME_PATTERNS:
        if pattern in name_up:
            meta.update(info)
            meta["status"] = "operational"
            # Use TLE launch year as launch date if we don't have a real one.
            meta["launch_date"] = (str(intl["launch_year"])
                                   if intl.get("launch_year") else None)
            meta["image"] = None
            meta["website"] = None
            meta["catalog_source"] = (
                f"Pattern match + TLE intl-designator ({intl.get('intl_designator')})"
                if intl.get("intl_designator") else "Pattern match"
            )
            meta["intl_designator"] = intl.get("intl_designator")
            return meta

    # 3. Honest unknown — but enriched with whatever we can derive from the TLE
    meta.update({
        "operator": "Unknown",
        "country": "Unknown",
        "country_name": "Unknown",
        # If the satellite is being actively tracked it's operational by
        # definition; "unknown" is misleading for an object we're showing
        # a live position for.
        "status": "operational" if tle else "unknown",
        "launch_date": str(intl["launch_year"]) if intl.get("launch_year") else None,
        "image": None,
        "website": None,
        "purpose": _infer_purpose(name),
        "source": (f"TLE intl-designator {intl.get('intl_designator')}"
                   if intl.get("intl_designator") else "Unknown"),
        "destination": _infer_destination(name),
        "catalog_source": (
            f"TLE only — not in public catalogs (intl-designator "
            f"{intl.get('intl_designator')})"
            if intl.get("intl_designator") else "None"
        ),
        "intl_designator": intl.get("intl_designator"),
    })
    return meta


def _infer_purpose(name: str) -> str:
    n = name.upper()
    if any(x in n for x in ["STARLINK", "ONEWEB", "KUIPER"]): return "Broadband Internet"
    if any(x in n for x in ["GPS", "NAVSTAR", "GLONASS", "GALILEO", "BEIDOU"]): return "Navigation"
    if any(x in n for x in ["NOAA", "METEOR", "METOP", "GOES", "DMSP"]): return "Weather / Earth Observation"
    if any(x in n for x in ["ISS", "TIANGONG", "CSS", "MIR"]): return "Space Station"
    if any(x in n for x in ["SOYUZ", "PROGRESS", "CYGNUS", "DRAGON", "HTV"]): return "Cargo / Crew Transport"
    if any(x in n for x in ["IRIDIUM", "GLOBALSTAR", "INTELSAT", "SES"]): return "Communications"
    if any(x in n for x in ["LANDSAT", "SENTINEL", "SPOT", "WORLDVIEW"]): return "Earth Observation"
    if any(x in n for x in ["CUBESAT", "NANOSAT"]): return "CubeSat / Research"
    return "Scientific / Research"


def _infer_destination(name: str) -> str:
    n = name.upper()
    if any(x in n for x in ["STARLINK", "ONEWEB"]): return "Global Internet Coverage"
    if any(x in n for x in ["GPS", "NAVSTAR", "GLONASS", "GALILEO"]): return "Global Navigation"
    if any(x in n for x in ["NOAA", "METEOR", "METOP", "GOES", "DMSP"]): return "Global Weather Monitoring"
    if any(x in n for x in ["ISS", "CSS", "TIANGONG"]): return "Low Earth Orbit Research"
    if any(x in n for x in ["PROGRESS", "CYGNUS", "DRAGON", "SOYUZ", "HTV"]): return "ISS Resupply"
    return "Low Earth Orbit"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/categories")
def list_categories():
    return {
        cat.value: {"label": meta["label"], "max": meta["max"]}
        for cat, meta in CATEGORY_META.items()
    }


@app.get("/api/tle", response_class=PlainTextResponse)
async def get_tle(category: str = Query(...)):
    # Special case: the curated Imagery+SAR list is not a single CelesTrak group
    # but a hand-picked NORAD set. Assemble its TLE block on the fly so the
    # frontend's generic loadSatellites() path works without an external proxy.
    if category == "hires-eo":
        import asyncio
        results = await asyncio.gather(
            *[_fetch_hires_eo_tle(s["norad"]) for s in HIRES_EO_SATS]
        )
        out: list[str] = []
        for sat, res in zip(HIRES_EO_SATS, results):
            if res is None:
                continue
            l1, l2 = res
            # Same name-match guard as /api/positions/hires-eo so the
            # frontend never builds a satrec for a wrong-NORAD entry.
            tle_meta = _hires_eo_tle_cache.get(sat["norad"], {})
            tle_name = tle_meta.get("tle_name") or ""
            if tle_name and not _names_match(sat["name"], tle_name):
                continue
            out.extend([sat["name"], l1, l2])
        return "\n".join(out) + "\n"

    try:
        cat = Category(category)
    except ValueError:
        raise HTTPException(400, detail=f"Unknown category: {category}")
    return await get_tle_text(cat)


def _country_for(norad: str, name: str, catalog: dict) -> tuple[str | None, str | None]:
    """(iso2_code, full_name) for a satellite so the frontend can flag generic
    (non-curated) satellites too. Tries the SatNOGS catalog first, then the
    name-pattern table (covers newer sats not yet in the catalog, e.g.
    PRAETORIAN/GPS/NOAA). None if neither knows the owner."""
    entry = catalog.get(norad)
    if entry:
        sat = entry.get("sat", [])
        if len(sat) >= 9 and sat[5]:
            cc = sat[5].split(",")[0].strip()
            if cc:
                return cc, COUNTRY_NAMES.get(cc, cc)
    nu = (name or "").upper()
    for pat, info in NAME_PATTERNS:
        if pat in nu and info.get("country"):
            cc = info["country"]
            return cc, info.get("country_name") or COUNTRY_NAMES.get(cc, cc)
    return None, None


def _attach_country(records, catalog: dict) -> list[dict]:
    """Propagate each record and stamp norad + country/country_code on it."""
    out: list[dict] = []
    for name, l1, l2 in records:
        p = propagate_now(name, l1, l2)
        if not p:
            continue
        norad = l1[2:7].strip()
        p["norad"] = norad
        code, cname = _country_for(norad, name, catalog)
        if code:
            p["country_code"] = code
        if cname:
            p["country"] = cname
        out.append(p)
    return out


@app.get("/api/positions")
async def get_positions(category: Category = Query(...)):
    """Return live SGP4-propagated positions for all satellites in a category."""
    text = await get_tle_text(category)
    catalog = await get_satnogs_catalog()
    records = parse_records(text, CATEGORY_META[category]["max"])
    positions = _attach_country(records, catalog)
    return {
        "category": category.value,
        "count": len(positions),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions": positions,
    }


@app.get("/api/positions/pakistan")
async def get_positions_pakistan(category: Category = Query(...)):
    """Return only satellites currently over Pakistan (23-37N, 60-78E)."""
    text = await get_tle_text(category)
    catalog = await get_satnogs_catalog()
    records = parse_records(text, CATEGORY_META[category]["max"])
    all_positions = _attach_country(records, catalog)
    over_pk = [
        p for p in all_positions
        if 23 <= p["lat"] <= 37 and 60 <= p["lon"] <= 78
    ]
    return {
        "category": category.value,
        "total": len(all_positions),
        "over_pakistan": len(over_pk),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions": over_pk,
    }


# ── Curated imagery & SAR surveillance satellite list (mirrors hires_eo_satellites.py) ───
# sensor_category: "Optical" | "SAR" | "Military"
# Per-satellite tilt + altitude metadata.
#
#   altitude_km    : nominal operating altitude (from spec sheet, NOT from live
#                    TLE — TLEs can be stale/swapped; nominal is the truth-of-
#                    record for capability analysis).
#   max_tilt_deg   : operationally documented maximum off-nadir tilt (optical)
#                    or maximum incidence angle (SAR). Sources:
#                      ISRO bulletins (CARTOSAT/RISAT/EOS),
#                      Maxar public spec sheets (WV/GeoEye),
#                      Airbus/CNES (Pleiades, CSO public bounds),
#                      DLR (TerraSAR-X), ASI (COSMO/CSG public modes),
#                      ESA (Sentinel-1 IW mode), JAXA (ALOS-2 ScanSAR),
#                      CNSA published bounds.
#                    For military-grade systems (CSO, TecSAR) the value is the
#                    public-domain upper bound; classified peak may exceed it.
#   tilt_standoff_km: pre-computed alt * tan(max_tilt_deg) — the ground-track
#                    horizontal distance the sensor footprint shifts at max
#                    tilt. Inserted at module load (see _annotate_hires_eo_).
#
HIRES_EO_SATS: list[dict] = [
    # India (ISRO) — Optical
    {"norad": "41599", "name": "CARTOSAT-2C",   "country": "India",       "operator": "ISRO",             "resolution_m": 0.65, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 505, "max_tilt_deg": 26},
    {"norad": "41948", "name": "CARTOSAT-2D",   "country": "India",       "operator": "ISRO",             "resolution_m": 0.65, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 505, "max_tilt_deg": 26},
    {"norad": "42767", "name": "CARTOSAT-2E",   "country": "India",       "operator": "ISRO",             "resolution_m": 0.65, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 505, "max_tilt_deg": 26},
    {"norad": "43111", "name": "CARTOSAT-2F",   "country": "India",       "operator": "ISRO",             "resolution_m": 0.65, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 505, "max_tilt_deg": 26},
    {"norad": "44804", "name": "CARTOSAT-3",    "country": "India",       "operator": "ISRO",             "resolution_m": 0.25, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 509, "max_tilt_deg": 32},
    # India (ISRO) — SAR reconnaissance
    {"norad": "51656", "name": "EOS-04",         "country": "India",       "operator": "ISRO",             "resolution_m": 1.00, "sensor": "SAR C-band",          "sensor_category": "SAR",      "altitude_km": 529, "max_tilt_deg": 49},
    {"norad": "44233", "name": "RISAT-2B",       "country": "India",       "operator": "ISRO",             "resolution_m": 0.50, "sensor": "SAR X-band",          "sensor_category": "SAR",      "altitude_km": 555, "max_tilt_deg": 49},
    {"norad": "44857", "name": "RISAT-2BR1",     "country": "India",       "operator": "ISRO",             "resolution_m": 0.50, "sensor": "SAR X-band",          "sensor_category": "SAR",      "altitude_km": 555, "max_tilt_deg": 49},
    # USA (Maxar) — Optical
    {"norad": "32060", "name": "WORLDVIEW-1",   "country": "USA",         "operator": "Maxar",            "resolution_m": 0.50, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 496, "max_tilt_deg": 40},
    {"norad": "35946", "name": "WORLDVIEW-2",   "country": "USA",         "operator": "Maxar",            "resolution_m": 0.46, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 770, "max_tilt_deg": 45},
    {"norad": "40115", "name": "WORLDVIEW-3",   "country": "USA",         "operator": "Maxar",            "resolution_m": 0.31, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 617, "max_tilt_deg": 45},
    {"norad": "33331", "name": "GEOEYE-1",      "country": "USA",         "operator": "Maxar",            "resolution_m": 0.41, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 681, "max_tilt_deg": 40},
    # France — Optical + Military
    {"norad": "38012", "name": "PLEIADES 1A",   "country": "France",      "operator": "Airbus DS",        "resolution_m": 0.50, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 694, "max_tilt_deg": 47},
    {"norad": "39019", "name": "PLEIADES 1B",   "country": "France",      "operator": "Airbus DS",        "resolution_m": 0.50, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 694, "max_tilt_deg": 47},
    {"norad": "43813", "name": "CSO-1",          "country": "France",      "operator": "DGA/French MoD",   "resolution_m": 0.35, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 800, "max_tilt_deg": 30},
    # CSO-2 (46070) and CSO-3 (49438) removed 2026-06-10: those NORAD IDs
    # actually belong to STARLINK-1536 / STARLINK-3044 in the active TLE feed,
    # not the French recon sats. Showing them mislabelled a Starlink as CSO.
    # Re-add with the correct NORADs (CSO-2 = 47307, CSO-3 = ~63000) once verified.
    # Italy — COSMO-SkyMed military SAR
    {"norad": "31598", "name": "COSMO-SKYMED 1","country": "Italy",       "operator": "ASI/Italian MoD",  "resolution_m": 1.00, "sensor": "SAR X-band Military", "sensor_category": "Military", "altitude_km": 619, "max_tilt_deg": 50},
    {"norad": "32376", "name": "COSMO-SKYMED 2","country": "Italy",       "operator": "ASI/Italian MoD",  "resolution_m": 1.00, "sensor": "SAR X-band Military", "sensor_category": "Military", "altitude_km": 619, "max_tilt_deg": 50},
    {"norad": "33412", "name": "COSMO-SKYMED 3","country": "Italy",       "operator": "ASI/Italian MoD",  "resolution_m": 1.00, "sensor": "SAR X-band Military", "sensor_category": "Military", "altitude_km": 619, "max_tilt_deg": 50},
    {"norad": "37216", "name": "COSMO-SKYMED 4","country": "Italy",       "operator": "ASI/Italian MoD",  "resolution_m": 1.00, "sensor": "SAR X-band Military", "sensor_category": "Military", "altitude_km": 619, "max_tilt_deg": 50},
    # CSG-1 NORAD corrected 2026-06-10: was 45026 (wrong sat in TLE feed), real is 44873.
    {"norad": "44873", "name": "CSG-1",          "country": "Italy",       "operator": "ASI/Italian MoD",  "resolution_m": 0.40, "sensor": "SAR X-band Military", "sensor_category": "Military", "altitude_km": 619, "max_tilt_deg": 60},
    # CSG-2 NORAD corrected 2026-06-10: was 49719 (wrong sat in TLE feed), real is 51444.
    {"norad": "51444", "name": "CSG-2",          "country": "Italy",       "operator": "ASI/Italian MoD",  "resolution_m": 0.40, "sensor": "SAR X-band Military", "sensor_category": "Military", "altitude_km": 619, "max_tilt_deg": 60},
    # CSG-3 added 2026-06-10 — new sub-metre SAR military sat, NORAD 67304.
    {"norad": "67304", "name": "CSG-3",          "country": "Italy",       "operator": "ASI/Italian MoD",  "resolution_m": 0.40, "sensor": "SAR X-band Military", "sensor_category": "Military", "altitude_km": 619, "max_tilt_deg": 60},
    # Germany — SAR
    {"norad": "31698", "name": "TERRASAR-X",    "country": "Germany",     "operator": "DLR/Airbus",       "resolution_m": 0.25, "sensor": "SAR X-band",          "sensor_category": "SAR",      "altitude_km": 514, "max_tilt_deg": 55},
    {"norad": "36605", "name": "TANDEM-X",      "country": "Germany",     "operator": "DLR/Airbus",       "resolution_m": 0.25, "sensor": "SAR X-band",          "sensor_category": "SAR",      "altitude_km": 514, "max_tilt_deg": 55},
    # South Korea
    {"norad": "38338", "name": "KOMPSAT-3",     "country": "South Korea", "operator": "KARI",             "resolution_m": 0.70, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 685, "max_tilt_deg": 30},
    {"norad": "40536", "name": "KOMPSAT-3A",    "country": "South Korea", "operator": "KARI",             "resolution_m": 0.55, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 528, "max_tilt_deg": 30},
    {"norad": "39227", "name": "KOMPSAT-5",     "country": "South Korea", "operator": "KARI",             "resolution_m": 1.00, "sensor": "SAR X-band",          "sensor_category": "SAR",      "altitude_km": 550, "max_tilt_deg": 55},
    # China
    {"norad": "40118", "name": "GAOFEN-2",      "country": "China",       "operator": "CNSA",             "resolution_m": 0.80, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 631, "max_tilt_deg": 35},
    {"norad": "44703", "name": "GAOFEN-7",      "country": "China",       "operator": "CNSA",             "resolution_m": 0.65, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 506, "max_tilt_deg": 25},
    {"norad": "43585", "name": "GAOFEN-11",     "country": "China",       "operator": "CNSA",             "resolution_m": 0.10, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 695, "max_tilt_deg": 35},
    # GAOFEN-3 NORAD corrected 2026-06-10: was 41384 (wrong sat in TLE feed), real is 41727.
    {"norad": "41727", "name": "GAOFEN-3",      "country": "China",       "operator": "CNSA",             "resolution_m": 1.00, "sensor": "SAR C-band",          "sensor_category": "SAR",      "altitude_km": 755, "max_tilt_deg": 50},
    # Spain
    {"norad": "40013", "name": "DEIMOS-2",      "country": "Spain",       "operator": "Deimos Imaging",   "resolution_m": 0.75, "sensor": "Panchromatic",        "sensor_category": "Optical",  "altitude_km": 620, "max_tilt_deg": 30},
    {"norad": "43215", "name": "PAZ",            "country": "Spain",       "operator": "Hisdesat",         "resolution_m": 0.25, "sensor": "SAR X-band",          "sensor_category": "SAR",      "altitude_km": 514, "max_tilt_deg": 55},
    # ESA — Sentinel-1 SAR
    # SENTINEL-1A (39634) removed 2026-06-10: 5 m resolution violates the
    # ≤1 m sub-metre rule this catalog enforces.
    # Israel — Ofeq military recon + EROS-C3 commercial optical.
    # NORADs realigned 2026-06-11 to the authoritative analyst source (McCants):
    # Ofeq 16 = 45860 (was 46123, wrong), Ofeq 19 = 65432 (new), TecSAR = 32476.
    # Ofeq/TecSAR are WITHHELD from CelesTrak, so their TLEs come from the
    # supplemental analyst source (supplemental_tle.py) — lower confidence.
    # Old dark entries OFEQ 9 (36608) / OFEQ 11 (41759) dropped: decayed /
    # not in the current authoritative file.
    {"norad": "45860", "name": "OFEQ 16",       "country": "Israel",      "operator": "IAI/Israeli MoD",  "resolution_m": 0.50, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 600, "max_tilt_deg": 40},
    {"norad": "65432", "name": "OFEQ 19",       "country": "Israel",      "operator": "IAI/Israeli MoD",  "resolution_m": 0.50, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 600, "max_tilt_deg": 40},
    {"norad": "32476", "name": "TECSAR",        "country": "Israel",      "operator": "IAI/Israeli MoD",  "resolution_m": 1.00, "sensor": "SAR X-band Military", "sensor_category": "Military", "altitude_km": 580, "max_tilt_deg": 50},
    {"norad": "54880", "name": "EROS C3",       "country": "Israel",      "operator": "ImageSat International", "resolution_m": 0.30, "sensor": "Panchromatic",   "sensor_category": "Optical",  "altitude_km": 510, "max_tilt_deg": 40},
    # Japan — SAR
    # ALOS-2 (39769) removed 2026-06-10: NORAD belongs to RISING 2 (a Japanese
    # student CubeSat), AND ALOS-2's true resolution (3 m) violates ≤1 m rule.
    # China — Yaogan military reconnaissance (PLA). NORADs verified from
    # CelesTrak; resolution_m is an open-source ESTIMATE (true GSD classified).
    {"norad": "32289", "name": "YAOGAN-3",      "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "SAR Military",        "sensor_category": "Military", "altitude_km": 630, "max_tilt_deg": 40},
    {"norad": "33446", "name": "YAOGAN-4",      "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 650, "max_tilt_deg": 35},
    {"norad": "36110", "name": "YAOGAN-7",      "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 650, "max_tilt_deg": 35},
    {"norad": "36834", "name": "YAOGAN-10",     "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "SAR Military",        "sensor_category": "Military", "altitude_km": 630, "max_tilt_deg": 40},
    {"norad": "40143", "name": "YAOGAN-21",     "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 490, "max_tilt_deg": 35},
    {"norad": "40275", "name": "YAOGAN-22",     "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 490, "max_tilt_deg": 35},
    {"norad": "40310", "name": "YAOGAN-24",     "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 490, "max_tilt_deg": 35},
    {"norad": "40362", "name": "YAOGAN-26",     "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 490, "max_tilt_deg": 35},
    {"norad": "40878", "name": "YAOGAN-27",     "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "SAR Military",        "sensor_category": "Military", "altitude_km": 630, "max_tilt_deg": 40},
    {"norad": "41026", "name": "YAOGAN-28",     "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "Optical Military",    "sensor_category": "Military", "altitude_km": 490, "max_tilt_deg": 35},
    {"norad": "41038", "name": "YAOGAN-29",     "country": "China",       "operator": "PLA / CNSA",       "resolution_m": 1.00, "sensor": "SAR Military",        "sensor_category": "Military", "altitude_km": 630, "max_tilt_deg": 40},
]

# ── Full reference-book fleet (auto-loaded, name-verified NORADs) ─────────────
# Extends the curated core with the additional imaging satellites from the
# May-2026 Reference Book so the Pakistan Orbit Tracker's hi-res layer matches
# the 15-Day Forecast fleet (both now cover ~497). Mirrors the Tk-side
# Satellite_Tracker/hires_eo_extra.py.
try:
    import os as _os_x, sys as _sys_x
    _bd_x = _os_x.path.dirname(__file__)
    if _bd_x not in _sys_x.path:
        _sys_x.path.insert(0, _bd_x)
    # Uniquely-named so it can NEVER collide with Satellite_Tracker's
    # hires_eo_extra.py when both are frozen into the same PyInstaller bundle.
    # (That collision made the packaged tracker fall back to 47 satellites.)
    from hires_eo_ext_backend import EXTRA_HIRES_EO
    _seen_x = {s["norad"] for s in HIRES_EO_SATS}
    for _s_x in EXTRA_HIRES_EO:
        if _s_x["norad"] not in _seen_x:
            HIRES_EO_SATS.append(_s_x)
            _seen_x.add(_s_x["norad"])
    print(f"[FLEET] backend loaded {len(HIRES_EO_SATS)} hi-res satellites "
          f"(curated core + reference-book catalog)")
except Exception as _e_x:
    print(f"[FLEET] backend reference-book extension not loaded: {_e_x}")


# ── Resolution filter: track ONLY satellites 3 m or better (per user spec) ────
# Mirrors the Satellite_Tracker forecast-engine filter so the live tracker map /
# position API shows the same <=3 m fleet as the forecast. Satellites with no
# known resolution are dropped. Keep MAX_RESOLUTION_M in sync with the Tk side
# (Satellite_Tracker/hires_eo_satellites.py); set to None to disable.
MAX_RESOLUTION_M = 3.0
if MAX_RESOLUTION_M is not None:
    _n_before = len(HIRES_EO_SATS)
    HIRES_EO_SATS[:] = [
        s for s in HIRES_EO_SATS
        if isinstance(s.get("resolution_m"), (int, float)) and s["resolution_m"] <= MAX_RESOLUTION_M
    ]
    print(f"[FLEET] backend resolution filter <= {MAX_RESOLUTION_M} m: kept "
          f"{len(HIRES_EO_SATS)} of {_n_before} satellites")


# Pre-compute the tilt standoff radius for each satellite once at import.
# Standoff = altitude * tan(max_tilt). This is the flat-earth approximation
# which is accurate to within a few percent for LEO altitudes <= 800 km and
# tilt angles <= 60 deg; spherical-earth correction would add < 5 km here.
def _annotate_hires_eo_with_standoff():
    for s in HIRES_EO_SATS:
        alt = s.get("altitude_km", 0)
        tilt = s.get("max_tilt_deg", 0)
        s["tilt_standoff_km"] = round(alt * math.tan(math.radians(tilt)), 1)
_annotate_hires_eo_with_standoff()
_HIRES_EO_BY_NORAD = {s["norad"]: s for s in HIRES_EO_SATS}


# ── Pakistan strategic-site catalog (FEAT-004) ──────────────────────────────
# Import from the Satellite_Tracker sibling module so both the Tk app and
# this backend share one source of truth for the publicly-known military /
# capital / nuclear / port facilities used in targeting analysis.
import os as _os
import sys as _sys
_SAT_DIR = _os.path.normpath(_os.path.join(
    _os.path.dirname(__file__), "..", "..", "..", "Satellite_Tracker"))
if _SAT_DIR not in _sys.path:
    _sys.path.insert(0, _SAT_DIR)
try:
    from pakistan_strategic_sites import STRATEGIC_SITES, haversine_km
    _STRATEGIC_SITES_OK = True
except ImportError:
    STRATEGIC_SITES = []
    _STRATEGIC_SITES_OK = False
    def haversine_km(a, b, c, d): return 1e9


def _instant_targets(lat: float, lon: float,
                     standoff_km: float | None) -> list[dict]:
    """Snapshot version of strategic-site targeting: which catalog sites
    are within the satellite's standoff_km of THIS sub-point right now.
    Used by the live /api/positions endpoint (the forecast does the same
    over the full pass arc, not just instant).
    """
    if not standoff_km or standoff_km <= 0:
        return []
    out: list[dict] = []
    for s in STRATEGIC_SITES:
        d = haversine_km(lat, lon, s["lat"], s["lon"])
        if d <= standoff_km:
            out.append({
                "name":        s["name"],
                "city":        s["city"],
                "tier":        s["tier"],
                "category":    s["category"],
                "min_dist_km": round(d, 1),
            })
    out.sort(key=lambda x: x["min_dist_km"])
    return out

# TLE cache for individual NORAD fetches: norad -> {fetched_at, line1, line2}
_hires_eo_tle_cache: dict[str, dict] = {}
_HIRES_EO_TLE_TTL = 2 * 3600   # 2 h — matches category cache

# Bulk-mirror cache: a single fetch of the active.tle file (~15k sats) on the
# GitHub mirror covers nearly every curated NORAD. Per-NORAD CelesTrak
# requests get rate-limited fast (37 parallel requests trip it instantly),
# so the mirror is the primary path; CelesTrak is the fallback for any
# NORAD missing from the mirror.
_HIRES_EO_NORADS: set[str] = {s["norad"] for s in HIRES_EO_SATS}


async def _populate_hires_eo_cache_from_mirror() -> int:
    """Fetch the bulk active TLE from the mirror, extract our 37 curated NORADs.
    Returns the number of entries populated into the per-NORAD cache."""
    try:
        text = await get_tle_text(Category.active)
    except Exception:
        return 0
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    populated = 0
    now = time.time()
    for i in range(0, len(lines) - 2):
        l1, l2 = lines[i + 1], lines[i + 2]
        if not l1.startswith("1 ") or not l2.startswith("2 "):
            continue
        # TLE line 1: "1 NNNNNU ..." — NORAD is chars 2-7, strip non-digits
        norad_raw = l1[2:7].strip()
        norad = norad_raw.lstrip("0") or "0"
        if norad in _HIRES_EO_NORADS:
            _hires_eo_tle_cache[norad] = {
                "fetched_at": now,
                "line1": l1,
                "line2": l2,
                # Save the TLE-side name (title line, immediately before l1)
                # so /api/positions/hires-eo can detect catalog NORAD typos
                # — see _names_match + _pos guard.
                "tle_name": lines[i],
            }
            populated += 1
    return populated


# ── Forecast TLE cache (the authoritative, FRESH source) ────────────────────
# The 15-day forecast engine keeps a per-NORAD TLE cache that its hourly task
# refreshes from CelesTrak gp.php (per-NORAD, so it is never the stale bulk
# snapshot the GitHub mirror can be). Reusing it here makes the LIVE MAP draw
# orbits from the SAME up-to-date elements as the forecast — fixing the
# "blind-calendar crossing vs live-tracker orbit" mismatch that appears when
# the mirror's TLE for a satellite is weeks old (SGP4 extrapolated that far is
# a quarter-orbit wrong).
_hires_eo_forecast_mtime = 0.0


def _forecast_tle_cache_path() -> str:
    # backend/ -> pot/ -> pot/ -> <root> -> Satellite_Tracker/. Same relative
    # layout in dev and in the PyInstaller onedir bundle (_internal/...).
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(
        here, "..", "..", "..", "Satellite_Tracker", "tle_cache_celestrak.json"))


def _populate_hires_eo_cache_from_forecast() -> int:
    """Load the forecast engine's fresh per-NORAD TLE cache into ours.
    Returns the number of curated NORADs refreshed."""
    try:
        with open(_forecast_tle_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    # NORAD-keyed lookup tolerant of leading zeros.
    by_norad: dict[str, dict] = {}
    for k, e in data.items():
        if isinstance(e, dict) and e.get("line1") and e.get("line2"):
            by_norad[str(k).lstrip("0") or "0"] = e
    now = time.time()
    n = 0
    for sat in HIRES_EO_SATS:
        e = by_norad.get(str(sat["norad"]).lstrip("0") or "0")
        if not e:
            continue
        l1, l2 = e["line1"], e["line2"]
        if not (l1.startswith("1 ") and l2.startswith("2 ")):
            continue
        _hires_eo_tle_cache[sat["norad"]] = {
            "fetched_at": now, "line1": l1, "line2": l2,
            "tle_name": e.get("name", ""),
        }
        n += 1
    return n


def _names_match(curated: str, tle_name: str) -> bool:
    """Fuzzy match between a curated catalog name and the satellite name in the
    TLE feed. Tolerates common decorations:
      - "EOS-04" vs "EOS-4"                        (leading-zero padding)
      - "KOMPSAT-3" vs "ARIRANG-3 (KOMPSAT-3)"     (alias suffix)
      - "WORLDVIEW-3" vs "WORLDVIEW-3 (WV-3)"      (parenthetical)
    Returns False when the names plausibly refer to different satellites,
    so the caller can drop the catalog entry rather than show a Starlink
    mislabelled as something else.
    """
    if not curated or not tle_name:
        return False
    a = re.sub(r'[^A-Z0-9]', '', curated.upper())
    b = re.sub(r'[^A-Z0-9]', '', tle_name.upper())
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    # Strip leading zeros after a letter run: "EOS04" -> "EOS4"
    norm = lambda s: re.sub(r'([A-Z])0+(\d)', r'\1\2', s)
    a2, b2 = norm(a), norm(b)
    if a2 == b2 or a2 in b2 or b2 in a2:
        return True
    return False


# Negative cache: NORADs whose last per-NORAD fetch failed. Re-hitting a
# dead/slow CelesTrak for these on every request is what made
# /api/tle?category=hires-eo take 15+ s each call. Skip them for a window.
_hires_eo_tle_negcache: dict[str, float] = {}
_HIRES_EO_NEG_TTL = 15 * 60   # 15 min

# NORADs whose per-NORAD CelesTrak fetch is in flight in the BACKGROUND. With a
# 500+ satellite fleet, a fresh cache miss on ~50 sats used to be fetched
# synchronously inside /api/positions/hires-eo, stalling the whole response for
# ~18 s on the first load (and again every neg-cache window). We now fetch those
# in a background task so the live endpoint always returns instantly with
# whatever is cached; the missing TLEs land on a later poll.
_hires_eo_inflight: set[str] = set()


async def _bg_fetch_hires_eo_tle(norad: str) -> None:
    try:
        url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle"
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "pakistan-orbit-tracker/1.0"})
            r.raise_for_status()
            lines = [l.strip() for l in r.text.splitlines() if l.strip()]
            if len(lines) >= 3 and lines[1].startswith("1 ") and lines[2].startswith("2 "):
                _hires_eo_tle_cache[norad] = {
                    "fetched_at": time.time(), "line1": lines[1],
                    "line2": lines[2], "tle_name": lines[0],
                }
                _hires_eo_tle_negcache.pop(norad, None)
                return
        _hires_eo_tle_negcache[norad] = time.time()   # bad/empty response
    except Exception:
        _hires_eo_tle_negcache[norad] = time.time()   # skip retries for a window
    finally:
        _hires_eo_inflight.discard(norad)


@app.on_event("startup")
async def _warm_hires_eo_cache_on_startup():
    """Pre-warm the hi-res TLE cache in the BACKGROUND at boot so the very first
    /api/positions/hires-eo poll returns instantly (populated) instead of
    blocking ~12 s on the local-forecast read + bulk-mirror download. Without
    this, a freshly-launched app shows an empty map for the first ~15 s."""
    import asyncio

    async def _warm():
        try:
            _populate_hires_eo_cache_from_forecast()          # local file, fast
        except Exception:
            pass
        try:
            await _populate_hires_eo_cache_from_mirror()      # bulk mirror, ~s
        except Exception:
            pass

    try:
        asyncio.create_task(_warm())
    except Exception:
        pass

# Serialises the bulk-mirror repopulate. Without it, ~48 parallel
# _fetch_hires_eo_tle() callers each download the huge active TLE file at
# once. With it, the first caller fills the cache and the rest find it warm.
import asyncio as _asyncio
_hires_eo_mirror_lock = _asyncio.Lock()
# True while a background bulk-mirror repopulate is running, so we trigger it
# exactly once instead of blocking every gathered caller on the download.
_hires_eo_mirror_inflight = False


async def _fetch_hires_eo_tle(norad: str) -> tuple[str, str] | None:
    """Fetch TLE for a single NORAD ID. Source priority:
    1. the forecast engine's FRESH per-NORAD cache (local, authoritative),
    2. the bulk GitHub mirror (fast, but can be weeks stale),
    3. per-NORAD CelesTrak gp.php (fallback for NORADs missing from 1 & 2).
    Successes cached 2 h; failures negative-cached 15 min + a short 4 s
    timeout, so a down CelesTrak can't stall the whole request."""
    now = time.time()
    # Prefer the forecast's fresh cache. Re-seed whenever its hourly task has
    # rewritten the file (cheap mtime check), overwriting any stale entries the
    # mirror left behind — this keeps live orbits consistent with the forecast.
    global _hires_eo_forecast_mtime
    try:
        m = os.path.getmtime(_forecast_tle_cache_path())
        if m != _hires_eo_forecast_mtime and _populate_hires_eo_cache_from_forecast() > 0:
            _hires_eo_forecast_mtime = m
    except OSError:
        pass
    cached = _hires_eo_tle_cache.get(norad)
    if cached and now - cached["fetched_at"] < _HIRES_EO_TLE_TTL:
        return cached["line1"], cached["line2"]

    # Withheld sats (Israeli Ofeq / TecSAR) are never on CelesTrak — serve them
    # from the analyst supplemental source (bundled seed + a cache the hourly
    # task refreshes). allow_network=False so we never block the event loop.
    try:
        from supplemental_tle import SUPPLEMENTAL_NORADS, supplemental_tles
        if norad in SUPPLEMENTAL_NORADS:
            supp = supplemental_tles(allow_network=False)
            if norad in supp:
                nm, l1, l2 = supp[norad]
                _hires_eo_tle_cache[norad] = {
                    "fetched_at": now, "line1": l1, "line2": l2, "tle_name": nm,
                }
                return l1, l2
            return None
    except Exception:
        pass

    # Cache miss — kick off a SINGLE background repopulate from the bulk mirror
    # and return immediately. Awaiting the ~15-20 s mirror download HERE, inside
    # the whole-fleet asyncio.gather, serialises 370+ coroutines behind one slow
    # network call and starves the single free-tier worker until the request
    # times out — that is the "Loading TLE data…" hang. The tracker re-polls
    # every few seconds and picks up the now-warm cache.
    global _hires_eo_mirror_inflight
    if not _hires_eo_mirror_inflight and (
        not _hires_eo_tle_cache or all(
            time.time() - e["fetched_at"] >= _HIRES_EO_TLE_TTL
            for e in _hires_eo_tle_cache.values()
        )
    ):
        _hires_eo_mirror_inflight = True
        async def _bg_mirror():
            try:
                await _populate_hires_eo_cache_from_mirror()
            finally:
                globals()["_hires_eo_mirror_inflight"] = False
        try:
            _asyncio.get_running_loop().create_task(_bg_mirror())
        except RuntimeError:
            _hires_eo_mirror_inflight = False
    cached = _hires_eo_tle_cache.get(norad)
    if cached:
        return cached["line1"], cached["line2"]

    # Recently failed? Don't re-stall on the slow CelesTrak round-trip.
    neg = _hires_eo_tle_negcache.get(norad)
    if neg and now - neg < _HIRES_EO_NEG_TTL:
        return (cached["line1"], cached["line2"]) if cached else None

    # Not cached and not recently-failed: fetch per-NORAD CelesTrak in the
    # BACKGROUND so this live call never blocks. A 500+ satellite fleet with
    # ~50 fresh cache misses used to stall /api/positions/hires-eo for ~18 s
    # (fetched synchronously). Now we serve cached/None immediately and the
    # TLE lands on a later poll once the background task completes.
    import asyncio
    if norad not in _hires_eo_inflight:
        _hires_eo_inflight.add(norad)
        try:
            asyncio.get_running_loop().create_task(_bg_fetch_hires_eo_tle(norad))
        except RuntimeError:
            _hires_eo_inflight.discard(norad)   # no running loop (should not happen)
    return (cached["line1"], cached["line2"]) if cached else None


# Pakistan bounding box
_PK_LAT_MIN, _PK_LAT_MAX = 23.5, 37.5
_PK_LON_MIN, _PK_LON_MAX = 60.5, 77.5
# 300 km ≈ 2.7° lat, 3.1° lon at ~30°N
_TILT_LAT_BUF = 2.7
_TILT_LON_BUF = 3.1


def _pk_zone(lat: float, lon: float) -> str:
    """
    Return zone string for a satellite ground point:
      'overhead'   — sub-satellite point inside Pakistan box
      'tilt_range' — within 300 km buffer of Pakistan border
      'outside'    — beyond tilt range
    """
    if (_PK_LAT_MIN <= lat <= _PK_LAT_MAX and
            _PK_LON_MIN <= lon <= _PK_LON_MAX):
        return "overhead"
    if (_PK_LAT_MIN - _TILT_LAT_BUF <= lat <= _PK_LAT_MAX + _TILT_LAT_BUF and
            _PK_LON_MIN - _TILT_LON_BUF <= lon <= _PK_LON_MAX + _TILT_LON_BUF):
        return "tilt_range"
    return "outside"


@app.get("/api/positions/hires-eo")
async def get_hires_eo_positions():
    """Return live positions for all curated Imagery & SAR surveillance satellites."""
    import asyncio
    async def _pos(sat: dict):
        result = await _fetch_hires_eo_tle(sat["norad"])
        if result is None:
            return None
        l1, l2 = result
        # Defensive name-match guard: if the curated catalog says NORAD X is
        # "CSO-2" but the TLE for X is actually "STARLINK-1536", silently
        # drop it instead of showing a Starlink mislabelled as CSO-2.
        tle_meta = _hires_eo_tle_cache.get(sat["norad"], {})
        tle_name = tle_meta.get("tle_name") or ""
        if tle_name and not _names_match(sat["name"], tle_name):
            return None
        p = propagate_now(sat["name"], l1, l2)
        if p is None:
            return None
        zone = _pk_zone(p["lat"], p["lon"])
        return {
            **p,
            "norad":             sat["norad"],
            "country":           sat["country"],
            "operator":          sat["operator"],
            "resolution_m":      sat["resolution_m"],
            "sensor":            sat.get("sensor", "Unknown"),
            "sensor_category":   sat.get("sensor_category", "Optical"),
            "altitude_km":       sat.get("altitude_km"),
            "max_tilt_deg":      sat.get("max_tilt_deg"),
            "tilt_standoff_km":  sat.get("tilt_standoff_km"),
            "over_pakistan":     zone == "overhead",
            "tilt_range":        zone == "tilt_range",
            "zone":              zone,
            # FEAT-004: which Pakistan strategic sites are within this sat's
            # standoff radius RIGHT NOW (instant snapshot — different from
            # the forecast's per-arc targeting). Empty when nothing in reach.
            "targeted_sites":    _instant_targets(
                p["lat"], p["lon"], sat.get("tilt_standoff_km")),
        }

    results = await asyncio.gather(*[_pos(s) for s in HIRES_EO_SATS])
    positions = [r for r in results if r is not None]
    return {
        "category":   "hires-eo",
        "count":      len(positions),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "satellites": len(HIRES_EO_SATS),
        "positions":  positions,
    }


@app.get("/api/hires-eo/catalog")
def get_hires_eo_catalog():
    """Return the curated ≤1m satellite catalog with metadata."""
    return {"satellites": HIRES_EO_SATS, "count": len(HIRES_EO_SATS)}


# ── Live "focus" mailbox ────────────────────────────────────────────────────
# Lets the ATLAS desktop app tell an ALREADY-OPEN map tab to jump to a
# satellite without spawning a new browser window. The desktop app POSTs a
# focus request into this mailbox; the open SPA polls GET /api/focus (~1.5 s)
# and reacts in place. That poll doubles as a heartbeat, so the desktop app
# can check GET /api/focus/clients and only launch a new window when no tab
# is currently open. State is intentionally process-local + ephemeral.
_focus_state: dict = {"seq": 0, "norad": None, "t": None, "note": None, "set_at": 0.0}
_focus_last_poll: float = 0.0


@app.post("/api/focus")
def set_focus(norad: str = Query(...), t: str | None = Query(None),
              note: str | None = Query(None)):
    """Desktop app → 'jump the open map to this satellite'. Increments seq so
    the polling SPA can tell a fresh request from a repeat. `note` is an
    optional trustworthiness warning the map renders as an animated banner."""
    _focus_state["seq"] += 1
    _focus_state["norad"] = str(norad)
    _focus_state["t"] = t
    _focus_state["note"] = note
    _focus_state["set_at"] = time.time()
    return {"ok": True, **_focus_state}


@app.get("/api/focus")
def get_focus():
    """SPA polls this. Recording the poll time lets /api/focus/clients report
    whether a live tab exists."""
    global _focus_last_poll
    _focus_last_poll = time.time()
    return _focus_state


@app.get("/api/focus/clients")
def get_focus_clients():
    """Heartbeat probe for the desktop app: is a map tab currently open and
    polling? True when a poll arrived within the last 6 s (poll cadence ~1.5 s)."""
    age = (time.time() - _focus_last_poll) if _focus_last_poll else None
    return {"tab_open": age is not None and age < 6.0, "last_poll_age_s": age}


@app.get("/api/strategic-sites")
def get_strategic_sites():
    """Return the Pakistan strategic-site catalog (FEAT-004) — public-domain
    coordinates used by the targeting analysis. Frontend can render these
    as pins on the Leaflet map; document generators consume the same list."""
    return {
        "sites":  STRATEGIC_SITES,
        "count":  len(STRATEGIC_SITES),
        "loaded": _STRATEGIC_SITES_OK,
        "source": "public open-source (Wikipedia / OSINT) — no classified data",
    }


@app.get("/api/satellite/{norad}")
async def get_satellite_metadata(norad: str):
    """Return full metadata for a satellite by NORAD ID: country, operator, purpose, source/destination."""
    catalog = await get_satnogs_catalog()

    # Try to find the name from any cached TLE
    name = norad
    for cached in tle_cache.values():
        lines = [l.strip() for l in cached["text"].splitlines() if l.strip()]
        for i in range(0, len(lines)-2, 3):
            if lines[i+1][2:7].strip() == norad:
                name = lines[i]
                break

    return build_metadata(norad, name, catalog)


@app.get("/api/metadata")
async def get_bulk_metadata(category: Category = Query(...)):
    """Return metadata for all satellites in a category (bulk, one call)."""
    catalog = await get_satnogs_catalog()
    text = await get_tle_text(category)
    records = parse_records(text, CATEGORY_META[category]["max"])
    result = {}
    for name, l1, _ in records:
        norad = l1[2:7].strip()
        result[name] = build_metadata(norad, name, catalog)
    return result


# ── HiRes EO 15-day forecast ──────────────────────────────────────────────────
# The forecast JSON is produced by Satellite_Tracker/forecast_15day.py and
# saved to that module's directory. We read it directly off disk so this
# backend stays decoupled from the tracker module.
import json
import os
from pathlib import Path


def _find_satellite_tracker_dir() -> Path:
    """Locate the Satellite_Tracker directory. The naive approach of
    ``Path(__file__).resolve().parents[3]`` blew up with ``IndexError: 3``
    on a user's PC when the bundle was installed in a shallow path
    (PyInstaller can synthesize __file__ values that don't have 4 levels
    of parents). This robust version checks every plausible location."""
    candidates: list[Path] = []

    # 1. PyInstaller bundle: _MEIPASS/Satellite_Tracker
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "Satellite_Tracker")

    # 2. Frozen .exe: <exe_dir>/_internal/Satellite_Tracker
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "_internal" / "Satellite_Tracker")
        candidates.append(exe_dir / "Satellite_Tracker")

    # 3. Walk UP from this file's dir checking each level
    try:
        here = Path(__file__).resolve()
        for ancestor in [here.parent, *here.parents]:
            cand = ancestor / "Satellite_Tracker"
            if cand.is_dir():
                return cand
            # Hard cap on how far we walk so we don't recurse to C:\
            if str(ancestor) in ("/", "\\") or ancestor == ancestor.parent:
                break
    except (NameError, OSError):
        pass

    # 4. CWD fallback
    candidates.append(Path.cwd() / "Satellite_Tracker")

    for c in candidates:
        try:
            if c.is_dir():
                return c
        except OSError:
            continue

    # Last resort — return _MEIPASS path even if it doesn't exist, so
    # downstream .is_file() checks return False (clean 404) rather than
    # crashing on import.
    if meipass:
        return Path(meipass) / "Satellite_Tracker"
    return Path("Satellite_Tracker")


_SAT_DIR = _find_satellite_tracker_dir()
_FORECAST_PATH = _SAT_DIR / "forecast_15day.json"


def _load_forecast() -> dict | None:
    if not _FORECAST_PATH.is_file():
        return None
    try:
        with _FORECAST_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


@app.get("/api/forecast/health")
def forecast_health():
    """
    Lightweight readiness probe for the forecast pipeline.
    Returns whether a forecast exists and whether it is stale (> 36 h old).
    """
    fc = _load_forecast()
    if fc is None:
        return {"ok": False, "reason": "no forecast generated yet"}
    generated_at = fc.get("generated_at")
    stale = False
    if generated_at:
        try:
            gen_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - gen_dt).total_seconds() / 3600
            stale = age_hours > 36
        except ValueError:
            pass
    return {
        "ok": True,
        "generated_at": generated_at,
        "start_date": fc.get("start_date"),
        "end_date": fc.get("end_date"),
        "satellite_count": fc.get("satellite_count"),
        "indian_satellite_count": fc.get("indian_satellite_count"),
        "stale": stale,
    }


@app.get("/api/forecast")
def get_forecast():
    """
    Return the full 15-day HiRes EO surveillance forecast.

    Shape:
      generated_at, start_date, end_date, satellite_count,
      indian_satellite_count, propagator, days[].crossings,
      days[].observation_windows, days[].blind_windows, days[].totals
    """
    fc = _load_forecast()
    if fc is None:
        raise HTTPException(
            status_code=404,
            detail="No forecast available. Run Satellite_Tracker/run_daily.py.",
        )
    return fc


@app.get("/api/forecast/day/{date}")
def get_forecast_day(date: str):
    """Return a single day's forecast slice (date format YYYY-MM-DD)."""
    fc = _load_forecast()
    if fc is None:
        raise HTTPException(404, detail="No forecast available.")
    for day in fc.get("days", []):
        if day.get("date") == date:
            return day
    raise HTTPException(
        404, detail=f"Date {date} not in forecast window "
                    f"{fc.get('start_date')}..{fc.get('end_date')}",
    )


@app.get("/api/forecast/blind-windows")
def get_blind_windows():
    """Aggregate every blind window across the forecast window, sorted longest-first."""
    fc = _load_forecast()
    if fc is None:
        raise HTTPException(404, detail="No forecast available.")
    out = []
    for day in fc.get("days", []):
        for b in day.get("blind_windows", []):
            out.append({"date": day["date"], **b})
    out.sort(key=lambda b: -b["duration_min"])
    return {
        "generated_at": fc.get("generated_at"),
        "count": len(out),
        "blind_windows": out,
    }


_SUMMARY_CACHE = {"mtime": None, "data": None}

@app.get("/api/forecast/summary")
def forecast_summary():
    """Compact, pre-aggregated forecast for lightweight clients (the intel-theme
    web dashboard AND a future Android app). Server-side aggregation keeps the
    payload tiny vs. the multi-MB raw /api/forecast. Per day it returns pass
    counts (india/other/optical/sar/military), blind minutes + longest gap, and
    per-sensor OBSERVED windows (PKT minutes) for the OPT/SAR blind calendar;
    plus per-country daily counts, an 'upcoming' pass list, and fleet totals."""
    # Cache the aggregated summary keyed by the forecast file's mtime: reading +
    # re-aggregating the large forecast_15day.json on EVERY request was the 3-5 s
    # "refresh" cost. Now it recomputes only when the forecast actually changes.
    try:
        _mt = _FORECAST_PATH.stat().st_mtime if _FORECAST_PATH.is_file() else None
    except OSError:
        _mt = None
    if _mt is not None and _SUMMARY_CACHE["mtime"] == _mt and _SUMMARY_CACHE["data"] is not None:
        return _SUMMARY_CACHE["data"]

    fc = _load_forecast()
    if fc is None:
        raise HTTPException(404, detail="No forecast available. Run Satellite_Tracker/run_daily.py.")

    def _up(s):  # normalise sensor string
        return (s or "").upper()
    def is_sar(s): return "SAR" in _up(s)
    def is_mil(s): return "MILITARY" in _up(s)

    def pkt_min(iso):
        # 'YYYY-MM-DDTHH:MM:SSZ' UTC -> minutes from PKT (UTC+5) midnight, 0..1439
        try:
            hh = int(iso[11:13]); mm = int(iso[14:16])
            return (hh * 60 + mm + 300) % 1440
        except Exception:
            return 0

    def merge(ivs):
        seg = []
        for a, b in ivs:
            if b < a:                       # wraps PKT midnight
                seg.append((a, 1440)); seg.append((0, b))
            elif b > a:
                seg.append((a, b))
        seg.sort()
        outw = []
        for a, b in seg:
            if outw and a <= outw[-1][1]:
                outw[-1][1] = max(outw[-1][1], b)
            else:
                outw.append([a, b])
        return outw

    def cgroup(country, is_indian):
        c = (country or "").lower()
        if is_indian or c == "india": return "India"
        if "china" in c: return "China"
        if c in ("usa", "united states", "us", "u.s.a."): return "USA"
        if "israel" in c: return "Israel"
        return "Other"

    COUNTRIES = ["China", "USA", "India", "Israel", "Other"]
    cty = {k: {"sats": set(), "optset": set(), "sarset": set(), "milset": set(), "daily": []} for k in COUNTRIES}
    days_out = []
    _now_dt = datetime.now(timezone.utc)
    now_utc = _now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    horizon_utc = (_now_dt + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")  # next-24h window
    upcoming = []

    for day in fc.get("days", []):
        t = day.get("totals", {})
        cr = day.get("crossings", [])
        sar = sum(1 for c in cr if is_sar(c.get("sensor")))
        mil = sum(1 for c in cr if is_mil(c.get("sensor")))
        opt = len(cr) - sar - mil
        opt_iv, sar_iv = [], []
        opt_cyan, opt_red, sar_pur, sar_red = [], [], [], []   # per-pass tick minutes
        sched = []   # per-pass schedule row for the client-side coverage timetable
        per = {k: 0 for k in COUNTRIES}
        for c in cr:
            en = pkt_min(c.get("entry_utc", ""))
            iv = (en, pkt_min(c.get("exit_utc", "")))
            _sar = is_sar(c.get("sensor"))
            _red = bool(c.get("is_indian")) or is_mil(c.get("sensor"))   # military/India → red tick
            if _sar:
                sar_iv.append(iv); (sar_red if _red else sar_pur).append(en)
            else:
                opt_iv.append(iv); (opt_red if _red else opt_cyan).append(en)
            g = cgroup(c.get("country"), c.get("is_indian"))
            per[g] += 1
            sched.append({
                "t": en, "e": pkt_min(c.get("exit_utc", "")),   # entry+exit PKT min → time ranges
                "p": "O" if c.get("pass_type") == "overhead" else "T",
                "n": (c.get("name") or "")[:28], "c": g,
                "s": "SAR" if _sar else "OPT",                   # radar vs optical (for the OPTICAL/SAR grid sections)
                "r": c.get("resolution_m"),
            })
            nid = c.get("norad_id")
            cty[g]["sats"].add(nid)                       # unique-sat classification (set dedupes)
            if is_sar(c.get("sensor")): cty[g]["sarset"].add(nid)
            elif is_mil(c.get("sensor")): cty[g]["milset"].add(nid)
            else: cty[g]["optset"].add(nid)
            # upcoming: every pass whose entry is within the next 24 h (deduped
            # to one row per satellite below, so this holds all raw passes first)
            if now_utc <= c.get("entry_utc", "") <= horizon_utc and len(upcoming) < 3000:
                upcoming.append({
                    "name": c.get("name"), "country": c.get("country"),
                    "sensor": "SAR" if is_sar(c.get("sensor")) else ("MIL" if is_mil(c.get("sensor")) else "OPT"),
                    "resolution_m": c.get("resolution_m"), "entry_utc": c.get("entry_utc"),
                    "max_alt_km": c.get("max_alt_km"), "pass_type": c.get("pass_type"),
                    "norad_id": c.get("norad_id"),
                })
        for k in COUNTRIES:
            cty[k]["daily"].append(per[k])
        days_out.append({
            "date": day.get("date"),
            "india_over": t.get("indian_overhead", 0), "india_tilt": t.get("indian_tilt_range", 0),
            "other_over": t.get("other_overhead", 0), "other_tilt": t.get("other_tilt_range", 0),
            "opt": opt, "sar": sar, "mil": mil,
            "blind_min": round(t.get("blind_minutes", 0)), "longest_gap": round(t.get("longest_blind_min", 0)),
            "sats": t.get("unique_sats", 0),
            "opt_windows": merge(opt_iv), "sar_windows": merge(sar_iv),
            # per-pass tick minutes for the dense barcode calendar
            "opt_cyan": opt_cyan, "opt_red": opt_red,
            "sar_pur": sar_pur, "sar_red": sar_red,
            # per-pass schedule rows (Time·Pass·Satellite·Country·Sensor·Res) for
            # the client-side coverage TIMETABLE (Generate Report / chart export).
            "sched": sorted(sched, key=lambda r: r["t"]),
        })

    upcoming.sort(key=lambda u: u.get("entry_utc") or "")
    # One row per satellite: keep each sat's soonest pass in the next 24 h, so the
    # list is "every satellite due overhead" rather than repeated passes.
    _seen_norad = set()
    _uniq_upcoming = []
    for _u in upcoming:
        _nid = _u.get("norad_id")
        if _nid in _seen_norad:
            continue
        _seen_norad.add(_nid)
        _uniq_upcoming.append(_u)
    upcoming = _uniq_upcoming
    cty = {k: {"sats": len(v["sats"]), "opt": len(v["optset"]), "sar": len(v["sarset"]),
               "mil": len(v["milset"]), "daily": v["daily"]} for k, v in cty.items()}

    _result = {
        "generated_at": fc.get("generated_at"),
        "start_date": fc.get("start_date"), "end_date": fc.get("end_date"),
        "satellite_count": fc.get("satellite_count"),
        "days": days_out, "countries": cty, "upcoming": upcoming[:400],
    }
    if _mt is not None:
        _SUMMARY_CACHE["mtime"] = _mt
        _SUMMARY_CACHE["data"] = _result
    return _result


# ── Mobile app auth gate ──────────────────────────────────────────────────────
# The Android app (Option A) fetches its 15-day data through THIS gate: a valid
# id+password is required or nothing is returned. For now it's a single login in
# mobile_auth.json; later this becomes a multi-user list. The exact same check is
# mirrored in the Cloudflare Worker that fronts the cloud data — this local copy
# lets us test the app's login/offline flow against the running backend.
import base64 as _base64

_TLE_LIST_CACHE = None
def _mobile_tles():
    """TLE lines for the tracked (<=3 m) fleet so the mobile LIVE TRACKER can
    propagate real-time positions on-device (SGP4). Merged from the CelesTrak +
    Space-Track caches; cached in memory."""
    global _TLE_LIST_CACHE
    if _TLE_LIST_CACHE is not None:
        return _TLE_LIST_CACHE
    tle_by_norad = {}
    for fn in ("tle_cache_celestrak.json", "spacetrack_tle_cache.json", "tle_cache.json"):
        try:
            d = json.loads((Path(_SAT_DIR) / fn).read_text(encoding="utf-8"))
            if isinstance(d, dict):
                for k, v in d.items():
                    if isinstance(v, dict) and v.get("line1") and v.get("line2"):
                        tle_by_norad.setdefault(str(k), (v["line1"], v["line2"]))
        except Exception:
            pass
    out = []
    for s in HIRES_EO_SATS:
        t = tle_by_norad.get(str(s.get("norad")))
        if not t:
            continue
        cat = (s.get("sensor_category") or "").upper()
        code = "SAR" if "SAR" in cat else ("MIL" if "MILITARY" in cat else "OPT")
        out.append({"n": str(s.get("norad")), "nm": s.get("name"), "s": code,
                    "c": s.get("country"), "r": s.get("resolution_m"), "l1": t[0], "l2": t[1]})
    _TLE_LIST_CACHE = out
    return out


def _mobile_creds():
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        try:
            p = base / "mobile_auth.json"
            if p.is_file():
                d = json.loads(p.read_text(encoding="utf-8"))
                return str(d.get("id", "")), str(d.get("password", ""))
        except Exception:
            pass
    return "atlas", "change-me-now"

def _check_basic(authorization: str):
    """Return the id if the Basic-auth header matches mobile_auth.json, else 401."""
    want_id, want_pw = _mobile_creds()
    if not authorization or not authorization.lower().startswith("basic "):
        raise HTTPException(401, detail="login required", headers={"WWW-Authenticate": "Basic"})
    try:
        raw = _base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
        got_id, got_pw = raw.split(":", 1)
    except Exception:
        raise HTTPException(401, detail="bad credentials", headers={"WWW-Authenticate": "Basic"})
    if got_id != want_id or got_pw != want_pw:
        raise HTTPException(401, detail="wrong id or password", headers={"WWW-Authenticate": "Basic"})
    return got_id


@app.get("/api/mobile/login", include_in_schema=False)
def mobile_login(authorization: str = Header(default="")):
    """Cheap credential check so the app's login screen can verify before saving."""
    return {"ok": True, "id": _check_basic(authorization)}


@app.get("/api/mobile/summary", include_in_schema=False)
def mobile_summary(authorization: str = Header(default="")):
    """Same 15-day summary as /api/forecast/summary, but LOCKED behind the login."""
    _check_basic(authorization)
    return forecast_summary()


# ── On-demand forecast recompute (mobile "Refresh Forecast") ──────────────────
# The phone triggers this; it runs the full 15-day forecast in a background
# thread (~3-8 min), rebuilds the summary, and pushes it to the Cloudflare gate
# so every client picks up the fresh data. The app polls /refresh_status and
# shows a live "Generating… Xs" counter meanwhile.
import threading as _threading
_REFRESH = {"running": False, "started_at": 0.0, "generated_at": None, "error": None}

def _recompute_forecast():
    try:
        _REFRESH.update(running=True, error=None, started_at=time.time())
        if _SAT_DIR not in sys.path:
            sys.path.insert(0, _SAT_DIR)
        import forecast_15day as _fc
        _fc.run(force_refresh_tles=True, render_doc=False)   # writes forecast_15day.json (~3-8 min)
        summary = forecast_summary()
        # .strip() guards against a trailing newline/space that the Render env
        # var may have picked up (e.g. copied from `type file`), which would make
        # the gate reject the admin key.
        gate = os.getenv("GATE_URL", "").strip().rstrip("/")
        key = os.getenv("ADMIN_KEY", "").strip()
        if gate and key:
            try:
                r = httpx.post(gate + "/update",
                               headers={"X-Admin-Key": key, "Content-Type": "application/json"},
                               content=json.dumps(summary), timeout=90.0)
                if r.status_code != 200:
                    _REFRESH["error"] = "gate returned %s: %s" % (r.status_code, r.text[:100])
            except Exception as e:
                _REFRESH["error"] = "gate push failed: " + str(e)[:120]
        else:
            _REFRESH["error"] = "GATE_URL/ADMIN_KEY not set on the server"
        _REFRESH["generated_at"] = summary.get("generated_at")
    except Exception as e:
        _REFRESH["error"] = str(e)[:200]
    finally:
        _REFRESH["running"] = False

@app.post("/api/mobile/refresh", include_in_schema=False)
def mobile_refresh(authorization: str = Header(default="")):
    """Kick off a fresh 15-day forecast in the background. Returns immediately."""
    _check_basic(authorization)
    if not _REFRESH["running"]:
        _threading.Thread(target=_recompute_forecast, daemon=True).start()
    return {"started": True, "running": _REFRESH["running"]}

@app.get("/api/mobile/refresh_status", include_in_schema=False)
def mobile_refresh_status(authorization: str = Header(default="")):
    _check_basic(authorization)
    el = int(time.time() - _REFRESH["started_at"]) if _REFRESH["running"] and _REFRESH["started_at"] else None
    return {"running": _REFRESH["running"], "elapsed_s": el,
            "generated_at": _REFRESH["generated_at"], "error": _REFRESH["error"]}


# ── Custom-AOI coverage (draw any polygon → its own 15-day blind-time) ─────────
# Real SGP4 over the polygon via the shared Satellite_Tracker/aoi_forecast engine.
# Runs in a background thread (~1-2 min for 15 days) and the app polls status.
_AOI = {"running": False, "started_at": 0.0, "result": None, "error": None}

def _aoi_fleet():
    """Build the ≤3 m fleet as {name,norad,sensor,resolution_m,country,line1,line2}
    from the forecast TLE cache (same source the Pakistan forecast uses)."""
    with open(_forecast_tle_cache_path(), "r", encoding="utf-8") as f:
        d = json.load(f)
    sats = []
    for k, v in d.items():
        if not isinstance(v, dict) or not v.get("line1") or not v.get("line2"):
            continue
        r = v.get("resolution_m")
        if r is not None and r > (MAX_RESOLUTION_M or 3.0):
            continue
        sats.append({"name": v.get("name"), "norad": str(k), "sensor": v.get("sensor"),
                     "resolution_m": r, "country": v.get("country"),
                     "line1": v["line1"], "line2": v["line2"]})
    return sats

def _compute_aoi_job(poly, days):
    try:
        _AOI.update(running=True, error=None, result=None, started_at=time.time())
        if _SAT_DIR not in sys.path:
            sys.path.insert(0, _SAT_DIR)
        import aoi_forecast as _aoi
        sats = _aoi_fleet()
        _AOI["result"] = _aoi.compute_aoi_forecast(poly, sats, days=days)
    except Exception as e:
        _AOI["error"] = str(e)[:200]
    finally:
        _AOI["running"] = False

@app.post("/api/aoi/compute", include_in_schema=False)
def aoi_compute(payload: dict = Body(...), authorization: str = Header(default="")):
    """Body: {polygon:[[lat,lon],...], days:15}. Kicks off a background AOI job."""
    _check_basic(authorization)
    poly = payload.get("polygon") or []
    days = int(payload.get("days", 15) or 15)
    if not isinstance(poly, list) or len(poly) < 3:
        raise HTTPException(400, detail="polygon needs at least 3 [lat,lon] points")
    days = max(1, min(15, days))
    if not _AOI["running"]:
        _threading.Thread(target=_compute_aoi_job, args=(poly, days), daemon=True).start()
    return {"started": True, "running": _AOI["running"]}

@app.get("/api/aoi/status", include_in_schema=False)
def aoi_status(authorization: str = Header(default="")):
    _check_basic(authorization)
    el = int(time.time() - _AOI["started_at"]) if _AOI["running"] and _AOI["started_at"] else None
    return {"running": _AOI["running"], "elapsed_s": el,
            "ready": _AOI["result"] is not None, "error": _AOI["error"]}

@app.get("/api/aoi/result", include_in_schema=False)
def aoi_result(authorization: str = Header(default="")):
    _check_basic(authorization)
    if _AOI["result"] is None:
        raise HTTPException(404, detail="no AOI result yet")
    return _AOI["result"]


# ── Intel-theme dashboard (self-contained HTML that fetches the summary above) ──
def _intel_html_path() -> Path:
    """dashboard_ui/ lives next to Satellite_Tracker at the project root, and is
    bundled to the same relative spot in the frozen app."""
    for base in (_SAT_DIR.parent, _SAT_DIR.parent / "_internal", Path.cwd()):
        p = base / "dashboard_ui" / "intel_analyst.html"
        if p.is_file():
            return p
    return _SAT_DIR.parent / "dashboard_ui" / "intel_analyst.html"


@app.get("/intel", include_in_schema=False)
def serve_intel(mobile: int = 0):
    p = _intel_html_path()
    if not p.is_file():
        raise HTTPException(404, detail="Intel dashboard not found (dashboard_ui/intel_analyst.html).")
    if mobile:
        # Same page, but as the login-gated mobile app would load it: same-origin
        # gate + auth required. This is exactly how the Capacitor build behaves,
        # except there ATLAS_CFG.base points at the cloud gate instead of ''.
        html = p.read_text(encoding="utf-8")
        # Prepend the config so it runs before the app script. (Do NOT inject at
        # </head> — the page's own HTML strings contain </head>, which would
        # corrupt them.)
        cfg = '<script>window.ATLAS_CFG={base:"",auth:true};</script>'
        html = cfg + html
        from fastapi.responses import HTMLResponse
        return HTMLResponse(html)
    return FileResponse(str(p))


# Same robust resolution as _FORECAST_PATH — _SAT_DIR was found earlier
# (defined above where _FORECAST_PATH is set) so we just reuse it.
_CHANGES_PATH = _SAT_DIR / "forecast_changes.json"


@app.get("/api/forecast/changes")
def get_forecast_changes():
    """
    Return the latest 'what changed vs the previous daily run' diff.
    Each day-bucket has new_passes, removed_passes, shifted_passes
    (entry-time shift in minutes), plus blind_delta_min.
    """
    if not _CHANGES_PATH.is_file():
        raise HTTPException(404,
            detail="No change record yet — run Satellite_Tracker/run_daily.py at least twice.")
    try:
        with _CHANGES_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        raise HTTPException(500, detail="forecast_changes.json unreadable.")


# ── Static-file serving for the bundled SPA ─────────────────────────────
# In dev mode the React app is served by Vite on :8080 and this code path
# is a no-op (the dist/ folder doesn't exist). In bundled-exe mode the
# launcher copies the React build into <backend>/static/ so the backend
# serves the whole orbit-tracker UI from a single port. The SPA fallback
# (catch-all GET serving index.html) lets client-side React Router work.
def _find_static_dir() -> str | None:
    """Locate the pre-built React 'dist' bundle. Tries several plausible
    paths because the resolved location depends on whether we're running
    in the source tree, in a PyInstaller bundle (which sets _MEIPASS),
    or invoked from somewhere odd via the .exe launcher.

    The PyInstaller bundle ships the static files at
        <_internal>/pakistan-orbit-tracker-main/pakistan-orbit-tracker-main/backend/static
    so we look there explicitly — previously we only looked at
        <_internal>/static
    which never matched because that's not where the spec puts them."""
    candidates: list[str] = []

    # 1. PyInstaller bundle: explicit relative path from _MEIPASS that
    #    matches our atlas.spec datas[] target. THIS is the path that
    #    actually exists in the bundle.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(
            meipass,
            "pakistan-orbit-tracker-main", "pakistan-orbit-tracker-main",
            "backend", "static",
        ))
        # Fallback for any earlier bundle layouts
        candidates.append(os.path.join(meipass, "static"))

    # 2. If bundled but _MEIPASS-less (rare), or if frozen with --onefile,
    #    the .exe's directory has the _internal/ tree.
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(
            exe_dir, "_internal",
            "pakistan-orbit-tracker-main", "pakistan-orbit-tracker-main",
            "backend", "static",
        ))

    # 3. Source-tree path: main.py's own dir / static
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here, "static"))
        # 4. Source-tree path: ../dist (where `npm run build` puts the bundle
        # in dev mode before it's copied into static/)
        candidates.append(os.path.abspath(os.path.join(here, "..", "dist")))
    except NameError:
        # __file__ undefined (very unusual in modern Python, but defensive)
        pass

    for c in candidates:
        if c and os.path.isdir(c) and os.path.isfile(os.path.join(c, "index.html")):
            return c
    return None


_STATIC_DIR = _find_static_dir()
if _STATIC_DIR:
    # Mount /assets and any other static subfolders directly. Then add a
    # catch-all route that serves index.html for unknown paths so React
    # Router's client-side routes work on direct URL loads / page refresh.
    _assets_dir = os.path.join(_STATIC_DIR, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def _spa_root():
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str):
        # API routes are matched by FastAPI before this fallback (route
        # registration order). For anything else, serve a real file if it
        # exists under static/, otherwise serve index.html so React Router
        # owns the URL.
        candidate = os.path.join(_STATIC_DIR, full_path)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    print(f"[BACKEND] SPA mounted from {_STATIC_DIR}")
else:
    print("[BACKEND] No static SPA bundle found — dev mode (Vite on :8080 expected)")
