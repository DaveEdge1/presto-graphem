# Adapting this template

This template ships as a runnable demo (the placeholder algorithm averages all Pages2k 2.2.0 proxies into a 1D timeseries). To make it yours: fork, get the demo running end-to-end on your fork first, then progressively swap in your code.

## 1. Quick start

```sh
# Use the GitHub "Use this template" button on https://github.com/DaveEdge1/presto-template,
# or clone + push to a new repo of your own.
git clone https://github.com/DaveEdge1/presto-template.git my-reconstruction
cd my-reconstruction
gh repo create my-reconstruction --public --source=. --push
```

Then in your new repo:

1. **Settings → Pages → Source = "GitHub Actions"** (one-time; required for `visualize.yml` to deploy).
2. **Actions tab → "Reconstruction" → Run workflow.** First build takes ~10 min (cold conda env install); subsequent builds are ~1 min cached.
3. When the run finishes: check `results/` for the reconstruction outputs, the Actions tab for the GitHub Pages URL, and `README.md` for the auto-regenerated summary.

If all three workflows go green (`Reconstruction` → `Visualize Reconstruction Results` → `Update README`), the scaffold is wired correctly on your repo. Now you can swap in your code.

## 2. Swap in your algorithm

Edit these files in order — each step is independently verifiable:

| Step | File | What to change |
|------|------|----------------|
| 1 | `environment.yml` | Add your reconstruction's Python deps (or replace the conda env wholesale). |
| 2 | `scripts/reconstruct.py` | Replace the placeholder mean-composite with your algorithm. Keep the `--proxy-matrix / --config / --out-csv` CLI contract or update `entrypoint.sh` to match. |
| 3 | `scripts/outputs_to_netcdf.py` | Update the NetCDF schema. **Spatial output authors:** emit `time / lat / lon` dims so `visualize.yml` autodetects and routes to `presto-viz`. **1D authors:** keep the existing `(time,)` shape. |
| 4 | `scripts/make_figures.py` | Replace with plots that suit your output (lat/lon maps, ensemble fans, residual diagnostics, etc.). Every PNG dropped into `$OUT/figures/` is surfaced on the static-Pages tile UI. |
| 5 | `scripts/lipd_to_input.py` | Most authors keep this unchanged. Replace if you need PSM calibration (see `LMR2/scripts/lipd_to_pdb.py` for the cfr pattern), non-LiPD input, or non-annual binning. |
| 6 | `config/user_config.yml` | Replace the two demo knobs with your algorithm's parameters. Keep nesting shallow so the README templater renders them cleanly. |
| 7 | `entrypoint.sh` | Add/remove pipeline steps; update mount-point env vars if your container expects different paths. |
| 8 | `CITATION.cff` | Add your method-paper reference and your author info. Data citations get appended automatically by lipdGenerator on each run. |
| 9 | `README_NOTES.md` | Replace the placeholder intro with your real project description. This text is preserved across README regenerations. |

After each step, push and watch the Actions tab. The Docker build caches everything above the script-layer COPY, so iteration on `scripts/` rebuilds in ~5 seconds.

## 3. Customize the data input

**Keep `scripts/lipd_to_input.py` as-is when:**
- You're happy with a year × proxy matrix (annual averages, NaN for missing) as input.
- You want flexibility for users to pick any LiPDverse compilation via `query_params.json`.

