#!/usr/bin/env python3
"""DEMO: reconstruction.csv → figures/reconstruction_ts.png.

Saves one figure per file in $OUT/figures. The static-Pages visualize
fallback in .github/workflows/visualize.yml surfaces every PNG in this
directory; add more figures here as your output schema grows.

──────────────────────────────────────────────────────────────────────
TODO: REPLACE with your own plotting code.

Useful patterns from existing PReSto templates:
    • LMR2 produces lat/lon maps of trend + climatology bands.
    • Holocene-DA produces composite time-series + spatial-anomaly maps.
    • BayGMST produces a reconstruction TS, posterior trace plots,
      and residual ACF/PACF diagnostics.
Pick what serves your science best.
──────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless backend; CI has no display
import matplotlib.pyplot as plt
import pandas as pd


def make(in_csv: Path, out_dir: Path) -> None:
    df = pd.read_csv(in_csv).sort_values("year")
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9, 4), dpi=150)
    if {"lo_95", "hi_95"}.issubset(df.columns):
        ax.fill_between(df["year"], df["lo_95"], df["hi_95"],
                        alpha=0.25, label="95% band", linewidth=0)
    ax.plot(df["year"], df["mean"], lw=1.2, label="reconstruction")
    ax.set_xlabel("Year AD")
    ax.set_ylabel("Composite (z-score units)")
    ax.set_title("PReSto template — demo reconstruction (z-score composite)")
    ax.legend(loc="best", frameon=False)
    ax.grid(alpha=0.3, linewidth=0.5)
    fig.tight_layout()

    out_path = out_dir / "reconstruction_ts.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[make_figures] wrote {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-csv",  required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()
    make(args.in_csv, args.out_dir)


if __name__ == "__main__":
    main()
