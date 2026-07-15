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


# --- catalog_path resolution ------------------------------------------------


def test_catalog_path_none_without_gpsconfig(monkeypatch, tmp_path):
    # No GPS_CONFIG_PATH and no default dir → ConfigParser raises → None.
    monkeypatch.setenv("GPS_CONFIG_PATH", str(tmp_path / "does-not-exist"))
    assert oc.catalog_path("steps", oc.STEPS_FILENAME) is None
