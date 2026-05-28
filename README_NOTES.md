# PReSto — GraphEM gridded climate-field reconstruction

> This file is **prepended verbatim** to the auto-generated `README.md`
> by `update-readme.yml`. Everything below the `<!-- BEGIN GENERATED -->`
> marker in `README.md` is rebuilt from `config/user_config.yml` +
> `query_params.json` after each successful run.

**Method:** GraphEM (Graphical Expectation-Maximization)
**Method paper:** Guillot, Rajaratnam & Emile-Geay (2015), *The Annals of
Applied Statistics* — [doi:10.1214/14-AOAS794](https://doi.org/10.1214/14-AOAS794)
**Implementation:** [`cfr`](https://fzhu2e.github.io/cfr/) + `cfr-graphem`
(`ReconJob.run_graphem_cfg`)

## What this reconstruction does

GraphEM reconstructs a **gridded climate field** (e.g. surface temperature)
back in time by combining an instrumental observation field with proxy
records. It models the joint field+proxy covariance as a Gaussian Markov
random field, learns the graph (which grid cells and proxies are
conditionally dependent) and fills in the pre-instrumental field with an
EM algorithm. Unlike data-assimilation methods, GraphEM uses no climate-model
prior — the spatial covariance is estimated directly from the calibration
period.

The default configuration reproduces the tropical-Pacific coral SST
reconstruction from cfr's GraphEM tutorial: coral proxies are calibrated
against the GISTEMP (GHCNv4 + ERSSTv5) instrumental field over a tropical
Pacific box, with a hybrid neighborhood→GLASSO graph. Output is a gridded
`(time, lat, lon)` NetCDF plus global / hemispheric / Niño-3.4 index series,
visualized through the interactive presto-viz map.

See [`ADAPTING.md`](ADAPTING.md) for the template scaffolding this is built on.
