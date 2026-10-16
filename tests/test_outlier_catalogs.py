"""Unit tests for the shared outlier-catalog resolver (stdlib only)."""

from __future__ import annotations

import pytest

from gps_parser import outlier_catalogs as oc


# --- steps.csv --------------------------------------------------------------


def test_read_steps_per_component_sorted(tmp_path):
    p = tmp_path / "steps.csv"
    p.write_text(
        "sta,epoch_yearf,component,kind,source,comment\n"
        "# a comment line\n"
        "SENG,2021.5,U,eq,skjalftalisa,Fagradalsfjall\n"
        "SENG,2020.1,ALL,equip,tos,\n"
        "HOFN,2018.0,N,eq,skjalftalisa,\n"
    )
    cat = oc.read_steps(p)
    assert set(cat) == {"SENG", "HOFN"}
    seng = cat["SENG"]
    assert [r.epoch_yearf for r in seng] == [2020.1, 2021.5]  # sorted
    assert seng[0].component == "ALL" and seng[0].applies_to("north")
    assert seng[1].component == "U" and seng[1].applies_to("up")
    assert not seng[1].applies_to("north")


def test_read_steps_rejects_bad_component(tmp_path):
    p = tmp_path / "steps.csv"
    p.write_text("sta,epoch_yearf,component\nSENG,2021.5,X\n")
    with pytest.raises(ValueError, match="component"):
        oc.read_steps(p)


def test_read_steps_rejects_bad_epoch(tmp_path):
    p = tmp_path / "steps.csv"
    p.write_text("sta,epoch_yearf,component\nSENG,notayear,U\n")
    with pytest.raises(ValueError, match="epoch_yearf"):
        oc.read_steps(p)


def test_read_steps_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        oc.read_steps(tmp_path / "absent.csv")


# --- protect_windows.csv ----------------------------------------------------


def test_read_protect_windows_sorted(tmp_path):
    p = tmp_path / "protect_windows.csv"
    p.write_text(
        "sta,start_yearf,end_yearf,comment\n"
        "SENG,2023.9,2024.1,Sundhnukur\n"
        "SENG,2021.2,2021.6,dike\n"
    )
    cat = oc.read_protect_windows(p)
    assert cat["SENG"] == ((2021.2, 2021.6), (2023.9, 2024.1))


def test_read_protect_windows_rejects_inverted(tmp_path):
    p = tmp_path / "protect_windows.csv"
    p.write_text("sta,start_yearf,end_yearf\nSENG,2024.1,2023.9\n")
    with pytest.raises(ValueError, match="end .* < .* start"):
        oc.read_protect_windows(p)


# --- outlier_overrides.csv --------------------------------------------------


def test_read_overrides_fields_and_floors(tmp_path):
    p = tmp_path / "outlier_overrides.csv"
    p.write_text(
        "sta,despike,window_order,epoch_policy,min_outlier_n,min_outlier_e,min_outlier_u\n"
        "SENG,true,1,union,5,5,10\n"
        "HOFN,,,,,,\n"  # all-blank row → no fields, no floor
    )
    cat = oc.read_outlier_overrides(p)
    seng = cat["SENG"]
    assert seng.fields == {
        "despike": True,
        "window_order": 1,
        "epoch_policy": "union",
    }
    assert seng.min_outlier == (5.0, 5.0, 10.0)
    hofn = cat["HOFN"]
    assert hofn.fields == {} and hofn.min_outlier is None


def test_read_overrides_partial_floor_fills_zero(tmp_path):
    p = tmp_path / "outlier_overrides.csv"
    p.write_text("sta,min_outlier_u\nSENG,12\n")
    assert oc.read_outlier_overrides(p)["SENG"].min_outlier == (0.0, 0.0, 12.0)


def test_read_overrides_rejects_unknown_column(tmp_path):
    p = tmp_path / "outlier_overrides.csv"
    p.write_text("sta,bogus\nSENG,1\n")
    with pytest.raises(ValueError, match="unknown column"):
        oc.read_outlier_overrides(p)


