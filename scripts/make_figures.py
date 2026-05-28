#!/usr/bin/env python3
"""GraphEM reconstruction.nc -> figures/*.png.

Two figures, both surfaced on the result page:
  - reconstruction_field.png — time-mean map of the reconstructed field
    (the spatial product GraphEM is for), with coastlines if cartopy is
    available.
  - reconstruction_indices.png — the 1-D climate indices through time
    (global mean + Nino 3.4 etc.), the headline summary of the field.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless backend; CI has no display
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr


def _plot_field(ds: xr.Dataset, out_dir: Path) -> None:
    spatial = [v for v in ds.data_vars if {"lat", "lon"}.issubset(ds[v].dims)]
    if not spatial:
        print("[make_figures] no spatial field found; skipping field map")
        return
    vn = spatial[0]
    field = ds[vn].mean(dim="time")

    try:
        import cartopy.crs as ccrs  # type: ignore
        proj = ccrs.PlateCarree()
        fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150,
                               subplot_kw={"projection": proj})
        mesh = ax.pcolormesh(ds["lon"], ds["lat"], field,
                             transform=proj, cmap="RdBu_r", shading="auto")
        ax.coastlines(linewidth=0.5)
        gl = ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.4)
        gl.top_labels = gl.right_labels = False
    except Exception as e:  # noqa: BLE001 — cartopy optional, degrade gracefully
        print(f"[make_figures] cartopy unavailable ({e}); plain pcolormesh")
        fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150)
        mesh = ax.pcolormesh(ds["lon"], ds["lat"], field,
                             cmap="RdBu_r", shading="auto")
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")

    fig.colorbar(mesh, ax=ax, shrink=0.8, label=f"{vn} (time mean)")
    ax.set_title(f"GraphEM reconstructed {vn} — time-mean field")
    fig.tight_layout()
    out_path = out_dir / "reconstruction_field.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[make_figures] wrote {out_path}")


def _plot_indices(ds: xr.Dataset, out_dir: Path) -> None:
    index_vars = [v for v in ds.data_vars if ds[v].dims == ("time",)]
    if not index_vars:
        print("[make_figures] no 1-D index series found; skipping index plot")
        return
    year = np.asarray(ds["time"].values)

    fig, ax = plt.subplots(figsize=(9, 4), dpi=150)
    for v in index_vars:
        ax.plot(year, np.asarray(ds[v].values), lw=1.1, label=v)
    ax.axhline(0, color="k", lw=0.5, alpha=0.4)
    ax.set_xlabel("Year AD")
    ax.set_ylabel("anomaly")
    ax.set_title("GraphEM reconstruction — climate indices")
    ax.legend(loc="best", frameon=False, fontsize=8)
    ax.grid(alpha=0.3, linewidth=0.5)
    fig.tight_layout()
    out_path = out_dir / "reconstruction_indices.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[make_figures] wrote {out_path}")


def make(in_nc: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ds = xr.open_dataset(in_nc)
    _plot_field(ds, out_dir)
    _plot_indices(ds, out_dir)
    ds.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-nc",   required=True, type=Path,
                    help="finalized reconstruction NetCDF")
    ap.add_argument("--out-dir", required=True, type=Path,
                    help="figures output directory")
    args = ap.parse_args()
    make(args.in_nc, args.out_dir)


if __name__ == "__main__":
    main()
