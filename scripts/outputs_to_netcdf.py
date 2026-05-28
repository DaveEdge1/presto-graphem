#!/usr/bin/env python3
"""Finalize cfr's GraphEM output into the platform's expected artifacts.

cfr already writes a gridded NetCDF (job_r01_recon.nc) containing the
reconstructed field `tas` with dims (time, lat, lon) plus the requested
climate indices (tas_gm, tas_nhm, tas_shm, nino3.4) as (time,) series.

This step:
  1. Re-saves it as results/reconstruction.nc, stamping CF attributes on
     lat / lon / time so visualize.yml's autodetect sees {lat, lon} ⊆ dims
     and routes the result to the presto-viz interactive map.
  2. Writes results/reconstruction.csv from the 1-D index series — the
     core workflow's verify step requires reconstruction.csv to exist, and
     the indices are the natural 1-D summary of a gridded field.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


def _stamp_cf_attrs(ds: xr.Dataset) -> None:
    if "lat" in ds.coords:
        ds["lat"].attrs.update(units="degrees_north", standard_name="latitude",
                               long_name="latitude")
    if "lon" in ds.coords:
        ds["lon"].attrs.update(units="degrees_east", standard_name="longitude",
                               long_name="longitude")
    if "time" in ds.coords:
        ds["time"].attrs.setdefault("units", "years_AD")
        ds["time"].attrs.setdefault("standard_name", "time")


def convert(in_nc: Path, out_nc: Path, out_csv: Path) -> None:
    ds = xr.open_dataset(in_nc)

    # cfr emits the climate indices (tas_gm, nino3.4, ...) with a singleton
    # 'ens' dimension, so their dims are (time, ens). Squeeze it so they
    # become clean (time,) series; the field tas is already (time, lat, lon).
    if "ens" in ds.dims and ds.sizes["ens"] == 1:
        ds = ds.isel(ens=0, drop=True)

    _stamp_cf_attrs(ds)
    ds.attrs.setdefault("title", "GraphEM gridded climate-field reconstruction")
    ds.attrs.setdefault("source", "cfr + cfr-graphem (run_graphem_cfg)")
    ds.attrs.setdefault("Conventions", "CF-1.10")

    spatial = [v for v in ds.data_vars
               if {"lat", "lon"}.issubset(ds[v].dims)]
    print(f"[outputs_to_netcdf] spatial fields: {spatial}")

    out_nc.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out_nc)
    print(f"[outputs_to_netcdf] wrote {out_nc} (dims: {dict(ds.sizes)})")

    # ── 1-D index series → CSV ──────────────────────────────────────────
    index_vars = [v for v in ds.data_vars if ds[v].dims == ("time",)]
    if "time" in ds.coords:
        table = {"year": np.asarray(ds["time"].values)}
        for v in index_vars:
            table[v] = np.asarray(ds[v].values)
        df = pd.DataFrame(table)
    else:
        df = pd.DataFrame({"year": []})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"[outputs_to_netcdf] wrote {out_csv} "
          f"({len(df)} years, indices: {index_vars})")

    ds.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-nc",  required=True, type=Path,
                    help="cfr's saved reconstruction NetCDF (job_r01_recon.nc)")
    ap.add_argument("--out-nc", required=True, type=Path,
                    help="finalized gridded NetCDF (results/reconstruction.nc)")
    ap.add_argument("--out-csv", required=True, type=Path,
                    help="index summary CSV (results/reconstruction.csv)")
    args = ap.parse_args()
    convert(args.in_nc, args.out_nc, args.out_csv)


if __name__ == "__main__":
    main()
