#!/usr/bin/env python3
"""LiPD legacy pickle -> cfr.ProxyDatabase DataFrame pickle.

GraphEM (via cfr.ReconJob.run_graphem_cfg) consumes a proxy database loaded
with `ProxyDatabase().fetch(<path.pkl>)`, which reads a pickled pandas
DataFrame (one row per proxy record) through `ProxyDatabase.from_df`. This
adapter turns the lipdverse "legacy" pickle the platform mounts at
/proxies/lipd_legacy.pkl into exactly that DataFrame and pickles it.

Unlike the demo adapter (which bins to a year x proxy matrix), cfr wants the
raw (time, value) pairs per record — cfr does its own annual binning in
`annualize_proxydb`. So each output row carries a `year` array and a
`paleoData_values` array.

Columns emitted (matching ProxyDatabase.from_df defaults):
    paleoData_pages2kID  — unique proxy id (pid)
    geo_meanLat/Lon/Elev — coordinates
    year                 — time axis (year CE), array
    paleoData_values     — proxy values, array (aligned to year)
    ptype                — "archive.proxy" (e.g. coral.d18O)
    archiveType          — raw archive string (kept for reference)
    paleoData_variableName, paleoData_units

Extraction mirrors the template adapter: try lipd.extractTs, then fall back
to a raw walk of the legacy {'D': {datasetName: ds}} layout. The ptype
mapping is ported from LMR2/scripts/lipd_to_pdb.py.
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ── Proxy-type mapping (ported from LMR2/scripts/lipd_to_pdb.py) ──────────────
PTYPE_MAP = {
    ('tree',            'trw'):                      'tree.TRW',
    ('tree',            'tree ring width'):           'tree.TRW',
    ('tree',            'ringwidth'):                 'tree.TRW',
    ('tree',            'ring width'):                'tree.TRW',
    ('tree',            'mxd'):                       'tree.MXD',
    ('tree',            'maximum latewood density'):  'tree.MXD',
    ('wood',            'trw'):                       'tree.TRW',
    ('wood',            'ringwidth'):                 'tree.TRW',
    ('wood',            'ring width'):                'tree.TRW',
    ('wood',            'mxd'):                       'tree.MXD',
    ('coral',           'd18o'):                      'coral.d18O',
    ('coral',           'srca'):                      'coral.SrCa',
    ('coral',           'sr/ca'):                     'coral.SrCa',
    ('coral',           'calcification'):             'coral.calc',
    ('sclerosponge',    'd18o'):                      'sclerosponge.d18O',
    ('sclerosponge',    'srca'):                      'sclerosponge.SrCa',
    ('ice core',        'd18o'):                      'ice.d18O',
    ('ice core',        'dd'):                        'ice.dD',
    ('ice core',        'd2h'):                       'ice.dD',
    ('ice core',        'melt'):                      'ice.melt',
    ('ice core',        'accumulation'):              'ice.accumulation',
    ('glacierice',      'd18o'):                      'ice.d18O',
    ('glacierice',      'dd'):                        'ice.dD',
    ('lake sediment',   'varve_thickness'):           'lake.varve_thickness',
    ('lake sediment',   'varve thickness'):           'lake.varve_thickness',
    ('lake sediment',   'varve_property'):            'lake.varve_property',
    ('lake sediment',   'chironomid'):                'lake.chironomid',
    ('lake sediment',   'midge'):                     'lake.midge',
    ('lake sediment',   'reflectance'):               'lake.reflectance',
    ('lake sediment',   'bsi'):                       'lake.BSi',
    ('lake sediment',   'accumulation'):              'lake.accumulation',
    ('lakesediment',    'chironomid'):                'lake.chironomid',
    ('lakesediment',    'reflectance'):               'lake.reflectance',
    ('lakesediment',    'bsi'):                       'lake.BSi',
    ('marine sediment', 'alkenone'):                  'marine.alkenone',
    ('marine sediment', 'uk37'):                      'marine.alkenone',
    ('marine sediment', 'mgca'):                      'marine.MgCa',
    ('marine sediment', 'mg/ca'):                     'marine.MgCa',
    ('marine sediment', 'tex86'):                     'marine.other',
    ('marine sediment', 'temperature'):               'marine.other',
    ('marinesediment',  'alkenone'):                  'marine.alkenone',
    ('marinesediment',  'uk37'):                      'marine.alkenone',
    ('marinesediment',  'mgca'):                      'marine.MgCa',
    ('borehole',        'temperature'):               'borehole',
    ('speleothem',      'd18o'):                      'speleothem.d18O',
    ('documents',       'temperature'):               'documents',
    ('bivalve',         'd18o'):                      'bivalve.d18O',
    ('molluskshell',    'd18o'):                      'bivalve.d18O',
}

ARCHIVE_DEFAULTS = {
    'tree':                 'tree.TRW',
    'wood':                 'tree.TRW',
    'coral':                'coral.d18O',
    'ice core':             'ice.d18O',
    'glacierice':           'ice.d18O',
    'lake sediment':        'lake.other',
    'lakesediment':         'lake.other',
    'marine sediment':      'marine.other',
    'marinesediment':       'marine.other',
    'speleothem':           'speleothem.d18O',
    'borehole':             'borehole',
    'documents':            'documents',
    'sclerosponge':         'sclerosponge.d18O',
    'bivalve':              'bivalve.d18O',
    'molluskshell':         'bivalve.d18O',
    'hybrid':               'hybrid',
    'peat':                 'lake.other',
    'terrestrialsediment':  'lake.other',
}


def create_ptype(archive_type, standard_name) -> str:
    arch = str(archive_type or '').lower().strip()
    std  = str(standard_name  or '').lower().strip()
    arch_nsp = arch.replace(' ', '')
    key = (arch, std)
    if key in PTYPE_MAP:
        return PTYPE_MAP[key]
    for (a, s), ptype in PTYPE_MAP.items():
        if a.replace(' ', '') == arch_nsp and s == std:
            return ptype
    for (a, s), ptype in PTYPE_MAP.items():
        if (a == arch or a.replace(' ', '') == arch_nsp) and s and s in std:
            return ptype
    return ARCHIVE_DEFAULTS.get(arch, ARCHIVE_DEFAULTS.get(arch_nsp, f'{arch}.unknown'))


# ── Time-axis handling (mirrors the template adapter) ─────────────────────────
def _coerce_year(years_raw, ages_raw, year_units: str = "") -> np.ndarray:
    """Return year-AD as a float array.

    Prefer the record's 'year' axis if present; otherwise convert 'age'
    (years BP, 1950 reference).
    """
    if years_raw is not None and len(years_raw):
        arr = np.asarray(years_raw, dtype=float)
        if "bp" in (year_units or "").lower():
            arr = 1950.0 - arr
        return arr
    if ages_raw is not None and len(ages_raw):
        return 1950.0 - np.asarray(ages_raw, dtype=float)
    return np.array([], dtype=float)


def _safe_float(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# Variable names that are time axes / metadata, never proxy values.
_SKIP_VARS = {
    "year", "age", "depth", "depthtop", "depthbottom", "depthcomposite",
    "yearce", "yearad", "agebp", "ageka", "time", "latitude", "longitude",
    "elevation", "uncertainty",
}


def _is_skip_var(vname: str) -> bool:
    v = str(vname or "").strip().lower()
    return (v in _SKIP_VARS or v.startswith("depth")
            or v.startswith("age") or v.startswith("year")
            or v.startswith("uncertainty"))


def _extract_ts(pkl_path: Path) -> list[dict]:
    """Load the legacy pickle and flatten to a list of time-series dicts.

    lipdverse "legacy" pickles carry a pre-extracted 'TS' list (the output of
    lipd.extractTs: one flat dict per paleo column, with paleoData_* / geo_* /
    year keys) alongside the nested 'D'. Prefer 'TS' — it's already the shape
    build_proxydb wants and needs no lipd dependency. Otherwise try
    lipd.extractTs, then a defensive raw walk of the {'D': {name: ds}} layout.
    """
    with pkl_path.open("rb") as f:
        raw = pickle.load(f)

    if isinstance(raw, dict) and isinstance(raw.get("TS"), list) and raw["TS"]:
        print(f"[lipd_to_input] using embedded 'TS' list ({len(raw['TS'])} records)",
              file=sys.stderr)
        return raw["TS"]

    D = raw.get("D", raw) if isinstance(raw, dict) else raw

    try:
        import lipd  # type: ignore
        ts = lipd.extractTs(D)
        if ts:
            print(f"[lipd_to_input] lipd.extractTs returned {len(ts)} records",
                  file=sys.stderr)
            return ts
        print("[lipd_to_input] lipd.extractTs returned 0 records — falling back",
              file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — any failure → raw walk
        print(f"[lipd_to_input] lipd.extractTs failed ({e}); falling back to raw walk",
              file=sys.stderr)

    out: list[dict] = []

    def _as_entries(x):
        # paleoData / measurementTable may be a list or an (Ordered)dict keyed
        # by table name; normalise to a list of values.
        if isinstance(x, dict):
            return list(x.values())
        if isinstance(x, list):
            return x
        return []

    def _flatten_ds(name: str, ds: dict) -> None:
        if not isinstance(ds, dict):
            return
        geo_props = ((ds.get("geo") or {}).get("properties") or {})
        lat  = _safe_float(geo_props.get("latitude"))
        lon  = _safe_float(geo_props.get("longitude"))
        elev = _safe_float(geo_props.get("elevation"))
        archive = str(ds.get("archiveType", "unknown")).lower()
        for pd_entry in _as_entries(ds.get("paleoData")):
            if not isinstance(pd_entry, dict):
                continue
            for mt in _as_entries(pd_entry.get("measurementTable")):
                if not isinstance(mt, dict):
                    continue
                cols = mt.get("columns") or []
                if isinstance(cols, dict):
                    cols = list(cols.values())
                year_col = next((c for c in cols
                                 if str(c.get("variableName", "")).lower() == "year"), None)
                age_col  = next((c for c in cols
                                 if str(c.get("variableName", "")).lower() == "age"), None)
                year_vals  = year_col.get("values") if year_col else None
                age_vals   = age_col.get("values")  if age_col  else None
                year_units = (year_col or {}).get("units", "")
                for c in cols:
                    if c is year_col or c is age_col:
                        continue
                    vname = str(c.get("variableName", ""))
                    if not vname:
                        continue
                    out.append({
                        "dataSetName": name,
                        "paleoData_variableName": vname,
                        "paleoData_values": c.get("values", []),
                        "year":  year_vals,
                        "age":   age_vals,
                        "yearUnits":  year_units,
                        "geo_meanLat":  lat,
                        "geo_meanLon":  lon,
                        "geo_meanElev": elev,
                        "archiveType":  archive,
                        "paleoData_proxy": c.get("proxy", c.get("proxyGeneral", vname)),
                        "paleoData_units": c.get("units", "unknown"),
                    })

    if isinstance(D, dict):
        for name, ds in D.items():
            if isinstance(ds, list):
                for i, sub in enumerate(ds):
                    _flatten_ds(f"{name}__{i}", sub)
            else:
                _flatten_ds(name, ds)
    elif isinstance(D, list):
        for i, ds in enumerate(D):
            n = str(ds.get("dataSetName", f"ds_{i}")) if isinstance(ds, dict) else f"ds_{i}"
            _flatten_ds(n, ds)

    print(f"[lipd_to_input] raw walker returned {len(out)} records", file=sys.stderr)
    return out


def build_proxydb(pkl_path: Path, out_path: Path) -> None:
    records = _extract_ts(pkl_path)
    if not records:
        raise SystemExit("No records extracted from LiPD pickle — cannot proceed.")

    rows: list[dict] = []
    seen_ids: set[str] = set()
    dropped = 0

    for rec in records:
        ds_name  = str(rec.get("dataSetName", "")) or "unknown"
        var_name = str(rec.get("paleoData_variableName", ""))
        if _is_skip_var(var_name):
            continue

        raw_vals = rec.get("paleoData_values")
        if raw_vals is None:
            dropped += 1
            continue
        try:
            vals = np.asarray(raw_vals, dtype=float)
        except (TypeError, ValueError):
            dropped += 1
            continue

        years = _coerce_year(rec.get("year"), rec.get("age"),
                             year_units=str(rec.get("yearUnits", "")))
        # Align and drop non-finite pairs.
        n = min(years.size, vals.size)
        if n == 0:
            dropped += 1
            continue
        years, vals = years[:n], vals[:n]
        mask = np.isfinite(years) & np.isfinite(vals)
        if not mask.any():
            dropped += 1
            continue
        years, vals = years[mask], vals[mask]
        order = np.argsort(years)
        years, vals = years[order], vals[order]

        # Constant-value records carry no signal and can destabilise GraphEM.
        if np.std(vals) < 1e-9:
            dropped += 1
            continue

        lat = _safe_float(rec.get("geo_meanLat"))
        lon = _safe_float(rec.get("geo_meanLon"))
        if not (np.isfinite(lat) and np.isfinite(lon)):
            dropped += 1
            continue
        elev = _safe_float(rec.get("geo_meanElev"))

        archive = str(rec.get("archiveType")
                       or rec.get("paleoData_archiveType") or "unknown").lower()
        proxy   = str(rec.get("paleoData_proxy")
                      or rec.get("paleoData_proxyObservationType") or var_name)
        ptype   = create_ptype(archive, proxy)

        # Prefer a stable unique id (TSid / pages2kID) so the cfr pid matches
        # the lipdverse catalog; fall back to dataset+variable.
        pid = str(rec.get("paleoData_TSid")
                  or rec.get("paleoData_pages2kID")
                  or f"{ds_name}__{var_name}")
        base, i = pid, 1
        while pid in seen_ids:
            i += 1
            pid = f"{base}__{i}"
        seen_ids.add(pid)

        rows.append({
            "paleoData_pages2kID":    pid,
            "geo_meanLat":            lat,
            "geo_meanLon":            lon,
            "geo_meanElev":           elev,
            "year":                   years,
            "paleoData_values":       vals,
            "ptype":                  ptype,
            "archiveType":            archive,
            "paleoData_variableName": var_name,
            "paleoData_units":        str(rec.get("paleoData_units", "unknown")),
        })

    if not rows:
        raise SystemExit(
            f"All {len(records)} records were dropped during conversion "
            f"({dropped} explicitly rejected) — cannot proceed."
        )

    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(out_path)

    ptype_counts = df["ptype"].value_counts()
    print(f"[lipd_to_input] wrote {out_path} ({len(df)} records, {dropped} dropped)")
    print("[lipd_to_input] proxy-type breakdown:")
    for pt, cnt in ptype_counts.items():
        print(f"    {pt:<32} {cnt:>4}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pickle", required=True, type=Path,
                    help="LiPD legacy pickle (the platform's /proxies/lipd_legacy.pkl)")
    ap.add_argument("--out", required=True, type=Path,
                    help="output cfr ProxyDatabase DataFrame pickle")
    args = ap.parse_args()
    build_proxydb(args.pickle, args.out)


if __name__ == "__main__":
    main()
