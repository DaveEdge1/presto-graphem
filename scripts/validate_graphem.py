#!/usr/bin/env python3
"""Instrumental validation for a GraphEM (cfr) gridded reconstruction.

Compares the reconstructed temperature field against the GISTEMP instrumental
record over the period the two share, producing:

  * spatial correlation (r) and coefficient-of-efficiency (CE) maps on the
    reconstruction's own grid,
  * a domain-mean time series (reconstruction vs GISTEMP), plus the Nino3.4
    index when the reconstruction carries it,
  * machine-readable metrics (validation_metrics.json / .csv), and
  * an HTML report (validation/index.html) for the GitHub Pages landing tile.

Modeled on DaveEdge1/LMR2's validate_recon.py, but trimmed to the single
GISTEMP reference and adapted for a regional reconstruction whose period and
domain are user-configurable: the validation window is derived at runtime from
the overlap of the reconstruction's time axis and GISTEMP's, and the map extent
is taken from the reconstruction grid — nothing about the period or region is
hard-coded.

Run inside the presto-graphem image (cfr on the presto-env conda env):

    docker run --rm --entrypoint python \\
      -v $(pwd)/recon-data:/recons:ro \\
      -v $(pwd)/reference_data:/reference_data:ro \\
      -v $(pwd)/validation:/validation \\
      presto-graphem:local /app/scripts/validate_graphem.py
"""

from __future__ import annotations

import ast
import csv
import glob
import json
import os

import numpy as np
import xarray as xr
import yaml

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

import cfr


RECON_DIR      = os.environ.get('RECON_DIR', '/recons')
VALIDATION_DIR = os.environ.get('VALIDATION_DIR', '/validation')
REFERENCE_DIR  = os.environ.get('REFERENCE_DIR', '/reference_data')
# Same instrumental field the reconstruction was calibrated against (baked
# into the image). Override via OBS_PATH for non-default obs.
OBS_PATH = os.environ.get(
    'OBS_PATH', os.path.join(REFERENCE_DIR, 'gistemp1200_GHCNv4_ERSSTv5.nc'))
OBS_VAR  = os.environ.get('OBS_VAR', 'tempanomaly')

os.makedirs(VALIDATION_DIR, exist_ok=True)


