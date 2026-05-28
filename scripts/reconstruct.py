#!/usr/bin/env python3
"""DEMO algorithm: simple mean composite reconstruction.

Reads proxy_matrix.csv (year × proxy table from scripts/lipd_to_input.py),
computes per-year mean and standard-deviation across all available proxies,
and writes reconstruction.csv with mean + 95% bands.

This exists so the template runs end-to-end out of the box against the
default Pages2k 2_2_0 query — you can verify Pages, CI, and visualization
work before swapping in your real science.

──────────────────────────────────────────────────────────────────────
TODO: REPLACE with your actual reconstruction algorithm.

Your script should accept:
    --proxy-matrix  PATH    (year x proxy CSV from lipd_to_input.py)
    --config        PATH    (config/user_config.yml — your parameter knobs)
    --out-csv       PATH    (where to write your reconstruction table)

…and emit a CSV with at minimum a `year` column. Add any other columns
your visualization needs (uncertainty bounds, ensemble members, etc.).
scripts/outputs_to_netcdf.py and scripts/make_figures.py will need
updating in lockstep with your output schema.
──────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def reconstruct(proxy_matrix: Path, config_path: Path, out_csv: Path) -> None:
    cfg = yaml.safe_load(config_path.read_text()) or {}
    window = cfg.get("reconstruction_window") or {}
    year_start = int(window.get("start", 1))
    year_end   = int(window.get("end", 2000))
    min_n      = int(cfg.get("min_proxies_per_year", 5))

    df = pd.read_csv(proxy_matrix)
    df = df[(df["year"] >= year_start) & (df["year"] <= year_end)].copy()

    # Z-score each proxy over its valid period so different-unit records
    # (tree-ring widths in mm, δ¹⁸O in ‰, varve counts, etc.) contribute
    # equally to the composite. Without this the cross-proxy std for the
    # uncertainty band is dominated by whichever record has the largest
    # raw units, producing a band so wide the mean line looks flat.
    proxy_cols = [c for c in df.columns if c != "year"]
    proxies = df[proxy_cols]
    z = (proxies - proxies.mean(axis=0)) / proxies.std(axis=0).replace(0, np.nan)

    n_valid = z.notna().sum(axis=1)
    mean_   = z.mean(axis=1, skipna=True)
    # SEM (std of the mean) is the right uncertainty for a composite of
    # ~independent z-scored records — not the per-year cross-proxy std,
    # which is the *spread* of the input rather than the precision of
    # the average.
    sem_    = z.std(axis=1, skipna=True) / np.sqrt(n_valid.where(n_valid > 0))

    # Drop years that don't meet the per-year minimum proxy count.
    keep = n_valid >= min_n
    out = pd.DataFrame({
        "year":      df["year"][keep].to_numpy(),
        "mean":      mean_[keep].to_numpy(),
        "lo_95":     (mean_ - 1.96 * sem_)[keep].to_numpy(),
        "hi_95":     (mean_ + 1.96 * sem_)[keep].to_numpy(),
        "n_proxies": n_valid[keep].to_numpy(),
    })

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    print(f"[reconstruct] wrote {out_csv} "
          f"({len(out)} years, {out['n_proxies'].min()}–{out['n_proxies'].max()} proxies/year)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy-matrix", required=True, type=Path)
    ap.add_argument("--config",       required=True, type=Path)
    ap.add_argument("--out-csv",      required=True, type=Path)
    args = ap.parse_args()
    reconstruct(args.proxy_matrix, args.config, args.out_csv)


if __name__ == "__main__":
    main()
