# Self-contained container for the GraphEM (cfr) PReSto reconstruction.
#
# Three layers, ordered by change frequency (least → most). Docker
# caches each layer independently, so editing scripts/ re-runs only the
# final COPY (≪ 1 s) instead of rebuilding the conda env.

# ── Layer 1: base + system deps ────────────────────────────────────────
# Pinned for reproducibility. Bump deliberately (every ~6 mo) and
# re-test end-to-end before pushing.
FROM continuumio/miniconda3:24.7.1-0

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

# cfr-graphem's solver links LAPACK/BLAS and is built with a Fortran
# toolchain at install time, so gfortran + liblapack/openblas are needed
# on top of the usual netCDF/HDF5 stack. gzip is used below to inflate
# the baked instrumental obs field.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ gfortran make pkg-config git curl ca-certificates \
        libcurl4-openssl-dev libssl-dev libxml2-dev \
        libnetcdf-dev libhdf5-dev \
        liblapack-dev libopenblas-dev \
        gzip \
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

# ── Layer 2b: cfr stack (pip) ─────────────────────────────────────────
# cfr-graphem ships an sdist whose setup.py imports Cython, so it must
# build with --no-build-isolation against this env's Cython + numpy
# (PEP 517 isolation would hide them). Installed before cfr so cfr sees
# the dependency already satisfied. cfr / blosc2 / LiPD build/install
# from wheels or pure-python, so they keep default isolation.
RUN pip install --no-cache-dir --no-build-isolation cfr-graphem==0.5.0 && \
    pip install --no-cache-dir cfr==2025.7.28 blosc2 LiPD && \
    python -c "import cfr; from graphem import GraphEM, Graph; print('cfr', cfr.__version__, '+ graphem OK')"

# ── Layer 3: app source (cheap; iterates often) ───────────────────────
# Anything below this line rebuilds whenever you edit a script. Keep
# heavy work above so iteration stays fast.
COPY scripts/        /app/scripts/
COPY config/         /app/config/
COPY reference_data/ /app/reference_data/
COPY entrypoint.sh   /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Inflate the baked instrumental obs field once at build time so the
# config's obs_path points at a plain .nc (xarray/cfr can't read .nc.gz
# transparently). The repo ships the 25 MB gzip; the image carries the
# inflated copy. Keep only the .nc to avoid shipping both.
RUN gunzip -f /app/reference_data/gistemp1200_GHCNv4_ERSSTv5.nc.gz

# CI mounts these paths at runtime:
#   /proxies/lipd_legacy.pkl       (RO)   — proxy data from lipdverse
#   /app/config/user_config.yml    (RO)   — overwritten per run by PReSto
#   /results                       (RW)   — outputs land here
# Defaults below let `docker run presto-graphem:local` work standalone
# for local dev (mount a pickle into /proxies/lipd_legacy.pkl first).
ENV LIPD_PICKLE=/proxies/lipd_legacy.pkl \
    PRESTO_CONFIG=/app/config/user_config.yml \
    PRESTO_REFDATA=/app/reference_data \
    PRESTO_OUTPUT=/results \
    PRESTO_OBS=/app/reference_data/gistemp1200_GHCNv4_ERSSTv5.nc \
    PRESTO_PROXYDB=/tmp/proxydb_cfr.pkl

ENTRYPOINT ["/app/entrypoint.sh"]
