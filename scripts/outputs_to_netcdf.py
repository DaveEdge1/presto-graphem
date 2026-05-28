#!/usr/bin/env python3
"""DEMO: reconstruction.csv → 1D CF-NetCDF.

Emits a CF-1.10 NetCDF with a single `time` dim and the reconstruction
mean + 95% bands. visualize.yml's autodetect step inspects this file:
    - If `lat` and `lon` are present in dims → routes to presto-viz.
    - If only `time` is present (this script's output) → routes to the
      static-Pages tile UI.

──────────────────────────────────────────────────────────────────────
TODO: REPLACE if your output is spatial.

For a gridded reconstruction (the LMR2 / Holocene-DA case), emit dims
`(time, lat, lon)` so visualize.yml routes you to presto-viz:

    ds = xr.Dataset(
        data_vars={"tas": (("time", "lat", "lon"), tas_grid)},
        coords={"time": years, "lat": lat_grid, "lon": lon_grid},
    )
    ds["lat"].attrs.update(units="degrees_north", standard_name="latitude")
    ds["lon"].attrs.update(units="degrees_east",  standard_name="longitude")

For an ensemble, add an `ensemble_member` dim alongside time/lat/lon.
──────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


def convert(in_csv: Path, out_nc: Path) -> None:
    df = pd.read_csv(in_csv).sort_values("year").reset_index(drop=True)

    def col(name: str) -> np.ndarray:
        return df[name].to_numpy(dtype=float) if name in df.columns \
            else np.full(len(df), np.nan, dtype=float)

    ds = xr.Dataset(
        data_vars={
            "reconstruction":       ("time", col("mean")),
            "reconstruction_lo_95": ("time", col("lo_95")),
            "reconstruction_hi_95": ("time", col("hi_95")),
        },
        coords={"time": df["year"].to_numpy(dtype=int)},
        attrs={
            "title":       "PReSto template demo reconstruction",
            "source":      "presto-template demo pipeline (mean composite)",
            "Conventions": "CF-1.10",
        },
    )
    ds["time"].attrs.update(units="years_AD", standard_name="time")
    for v in ("reconstruction", "reconstruction_lo_95", "reconstruction_hi_95"):
        ds[v].attrs.update(long_name="reconstructed value (demo)")

    out_nc.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out_nc)
    print(f"[outputs_to_netcdf] wrote {out_nc} ({len(df)} time steps)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-csv", required=True, type=Path)
    ap.add_argument("--out-nc", required=True, type=Path)
    args = ap.parse_args()
    convert(args.in_csv, args.out_nc)


if __name__ == "__main__":
    main()
