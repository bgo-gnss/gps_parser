# DESIGN — single authoritative outlier-config source

**Status:** ✅ IMPLEMENTED (2026-07-15) · **Owner:** BGÓ · **Scope:** gps_parser
(new resolver) + geo_dataread + gps_api (both callers)

> **Landed:** gps_parser `outlier_catalogs` resolver (13 tests, py floor→3.13);
> gps_api floor-collapse fix + steps/overrides/protect_windows routed to the
> resolver, yaml per-station authority dropped (deprecated+warned), cross-repo
> parity test; geo_dataread all three readers shimmed to the resolver + migrated
> to gps_parser 0.4.x (golden fixtures config-dir-relative, **values unchanged**).
> Suites green: gps_api 140, geo_dataread 155, gps_parser resolver 13. CSV
> templates added under `config-templates/analysis-lane/`. **Deploy step still
> pending:** push gps_parser 0.4.x + bump the git deps (both repos use local
> `[tool.uv.sources]` overrides today; CI/prod pull git HEAD).

Resolves toolkit follow-on #2 ("single config source"). Decision taken
2026-07-14: the shared resolver lives in **gps_parser** — the config tier that
already owns `[FILES]`/`postprocess.cfg` resolution and is a declared dep of
both consumers, so a divergent resolution is structurally impossible.

---

## 1. Problem — the divergence surface

Two packages independently clean the same series and must agree, but resolve
per-station outlier config from different files, with different readers, and
different field coverage:

| Aspect | geo_dataread (`_cleaned.NEU`) | gps_api (store) |
|---|---|---|
| Per-station levers | `outlier_overrides.csv` (5 levers) | `analysis.yaml` `outliers.overrides` (20 keys) |
| **Floors** | **`min_outlier_n/e/u` — independent N/E/U** | **`min_outlier_{horizontal,vertical}` — N=E collapsed** → emits `(H,H,V)` |
| protect_windows | `protect_windows.csv` | `analysis.yaml` `outliers.protect_windows` |
| steps | `steps.csv` via **`[FILES] steps` → fallback** | `steps.csv` via **`config_dir/steps.csv` direct** |
| Reader | geo_dataread's own functions | gps_api's own functions |
| Location | deployed gpsconfig (gps_parser) | `analysis.yaml` |

**Three concrete bugs, not one:**

1. **Floor collapse** — the moment any station sets N≠E, gps_api's `(H,H,V)`
   silently produces a different mask than geo_dataread's `[N,E,U]`. Latent
   correctness bug, independent of architecture.
2. **Two resolutions** — even `steps.csv` is "shared" only by coincidence of
   geo_dataread's fallback. Set `[FILES] steps = <other>` in postprocess.cfg
   and geo_dataread follows it, gps_api does not. Same bug class, latent.
3. **Two override files** — `outlier_overrides.csv` vs `analysis.yaml`
   overrides; nothing forces them equal.

**Production reality (2026-07-14):** no `steps.csv` / `protect_windows.csv` /
`outlier_overrides.csv` is deployed yet (only legacy `detrend_itrf2008.csv`).
The divergence is **preventive** — this is the free moment to unify, before
operators populate two competing schemas.

---

## 2. Decision (settled)

- **Authority split (non-overlapping → no divergence):**
  - **Per-station** levers + floors + protect_windows + steps → **deployed CSV
    catalogs**, owned by the gps_parser resolver.
  - **Global / region defaults** → each caller's own base: `analysis.yaml`
    `outliers:` block for gps_api; `gps_analysis.OutlierParams` defaults for
    geo_dataread. gps_parser does **not** read yaml.
    - ⚠️ **Known boundary (globals are two-sourced):** because geo_dataread
      cannot read gps_api's `analysis.yaml`, the two sides' GLOBAL thresholds
      agree **only while the yaml globals are left at the `OutlierParams`
      defaults**. Set a non-default global (e.g. `window_n_sigma: 3.5`) in
      `analysis.yaml` and the store mask diverges from the `_cleaned.NEU` mask
      on that threshold — an operator tuning a *global* must change both sides.
      Only the **per-station** config (levers, N/E/U floors, protect_windows,
      steps) is truly single-sourced. Pinned by
      `gps_api/tests/test_outlier_config_parity.py::test_nondefault_global_is_a_known_divergence`.
      (Closing this fully would mean geo_dataread also reading the deployed
      globals — a future slice, not this one.)
- **One resolver, one resolution, one reader** in gps_parser. Both consumers
  call it and apply the per-station override on top of their own base.
- **Floors unify UP to independent N/E/U** (superset). gps_api's yaml keeps the
  simple `{horizontal, vertical}` GLOBAL default; per-station N/E/U from the CSV
  overrides it.
- **Keep the CSV narrow** — the ~5–8 genuinely per-station levers + floors, not
  20 columns for thresholds nobody sets per station. Rare threshold keys stay in
  the caller's global base.

---

## 3. Resolver API (new — `gps_parser.outlier_catalogs`)

