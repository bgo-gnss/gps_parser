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

- ``steps.yaml``            — known offsets the trajectory model must absorb
                             (the durable DECLARATION; ``detrend_params.json``
                             is the regenerated estimate and never a source)
- ``protect_windows.csv``  — active-unrest intervals excluded from flagging
- ``outlier_overrides.csv``— per-station detection levers + magnitude floors

``steps.yaml`` superseded ``steps.csv`` (2026-08-24): a declaration carries
structured metadata — ``kind`` (earthquake/equipment/icing/manual/other), ISO
``date``, ``event_id``, ``magnitude``, ``devices`` — that a flat CSV kept
cramming into ``comment``. The CSV is still read as a fallback so a config
tree deployed ahead of its package upgrade keeps working; the merge writer
(:func:`merge_station_steps`) migrates it in place. Dependencies are
``gtimes`` (the one canonical date↔fractional-year convention — the noon trap)
and ``pyyaml``; nothing heavier. Readers return PLAIN data — callers map to
``gps_analysis.OutlierParams`` themselves (as both already do), keeping
gps_parser decoupled from the analysis leaf.
"""

from __future__ import annotations

import csv
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from . import ConfigParser

__all__ = [
    "STEPS_FILENAME",
    "STEPS_CSV_FILENAME",
    "PROTECT_WINDOWS_FILENAME",
    "OUTLIER_OVERRIDES_FILENAME",
    "EXCLUDED_EPOCHS_FILENAME",
    "STEP_COMPONENTS",
    "STEP_KINDS",
    "STEP_SOURCES",
    "SEISMIC_KINDS",
    "STEPS_SCHEMA_VERSION",
    "STEPS_YAML_HEADER",
    "OUTLIER_OVERRIDE_COLUMNS",
    "StepRecord",
    "StationOutlierOverride",
    "catalog_path",
    "resolve_steps_path",
    "read_steps",
    "read_protect_windows",
    "read_outlier_overrides",
    "read_excluded_epochs",
    "match_declared_epochs",
    "write_steps_yaml",
    "merge_station_steps",
    "convert_steps_csv",
]

STEPS_FILENAME = "steps.yaml"
STEPS_CSV_FILENAME = "steps.csv"
PROTECT_WINDOWS_FILENAME = "protect_windows.csv"
OUTLIER_OVERRIDES_FILENAME = "outlier_overrides.csv"
EXCLUDED_EPOCHS_FILENAME = "excluded_epochs.csv"

#: Component tags a ``steps.yaml`` entry may carry (``ALL`` = every component).
STEP_COMPONENTS = ("N", "E", "U", "ALL")

#: What KIND of physical event a declared step is.  Controlled vocabulary:
#: the workbench colours event lines by it (seismic dark red, equipment dark
#: green) and future harvesters key on it.  ``other`` keeps the set closed
#: without lying about a cause we cannot name.
STEP_KINDS = ("earthquake", "equipment", "icing", "manual", "other")

#: Where a declaration's KNOWLEDGE came from (not who wrote the file —
#: ``workbench`` writes rows a human curated in the picker).
STEP_SOURCES = ("tos", "skjalftalisa", "manual", "workbench")

#: ``kind`` values treated as seismic (drawn dark-red, classified coseismic).
#: ``earthquake`` is the only one in the yaml vocabulary; the extra two cover
#: legacy spellings the csv fallback can still carry.
SEISMIC_KINDS = ("earthquake", "coseismic", "seismic")

#: ``schema_version`` of the ``steps.yaml`` document this module reads/writes.
STEPS_SCHEMA_VERSION = 1

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
    "min_abort_candidates",
    "whiten_sigma_clip",
    "min_outlier_n",
    "min_outlier_e",
    "min_outlier_u",
    "comment",
)


@dataclass(frozen=True)
class StepRecord:
    """One known step of one station (a ``steps.yaml`` entry).

    The canonical per-component record. ``gps_api`` consumes it directly
    (per-component step lists via :meth:`applies_to`); ``geo_dataread``
    flattens the per-station epochs to a de-duplicated union.

    The structured fields (``date``, ``event_id``, ``magnitude``, ``devices``)
    are DECLARATION metadata — what a human or a harvester knows about the
    event.  Estimated amplitudes deliberately live nowhere here: they are the
    estimate's job (``detrend_params.json`` ``step_amp_k``), and the old CSV's
    habit of typing them into ``comment`` duplicated numbers the fit owns.
    """

    marker: str
    epoch_yearf: float
    component: str
    kind: str = ""
    source: str = ""
    comment: str = ""
    #: ISO ``yyyy-mm-dd`` of the event — display + validation against
    #: ``epoch_yearf`` (the noon convention), never parsed for the model.
    date: str = ""
    #: skjálftalísa event id / TOS entity id / "" — the join key a future
    #: harvester deduplicates against.
    event_id: str = ""
    #: Earthquake magnitude (any scale; the ``comment`` names it if ambiguous).
    magnitude: float | None = None
    #: Equipment involved, e.g. ``("TRM29659.00", "TRIMBLE NETRS")`` — the
    #: TOS ``DeviceInfo`` a workbench declaration can carry verbatim.
    devices: tuple[str, ...] = ()

    def applies_to(self, component_name: str) -> bool:
        """Whether this step affects ``component_name`` (north/east/up)."""
        return self.component == "ALL" or self.component == component_name[0].upper()

    @property
    def is_seismic(self) -> bool:
        """Whether this step is a coseismic/earthquake event.

        The single classification both plotting paths (workbench event lines
        and ``plot-gps-timeseries --annotate-steps``) split on — a second
        copy would let a step change colour between tools.
        """
        return (self.kind or "").strip().lower() in SEISMIC_KINDS

    @property
    def label(self) -> str:
        """Human annotation text: ``"kind: comment"`` (comment truncated).

        The ONE place the step label is spelled — the workbench and the plot
        driver both draw it, so it must be assembled once.
        """
        kind = (self.kind or "").strip() or "step"
        note = (self.comment or "").strip()
        return f"{kind}: {note[:40]}" if note else kind


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


def _yearf_of_date(iso: str) -> float:
    """Fractional year (NOON convention) of an ISO ``yyyy-mm-dd`` string.

    The one convention, from the one place that owns it — ``gtimes``.  The
    noon trap (2008-05-29 -> 149.5/366 = 2008.40847, not 149/366) is why the
    derivation is not inlined here.
    """
    from gtimes.timefunc import TimetoYearf  # type: ignore[import-untyped]

    parsed = _date.fromisoformat(iso)
    return TimetoYearf(parsed.year, parsed.month, parsed.day)


#: Tolerance for ``date`` vs ``epoch_yearf`` agreement [yr] — ~9 h.  Typed
#: 4-decimal epochs land ~2e-5 away from the derived value; a wrong DATE is
#: off by >= 1/366 ~ 2.7e-3, an order of magnitude past this.
_DATE_EPOCH_TOLERANCE = 1e-3


def _parse_step_entry(
    resolved: Path, marker: str, entry: Mapping[str, object], *, index: int
) -> StepRecord:
    """Validate ONE ``steps.yaml`` entry — reject, never silently drop."""
    where = f"{resolved}: station {marker}: step #{index + 1}"
    if not isinstance(entry, Mapping):
        raise ValueError(f"{where}: expected a mapping, got {type(entry).__name__}")

    raw_epoch = entry.get("epoch_yearf")
    try:
        epoch = float(raw_epoch)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(
            f"{where}: epoch_yearf {raw_epoch!r} is not a fractional year"
        ) from None

    component = str(entry.get("component") or "ALL").strip().upper()
    if component not in STEP_COMPONENTS:
        raise ValueError(
            f"{where}: component {component!r} — must be one of {STEP_COMPONENTS}"
        )

    kind = str(entry.get("kind") or "").strip().lower()
    if kind not in STEP_KINDS:
        raise ValueError(
            f"{where}: kind {kind!r} — must be one of {STEP_KINDS}. "
            "kind is the point of the yaml catalog; use 'other' when the "
            "cause cannot be named"
        )

    source = str(entry.get("source") or "").strip().lower()
    if source and source not in STEP_SOURCES:
        raise ValueError(
            f"{where}: source {source!r} — must be one of {STEP_SOURCES} or blank"
        )

    iso = str(entry.get("date") or "").strip()
    if iso:
        try:
            _date.fromisoformat(iso)
        except ValueError:
            raise ValueError(f"{where}: date {iso!r} is not ISO yyyy-mm-dd") from None
        if abs(epoch - _yearf_of_date(iso)) > _DATE_EPOCH_TOLERANCE:
            raise ValueError(
                f"{where}: epoch_yearf {epoch} and date {iso} disagree "
                f"(date is {_yearf_of_date(iso):.5f} on the noon convention). "
                "A step declared at the wrong epoch misdirects the detector; "
                "fix one of the two."
            )

    magnitude: float | None = None
    raw_mag = entry.get("magnitude")
    if raw_mag is not None and str(raw_mag).strip() != "":
        try:
            magnitude = float(raw_mag)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError(
                f"{where}: magnitude {raw_mag!r} is not a number"
            ) from None
        if magnitude <= 0:
            raise ValueError(f"{where}: magnitude {magnitude} must be > 0")

    devices_raw = entry.get("devices") or ()
    if isinstance(devices_raw, str):
        devices_raw = (devices_raw,)
    if not isinstance(devices_raw, Iterable):
        raise ValueError(f"{where}: devices {devices_raw!r} is not a list")
    devices = tuple(str(d) for d in devices_raw)

    return StepRecord(
        marker=marker,
        epoch_yearf=epoch,
        component=component,
        kind=kind,
        source=source,
        comment=str(entry.get("comment") or "").strip(),
        date=iso,
        event_id=str(entry.get("event_id") or "").strip(),
        magnitude=magnitude,
        devices=devices,
    )


def resolve_steps_path(
    path: str | Path | None = None, *, config: ConfigParser | None = None
) -> Path | None:
    """The steps catalog file that ``read_steps`` would read.

    ``steps.yaml`` when it exists (the format), else the legacy
    ``steps.csv`` (the fallback), else the yaml path (the format a writer
    creates).  One resolution so readers, writers and UIs name the same file.
    """
    if path is not None:
        explicit = Path(path)
        if explicit.suffix == ".csv" or explicit.is_file():
            return explicit
        csv_path = explicit.with_name(STEPS_CSV_FILENAME)
        return csv_path if csv_path.is_file() else explicit
    yaml_path = catalog_path("steps", STEPS_FILENAME, config=config)
    if yaml_path is None:
        return None
    if yaml_path.is_file():
        return yaml_path
    csv_path = yaml_path.with_name(STEPS_CSV_FILENAME)
    return csv_path if csv_path.is_file() else yaml_path


def _read_steps_yaml(resolved: Path) -> dict[str, tuple[StepRecord, ...]]:
    import yaml

    doc = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(doc, Mapping) or "stations" not in doc:
        raise ValueError(
            f"{resolved}: expected a `stations:` mapping — this is the "
            "steps.yaml catalog, not an arbitrary yaml document"
        )
    version = doc.get("schema_version")
    if version != STEPS_SCHEMA_VERSION:
        raise ValueError(
            f"{resolved}: schema_version {version!r} — this reader is "
            f"{STEPS_SCHEMA_VERSION}. A wrong-version document is rejected "
            "outright, never best-effort parsed."
        )
    stations = doc["stations"]
    if not isinstance(stations, Mapping):
        raise ValueError(f"{resolved}: `stations:` must be a mapping")
    catalog: dict[str, list[StepRecord]] = {}
    for marker, entries in stations.items():
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise ValueError(f"{resolved}: station {marker}: expected a list of steps")
        catalog[str(marker)] = [
            _parse_step_entry(resolved, str(marker), e, index=i)
            for i, e in enumerate(entries)
        ]
    return {
        marker: tuple(sorted(records, key=lambda r: r.epoch_yearf))
        for marker, records in catalog.items()
    }


def _read_steps_csv(resolved: Path) -> dict[str, tuple[StepRecord, ...]]:
    """The legacy 6-column format — read, never written."""
    lines = _catalog_lines(resolved, STEPS_CSV_FILENAME, "step catalog")
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


def read_steps(
    path: str | Path | None = None, *, config: ConfigParser | None = None
) -> dict[str, tuple[StepRecord, ...]]:
    """Read the deployed per-station step catalog (``steps.yaml``).

    Format: the ``stations:`` mapping of per-step entries — ``epoch_yearf``
    (required, fractional year), ``kind`` (required, one of
    :data:`STEP_KINDS`), optional ``component`` (``N|E|U|ALL``, default
    ``ALL``), ``source``, ``date`` (ISO, cross-validated against
    ``epoch_yearf`` on the noon convention), ``event_id``, ``magnitude``,
    ``devices``, ``comment``.  The legacy ``steps.csv`` is still read when it
    is the only catalog deployed.

    Args:
        path: Explicit catalog path; None resolves via
            :func:`resolve_steps_path`.
        config: A ready :class:`ConfigParser` for the None-path resolution.

    Returns:
        ``{station: (StepRecord, ...)}`` — per-station records sorted by epoch
        (only stations with entries appear).

    Raises:
        FileNotFoundError: When no catalog (nor a gpsconfig to resolve it
            from) exists.
        ValueError: On a malformed entry (unknown component tag or kind,
            non-numeric epoch, date/epoch disagreement, wrong
            ``schema_version``) — a corrupt catalog is rejected, never
            silently dropped.
    """
    resolved = Path(path) if path is not None else resolve_steps_path(config=config)
    if resolved is None:
        raise FileNotFoundError("no gpsconfig available to resolve the step catalog")
    if not resolved.is_file():
        raise FileNotFoundError(f"step catalog not found: {resolved}")
    if resolved.suffix == ".csv":
        import warnings

        warnings.warn(
            f"{resolved}: legacy steps.csv — migrate to steps.yaml "
            "(gps_parser.outlier_catalogs.convert_steps_csv); the csv is "
            "read-only forever",
            UserWarning,
            stacklevel=2,
        )
        return _read_steps_csv(resolved)
    return _read_steps_yaml(resolved)


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
        else catalog_path("protect_windows", PROTECT_WINDOWS_FILENAME, config=config)
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

    # min_abort_candidates → §3.5a absolute floor on the excess-candidate
    # abort. Per station because the fraction gate is quantized at small N,
    # and how small N gets depends on that station's own gap structure
    # (GFUM over a 90-day window aborts on 4 candidates of 63 = 6.3 %).
    # whiten_sigma_clip → §13 cap on the whitening denominator. Per station
    # because how badly sigma co-inflates is a property of the site's own
    # solution quality, not a fleet constant.
    clip = str(row.get("whiten_sigma_clip") or "").strip()
    if clip:
        try:
            value_c = float(clip)
        except ValueError:
            raise ValueError(
                f"station {marker}: whiten_sigma_clip {clip!r} is not a number"
            ) from None
        if value_c < 0.0:
            raise ValueError(
                f"station {marker}: whiten_sigma_clip {value_c} must be >= 0"
            )
        overrides["whiten_sigma_clip"] = value_c

    min_abort = str(row.get("min_abort_candidates") or "").strip()
    if min_abort:
        try:
            value = int(min_abort)
        except ValueError:
            raise ValueError(
                f"station {marker}: min_abort_candidates {min_abort!r} "
                "is not an integer"
            ) from None
        if value < 0:
            raise ValueError(
                f"station {marker}: min_abort_candidates {value} must be >= 0"
            )
        overrides["min_abort_candidates"] = value

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
    assert resolved is not None  # _catalog_lines raised otherwise
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


#: Column names of the deployed ``excluded_epochs.csv`` (the manual-removal
#: catalog — operator-declared blunder epochs force-flagged as outliers).
EXCLUDED_EPOCHS_COLUMNS = ("sta", "date", "comment")


def read_excluded_epochs(
    path: str | Path | None = None, *, config: ConfigParser | None = None
) -> dict[str, tuple[float, ...]]:
    """Read the deployed per-station manual-epoch-exclusion catalog.

    The operator-declared "these specific epochs are blunders" list — the
    lever the automatic detector deliberately does not have (it errs
    conservative on ambiguous spikes-on-drift).  Each row is one epoch of one
    station; the epoch is given as an ISO date (``yyyy-mm-dd``, noon
    convention via :func:`_yearf_of_date`) and every component (N/E/U) of
    that epoch is force-flagged as an outlier.

    Format: ``sta,date,comment`` with ``#`` comment lines; multiple rows per
    station are allowed.  This is the INVERSE of ``protect_windows.csv`` (that
    file protects signal from flagging; this one forces flagging).

    Args:
        path: Explicit catalog path; None resolves via :func:`catalog_path`.
        config: A ready :class:`ConfigParser` for the None-path resolution.

    Returns:
        ``{station: (epoch, ...)}`` — per-station fractional-year epochs,
        sorted ascending (only stations with rows appear).

    Raises:
        FileNotFoundError: When the catalog (or a gpsconfig to resolve it from)
            does not exist.
        ValueError: On a malformed row (missing marker or an unparseable
            date).
    """
    resolved = (
        Path(path)
        if path is not None
        else catalog_path("excluded_epochs", EXCLUDED_EPOCHS_FILENAME, config=config)
    )
    lines = _catalog_lines(resolved, EXCLUDED_EPOCHS_FILENAME, "excluded-epoch catalog")
    catalog: dict[str, list[float]] = {}
    for row in csv.DictReader(lines):
        marker = str(row.get("sta") or "").strip()
        if not marker:
            raise ValueError(
                f"{resolved}: excluded_epochs.csv row without a 'sta' marker: {row}"
            )
        raw_date = str(row.get("date") or "").strip()
        if not raw_date:
            raise ValueError(
                f"{resolved}: station {marker}: excluded_epochs.csv row "
                "without a 'date'"
            )
        try:
            epoch = _yearf_of_date(raw_date)
        except ValueError:
            raise ValueError(
                f"{resolved}: station {marker}: date {raw_date!r} is not a "
                "valid yyyy-mm-dd date"
            ) from None
        catalog.setdefault(marker, []).append(epoch)
    return {marker: tuple(sorted(epochs)) for marker, epochs in catalog.items()}


def match_declared_epochs(
    series_yearf: Sequence[float],
    epochs: Sequence[float],
    *,
    tolerance: float = _DATE_EPOCH_TOLERANCE,
) -> tuple[int, ...]:
    """Match declared epochs to the nearest series index, within tolerance.

    Pure-Python nearest-index match (no numpy — this module stays
    config-tier, so both ``geo_dataread`` and ``gps_api`` can use it).  Each
    declared epoch maps to the series index whose ``yearf`` is closest, IF
    that gap is ``≤ tolerance`` (default ~9 h, the measured data-epoch jitter
    scale of a noon-convention daily series); farther matches are skipped so
    the caller can warn rather than flag a neighbouring day.

    Args:
        series_yearf: The series epochs, ascending [yr].
        epochs: The declared fractional-year epochs to locate.
        tolerance: Maximum allowed |series - declared| gap [yr].

    Returns:
        Sorted, de-duplicated series indices.
    """
    if len(epochs) == 0:
        return ()
    n = len(series_yearf)
    out: list[int] = []
    for e in epochs:
        best = min(range(n), key=lambda j: abs(float(series_yearf[j]) - e))
        if abs(float(series_yearf[best]) - e) <= tolerance:
            out.append(best)
    return tuple(sorted(set(out)))


# ---------------------------------------------------------------------------
# steps.yaml — the WRITE side (declaration, not estimation)
#
# detrend_params.json is regenerated from these declarations (plus the data);
# the declarations themselves are merged one station at a time by the tools a
# human curates with.  The write is READ-MODIFY-WRITE with an atomic replace,
# mirroring the record commit's discipline: a half-written declaration
# document would degrade every consumer of the catalog.
# ---------------------------------------------------------------------------

#: The comment block every written ``steps.yaml`` carries.  Regenerated on
#: each merge — per-step annotations are DATA (``comment``), never yaml
#: comments, which is what keeps the write lossless.
STEPS_YAML_HEADER = """\
# steps.yaml — known offsets/steps per station: the DURABLE DECLARATION.
#
# This file is INPUT, not output: detrend_params.json (the fitted records) is
# REGENERATED from it and the data, so a declaration survives every
# re-estimation.  Estimated amplitudes live NOWHERE here — they are the
# record's job (step_amp_k), and duplicating them here would go stale.
#
# Per step: epoch_yearf (required; fractional year, NOON convention), kind
# (required; earthquake|equipment|icing|manual|other), component (N|E|U|ALL,
# default ALL), date (ISO yyyy-mm-dd; validated against epoch_yearf), source
# (tos|skjalftalisa|manual|workbench), event_id, magnitude, devices, comment.
#
# Merge-written one station at a time (gps_parser.outlier_catalogs.
# merge_station_steps); this header is regenerated, entries are preserved.
"""


def _step_entry_dict(record: StepRecord) -> dict[str, object]:
    """Serialize a :class:`StepRecord` as a steps.yaml entry mapping.

    Validates ``kind`` here — the READ side of the yaml rejects anything
    outside :data:`STEP_KINDS`, so writing such an entry (e.g. merged from a
    legacy csv row) would produce a document the reader refuses.
    """
    if record.kind not in STEP_KINDS:
        raise ValueError(
            f"station {record.marker}: step at {record.epoch_yearf}: kind "
            f"{record.kind!r} is not in {STEP_KINDS} — name it properly "
            "before it is written (the reader would reject the document)"
        )
    entry: dict[str, object] = {
        "epoch_yearf": round(float(record.epoch_yearf), 6),
        "kind": record.kind,
    }
    if record.component != "ALL":
        entry["component"] = record.component
    if record.date:
        entry["date"] = record.date
    if record.source:
        entry["source"] = record.source
    if record.event_id:
        entry["event_id"] = record.event_id
    if record.magnitude is not None:
        entry["magnitude"] = record.magnitude
    if record.devices:
        entry["devices"] = list(record.devices)
    if record.comment:
        entry["comment"] = record.comment
    return entry


def write_steps_yaml(
    catalog: Mapping[str, Sequence[StepRecord]], path: str | Path
) -> Path:
    """Write the whole steps.yaml document (header + sorted entries).

    Atomic: written beside the target, then renamed — the same discipline as
    the record commit.  Not a merge: see :func:`merge_station_steps` for the
    one-station edit that preserves the rest.
    """
    import yaml

    doc = {
        "schema_version": STEPS_SCHEMA_VERSION,
        "stations": {
            marker: [
                _step_entry_dict(r)
                for r in sorted(records, key=lambda r: r.epoch_yearf)
            ]
            for marker, records in catalog.items()
        },
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(STEPS_YAML_HEADER)
            yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def merge_station_steps(
    path: str | Path | None,
    marker: str,
    entries: Sequence[StepRecord],
    *,
    replace: bool = False,
) -> tuple[Path, int, int, Path | None]:
    """Merge-write ONE station's declarations into ``steps.yaml``.

    READ-MODIFY-WRITE, never build-from-scratch: other stations' declarations
    are preserved verbatim.  Every entry must carry ``marker`` — a row
    labelled with another station is refused, not reassigned.

    Duplicate policy: an entry whose ``epoch_yearf`` already exists for the
    station (within 1e-4 yr ≈ 1 h) is SKIPPED — re-declaring the same event
    is the normal outcome of re-running a curation, and a near-duplicate
    epoch pair is rank-deficient in the fit, so it must never accumulate.
    Pass ``replace`` to substitute the station's whole list instead.

    If only the legacy ``steps.csv`` exists at the resolved location, its
    content is carried into the new ``steps.yaml`` and the csv is renamed to
    ``steps.csv.bak`` — an in-place migration; the reader prefers the yaml,
    so leaving a stale csv behind would invite edits to a dead file.

    Args:
        path: Catalog path; None resolves the deployed one.
        marker: The station whose list is being written.
        entries: The declarations to store for ``marker``.
        replace: Replace the station's whole list instead of merging.

    Returns:
        ``(yaml_path, n_before, n_after, migrated_csv)`` — station counts
        before/after the merge (unchanged unless bootstrapping), and the
        renamed csv when a migration happened.
    """
    resolved = Path(path) if path is not None else resolve_steps_path()
    if resolved is None:
        raise RuntimeError("no gpsconfig available to resolve steps.yaml; pass a path")
    migrated: Path | None = None
    if resolved.is_file():
        catalog = {m: list(r) for m, r in read_steps(resolved).items()}
        if resolved.suffix == ".csv":
            migrated = resolved
            resolved = resolved.with_name(STEPS_FILENAME)
    else:
        if resolved.name != STEPS_FILENAME:
            resolved = resolved.with_name(STEPS_FILENAME)
        catalog = {}

    for entry in entries:
        if entry.marker != marker:
            raise ValueError(
                f"entry for {entry.marker} cannot be merged under {marker}"
            )

    n_before = len(catalog)
    existing = catalog.get(marker, [])
    if replace:
        merged: list[StepRecord] = list(entries)
    else:
        kept = [
            r
            for r in existing
            if not any(abs(r.epoch_yearf - e.epoch_yearf) < 1e-4 for e in entries)
        ]
        merged = sorted([*kept, *entries], key=lambda r: r.epoch_yearf)
    catalog[marker] = merged

    write_steps_yaml(catalog, resolved)
    if migrated is not None:
        backup = migrated.with_name(STEPS_CSV_FILENAME + ".bak")
        migrated.rename(backup)
        migrated = backup
    return resolved, n_before, len(catalog), migrated


def convert_steps_csv(
    csv_path: str | Path, yaml_path: str | Path | None = None
) -> Path:
    """One-time migration of a legacy ``steps.csv`` to ``steps.yaml``.

    The declarations keep their epochs/kinds/comments verbatim; the two
    hand-curated rows in the deployed file carry hand-typed amplitudes in
    their comments, which stay comments (the record owns amplitudes).  A
    ``kind`` outside the vocabulary is a hard error — migrating is exactly
    the moment to name it properly.

    Refuses to overwrite an existing yaml: run once, then delete the csv.
    """
    csv_file = Path(csv_path)
    target = Path(yaml_path) if yaml_path else csv_file.with_name(STEPS_FILENAME)
    if target.is_file():
        raise FileExistsError(
            f"{target} already exists — the yaml catalog wins; delete the csv"
        )
    catalog = _read_steps_csv(csv_file)
    for marker, records in catalog.items():
        for i, r in enumerate(records):
            if r.kind not in STEP_KINDS:
                raise ValueError(
                    f"{csv_file}: station {marker} step #{i + 1}: kind "
                    f"{r.kind!r} is not in {STEP_KINDS} — name it properly "
                    "during migration (this is the one moment a human is "
                    "looking at every row)"
                )
    write_steps_yaml(catalog, target)
    return target