# ── small numeric helpers ──────────────────────────────────────────────────
def pearson_r(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 5:
        return float('nan')
    return float(np.corrcoef(a[mask], b[mask])[0, 1])


def coefficient_of_efficiency(obs, pred):
    """CE = 1 - SS_res/SS_tot, with obs as the reference series."""
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    mask = np.isfinite(obs) & np.isfinite(pred)
    if mask.sum() < 5:
        return float('nan')
    o, p = obs[mask], pred[mask]
    ss_tot = np.sum((o - np.mean(o)) ** 2)
    if ss_tot == 0:
        return float('nan')
    return float(1.0 - np.sum((o - p) ** 2) / ss_tot)


def to_int_years(time):
    """Annual cfr series carry float/cftime years; collapse to integer years."""
    arr = np.asarray(time)
    try:
        return np.array([int(t.year) for t in arr])
    except AttributeError:
        return np.floor(np.asarray(arr, dtype=float)).astype(int)


def ensts_median(ensts):
    """(int years, 1-D median across ensemble) from a cfr EnsTS."""
    t = to_int_years(ensts.time)
    v = np.asarray(ensts.value, dtype=float)
    if v.ndim == 2:
        v = np.nanmedian(v, axis=1)
    return t, v


def overlap_on_common_years(ta, va, tb, vb, lo, hi):
    """Restrict two integer-year series to their shared years within [lo, hi]."""
    ta, tb = np.asarray(ta, int), np.asarray(tb, int)
    common = np.intersect1d(ta, tb)
    common = common[(common >= lo) & (common <= hi)]
    ia = {y: i for i, y in enumerate(ta)}
    ib = {y: i for i, y in enumerate(tb)}
    a = np.array([va[ia[y]] for y in common], dtype=float)
    b = np.array([vb[ib[y]] for y in common], dtype=float)
    return common, a, b


def field_area_mean(da):
    """cos(lat)-weighted mean of a (time=1, lat, lon) statistic field."""
    d = da.squeeze()
    wgts = np.cos(np.deg2rad(d['lat']))
    return float(d.weighted(wgts).mean(('lat', 'lon')).values)


def read_config_anom_period(default=(1951, 1980)):
    """Best-effort obs anomaly reference period from the recon's configs.yml.

    The pipeline writes a flattened {presto_config: {key: {value: '...'}}}
    configs.yml alongside the NetCDFs; fall back to the cfr default if it's
    absent or unparseable so validation still runs.
    """
    path = os.path.join(RECON_DIR, 'configs.yml')
    if not os.path.exists(path):
        return list(default)
    try:
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
        raw = cfg.get('presto_config', {}).get('obs_anom_period', {}).get('value')
        period = ast.literal_eval(raw) if isinstance(raw, str) else raw
        if isinstance(period, (list, tuple)) and len(period) == 2:
            return [int(period[0]), int(period[1])]
    except Exception as e:  # noqa: BLE001 - config is advisory only
        print(f'[validate] could not parse obs_anom_period from configs.yml: {e}')
    return list(default)


# ── 1. reconstruction ───────────────────────────────────────────────────────
print(f'[validate] loading reconstruction from {RECON_DIR} ...')
res = cfr.ReconRes(RECON_DIR)
load_vars = ['tas', 'tas_gm']
res.load(load_vars, verbose=True)
recon_tas = res.recons['tas']     # ClimateField (ensemble-mean spatial field)
recon_gm  = res.recons['tas_gm']  # EnsTS (domain mean, full ensemble)

recon_years, recon_gm_median = ensts_median(recon_gm)

# Map extent + domain-mean bounds straight from the reconstruction grid.
lat_vals = np.asarray(recon_tas.da['lat'].values, dtype=float)
lon_vals = np.asarray(recon_tas.da['lon'].values, dtype=float)
dom = dict(lat_min=float(lat_vals.min()), lat_max=float(lat_vals.max()),
           lon_min=float(lon_vals.min()), lon_max=float(lon_vals.max()))
print(f'[validate] reconstruction domain: {dom}')

# Optional Nino3.4 index (only if reconstructed and the domain contains it).
recon_nino = None
nino_box_covered = (dom['lat_min'] <= -5 and dom['lat_max'] >= 5
                    and dom['lon_min'] <= 190 and dom['lon_max'] >= 240)
try:
    res.load(['nino3.4'], verbose=False)
    if nino_box_covered:
        recon_nino = res.recons['nino3.4']
except Exception as e:  # noqa: BLE001
    print(f'[validate] no Nino3.4 in reconstruction ({e}); skipping that panel.')


# ── 2. instrumental observations (baked GISTEMP) ────────────────────────────
anom_period = read_config_anom_period()
print(f'[validate] loading GISTEMP from {OBS_PATH} (anom ref {anom_period}) ...')
obs = cfr.ClimateField().load_nc(OBS_PATH, vn=OBS_VAR)
obs = obs.get_anom(ref_period=anom_period)
obs = obs.annualize(months=list(range(1, 13)))

obs_dm = obs.geo_mean(**dom)               # domain-mean instrumental series
obs_years, obs_dm_vals = ensts_median(obs_dm)


# ── 3. validation window = overlap of recon and obs coverage ────────────────
valid_start = int(max(recon_years.min(), obs_years.min()))
valid_end   = int(min(recon_years.max(), obs_years.max()))
if valid_end <= valid_start:
    raise SystemExit(
        f'[validate] no overlap between reconstruction '
        f'({recon_years.min()}-{recon_years.max()}) and GISTEMP '
        f'({obs_years.min()}-{obs_years.max()}); cannot validate.')
period = [valid_start, valid_end]
print(f'[validate] validation window (recon ∩ GISTEMP): {valid_start}-{valid_end}')


# ── 4. spatial validation maps (correlation + CE) ───────────────────────────
print('[validate] computing spatial correlation / CE maps ...')
# interp_target='self' regrids the global obs onto the reconstruction's grid so
# the statistics live on the reconstructed domain (not a global field of NaNs).
corr_da = recon_tas.compare(obs, stat='corr', timespan=period,
                            interp_target='self').da
ce_da = recon_tas.compare(obs, stat='CE', timespan=period,
                          interp_target='self').da
geo_mean_corr = field_area_mean(corr_da)
geo_mean_ce   = field_area_mean(ce_da)
print(f'[validate]   domain-mean r = {geo_mean_corr:.3f}, CE = {geo_mean_ce:.3f}')


def _plot_stat_map(da, fname, title, cmap='RdBu_r'):
    """Plot a regional statistic field. Best-effort: cartopy projection/extent
    quirks on a regional (possibly >180°E) domain must not sink the whole
    validation, so on any failure we log and skip the image — the skill table
    and metrics files still carry the numbers."""
    try:
        extent = [dom['lon_min'], dom['lon_max'], dom['lat_min'], dom['lat_max']]
        # Center longitudes near the domain so a Pacific box (lon up to 260°E)
        # doesn't wrap awkwardly across the antimeridian.
        proj = ccrs.PlateCarree(central_longitude=float(np.mean(lon_vals)))
        fig, ax = plt.subplots(1, 1, figsize=(9, 5), subplot_kw={'projection': proj})
        da.squeeze().plot(ax=ax, transform=ccrs.PlateCarree(),
                          cmap=cmap, vmin=-1, vmax=1,
                          cbar_kwargs={'label': title.split('\n')[0],
                                       'orientation': 'horizontal',
                                       'shrink': 0.8, 'pad': 0.08})
        ax.coastlines(linewidth=0.6)
        ax.set_extent(extent, crs=ccrs.PlateCarree())
        ax.set_title(title, fontsize=12)
        fig.savefig(os.path.join(VALIDATION_DIR, fname), dpi=150, bbox_inches='tight')
        plt.close(fig)
        return True
    except Exception as e:  # noqa: BLE001 - plotting is non-essential
        print(f'[validate] WARNING: could not render {fname}: {e}')
        plt.close('all')
        return False


_plot_stat_map(corr_da, 'spatial_corr_map.png',
               f'Reconstruction vs GISTEMP correlation ({valid_start}–{valid_end})\n'
               f'domain-mean r = {geo_mean_corr:.3f}')
_plot_stat_map(ce_da, 'spatial_ce_map.png',
               f'Reconstruction vs GISTEMP CE ({valid_start}–{valid_end})\n'
               f'domain-mean CE = {geo_mean_ce:.3f}')


# ── 5. domain-mean (and Nino3.4) time series ────────────────────────────────
print('[validate] computing domain-mean time series metrics ...')
_, dm_recon, dm_obs = overlap_on_common_years(
    recon_years, recon_gm_median, obs_years, obs_dm_vals, valid_start, valid_end)
dm_r  = pearson_r(dm_recon, dm_obs)
dm_ce = coefficient_of_efficiency(dm_obs, dm_recon)
print(f'[validate]   domain-mean series: R = {dm_r:.3f}, CE = {dm_ce:.3f}')

panels = [('Domain-mean temperature anomaly', recon_years, recon_gm_median,
           obs_years, obs_dm_vals, dm_r, dm_ce)]

nino_r = nino_ce = None
if recon_nino is not None:
    nino_years, nino_recon = ensts_median(recon_nino)
    obs_nino = obs.index('nino3.4')
    nino_obs_years, nino_obs_vals = ensts_median(obs_nino)
    _, nr, no = overlap_on_common_years(
        nino_years, nino_recon, nino_obs_years, nino_obs_vals,
        valid_start, valid_end)
    nino_r  = pearson_r(nr, no)
    nino_ce = coefficient_of_efficiency(no, nr)
    print(f'[validate]   Nino3.4 series: R = {nino_r:.3f}, CE = {nino_ce:.3f}')
    panels.append(('Niño3.4 index', nino_years, nino_recon,
                   nino_obs_years, nino_obs_vals, nino_r, nino_ce))

try:
    fig, axes = plt.subplots(len(panels), 1, figsize=(10, 3.2 * len(panels)),
                             squeeze=False)
    for ax, (label, rt, rv, ot, ov, r, ce) in zip(axes[:, 0], panels):
        ax.plot(ot, ov, color='#444', lw=1.4, label='GISTEMP')
        ax.plot(rt, rv, color='#2563eb', lw=1.6, label='Reconstruction')
        ax.axvspan(valid_start, valid_end, color='#2563eb', alpha=0.06,
                   label='validation window')
        ax.set_title(f'{label}   (R = {r:.3f}, CE = {ce:.3f})', fontsize=11)
        ax.set_xlabel('Year (CE)')
        ax.set_ylabel('°C anomaly')
        ax.legend(fontsize=8, loc='best')
    fig.tight_layout()
    fig.savefig(os.path.join(VALIDATION_DIR, 'timeseries.png'),
                dpi=150, bbox_inches='tight')
    plt.close(fig)
except Exception as e:  # noqa: BLE001 - plotting is non-essential
    print(f'[validate] WARNING: could not render timeseries.png: {e}')
    plt.close('all')


# ── 6. machine-readable metrics ─────────────────────────────────────────────
metrics = {
    'validation_period': period,
    'reference': 'GISTEMP (gistemp1200_GHCNv4_ERSSTv5)',
    'domain': dom,
    'spatial': {'domain_mean_corr': geo_mean_corr, 'domain_mean_CE': geo_mean_ce},
    'domain_mean_series': {'R': dm_r, 'CE': dm_ce},
}
if nino_r is not None:
    metrics['nino3.4_series'] = {'R': nino_r, 'CE': nino_ce}

with open(os.path.join(VALIDATION_DIR, 'validation_metrics.json'), 'w') as f:
    json.dump(metrics, f, indent=2, default=str)

with open(os.path.join(VALIDATION_DIR, 'validation_metrics.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['metric', 'value'])
    w.writerow(['validation_period', f'{valid_start}-{valid_end}'])
    w.writerow(['spatial_domain_mean_corr', f'{geo_mean_corr:.4f}'])
    w.writerow(['spatial_domain_mean_CE', f'{geo_mean_ce:.4f}'])
    w.writerow(['domain_mean_series_R', f'{dm_r:.4f}'])
    w.writerow(['domain_mean_series_CE', f'{dm_ce:.4f}'])
    if nino_r is not None:
        w.writerow(['nino3.4_series_R', f'{nino_r:.4f}'])
        w.writerow(['nino3.4_series_CE', f'{nino_ce:.4f}'])


# ── 7. HTML report (validation/index.html) ──────────────────────────────────
def _fmt(v):
    return '—' if v is None or (isinstance(v, float) and np.isnan(v)) else f'{v:.3f}'

nino_rows = ''
if nino_r is not None:
    nino_rows = (f'<tr><td>Niño3.4 index series</td>'
                 f'<td>{_fmt(nino_r)}</td><td>{_fmt(nino_ce)}</td></tr>')

html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reconstruction validation — PReSto</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         max-width:900px;margin:0 auto;padding:32px 20px;color:#1a1a1a;line-height:1.5; }}
  h1 {{ font-size:1.6rem;margin-bottom:.2em; }} h2 {{ font-size:1.2rem;margin-top:1.8em; }}
  p.sub {{ color:#666;margin-top:0; }}
  table {{ border-collapse:collapse;margin:1em 0;width:100%;max-width:560px; }}
  th,td {{ border:1px solid #ddd;padding:8px 12px;text-align:left; }}
  th {{ background:#f3f4f6; }} td:nth-child(n+2),th:nth-child(n+2) {{ text-align:right; }}
  img {{ max-width:100%;height:auto;border:1px solid #eee;border-radius:8px;margin:.5em 0; }}
  .note {{ background:#f7f8fa;border-left:3px solid #2563eb;padding:10px 14px;font-size:.92em;color:#333; }}
  a {{ color:#2563eb; }}
</style></head><body>
<p><a href="../">← Back to reconstruction</a></p>
<h1>Reconstruction validation</h1>
<p class="sub">Reconstructed temperature field vs. GISTEMP instrumental data,
over the period the two share: <strong>{valid_start}–{valid_end}</strong>.</p>

<div class="note">Skill is measured against GISTEMP — the same instrumental
product the reconstruction is calibrated against — so these statistics describe
how faithfully the reconstruction reproduces the observed field over their
common period, not out-of-sample skill. The validation window is derived
automatically from the reconstruction's own time span.</div>

<h2>Skill metrics</h2>
<table>
  <tr><th>Quantity</th><th>R</th><th>CE</th></tr>
  <tr><td>Spatial field (domain mean of per-cell stats)</td>
      <td>{_fmt(geo_mean_corr)}</td><td>{_fmt(geo_mean_ce)}</td></tr>
  <tr><td>Domain-mean temperature series</td>
      <td>{_fmt(dm_r)}</td><td>{_fmt(dm_ce)}</td></tr>
  {nino_rows}
</table>
<p class="sub"><em>R</em> = Pearson correlation; <em>CE</em> = coefficient of
efficiency (1 = perfect, 0 = no better than the observed mean, &lt;0 = worse).</p>

<h2>Spatial skill maps</h2>
<img src="spatial_corr_map.png" alt="Spatial correlation map">
<img src="spatial_ce_map.png" alt="Spatial CE map">

<h2>Time series</h2>
<img src="timeseries.png" alt="Domain-mean and index time series">

<h2>Downloads</h2>
<ul>
  <li><a href="validation_metrics.json">validation_metrics.json</a></li>
  <li><a href="validation_metrics.csv">validation_metrics.csv</a></li>
</ul>
<p class="sub">Generated by <a href="https://paleopresto.com">PReSto</a>.</p>
</body></html>
"""

with open(os.path.join(VALIDATION_DIR, 'index.html'), 'w') as f:
    f.write(html)

print(f'[validate] wrote validation report to {VALIDATION_DIR}/index.html')