Dependency-free (stdlib `csv` + the existing `ConfigParser`); returns plain
data (no `gps_analysis` import — keeps gps_parser decoupled; each caller maps to
`OutlierParams` itself, as both already do).

```python
# gps_parser/src/gps_parser/outlier_catalogs.py
@dataclass(frozen=True)
class StationOutlierOverride:
    fields: dict[str, object]                 # OutlierParams keys the CSV sets
    min_outlier: tuple[float, float, float] | None   # [N,E,U] floor, or None
    source: str | None

@dataclass(frozen=True)
class OutlierCatalogs:
    steps: dict[str, tuple[StepEntry, ...]]           # per-station step epochs (+component)
    protect_windows: dict[str, tuple[tuple[float, float], ...]]
    overrides: dict[str, StationOutlierOverride]

def resolve_outlier_catalogs(config: ConfigParser | None = None) -> OutlierCatalogs:
    """Read all three deployed catalogs through ONE resolution.
    Each catalog path: [FILES] <name> if present, else <config_dir>/<name>.csv.
    Missing catalog → empty mapping (all three are optional enhancements)."""

def station_override(cat: OutlierCatalogs, sta: str) -> StationOutlierOverride: ...
```

Single path resolver (the crux — one function, used for all three catalogs and
by both consumers):

```python
def _catalog_path(config, files_key: str, default_name: str) -> Path | None:
    try:    return Path(config.getPostProcessConfig(files_key))   # [FILES] first
    except Exception:
        cp = getattr(config, "config_path", None)
        return Path(cp) / default_name if cp else None            # fallback
```

Column/enum gates (`_OVERRIDE_COLUMNS`, `window_order ∈ {0,1,2}`,
`epoch_policy ∈ {per_component, union}`, floor ≥ 0, reject unknown columns) move
verbatim from geo_dataread — one validation site.

---

## 4. Migration

### geo_dataread (thin-shim; keep public names)
- `read_step_catalog`, `default_steps_path`, `read_protect_windows`,
  `station_protect_windows`, `default_protect_windows_path`,
  `read_outlier_overrides`, `default_outlier_overrides_path` →
  delegate to `gps_parser.outlier_catalogs` (re-export or thin wrapper so
  existing call sites and tests keep working).
- `resolve_outlier_detection(sta, base=…)` stays in geo_dataread: base =
  `OutlierParams()` defaults, then apply `station_override(...).fields` +
  `.min_outlier`. Behavior byte-identical when no catalogs deployed.

### gps_api (`precompute/`)
- `load_step_catalog(config_dir)` → call the shared resolver (via a
  `ConfigParser` bound to `config_dir`); delete the duplicate reader.
- `OutlierConfig`: **drop** `overrides` and `protect_windows` from yaml
  authority; the job merges yaml globals → `station_override` (CSV) →
  `OutlierParams`. `min_outlier_{horizontal,vertical}` stay as the **global**
  floor default; `station_outlier_params` returns the CSV `[N,E,U]` when the
  station has one, else `(H,H,V)`.
- **Floor fix:** `station_outlier_params` no longer hardcodes `(H,H,V)`.

### Removed
- geo_dataread's private CSV parsing bodies (moved, not deleted-in-behavior).
- gps_api yaml `outliers.overrides` / `outliers.protect_windows` authority
  (keys may remain as deprecated no-ops for one release, warned).

---

## 5. Back-compat, risks, test plan

- **Zero-regression default:** no deployed catalogs ⇒ both paths reproduce
  current masks exactly (empty override → `OutlierParams()` defaults / yaml
  globals). Pin this.
- **gps_parser Python floor:** package classifiers list 3.8+. Keep the new
  module 3.8-safe **or** bump the floor (ecosystem is ≥3.13; confirm with BGÓ).
- **Golden masters:** run `geo_dataread/tests/goldenmaster/` before+after — the
  shim must not perturb `getData`/`gamittoNEU`.
- **Re-run BOTH suites** (the lane's burn lesson — a leaf/config change once
  broke a gps_api test that wasn't re-run): `geo_dataread` + `gps_api` +
  `gps_parser` full `pytest`, plus `test_outliers_wiring.py` /
  `test_cleaned_neu.py` (override precedence, `.DEGRADED` naming, declared-step
  behavior) explicitly.
- **New parity test:** one fixture catalog, assert geo_dataread's
  `resolve_outlier_detection` and gps_api's `station_outlier_params` produce the
  **same `OutlierParams` + `[N,E,U]` floor** for the same station — the forcing
  function that was missing.
- **Dep edges:** gps_parser gains no deps. gps_api.precompute already deps
  gps_parser; geo_dataread already deps gps_parser. No new edges.

## 6. Rollout order

1. gps_parser: add `outlier_catalogs`, port validation, unit-test in isolation.
2. gps_api: floor-collapse fix alone (independent bug) → green.
3. geo_dataread: shim readers → gps_parser; golden masters green.
4. gps_api: `load_step_catalog` + `OutlierConfig` authority → resolver.
5. Cross-repo parity test; both suites green; update the three `analysis.yaml` /
   template comments claiming "field parity".
```
