#!/usr/bin/env bash
# Orchestrates the demo reconstruction pipeline inside the container.
#
# Pipeline (DEMO):
#   1. lipd_to_input.py     — LiPD pickle  → proxy_matrix.csv + proxy_metadata.csv
#   2. reconstruct.py       — proxy_matrix → reconstruction.csv (mean composite)
#   3. outputs_to_netcdf.py — reconstruction.csv → reconstruction.nc (1D CF-NetCDF)
#   4. make_figures.py      — reconstruction.csv → figures/reconstruction_ts.png
#
# CUSTOMIZATION POINTS:
#   - Add / remove steps as your algorithm needs.
#   - Read env vars (LIPD_PICKLE, PRESTO_CONFIG, PRESTO_OUTPUT, PRESTO_REFDATA)
#     instead of hard-coding paths — CI mounts these at consistent locations.
#   - Set `set -e` (already on) so any failing step halts the run.
#   - Anything you `echo` here shows up in the Actions log; use this for
#     progress messages and config dumps that aid debugging.

set -euo pipefail

LIPD_PICKLE="${LIPD_PICKLE:-/proxies/lipd_legacy.pkl}"
CONFIG="${PRESTO_CONFIG:-/app/config/user_config.yml}"
REFDATA="${PRESTO_REFDATA:-/app/reference_data}"
OUT="${PRESTO_OUTPUT:-/results}"

mkdir -p "$OUT" "$OUT/figures"

echo "[entrypoint] presto-template demo pipeline"
echo "[entrypoint] LIPD_PICKLE=$LIPD_PICKLE"
echo "[entrypoint] CONFIG=$CONFIG"
echo "[entrypoint] OUT=$OUT"
echo "[entrypoint] config in use:"
cat "$CONFIG"
echo "[entrypoint] ---"

# Step 1: LiPD → proxy matrix CSV.
# TODO: REPLACE if your algorithm reads LiPD records differently (e.g.,
# you need PSM calibration, time-axis re-binning, or a non-LiPD source).
echo "[entrypoint] Step 1/4: LiPD pickle → proxy matrix"
python /app/scripts/lipd_to_input.py \
    --pickle       "$LIPD_PICKLE" \
    --out-matrix   "$OUT/proxy_matrix.csv" \
    --out-metadata "$OUT/proxy_metadata.csv"

# Step 2: run the demo reconstruction algorithm.
# TODO: REPLACE — this is where your science goes.
echo "[entrypoint] Step 2/4: reconstruction"
python /app/scripts/reconstruct.py \
    --proxy-matrix "$OUT/proxy_matrix.csv" \
    --config       "$CONFIG" \
    --out-csv      "$OUT/reconstruction.csv"

# Step 3: emit a CF-friendly NetCDF (presto-viz consumes this if it's
# spatial; otherwise the static-Pages visualize.yml fallback picks up
# the CSV + figures and ignores the .nc).
# TODO: REPLACE if your output is gridded (lat/lon/time) — emit those
# dims so visualize.yml's autodetect routes you to presto-viz.
echo "[entrypoint] Step 3/4: CSV → NetCDF"
python /app/scripts/outputs_to_netcdf.py \
    --in-csv "$OUT/reconstruction.csv" \
    --out-nc "$OUT/reconstruction.nc"

# Step 4: figures. Drop more PNGs into $OUT/figures as needed; the
# static-Pages visualize fallback surfaces whatever is here.
echo "[entrypoint] Step 4/4: figures"
python /app/scripts/make_figures.py \
    --in-csv  "$OUT/reconstruction.csv" \
    --out-dir "$OUT/figures"

echo "[entrypoint] Done. Contents of $OUT:"
ls -lhR "$OUT"
