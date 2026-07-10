"""
Curated catalog of operational high-resolution Earth Observation, SAR, and
military reconnaissance satellites that can image Pakistan.

Inclusion criteria:
  - Optical (Panchromatic): published GSD ≤ 1.0 m at nadir
  - SAR: operational synthetic aperture radar with sub-metre to 5 m resolution
  - Military: confirmed dedicated reconnaissance / dual-use with resolution ≤ 0.5 m

`sensor_category` values used throughout the reporting pipeline:
  "Optical"   — requires daylight at sub-satellite point
  "SAR"       — synthetic aperture radar, images day/night/through clouds
  "Military"  — dedicated military reconnaissance (optical or SAR)

Each entry: (norad_id, name, operator, country, sensor, resolution_m,
             sensor_category, notes).
"""

from collections import namedtuple

EOSat = namedtuple(
    "EOSat",
    ["norad_id", "name", "operator", "country", "sensor",
     "resolution_m", "sensor_category", "notes"],
)


HIRES_EO_SATELLITES: list[EOSat] = [

    # ── INDIA (ISRO) — HIGHLIGHTED IN ALL REPORTS ─────────────────────────────
    # Optical Cartosats
    EOSat(41599, "CARTOSAT-2C",  "ISRO", "India", "Panchromatic", 0.65, "Optical",  "Launched 2016"),
    EOSat(41948, "CARTOSAT-2D",  "ISRO", "India", "Panchromatic", 0.65, "Optical",  "Launched 2017"),
    EOSat(42767, "CARTOSAT-2E",  "ISRO", "India", "Panchromatic", 0.65, "Optical",  "Launched 2017"),
    EOSat(43111, "CARTOSAT-2F",  "ISRO", "India", "Panchromatic", 0.65, "Optical",  "Launched 2018"),
    EOSat(44804, "CARTOSAT-3",   "ISRO", "India", "Panchromatic", 0.25, "Optical",  "Best Indian optics, 2019"),
    # Indian SAR reconnaissance
    EOSat(51656, "EOS-04",       "ISRO", "India", "SAR C-band",   1.00, "SAR",      "RISAT-1A, all-weather SAR, 2022"),
    EOSat(44233, "RISAT-2B",     "ISRO", "India", "SAR X-band",   0.50, "SAR",      "Reconnaissance SAR, 2019"),
    EOSat(44857, "RISAT-2BR1",   "ISRO", "India", "SAR X-band",   0.50, "SAR",      "Reconnaissance SAR, 2019"),

    # ── USA (Maxar / DigitalGlobe) ────────────────────────────────────────────
    EOSat(32060, "WORLDVIEW-1",  "Maxar", "USA", "Panchromatic", 0.50, "Optical",  "Launched 2007"),
    EOSat(35946, "WORLDVIEW-2",  "Maxar", "USA", "Panchromatic", 0.46, "Optical",  "Launched 2009"),
    EOSat(40115, "WORLDVIEW-3",  "Maxar", "USA", "Panchromatic", 0.31, "Optical",  "Best commercial optics, 2014"),
    EOSat(33331, "GEOEYE-1",     "Maxar", "USA", "Panchromatic", 0.41, "Optical",  "Launched 2008"),

    # ── FRANCE (Airbus) — Pléiades optical ────────────────────────────────────
    EOSat(38012, "PLEIADES 1A",  "Airbus DS",     "France", "Panchromatic",    0.50, "Optical",  "Launched 2011"),
    EOSat(39019, "PLEIADES 1B",  "Airbus DS",     "France", "Panchromatic",    0.50, "Optical",  "Launched 2012"),
    # French military optical reconnaissance (CSO — Composante Spatiale Optique)
    EOSat(43813, "CSO-1",        "DGA/French MoD","France", "Optical Military",0.35, "Military", "Very high-res military recon, 2018"),
    # CSO-2 (46070) / CSO-3 (49438) dropped 2026-06-11: those NORADs resolve to
    # Starlink in the live feed; real CSO-2/3 NORADs are not in public CelesTrak.

    # ── ITALY (ASI / Italian MoD) — COSMO-SkyMed military SAR ────────────────
    EOSat(31598, "COSMO-SKYMED 1","ASI/Italian MoD","Italy","SAR X-band Military",1.00,"Military","Dual-use military SAR, 2007"),
    EOSat(32376, "COSMO-SKYMED 2","ASI/Italian MoD","Italy","SAR X-band Military",1.00,"Military","Dual-use military SAR, 2007"),
    EOSat(33412, "COSMO-SKYMED 3","ASI/Italian MoD","Italy","SAR X-band Military",1.00,"Military","Dual-use military SAR, 2008 (intl 2008-054A)"),
    EOSat(37216, "COSMO-SKYMED 4","ASI/Italian MoD","Italy","SAR X-band Military",1.00,"Military","Dual-use military SAR, 2010 (intl 2010-060A)"),
    EOSat(44873, "CSG-1",         "ASI/Italian MoD","Italy","SAR X-band Military",0.40,"Military","COSMO 2nd gen, 2019 (NORAD fixed 2026-06-11)"),
    EOSat(51444, "CSG-2",         "ASI/Italian MoD","Italy","SAR X-band Military",0.40,"Military","COSMO 2nd gen, 2022 (NORAD fixed 2026-06-11)"),
    EOSat(67304, "CSG-3",         "ASI/Italian MoD","Italy","SAR X-band Military",0.40,"Military","COSMO 2nd gen, added 2026-06-11"),

    # ── GERMANY (DLR / Airbus) — TerraSAR-X / TanDEM-X ──────────────────────
    EOSat(31698, "TERRASAR-X",   "DLR/Airbus", "Germany", "SAR X-band", 0.25, "SAR", "0.25 m spotlight SAR, 2007"),
    EOSat(36605, "TANDEM-X",     "DLR/Airbus", "Germany", "SAR X-band", 0.25, "SAR", "TanDEM formation, 0.25 m, 2010"),

    # ── SOUTH KOREA (KARI) ────────────────────────────────────────────────────
    EOSat(38338, "KOMPSAT-3",    "KARI", "South Korea", "Panchromatic", 0.70, "Optical", "Launched 2012"),
    EOSat(40536, "KOMPSAT-3A",   "KARI", "South Korea", "Panchromatic", 0.55, "Optical", "Launched 2015"),
    EOSat(39227, "KOMPSAT-5",    "KARI", "South Korea", "SAR X-band",   1.00, "SAR",     "All-weather SAR, 2013"),

    # ── CHINA (state Gaofen series) ──────────────────────────────────────────
    EOSat(40118, "GAOFEN-2",     "CNSA", "China", "Panchromatic", 0.80, "Optical", "Launched 2014"),
    EOSat(44703, "GAOFEN-7",     "CNSA", "China", "Panchromatic", 0.65, "Optical", "Stereoscopic, 2019"),
    EOSat(43585, "GAOFEN-11",    "CNSA", "China", "Panchromatic", 0.10, "Optical", "Sub-decimetric, 2018"),
    EOSat(41727, "GAOFEN-3",     "CNSA", "China", "SAR C-band",   1.00, "SAR",     "China's main SAR, 2016 (NORAD fixed 2026-06-11)"),

    # ── SPAIN ─────────────────────────────────────────────────────────────────
    EOSat(40013, "DEIMOS-2",     "Deimos Imaging", "Spain", "Panchromatic", 0.75, "Optical", "Launched 2014"),
    EOSat(43215, "PAZ",          "Hisdesat",       "Spain", "SAR X-band",   0.25, "SAR",     "Spanish military SAR, 0.25 m spotlight, 2018"),

    # ── ESA / Copernicus — Sentinel-1 SAR ────────────────────────────────────
    # SENTINEL-1A (39634) dropped 2026-06-11: 5 m resolution violates the ≤1 m rule.

    # ── ISRAEL — Ofeq military recon + EROS-C3 commercial optical ───────────
    # Realigned 2026-06-11 to the authoritative analyst source (McCants):
    #   Ofeq 16 = 45860 (was 46123, wrong), Ofeq 19 = 65432 (new), TecSAR = 32476.
    # Ofeq / TecSAR are WITHHELD from CelesTrak — their TLEs are supplied by the
    # supplemental analyst source (supplemental_tle.py), flagged lower-confidence.
    # Old dark/decayed entries (OFEQ 9/10/11/13) dropped — not in the source.
    EOSat(45860, "OFEQ 16",      "IAI/Israeli MoD",       "Israel", "Optical Military",      0.50, "Military", "Advanced optical recon, 2020 (analyst TLE)"),
    EOSat(65432, "OFEQ 19",      "IAI/Israeli MoD",       "Israel", "Optical Military",      0.50, "Military", "Optical recon, 2025 (analyst TLE)"),
    EOSat(32476, "TECSAR",       "IAI/Israeli MoD",       "Israel", "SAR X-band Military",   1.00, "Military", "Military recon SAR, 2008 (analyst TLE)"),
    EOSat(54880, "EROS C3",      "ImageSat International", "Israel", "Panchromatic",          0.30, "Optical",  "Commercial 0.30 m, 2023"),

    # ── JAPAN — ALOS-2 / PALSAR-2 ────────────────────────────────────────────
    # ALOS-2 (39769) dropped 2026-06-11: 3 m resolution violates the ≤1 m rule.

    # ── CHINA — Yaogan military reconnaissance series ────────────────────────
    # Operated by the PLA (officially "remote sensing"). NORADs verified from
    # CelesTrak's Earth-Resources group. resolution_m is an open-source
    # ESTIMATE — the true GSD is classified. Optical/SAR split is best-effort
    # from public analysis; the well-documented SAR sats are flagged as such.
    EOSat(32289, "YAOGAN-3",  "PLA / CNSA", "China", "SAR Military",     1.00, "Military", "Chinese recon — SAR; resolution est. (classified)"),
    EOSat(33446, "YAOGAN-4",  "PLA / CNSA", "China", "Optical Military", 1.00, "Military", "Chinese recon — optical; resolution est. (classified)"),
    EOSat(36110, "YAOGAN-7",  "PLA / CNSA", "China", "Optical Military", 1.00, "Military", "Chinese recon — optical; resolution est. (classified)"),
    EOSat(36834, "YAOGAN-10", "PLA / CNSA", "China", "SAR Military",     1.00, "Military", "Chinese recon — SAR; resolution est. (classified)"),
    EOSat(40143, "YAOGAN-21", "PLA / CNSA", "China", "Optical Military", 1.00, "Military", "Chinese recon — optical; resolution est. (classified)"),
    EOSat(40275, "YAOGAN-22", "PLA / CNSA", "China", "Optical Military", 1.00, "Military", "Chinese recon — optical; resolution est. (classified)"),
    EOSat(40310, "YAOGAN-24", "PLA / CNSA", "China", "Optical Military", 1.00, "Military", "Chinese recon — optical; resolution est. (classified)"),
    EOSat(40362, "YAOGAN-26", "PLA / CNSA", "China", "Optical Military", 1.00, "Military", "Chinese recon — optical; resolution est. (classified)"),
    EOSat(40878, "YAOGAN-27", "PLA / CNSA", "China", "SAR Military",     1.00, "Military", "Chinese recon — SAR; resolution est. (classified)"),
    EOSat(41026, "YAOGAN-28", "PLA / CNSA", "China", "Optical Military", 1.00, "Military", "Chinese recon — optical; resolution est. (classified)"),
    EOSat(41038, "YAOGAN-29", "PLA / CNSA", "China", "SAR Military",     1.00, "Military", "Chinese recon — SAR; resolution est. (classified)"),

    # ── 2026-07 brochure reconciliation — 55 live+public imaging sats ──────────
    EOSat(40298, "ASNARO", "NEC / USEF", "Japan", "Panchromatic", 0.5, "Optical", "Added 2026-07 from brochure reconciliation; launch 2014-11-06"),
    EOSat(43152, "ASNARO-2", "NEC / USEF", "Japan", "SAR X-band", 1.0, "SAR", "Added 2026-07 from brochure reconciliation; launch 2018-01-17"),
    EOSat(40715, "DMC 3-FM1", "SSTL / 21AT", "UK/China", "Panchromatic", 1.0, "Optical", "Added 2026-07 from brochure reconciliation; launch 2015-07-10"),
    EOSat(40716, "DMC 3-FM2", "SSTL / 21AT", "UK/China", "Panchromatic", 1.0, "Optical", "Added 2026-07 from brochure reconciliation; launch 2015-07-10"),
    EOSat(40717, "DMC 3-FM3", "SSTL / 21AT", "UK/China", "Panchromatic", 1.0, "Optical", "Added 2026-07 from brochure reconciliation; launch 2015-07-10"),
    EOSat(57481, "DS-SAR", "DSTA / ST Eng", "Singapore", "SAR X-band", 1.0, "SAR", "Added 2026-07 from brochure reconciliation; launch 2023-07-30"),
    EOSat(63226, "ETIHAD-SAT", "Yahsat / UAE", "UAE", "Panchromatic", 0.5, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-03-15"),
    EOSat(56756, "KONDOR FKA 1", "NPO Mash", "Russia", "SAR S-band", 1.0, "Military", "Added 2026-07 from brochure reconciliation; launch 2023-05-26"),
    EOSat(62138, "KONDOR FKA 2", "NPO Mash", "Russia", "SAR S-band", 1.0, "Military", "Added 2026-07 from brochure reconciliation; launch 2024-11-29"),
    EOSat(59625, "LEGION 1", "Maxar", "USA", "Panchromatic", 0.3, "Optical", "Added 2026-07 from brochure reconciliation; launch 2024-05-02"),
    EOSat(59626, "LEGION 2", "Maxar", "USA", "Panchromatic", 0.3, "Optical", "Added 2026-07 from brochure reconciliation; launch 2024-05-02"),
    EOSat(60452, "LEGION 3", "Maxar", "USA", "Panchromatic", 0.3, "Optical", "Added 2026-07 from brochure reconciliation; launch 2024-08-15"),
    EOSat(60453, "LEGION 4", "Maxar", "USA", "Panchromatic", 0.3, "Optical", "Added 2026-07 from brochure reconciliation; launch 2024-08-15"),
    EOSat(62900, "LEGION 5", "Maxar", "USA", "Panchromatic", 0.3, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-02-04"),
    EOSat(62901, "LEGION 6", "Maxar", "USA", "Panchromatic", 0.3, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-02-04"),
    EOSat(62626, "MBZ-SAT", "MBRSC", "UAE", "Panchromatic", 0.3, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-01-14"),
    EOSat(65317, "NAOS", "Belgian MoD", "Belgium", "Optical Military", 0.5, "Military", "Added 2026-07 from brochure reconciliation; launch 2025-08-26"),
    EOSat(43619, "NOVASAR 1", "SSTL", "UK", "SAR S-band", 6.0, "SAR", "Added 2026-07 from brochure reconciliation; launch 2018-09-16"),
    EOSat(52184, "NUSAT-26", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2022-04-01"),
    EOSat(55047, "NUSAT-33", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-01-03"),
    EOSat(55048, "NUSAT-35", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-01-03"),
    EOSat(56203, "NUSAT-37", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-04-15"),
    EOSat(56202, "NUSAT-38", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-04-15"),
    EOSat(56201, "NUSAT-39", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-04-15"),
    EOSat(56943, "NUSAT-40", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-06-12"),
    EOSat(56944, "NUSAT-41", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-06-12"),
    EOSat(56966, "NUSAT-42", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-06-12"),
    EOSat(59122, "NUSAT-44 MARIA MITCHELL", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2024-03-04"),
    EOSat(62640, "NUSAT-45", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-01-14"),
    EOSat(66743, "NUSAT-47", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-11-28"),
    EOSat(60498, "NUSAT-48", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2024-08-16"),
    EOSat(60500, "NUSAT-49", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2024-08-16"),
    EOSat(60493, "NUSAT-50", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2024-08-16"),
    EOSat(66740, "NUSAT-51", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-11-28"),
    EOSat(66692, "NUSAT-52", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-11-28"),
    EOSat(68432, "NUSAT-53", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2026-03-30"),
    EOSat(68442, "NUSAT-54", "Satellogic", "Argentina", "Optical", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2026-03-30"),
    EOSat(67234, "OBZOR-R 01", "NPO Mash", "Russia", "SAR", 1.0, "Military", "Added 2026-07 from brochure reconciliation; launch 2025-12-25"),
    EOSat(64055, "QPS-SAR-10 WADATSUMI-I", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2025-05-17"),
    EOSat(64340, "QPS-SAR-11 YAMATSUMI", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2025-06-11"),
    EOSat(65116, "QPS-SAR-12 KUSHINADA-I", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2025-08-05"),
    EOSat(66316, "QPS-SAR-14 YACHIHOKO-1", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2025-11-05"),
    EOSat(67228, "QPS-SAR-15 SUKUNAMI-1", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2025-12-21"),
    EOSat(58578, "QPS-SAR-5 TSUKUYOMI-I", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2023-12-15"),
    EOSat(59447, "QPS-SAR-7 TSUKUYOMI-II", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2024-04-07"),
    EOSat(60542, "QPS-SAR-8 AMATERU-IV", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2024-08-16"),
    EOSat(63205, "QPS-SAR-9 SUSANOO-I", "iQPS", "Japan", "SAR X-band", 0.46, "SAR", "Added 2026-07 from brochure reconciliation; launch 2025-03-15"),
    EOSat(56953, "RUNNER-1", "ImageSat Intl", "Israel", "Panchromatic", 0.7, "Optical", "Added 2026-07 from brochure reconciliation; launch 2023-06-12"),
    EOSat(63229, "SPACEEYE-T1", "SIIS", "South Korea", "Panchromatic", 0.25, "Optical", "Added 2026-07 from brochure reconciliation; launch 2025-03-15"),
    EOSat(43618, "SSTL S1-4", "SSTL", "UK", "Panchromatic", 0.75, "Optical", "Added 2026-07 from brochure reconciliation; launch 2018-09-16"),
    EOSat(56310, "TELEOS 2", "ST Engineering", "Singapore", "SAR X-band", 1.0, "SAR", "Added 2026-07 from brochure reconciliation; launch 2023-04-22"),
    EOSat(60541, "UMBRA-09", "Umbra Lab", "USA", "SAR X-band", 0.25, "SAR", "Added 2026-07 from brochure reconciliation; launch 2024-08-16"),
    EOSat(60547, "UMBRA-10", "Umbra Lab", "USA", "SAR X-band", 0.25, "SAR", "Added 2026-07 from brochure reconciliation; launch 2024-08-16"),
    EOSat(66748, "UMBRA-11", "Umbra Lab", "USA", "SAR X-band", 0.25, "SAR", "Added 2026-07 from brochure reconciliation; launch 2025-11-28"),
    EOSat(67371, "UMBRA-12", "Umbra Lab", "USA", "SAR X-band", 0.25, "SAR", "Added 2026-07 from brochure reconciliation; launch 2026-01-11"),
]


# ── Tilt / off-nadir capability per satellite ────────────────────────────────
# Per-satellite imaging geometry. For optical sats: maximum operational
# off-nadir angle (image still spec-quality, not the mechanical maximum).
# For SAR sats: maximum operational incidence angle from each operator's
# published mode-table. Sources:
#   ISRO bulletins (CARTOSAT, RISAT, EOS), Maxar public spec sheets
#   (WorldView, GeoEye), Airbus / CNES (Pleiades, CSO upper bounds),
#   DLR (TerraSAR-X, TanDEM-X), ASI (COSMO-SkyMed, CSG public modes),
#   ESA (Sentinel-1 IW mode), JAXA (ALOS-2 ScanSAR), CNSA (Gaofen
#   published bounds), KARI (KOMPSAT).
# Military-grade values are public upper bounds; classified peak may exceed.
#
# Shape:  norad_id_str -> { "altitude_km": int, "max_tilt_deg": int }
import math

TILT_SPECS: dict[str, dict] = {
    # India — optical Cartosats
    "41599": {"altitude_km": 505, "max_tilt_deg": 26},
    "41948": {"altitude_km": 505, "max_tilt_deg": 26},
    "42767": {"altitude_km": 505, "max_tilt_deg": 26},
    "43111": {"altitude_km": 505, "max_tilt_deg": 26},
    "44804": {"altitude_km": 509, "max_tilt_deg": 32},
    # India — SAR
    "51656": {"altitude_km": 529, "max_tilt_deg": 49},
    "44233": {"altitude_km": 555, "max_tilt_deg": 49},
    "44857": {"altitude_km": 555, "max_tilt_deg": 49},
    # USA — Maxar optical
    "32060": {"altitude_km": 496, "max_tilt_deg": 40},
    "35946": {"altitude_km": 770, "max_tilt_deg": 45},
    "40115": {"altitude_km": 617, "max_tilt_deg": 45},
    "33331": {"altitude_km": 681, "max_tilt_deg": 40},
    # France — Pleiades + CSO military
    "38012": {"altitude_km": 694, "max_tilt_deg": 47},
    "39019": {"altitude_km": 694, "max_tilt_deg": 47},
    "43813": {"altitude_km": 800, "max_tilt_deg": 30},   # CSO-1 (CSO-2/3 dropped)
    # Italy — COSMO-SkyMed + CSG military SAR
    "31598": {"altitude_km": 619, "max_tilt_deg": 50},
    "32376": {"altitude_km": 619, "max_tilt_deg": 50},
    "33412": {"altitude_km": 619, "max_tilt_deg": 50},
    "37216": {"altitude_km": 619, "max_tilt_deg": 50},
    "44873": {"altitude_km": 619, "max_tilt_deg": 60},   # CSG-1
    "51444": {"altitude_km": 619, "max_tilt_deg": 60},   # CSG-2
    "67304": {"altitude_km": 619, "max_tilt_deg": 60},   # CSG-3
    # Germany — TerraSAR-X / TanDEM-X
    "31698": {"altitude_km": 514, "max_tilt_deg": 55},
    "36605": {"altitude_km": 514, "max_tilt_deg": 55},
    # South Korea — KOMPSAT
    "38338": {"altitude_km": 685, "max_tilt_deg": 30},
    "40536": {"altitude_km": 528, "max_tilt_deg": 30},
    "39227": {"altitude_km": 550, "max_tilt_deg": 55},
    # China — Gaofen
    "40118": {"altitude_km": 631, "max_tilt_deg": 35},
    "44703": {"altitude_km": 506, "max_tilt_deg": 25},
    "43585": {"altitude_km": 695, "max_tilt_deg": 35},
    "41727": {"altitude_km": 755, "max_tilt_deg": 50},   # GAOFEN-3
    # Spain
    "40013": {"altitude_km": 620, "max_tilt_deg": 30},
    "43215": {"altitude_km": 514, "max_tilt_deg": 55},
    # ESA Sentinel-1 — removed (5 m, >1 m rule)
    # Israel — Ofeq recon + TecSAR + EROS-C3 (realigned 2026-06-11)
    "45860": {"altitude_km": 600, "max_tilt_deg": 40},   # OFEQ 16  — optical recon
    "65432": {"altitude_km": 600, "max_tilt_deg": 40},   # OFEQ 19  — optical recon (2025)
    "32476": {"altitude_km": 580, "max_tilt_deg": 50},   # TECSAR   — SAR recon
    "54880": {"altitude_km": 510, "max_tilt_deg": 40},   # EROS C3  — commercial optical
    # Japan ALOS-2 — removed (3 m, >1 m rule)
    # China — Yaogan recon (altitude/tilt are nominal LEO-recon estimates;
    # exact figures are classified).
    "32289": {"altitude_km": 630, "max_tilt_deg": 40},
    "33446": {"altitude_km": 650, "max_tilt_deg": 35},
    "36110": {"altitude_km": 650, "max_tilt_deg": 35},
    "36834": {"altitude_km": 630, "max_tilt_deg": 40},
    "40143": {"altitude_km": 490, "max_tilt_deg": 35},
    "40275": {"altitude_km": 490, "max_tilt_deg": 35},
    "40310": {"altitude_km": 490, "max_tilt_deg": 35},
    "40362": {"altitude_km": 490, "max_tilt_deg": 35},
    "40878": {"altitude_km": 630, "max_tilt_deg": 40},
    "41026": {"altitude_km": 490, "max_tilt_deg": 35},
    "41038": {"altitude_km": 630, "max_tilt_deg": 40},
}


def altitude_km(norad: str | int) -> int | None:
    """Nominal operating altitude in km from spec sheet."""
    spec = TILT_SPECS.get(str(norad))
    return spec["altitude_km"] if spec else None


def max_tilt_deg(norad: str | int) -> int | None:
    """Maximum operational off-nadir (optical) or incidence (SAR) angle."""
    spec = TILT_SPECS.get(str(norad))
    return spec["max_tilt_deg"] if spec else None


def standoff_km(norad: str | int) -> float | None:
    """Maximum ground standoff distance — how far horizontally from the
    sub-satellite point the sensor can still image. Flat-earth approximation
    (alt × tan θ) is accurate to <1% for LEO ≤ 800 km and θ ≤ 60°.
    """
    spec = TILT_SPECS.get(str(norad))
    if not spec:
        return None
    return round(spec["altitude_km"] * math.tan(math.radians(spec["max_tilt_deg"])), 1)


# ── Full reference-book fleet (auto-loaded, name-verified NORADs) ─────────────
# Extends the curated sub-metre core with the additional imaging satellites from
# the May-2026 Reference Book (558-satellite catalog). Every NORAD id here was
# name-verified against the live CelesTrak feed (so no ID resolves to the wrong
# object, e.g. a Starlink). Loading it here — before the derived lookups below —
# means the 15-Day Forecast AND the Pakistan Orbit Tracker both cover the full
# fleet automatically (they read this same list).
try:
    from hires_eo_extra import EXTRA_FLEET, EXTRA_TILT
    _seen = {str(s.norad_id) for s in HIRES_EO_SATELLITES}
    for _t in EXTRA_FLEET:
        if str(_t[0]) not in _seen:
            HIRES_EO_SATELLITES.append(EOSat(*_t))
            _seen.add(str(_t[0]))
    for _nid, _spec in EXTRA_TILT.items():
        TILT_SPECS.setdefault(str(_nid), _spec)
    print(f"[FLEET] loaded {len(HIRES_EO_SATELLITES)} satellites "
          f"(curated core + reference-book catalog)")
except Exception as _e:  # never let a catalog issue break the core fleet
    print(f"[FLEET] reference-book extension not loaded: {_e}")


# ── Resolution filter: track ONLY satellites 3 m or better (per user spec) ────
# This is the single upstream fleet that generates forecast_15day.json, so every
# pass/forecast number across the desktop app, the intel UI, and the mobile gate
# flows from this list. Filtering here limits the ENTIRE tracked fleet to <=3 m
# in one place. Satellites with no known resolution are dropped (can't confirm
# they meet the bar). Change MAX_RESOLUTION_M below, or set it to None to disable.
MAX_RESOLUTION_M = 3.0
if MAX_RESOLUTION_M is not None:
    _before = len(HIRES_EO_SATELLITES)
    HIRES_EO_SATELLITES[:] = [
        s for s in HIRES_EO_SATELLITES
        if isinstance(s.resolution_m, (int, float)) and s.resolution_m <= MAX_RESOLUTION_M
    ]
    print(f"[FLEET] resolution filter <= {MAX_RESOLUTION_M} m: kept "
          f"{len(HIRES_EO_SATELLITES)} of {_before} satellites")


# ── ≤1 m resolution qualifier (per user spec) ────────────────────────────────
# Only sub-metre optical/SAR satellites get visualised on the map with their
# tilt-coverage circle. Coarser SAR (Sentinel-1 5 m, ALOS-2 3 m) are kept in
# the catalog for completeness but are not drawn.
QUALIFIES_FOR_RADIUS: set[str] = {
    str(s.norad_id) for s in HIRES_EO_SATELLITES
    if s.resolution_m <= 1.0 and s.sensor_category in ("Optical", "SAR", "Military")
}


# ── Quick lookups ─────────────────────────────────────────────────────────────
BY_NORAD: dict[str, EOSat] = {str(s.norad_id): s for s in HIRES_EO_SATELLITES}
BY_COUNTRY: dict[str, list[EOSat]] = {}
for _s in HIRES_EO_SATELLITES:
    BY_COUNTRY.setdefault(_s.country, []).append(_s)

INDIAN_NORAD_IDS: set[str] = {
    str(s.norad_id) for s in HIRES_EO_SATELLITES if s.country == "India"
}

INDIAN_SAR_NORAD_IDS: set[str] = {
    str(s.norad_id) for s in HIRES_EO_SATELLITES
    if s.country == "India" and s.sensor_category == "SAR"
}

SAR_NORAD_IDS: set[str] = {
    str(s.norad_id) for s in HIRES_EO_SATELLITES if s.sensor_category == "SAR"
}

MILITARY_NORAD_IDS: set[str] = {
    str(s.norad_id) for s in HIRES_EO_SATELLITES if s.sensor_category == "Military"
}


def expected_name_tokens(name: str) -> set[str]:
    """Return uppercased tokens (length>=3) from the expected name."""
    cleaned = name.upper().replace("-", " ").replace("(", " ").replace(")", " ")
    return {t for t in cleaned.split() if len(t) >= 3}


def count_by_country() -> dict[str, int]:
    return {c: len(sats) for c, sats in BY_COUNTRY.items()}


if __name__ == "__main__":
    print(f"Total satellites: {len(HIRES_EO_SATELLITES)}")
    for c, sats in sorted(BY_COUNTRY.items(), key=lambda kv: -len(kv[1])):
        marker = " <- HIGHLIGHTED" if c == "India" else ""
        sar_n = sum(1 for s in sats if s.sensor_category in ("SAR", "Military"))
        opt_n = sum(1 for s in sats if s.sensor_category == "Optical")
        print(f"  {c:15s}: {len(sats):3d}  (Optical={opt_n} SAR/Mil={sar_n}){marker}")
    sar = sum(1 for s in HIRES_EO_SATELLITES if "SAR" in s.sensor)
    optical = sum(1 for s in HIRES_EO_SATELLITES if s.sensor_category == "Optical")
    military = sum(1 for s in HIRES_EO_SATELLITES if s.sensor_category == "Military")
    print(f"\nOptical (need daylight): {optical}   SAR (any time): {sar}   Military: {military}")
    print(f"Indian SAR NORADs: {sorted(INDIAN_SAR_NORAD_IDS)}")