def test_read_overrides_rejects_duplicate_station(tmp_path):
    p = tmp_path / "outlier_overrides.csv"
    p.write_text("sta,despike\nSENG,true\nSENG,false\n")
    with pytest.raises(ValueError, match="duplicate row"):
        oc.read_outlier_overrides(p)


def test_read_overrides_rejects_bad_window_order(tmp_path):
    p = tmp_path / "outlier_overrides.csv"
    p.write_text("sta,window_order\nSENG,3\n")
    with pytest.raises(ValueError, match="window_order"):
        oc.read_outlier_overrides(p)


def test_read_overrides_rejects_negative_floor(tmp_path):
    p = tmp_path / "outlier_overrides.csv"
    p.write_text("sta,min_outlier_u\nSENG,-1\n")
    with pytest.raises(ValueError, match="must be finite and >= 0"):
        oc.read_outlier_overrides(p)


# --- excluded_epochs.csv (manual-removal lever) -----------------------------


def test_read_excluded_epochs_sorted(tmp_path):
    p = tmp_path / "excluded_epochs.csv"
    p.write_text(
        "sta,date,comment\n"
        "RHOF,2022-03-17,north spike\n"
        "RHOF,2022-03-16,another\n"
        "SELF,2008-05-29,quake day\n"
    )
    cat = oc.read_excluded_epochs(p)
    assert set(cat) == {"RHOF", "SELF"}
    r = cat["RHOF"]
    assert len(r) == 2 and r[0] < r[1]  # sorted by epoch
    # noon convention: 2022-03-17 -> 2022.20685 (day 76+17, +12h)
    assert abs(r[1] - 2022.20685) < 1e-3


def test_read_excluded_epochs_rejects_bad_date(tmp_path):
    p = tmp_path / "excluded_epochs.csv"
    p.write_text("sta,date,comment\nRHOF,not-a-date,\n")
    with pytest.raises(ValueError, match="date"):
        oc.read_excluded_epochs(p)


def test_read_excluded_epochs_rejects_missing_sta(tmp_path):
    p = tmp_path / "excluded_epochs.csv"
    p.write_text("sta,date,comment\n,2022-03-17,\n")
    with pytest.raises(ValueError, match="sta"):
        oc.read_excluded_epochs(p)


def test_match_declared_epochs_exact_and_tolerant():
    series = [2022.204110, 2022.206850, 2022.209590]
    # exact match lands on the middle index
    assert oc.match_declared_epochs(series, [2022.206850]) == (1,)
    # a declared epoch beyond tolerance (a full week away) is skipped
    assert oc.match_declared_epochs(series, [2022.30]) == ()
    # duplicates de-duplicate
    assert oc.match_declared_epochs(series, [2022.206850, 2022.206851]) == (1,)


# --- catalog_path resolution ------------------------------------------------


def test_catalog_path_none_without_gpsconfig(monkeypatch, tmp_path):
    # No GPS_CONFIG_PATH and no default dir → ConfigParser raises → None.
    monkeypatch.setenv("GPS_CONFIG_PATH", str(tmp_path / "does-not-exist"))
    assert oc.catalog_path("steps", oc.STEPS_FILENAME) is None


# --- steps.yaml (the format; csv above is the legacy fallback) ---------------


def _yaml_catalog(tmp_path, body: str) -> object:
    p = tmp_path / "steps.yaml"
    p.write_text("schema_version: 1\nstations:\n" + body)
    return p


