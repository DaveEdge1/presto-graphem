# Self-contained container for a PReSto reconstruction.
#
# Three layers, ordered by change frequency (least → most). Docker
# caches each layer independently, so editing scripts/ re-runs only the
# final COPY (≪ 1 s) instead of rebuilding the conda env.
#
# CUSTOMIZATION POINTS:
#   1. Base image: stick with continuumio/miniconda3 unless your algorithm
#      needs something exotic (e.g., GPU CUDA → nvidia/cuda + miniconda).
#   2. environment.yml: list your reconstruction's deps.
#   3. COPY layout: add your own subdirectories (e.g., COPY my_algo/).

# ── Layer 1: base + system deps ────────────────────────────────────────
# Pinned for reproducibility. Bump deliberately (every ~6 mo) and
# re-test end-to-end before pushing.
FROM continuumio/miniconda3:24.7.1-0

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

# Most scientific Python stacks need at least these. Add to this list
# if your algorithm needs more system libraries (GDAL, HDF5 variants,
# proprietary drivers, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ gfortran make pkg-config git curl ca-certificates \
        libcurl4-openssl-dev libssl-dev libxml2-dev \
        libnetcdf-dev libhdf5-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Layer 2: conda env (heavy, but cached) ────────────────────────────
# This layer only rebuilds when environment.yml changes. Cold build is
# ~5–10 minutes; cached rebuild is ~5 seconds. Keep environment.yml
# tightly scoped (see comments in that file).
COPY environment.yml /app/environment.yml
RUN conda env create -f /app/environment.yml && \
    conda clean -afy && \
    find /opt/conda -follow -type f -name '*.a'     -delete && \
    find /opt/conda -follow -type f -name '*.pyc'   -delete && \
    find /opt/conda -follow -type f -name '*.js.map' -delete

# Activate the env for all subsequent RUN / ENTRYPOINT layers.
ENV PATH=/opt/conda/envs/presto-env/bin:$PATH \
    CONDA_DEFAULT_ENV=presto-env \
    CONDA_PREFIX=/opt/conda/envs/presto-env

# ── Layer 3: app source (cheap; iterates often) ───────────────────────
# Anything below this line rebuilds whenever you edit a script. Keep
# heavy work above so iteration stays fast.
COPY scripts/        /app/scripts/
COPY config/         /app/config/
COPY reference_data/ /app/reference_data/
COPY entrypoint.sh   /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# CI mounts these paths at runtime:
#   /proxies/lipd_legacy.pkl       (RO)   — proxy data from lipdverse
#   /app/config/user_config.yml    (RO)   — overwritten per run by PReSto
#   /results                       (RW)   — outputs land here
# Defaults below let `docker run presto-template:local` work standalone
# for local dev (mount a pickle into /proxies/lipd_legacy.pkl first).
ENV LIPD_PICKLE=/proxies/lipd_legacy.pkl \
    PRESTO_CONFIG=/app/config/user_config.yml \
    PRESTO_REFDATA=/app/reference_data \
    PRESTO_OUTPUT=/results

ENTRYPOINT ["/app/entrypoint.sh"]