**Write your own data adapter when:**
- Your algorithm needs **PSM-calibrated** records (CFR's `ProxyDatabase`) — port `LMR2/scripts/lipd_to_pdb.py`.
- Your algorithm reads from a **non-LiPD** source — read your CSV/NetCDF/HDF5/etc. directly in `entrypoint.sh` and skip Step 1.
- You need **non-annual** time resolution (decadal, sub-annual, irregular) — change `_aggregate_to_annual` in `scripts/lipd_to_input.py`.

**Static reference data** (climate priors, model fields, calibration tables) goes in `reference_data/`. It's baked into the Docker image at `/app/reference_data/` (read-only at runtime). Keep individual files under 50 MB to keep the image manageable; for larger reference datasets, download them at workflow-runtime to an external cache (see `presto-holocene_da/.github/workflows/holocene_da.yml` for the GitHub Release-asset download pattern).

## 4. Customize the visualization

`visualize.yml` autodetects spatial vs. 1D output by inspecting your `.nc` file's dims:

- **`{lat, lon}` ⊆ dims** → routes to the [`presto-viz` reusable workflow](https://github.com/DaveEdge1/presto-viz) (the interactive map UI used by LMR2 and Holocene-DA).
- **Otherwise** → routes to a static GitHub Pages site with a tile UI that surfaces every PNG in `$OUT/figures/` plus the CSV/NetCDF as downloads.

**Forcing the static path** (even if your output happens to have lat/lon): add `FORCE_STATIC_VIZ=true` as a step env var in the `inspect-output` job of `visualize.yml` and short-circuit the detection.

**Customizing the static UI:** edit the `cat > ./static-viz/index.html` heredoc inside `visualize-static`. The CSS is intentionally framework-free so you can edit without learning a build tool.

**Customizing presto-viz behavior:** see the `DaveEdge1/presto-viz` repo for the inputs the reusable workflow accepts. Most authors don't customize it.

## 5. Optional workflows

### `release-recon.yml` (enabled by default)

Bundles each successful reconstruction into a GitHub Release tagged `recon-<run_id>`. Each release contains a tarball with `results/`, `inputs/` (config + query snapshots + README), and the LiPD pickle. Top-level NetCDFs under 2 GB are also attached individually.

- **Disable:** delete the file (or comment out the `workflow_run` trigger).
- **Customize bundle contents:** edit the "Assemble release bundle" step in `release-recon.yml`.
- **Zenodo integration:** sign in at https://zenodo.org/account/settings/github/, toggle the switch next to your repo. Each new release gets a citable DOI automatically.

### `update-readme.yml` (enabled by default)

Regenerates `README.md` after each successful reconstruction. The generated block (between `<!-- BEGIN GENERATED -->` markers) is rewritten; everything above is preserved.

- **Edit the templater:** `scripts/generate_readme.py` — pure Python, no Jinja, easy to extend.
- **Add narrative that survives:** put it in `README_NOTES.md` (prepended verbatim every run).

### Large NetCDF output (>2 GB)

GitHub Releases cap individual assets at 2 GB. If your reconstruction emits a NetCDF that exceeds this:

- Use `ncks` to split along the record dim into `*.part<i>of<N>.nc` pieces (see `presto-holocene_da/.github/workflows/release-recon.yml` for the split logic).
- Add a `merge-recon-netcdf.yml` workflow (copy from `presto-holocene_da/.github/workflows/merge-recon-netcdf.yml`) that users dispatch to reassemble via `ncrcat`.

## 6. Going live with PReSto

1. **Enable Pages** (one-time): Settings → Pages → Source = "GitHub Actions".
2. **Set the About URL** (one-time, optional): use the ⚙ next to "About" on the repo home page to paste your Pages URL. The PReSto webhook handler does this automatically for PReSto-orchestrated forks (it has the admin scope the workflow `GITHUB_TOKEN` lacks).
3. **Mark as a GitHub template** (recommended): Settings → "Template repository" checkbox. Lets others click "Use this template" on your repo home page.
4. **Tell the PReSto team** to wire your template into the platform UI. They'll need: the repo URL, the path to `config/user_config.yml`, the schema of your config (so they can render form inputs), and whether your output is spatial.

## Conventions baked in

Everything below is wired correctly out of the box — you should never need to touch these unless you're tearing apart the scaffold:

- **Artifact names** — `reconstruction-proxy-data-<run_id>` (7 d retention) and `reconstruction-<run_id>` (90 d). `visualize.yml`, `release-recon.yml`, and `update-readme.yml` all find them by these exact names.
- **Mount points** — `/proxies/lipd_legacy.pkl` (RO), `/app/config/user_config.yml` (RO), `/results` (RW), `/app/reference_data` (RO baked into image).
- **Workflow names** — `name: Reconstruction` is referenced literally by `visualize.yml`, `release-recon.yml`, and `update-readme.yml`'s `workflow_run` triggers. Rename in all four files if you must change it.
- **Line endings** — `.gitattributes` forces LF on every executable / script / yml file. Don't disable on Windows.
- **Citation merging** — the lipdGenerator container merges data citations into your `CITATION.cff` via `--merge-cff`. Keep platform-level citations at the top.

## Reference templates

When stuck, read these for patterns that work:

- **[`DaveEdge1/presto-holocene_da`](https://github.com/DaveEdge1/presto-holocene_da)** — gridded NetCDF output, presto-viz visualization, pre-built `davidedge/lipd_webapps:holocene_da` base image.
- **[`DaveEdge1/LMR2`](https://github.com/DaveEdge1/LMR2)** — gridded output, conda env from `environment.yml`, presto-viz visualization with custom validation step.
- **[`DaveEdge1/presto-BayGMST`](https://github.com/DaveEdge1/presto-BayGMST)** — 1D output, R/Stan stack (custom Dockerfile), static-Pages visualization.

When you hit a problem that one of these has solved, port their solution.
