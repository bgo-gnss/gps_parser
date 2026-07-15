"""Deployed per-station outlier catalogs — the SINGLE resolver both consumers call.

``geo_dataread`` (the internal ``_cleaned.NEU`` path) and ``gps_api.precompute``
(the store's cleaned series) must clean the same station identically. Before
this module each owned its own catalog readers with a different path resolution,
so the two could silently diverge (see
``gps_parser/docs/DESIGN_shared_outlier_config.md``). This module is the one
resolution + one reader + one schema they both delegate to — hosted in the
config tier that already owns ``postprocess.cfg`` ``[FILES]`` resolution, so a
divergent resolution is structurally impossible.

Three deployed catalogs, all optional enhancements (absent ⇒ empty mapping):

- ``steps.csv``            — known offsets the trajectory model must absorb
- ``protect_windows.csv``  — active-unrest intervals excluded from flagging
- ``outlier_overrides.csv``— per-station detection levers + magnitude floors

Stdlib only (``csv`` + ``math`` + the existing :class:`gps_parser.ConfigParser`):
this package stays dependency-free. Readers return PLAIN data — callers map to
``gps_analysis.OutlierParams`` themselves (as both already do), keeping
gps_parser decoupled from the analysis leaf.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import ConfigParser

__all__ = [
    "STEPS_FILENAME",
    "PROTECT_WINDOWS_FILENAME",
    "OUTLIER_OVERRIDES_FILENAME",
    "STEP_COMPONENTS",
    "OUTLIER_OVERRIDE_COLUMNS",
    "StepRecord",
    "StationOutlierOverride",
    "catalog_path",
    "read_steps",
    "read_protect_windows",
    "read_outlier_overrides",
]

STEPS_FILENAME = "steps.csv"
PROTECT_WINDOWS_FILENAME = "protect_windows.csv"
OUTLIER_OVERRIDES_FILENAME = "outlier_overrides.csv"

#: Component tags a ``steps.csv`` row may carry (``ALL`` = every component).
STEP_COMPONENTS = ("N", "E", "U", "ALL")

_OVERRIDE_WINDOW_ORDERS = (0, 1, 2)
_OVERRIDE_EPOCH_POLICIES = ("per_component", "union")
_TRUE_TOKENS = ("1", "true", "yes", "y", "t")
_FALSE_TOKENS = ("0", "false", "no", "n", "f")

#: Recognised ``outlier_overrides.csv`` columns (any other column is rejected).
OUTLIER_OVERRIDE_COLUMNS = (
    "sta",
    "despike",
    "window_order",
    "window_robust_iterations",
    "epoch_policy",
    "despike_n_sigma",
    "min_outlier_n",
    "min_outlier_e",
    "min_outlier_u",
    "comment",
)


@dataclass(frozen=True)
class StepRecord:
    """One known step of one station (a ``steps.csv`` row).

    The canonical per-component record. ``gps_api`` consumes it directly
    (per-component step lists via :meth:`applies_to`); ``geo_dataread``
    flattens the per-station epochs to a de-duplicated union.
    """

    marker: str
    epoch_yearf: float
    component: str
    kind: str = ""
    source: str = ""
    comment: str = ""

    def applies_to(self, component_name: str) -> bool:
        """Whether this step affects ``component_name`` (north/east/up)."""
        return self.component == "ALL" or self.component == component_name[0].upper()


@dataclass(frozen=True)
class StationOutlierOverride:
    """One station's parsed ``outlier_overrides.csv`` row.

    Splits the two kinds of override the catalog carries:

    - ``fields`` — :class:`gps_analysis.OutlierParams` field values
      (``despike``, ``window_order``, …), ready for the caller's
      ``dataclasses.replace``;
    - ``min_outlier`` — the PER-COMPONENT magnitude floor ``[N, E, U]`` routed
      to the ``detect_outliers`` ``min_outlier`` kwarg (a separate array from
      the scalar ``OutlierParams.min_outlier``), or None when all three blank.
    """

    fields: dict[str, object]
    min_outlier: tuple[float, float, float] | None


def catalog_path(
    files_key: str, default_name: str, *, config: ConfigParser | None = None
) -> Path | None:
    """Resolve a deployed catalog path — the ONE resolution both consumers use.

    Resolution order:

    1. ``postprocess.cfg`` ``[FILES] <files_key>`` (resolved by
       :meth:`gps_parser.ConfigParser.getPostProcessConfig`, joined to the
       gpsconfig dir);
    2. ``<gpsconfig dir>/<default_name>`` (the deploy-target default).

    Args:
        files_key: The ``[FILES]`` option name (e.g. ``"steps"``).
        default_name: The fallback filename (e.g. ``"steps.csv"``).
        config: A ready :class:`ConfigParser`; None constructs the deployed one.

    Returns:
        The resolved path (which may not exist yet — every catalog is an
        optional enhancement), or None when no gpsconfig is reachable.
    """
    try:
        cfg = config if config is not None else ConfigParser()
    except Exception:  # pragma: no cover - no gpsconfig deployed at all
        return None
    try:
        return Path(str(cfg.getPostProcessConfig(files_key)))
    except Exception:
        # additive [FILES] key not deployed yet - fall back to the gpsconfig dir
        config_path = getattr(cfg, "config_path", None)
        if config_path:
            return Path(str(config_path)) / default_name
        return None


def _catalog_lines(resolved: Path | None, filename: str, label: str) -> list[str]:
    """Resolve-guard + read the non-comment, non-blank lines of a catalog."""
    if resolved is None:
        raise FileNotFoundError(f"no gpsconfig available to resolve {filename}")
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return [
        line
        for line in resolved.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def read_steps(
    path: str | Path | None = None, *, config: ConfigParser | None = None
) -> dict[str, tuple[StepRecord, ...]]:
    """Read the deployed per-station step catalog (``steps.csv``).

    Format: ``sta,epoch_yearf,component,kind,source,comment`` with ``#`` comment
    lines and ``component`` in ``N|E|U|ALL``.

    Args:
        path: Explicit catalog path; None resolves via :func:`catalog_path`.
        config: A ready :class:`ConfigParser` for the None-path resolution.

    Returns:
        ``{station: (StepRecord, ...)}`` — per-station records sorted by epoch
        (only stations with rows appear).

    Raises:
        FileNotFoundError: When the catalog (or a gpsconfig to resolve it from)
            does not exist.
        ValueError: On a malformed row (missing marker, unknown component tag,
            non-numeric epoch) — a corrupt catalog is rejected, never silently
            dropped.
    """
    resolved = (
        Path(path)
        if path is not None
        else catalog_path("steps", STEPS_FILENAME, config=config)
    )
    lines = _catalog_lines(resolved, STEPS_FILENAME, "step catalog")
    catalog: dict[str, list[StepRecord]] = {}
    for row in csv.DictReader(lines):
        marker = str(row.get("sta") or "").strip()
        if not marker:
            raise ValueError(f"{resolved}: steps.csv row without a 'sta' marker: {row}")
        component = str(row.get("component") or "ALL").strip().upper()
        if component not in STEP_COMPONENTS:
            raise ValueError(
                f"{resolved}: station {marker}: component {component!r} — "
                f"must be one of {STEP_COMPONENTS}"
            )
        try:
            epoch = float(str(row.get("epoch_yearf")))
        except (TypeError, ValueError):
            raise ValueError(
                f"{resolved}: station {marker}: epoch_yearf "
                f"{row.get('epoch_yearf')!r} is not a fractional year"
            ) from None
        catalog.setdefault(marker, []).append(
            StepRecord(
                marker=marker,
                epoch_yearf=epoch,
                component=component,
                kind=str(row.get("kind") or "").strip(),
                source=str(row.get("source") or "").strip(),
                comment=str(row.get("comment") or "").strip(),
            )
        )
    return {
        marker: tuple(sorted(records, key=lambda r: r.epoch_yearf))
        for marker, records in catalog.items()
    }


def read_protect_windows(
    path: str | Path | None = None, *, config: ConfigParser | None = None
) -> dict[str, tuple[tuple[float, float], ...]]:
    """Read the deployed per-station protect-window catalog.

    Format: ``sta,start_yearf,end_yearf,comment`` with ``#`` comment lines.
    Protect windows are the active-unrest cleaning lever — intervals the
    operator marks as real signal so detection excludes them.

    Args:
        path: Explicit catalog path; None resolves via :func:`catalog_path`.
        config: A ready :class:`ConfigParser` for the None-path resolution.

    Returns:
        ``{station: ((start, end), ...)}`` — closed fractional-year intervals
        sorted by start (only stations with rows appear).

    Raises:
        FileNotFoundError: When the catalog (or a gpsconfig to resolve it from)
            does not exist.
        ValueError: On a malformed row (missing marker, non-numeric bound, or
            ``end < start``).
    """
    resolved = (
        Path(path)
        if path is not None
        else catalog_path(
            "protect_windows", PROTECT_WINDOWS_FILENAME, config=config
        )
    )
    lines = _catalog_lines(resolved, PROTECT_WINDOWS_FILENAME, "protect-window catalog")
    catalog: dict[str, list[tuple[float, float]]] = {}
    for row in csv.DictReader(lines):
        marker = str(row.get("sta") or "").strip()
        if not marker:
            raise ValueError(
                f"{resolved}: protect_windows.csv row without a 'sta' marker: {row}"
            )
        try:
            start = float(str(row.get("start_yearf")))
            end = float(str(row.get("end_yearf")))
        except (TypeError, ValueError):
            raise ValueError(
                f"{resolved}: station {marker}: start_yearf/end_yearf "
                f"{row.get('start_yearf')!r}/{row.get('end_yearf')!r} "
                "are not fractional years"
            ) from None
        if end < start:
            raise ValueError(
                f"{resolved}: station {marker}: protect window end {end} < "
                f"start {start} — an interval must be (start, end) with "
                "end >= start"
            )
        catalog.setdefault(marker, []).append((start, end))
    return {marker: tuple(sorted(windows)) for marker, windows in catalog.items()}


def _parse_override_bool(marker: str, field: str, raw: str) -> bool:
    token = raw.strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    raise ValueError(
        f"station {marker}: {field} {raw!r} is not boolean "
        f"(use one of {_TRUE_TOKENS + _FALSE_TOKENS})"
    )


def _parse_override_row(
    resolved: Path, marker: str, row: Mapping[str, object]
) -> StationOutlierOverride:
    """Parse ONE ``outlier_overrides.csv`` row into a StationOutlierOverride.

    Only columns the operator actually filled contribute (blank = leave at the
    base default). Splits the OutlierParams field overrides from the
    per-component ``min_outlier`` floor.
    """
    overrides: dict[str, object] = {}

    despike = str(row.get("despike") or "").strip()
    if despike:
        overrides["despike"] = _parse_override_bool(marker, "despike", despike)

    window_order = str(row.get("window_order") or "").strip()
    if window_order:
        try:
            value = int(window_order)
        except ValueError:
            raise ValueError(
                f"station {marker}: window_order {window_order!r} is not an integer"
            ) from None
        if value not in _OVERRIDE_WINDOW_ORDERS:
            raise ValueError(
                f"station {marker}: window_order {value} — "
                f"must be one of {_OVERRIDE_WINDOW_ORDERS}"
            )
        overrides["window_order"] = value

    window_iters = str(row.get("window_robust_iterations") or "").strip()
    if window_iters:
        try:
            value = int(window_iters)
        except ValueError:
            raise ValueError(
                f"station {marker}: window_robust_iterations {window_iters!r} "
                "is not an integer"
            ) from None
        if value < 0:
            raise ValueError(
                f"station {marker}: window_robust_iterations {value} must be >= 0"
            )
        overrides["window_robust_iterations"] = value

    epoch_policy = str(row.get("epoch_policy") or "").strip()
    if epoch_policy:
        if epoch_policy not in _OVERRIDE_EPOCH_POLICIES:
            raise ValueError(
                f"station {marker}: epoch_policy {epoch_policy!r} — "
                f"must be one of {_OVERRIDE_EPOCH_POLICIES}"
            )
        overrides["epoch_policy"] = epoch_policy

    despike_n_sigma = str(row.get("despike_n_sigma") or "").strip()
    if despike_n_sigma:
        try:
            overrides["despike_n_sigma"] = float(despike_n_sigma)
        except ValueError:
            raise ValueError(
                f"station {marker}: despike_n_sigma {despike_n_sigma!r} is not a number"
            ) from None

    # min_outlier_{n,e,u} → the PER-COMPONENT magnitude floor [N,E,U] routed to
    # the detect_outliers ``min_outlier`` kwarg (a separate array, NOT the
    # scalar OutlierParams.min_outlier). Active stations want e.g. N/E=5, U=10
    # (U is ~2-3x noisier). Partial: any component left blank fills 0.0 (no
    # floor there); all blank → None (leaf falls back to params.min_outlier).
    raw_floors = [
        str(row.get(f"min_outlier_{c}") or "").strip() for c in ("n", "e", "u")
    ]
    if any(raw_floors):
        floor: list[float] = []
        for comp, raw in zip(("n", "e", "u"), raw_floors, strict=True):
            if not raw:
                floor.append(0.0)
                continue
            try:
                floor_value = float(raw)
            except ValueError:
                raise ValueError(
                    f"station {marker}: min_outlier_{comp} {raw!r} is not a number"
                ) from None
            if floor_value < 0.0 or not math.isfinite(floor_value):
                raise ValueError(
                    f"station {marker}: min_outlier_{comp} {floor_value} must be "
                    "finite and >= 0"
                )
            floor.append(floor_value)
        min_outlier: tuple[float, float, float] | None = (floor[0], floor[1], floor[2])
    else:
        min_outlier = None

    return StationOutlierOverride(fields=overrides, min_outlier=min_outlier)


def read_outlier_overrides(
    path: str | Path | None = None, *, config: ConfigParser | None = None
) -> dict[str, StationOutlierOverride]:
    """Read the deployed per-station outlier-parameter override catalog.

    Columns (all except ``sta`` optional; blank = leave at the base default; a
    ``comment`` column is allowed and ignored)::

        sta,despike,window_order,window_robust_iterations,epoch_policy,
        despike_n_sigma,min_outlier_n,min_outlier_e,min_outlier_u

    Args:
        path: Explicit catalog path; None resolves via :func:`catalog_path`.
        config: A ready :class:`ConfigParser` for the None-path resolution.

    Returns:
        ``{station: StationOutlierOverride}`` — the supplied OutlierParams field
        overrides plus the per-component ``min_outlier`` floor (only stations
        with rows appear).

    Raises:
        FileNotFoundError: When the catalog (or a gpsconfig to resolve it from)
            does not exist.
        ValueError: On an unknown column, a duplicate station row, a missing
            marker, a bad enum, or a non-numeric / negative field.
    """
    resolved = (
        Path(path)
        if path is not None
        else catalog_path(
            "outlier_overrides", OUTLIER_OVERRIDES_FILENAME, config=config
        )
    )
    lines = _catalog_lines(
        resolved, OUTLIER_OVERRIDES_FILENAME, "outlier-override catalog"
    )
    reader = csv.DictReader(lines)
    fieldnames = reader.fieldnames or []
    unknown = [c for c in fieldnames if c not in OUTLIER_OVERRIDE_COLUMNS]
    if unknown:
        raise ValueError(
            f"{resolved}: unknown column(s) {unknown!r}; recognised columns "
            f"are {OUTLIER_OVERRIDE_COLUMNS}"
        )
    catalog: dict[str, StationOutlierOverride] = {}
    for row in reader:
        marker = str(row.get("sta") or "").strip()
        if not marker:
            raise ValueError(
                f"{resolved}: outlier_overrides.csv row without a 'sta' marker: {row}"
            )
        if marker in catalog:
            raise ValueError(
                f"{resolved}: duplicate row for station {marker} — one override "
                "row per station"
            )
        try:
            catalog[marker] = _parse_override_row(resolved, marker, row)
        except ValueError as exc:
            raise ValueError(f"{resolved}: {exc}") from None
    return catalog
