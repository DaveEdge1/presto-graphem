#!/usr/bin/env python3
"""Run a GraphEM gridded reconstruction via cfr.

Thin wrapper around `cfr.ReconJob.run_graphem_cfg`, which does the whole
GraphEM pipeline from a single flat YAML config: load the proxy database,
filter / annualize / center it, load + annualize + regrid + crop the
instrumental obs field, estimate the graph, run the GraphEM solver, and
save the gridded reconstruction (time, lat, lon) plus the requested
climate indices to NetCDF.

This script's only job is to merge the runtime paths (the proxy DB that
lipd_to_input.py just produced, the baked obs field, and the output dir)
into the committed config, then hand the merged config to cfr. The committed
`config/user_config.yml` carries placeholder values for proxydb_path /
save_dirpath (hidden from the PReSto reuse view via runtimeHiddenKeys); the
real paths come from the CLI so the run works regardless of what the server
committed.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import yaml


def _validate_recon_period(cfg: dict) -> None:
    rp = cfg.get("recon_period")
    if not isinstance(rp, (list, tuple)) or len(rp) < 2:
        raise ValueError(f"recon_period must be [start_year, end_year]; got {rp!r}")
    start, end = int(rp[0]), int(rp[-1])
    if end < start:
        raise ValueError(
            f"recon_period end ({end}) must be >= start ({start}); swap your endpoints")
    if end - start < 1:
        raise ValueError(
            f"recon_period must span at least 2 years; got [{start}, {end}]")


def run(config_path: Path, proxydb: Path, obs: Path | None, out_dir: Path) -> None:
    # Import cfr lazily so --help works without the (heavy) cfr import.
    import cfr

    with config_path.open() as f:
        cfg = yaml.safe_load(f) or {}

    # ── Wire runtime paths into the config ──────────────────────────────
    cfg["proxydb_path"] = str(proxydb)
    cfg["save_dirpath"] = str(out_dir)
    cfg.setdefault("save_filename", "job_r01_recon.nc")

    if obs is not None:
        # obs_path is a {var: path} dict; keep the variable key, swap the path.
        obs_path = cfg.get("obs_path")
        if isinstance(obs_path, dict) and obs_path:
            vn = next(iter(obs_path))
            cfg["obs_path"] = {vn: str(obs)}
        else:
            cfg["obs_path"] = {"tas": str(obs)}

    _validate_recon_period(cfg)

    out_dir.mkdir(parents=True, exist_ok=True)

    print("[reconstruct] merged GraphEM config:")
    print(yaml.dump(cfg, default_flow_style=False, sort_keys=True))

    # run_graphem_cfg reads from a file path, so write the merged config out.
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as tf:
        yaml.dump(cfg, tf)
        merged_path = tf.name

    job = cfr.ReconJob()
    job.run_graphem_cfg(merged_path, verbose=True)

    saved = out_dir / cfg["save_filename"]
    print(f"[reconstruct] GraphEM finished; cfr reconstruction at {saved}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config",  required=True, type=Path,
                    help="flat cfr GraphEM config (config/user_config.yml)")
    ap.add_argument("--proxydb", required=True, type=Path,
                    help="cfr ProxyDatabase pickle from lipd_to_input.py")
    ap.add_argument("--obs", type=Path, default=None,
                    help="instrumental obs NetCDF (overrides obs_path in config)")
    ap.add_argument("--out", required=True, type=Path,
                    help="output directory (cfr save_dirpath)")
    args = ap.parse_args()
    run(args.config, args.proxydb, args.obs, args.out)


if __name__ == "__main__":
    main()
