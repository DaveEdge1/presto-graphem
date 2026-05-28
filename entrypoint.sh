#!/usr/bin/env bash
# Orchestrates the GraphEM (cfr) reconstruction pipeline inside the container.
#
# Pipeline:
#   1. lipd_to_input.py     — LiPD legacy pickle → cfr ProxyDatabase pickle
#   2. reconstruct.py       — run_graphem_cfg → gridded NetCDF (job_r01_recon.nc)
#   3. outputs_to_netcdf.py — finalize → reconstruction.nc (CF time/lat/lon) + reconstruction.csv
#   4. make_figures.py      — field map + index timeseries → figures/*.png
#
# CI mounts /proxies/lipd_legacy.pkl (RO), /app/config/user_config.yml (RO),
# and /results (RW). The obs field is baked into the image (PRESTO_OBS).

set -euo pipefail

LIPD_PICKLE="${LIPD_PICKLE:-/proxies/lipd_legacy.pkl}"
CONFIG="${PRESTO_CONFIG:-/app/config/user_config.yml}"
REFDATA="${PRESTO_REFDATA:-/app/reference_data}"
OUT="${PRESTO_OUTPUT:-/results}"
OBS="${PRESTO_OBS:-$REFDATA/gistemp1200_GHCNv4_ERSSTv5.nc}"
PROXYDB="${PRESTO_PROXYDB:-/tmp/proxydb_cfr.pkl}"

mkdir -p "$OUT" "$OUT/figures"

echo "[entrypoint] presto-graphem (GraphEM via cfr) pipeline"
echo "[entrypoint] LIPD_PICKLE=$LIPD_PICKLE"
echo "[entrypoint] CONFIG=$CONFIG"
echo "[entrypoint] OBS=$OBS"
echo "[entrypoint] OUT=$OUT"
echo "[entrypoint] config in use:"
cat "$CONFIG"
echo "[entrypoint] ---"

if [ ! -f "$OBS" ]; then
    echo "[entrypoint] ERROR: instrumental obs field not found at $OBS" >&2
    ls -lh "$REFDATA" || true
    exit 1
fi

# Step 1: LiPD legacy pickle → cfr ProxyDatabase pickle.
echo "[entrypoint] Step 1/4: LiPD pickle → cfr ProxyDatabase"
python /app/scripts/lipd_to_input.py \
    --pickle "$LIPD_PICKLE" \
    --out    "$PROXYDB"

# Step 2: run GraphEM via cfr.run_graphem_cfg.
echo "[entrypoint] Step 2/4: GraphEM reconstruction"
python /app/scripts/reconstruct.py \
    --config  "$CONFIG" \
    --proxydb "$PROXYDB" \
    --obs     "$OBS" \
    --out     "$OUT"

# Step 3: finalize gridded NetCDF (CF lat/lon → presto-viz) + index CSV.
echo "[entrypoint] Step 3/4: finalize NetCDF + CSV"
python /app/scripts/outputs_to_netcdf.py \
    --in-nc   "$OUT/job_r01_recon.nc" \
    --out-nc  "$OUT/reconstruction.nc" \
    --out-csv "$OUT/reconstruction.csv"

# Step 4: figures.
echo "[entrypoint] Step 4/4: figures"
python /app/scripts/make_figures.py \
    --in-nc   "$OUT/reconstruction.nc" \
    --out-dir "$OUT/figures"

echo "[entrypoint] Done. Contents of $OUT:"
ls -lhR "$OUT"