def test_read_steps_yaml_sorted_with_metadata(tmp_path):
    p = _yaml_catalog(
        tmp_path,
        "  SELF:\n"
        "    - epoch_yearf: 2008.4085\n"
        "      kind: earthquake\n"
        "      date: 2008-05-29\n"
        "      magnitude: 6.3\n"
        "      comment: Ölfus M6.3\n"
        "    - epoch_yearf: 2001.5\n"
        "      kind: manual\n"
        "  HOFN:\n"
        "    - epoch_yearf: 2001.7219\n"
        "      kind: equipment\n"
        "      date: 2001-09-21\n"
        "      devices: [TRM29659.00, TRIMBLE NETRS]\n",
    )
    cat = oc.read_steps(p)
    assert [r.epoch_yearf for r in cat["SELF"]] == [2001.5, 2008.4085]
    rec = cat["SELF"][1]
    assert rec.date == "2008-05-29" and rec.magnitude == 6.3
    assert cat["HOFN"][0].devices == ("TRM29659.00", "TRIMBLE NETRS")
    # date/epoch agreement on the noon convention holds (2008-05-29 → 2008.40847)
    assert abs(rec.epoch_yearf - 2008.40847) < 1e-3


def test_read_steps_yaml_requires_kind(tmp_path):
    p = _yaml_catalog(tmp_path, "  X:\n    - epoch_yearf: 2008.5\n")
    with pytest.raises(ValueError, match="kind"):
        oc.read_steps(p)


def test_read_steps_yaml_rejects_date_epoch_disagreement(tmp_path):
    p = _yaml_catalog(
        tmp_path,
        "  X:\n    - epoch_yearf: 2008.5\n      kind: earthquake\n"
        "      date: 2008-05-29\n",
    )
    with pytest.raises(ValueError, match="disagree"):
        oc.read_steps(p)


def test_read_steps_yaml_rejects_wrong_schema_version(tmp_path):
    p = tmp_path / "steps.yaml"
    p.write_text("schema_version: 2\nstations: {}\n")
    with pytest.raises(ValueError, match="schema_version"):
        oc.read_steps(p)


def test_convert_steps_csv_round_trips(tmp_path):
    csvp = tmp_path / "steps.csv"
    csvp.write_text(
        "sta,epoch_yearf,component,kind,source,comment\n"
        "SELF,2008.4085,ALL,earthquake,manual,Ölfus M6.3\n"
    )
    yml = oc.convert_steps_csv(csvp)
    cat = oc.read_steps(yml)
    (rec,) = cat["SELF"]
    assert rec.kind == "earthquake" and rec.comment == "Ölfus M6.3"
    # refusing to overwrite: the yaml wins once it exists
    with pytest.raises(FileExistsError):
        oc.convert_steps_csv(csvp)


def test_convert_steps_csv_rejects_offvocabulary_kind(tmp_path):
    csvp = tmp_path / "steps.csv"
    csvp.write_text("sta,epoch_yearf,kind\nX,2008.5,eq\n")
    with pytest.raises(ValueError, match="kind"):
        oc.convert_steps_csv(csvp)


def test_merge_station_steps_preserves_other_stations(tmp_path):
    yml = oc.convert_steps_csv(_legacy_csv(tmp_path), tmp_path / "steps.yaml")
    new = oc.StepRecord(
        marker="HOFN",
        epoch_yearf=2001.7219,
        component="ALL",
        kind="equipment",
        source="tos",
        date="2001-09-21",
    )
    path, n_before, n_after, migrated = oc.merge_station_steps(yml, "HOFN", [new])
    cat = oc.read_steps(path)
    assert set(cat) == {"SELF", "HOFN"} and (n_before, n_after) == (1, 2)
    assert migrated is None


def test_merge_station_steps_dedups_same_epoch(tmp_path):
    yml = _yaml_catalog(
        tmp_path, "  X:\n    - epoch_yearf: 2008.5\n      kind: manual\n"
    )
    again = oc.StepRecord(
        marker="X",
        epoch_yearf=2008.5,
        component="ALL",
        kind="earthquake",
        comment="re-declared",
    )
    path, _, _, _ = oc.merge_station_steps(yml, "X", [again])
    (rec,) = oc.read_steps(path)["X"]
    # the NEW declaration wins the epoch slot — latest curation
    assert rec.kind == "earthquake" and rec.comment == "re-declared"


def test_merge_station_steps_migrates_legacy_csv_in_place(tmp_path):
    csvp = _legacy_csv(tmp_path)
    new = oc.StepRecord(
        marker="HOFN", epoch_yearf=2001.7219, component="ALL", kind="equipment"
    )
    path, _, _, migrated = oc.merge_station_steps(csvp, "HOFN", [new])
    assert path.name == "steps.yaml" and path.is_file()
    assert migrated is not None and migrated.name == "steps.csv.bak"
    assert set(oc.read_steps(path)) == {"SELF", "HOFN"}


def test_merge_station_steps_refuses_mislabeled_entry(tmp_path):
    yml = _yaml_catalog(
        tmp_path, "  X:\n    - epoch_yearf: 2008.5\n      kind: manual\n"
    )
    wrong = oc.StepRecord(
        marker="Y", epoch_yearf=2009.0, component="ALL", kind="earthquake"
    )
    with pytest.raises(ValueError, match="cannot be merged"):
        oc.merge_station_steps(yml, "X", [wrong])


def _legacy_csv(tmp_path):
    csvp = tmp_path / "steps.csv"
    csvp.write_text(
        "sta,epoch_yearf,component,kind,source,comment\n"
        "SELF,2008.4085,ALL,earthquake,manual,Ölfus M6.3\n"
    )
    return csvp


def test_step_record_label():
    r = oc.StepRecord(
        marker="SELF",
        epoch_yearf=2008.4085,
        component="ALL",
        kind="earthquake",
        comment="Ölfus M6.3 — coseismic offset",
    )
    assert r.label == "earthquake: Ölfus M6.3 — coseismic offset"
    # comment truncated at 40 chars
    long = oc.StepRecord(
        marker="X",
        epoch_yearf=2010.0,
        component="ALL",
        kind="equipment",
        comment="a" * 80,
    )
    assert long.label == "equipment: " + "a" * 40
    # no comment -> just the kind
    bare = oc.StepRecord(marker="X", epoch_yearf=2011.0, component="ALL", kind="manual")
    assert bare.label == "manual"


def test_step_record_is_seismic():
    eq = oc.StepRecord(
        marker="X", epoch_yearf=2010.0, component="ALL", kind="earthquake"
    )
    eq2 = oc.StepRecord(
        marker="X", epoch_yearf=2011.0, component="ALL", kind="coseismic"
    )
    inst = oc.StepRecord(
        marker="X", epoch_yearf=2012.0, component="ALL", kind="equipment"
    )
    man = oc.StepRecord(marker="X", epoch_yearf=2013.0, component="ALL", kind="manual")
    assert eq.is_seismic and eq2.is_seismic
    assert not inst.is_seismic and not man.is_seismic


# ---------------------------------------------------------------------------
# detrend_status.csv
# ---------------------------------------------------------------------------


def test_read_detrend_status_normalises_and_keeps_notes(tmp_path):
    from gps_parser.outlier_catalogs import (
        read_detrend_status,
        skipped_detrend_stations,
    )

    f = tmp_path / "detrend_status.csv"
    f.write_text(
        "# comment\nsta,status,notes\n"
        "hrag,Skip,unrest: deformation-fitted record\n"
        "SENG,done,\n"
    )
    assert read_detrend_status(f) == {
        "HRAG": ("skip", "unrest: deformation-fitted record"),
        "SENG": ("done", ""),
    }
    assert skipped_detrend_stations(f) == {"HRAG": "unrest: deformation-fitted record"}


def test_detrend_status_missing_is_empty_but_malformed_raises(tmp_path):
    import pytest

    from gps_parser.outlier_catalogs import (
        read_detrend_status,
        skipped_detrend_stations,
    )

    assert skipped_detrend_stations(tmp_path / "nope.csv") == {}
    f = tmp_path / "detrend_status.csv"
    f.write_text("sta,status,notes\n,skip,no station\n")
    with pytest.raises(ValueError, match="without 'sta' or 'status'"):
        read_detrend_status(f)
