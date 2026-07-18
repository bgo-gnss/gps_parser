"""Passive-station schema: station_role / is_reference_site / is_in_iceland.

Stage 1 of the passive-station rollout (GLOBAL_SITES_investigation.md):
schema support only — no passive entries exist in production stations.cfg yet.
"""

import pytest

from src.gps_parser.__init__ import (
    STATION_ROLE_ACTIVE,
    STATION_ROLE_PASSIVE,
    ConfigParser,
    parse_config_bool,
)

STATIONS_CFG = """\
[Configs]
default_station=ACTV

[ACTV]
station_name=Operated station
router_ip=10.0.0.1
receiver_ftpport=2160
receiver_type=PolaRX5
latitude=64.0
longitude=-21.0

[ZIMM]
station_role=passive
is_reference_site=true
is_in_iceland=false
station_name=Zimmerwald
latitude=46.877094
longitude=7.465272

[TYPO]
station_role=pasive
is_reference_site=maybe
router_ip=10.0.0.2
receiver_ftpport=2160
receiver_type=PolaRX5
"""


@pytest.fixture
def role_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "gpsconfig"
    config_dir.mkdir()
    (config_dir / "stations.cfg").write_text(STATIONS_CFG)
    (config_dir / "postprocess.cfg").write_text("[Configs]\noption1=value1\n")
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    return config_dir


def test_default_role_is_active(role_config_dir):
    parser = ConfigParser()
    assert parser.getStationRole("ACTV") == STATION_ROLE_ACTIVE
    assert parser.isPassiveStation("ACTV") is False


def test_explicit_passive_role(role_config_dir):
    parser = ConfigParser()
    assert parser.getStationRole("ZIMM") == STATION_ROLE_PASSIVE
    assert parser.isPassiveStation("ZIMM") is True


def test_unknown_role_fails_open_to_active(role_config_dir, caplog):
    # A typo must never drop an operated station from the schedulers.
    parser = ConfigParser()
    with caplog.at_level("WARNING"):
        assert parser.getStationRole("TYPO") == STATION_ROLE_ACTIVE
    assert "unknown station_role" in caplog.text


def test_get_station_role_missing_station_raises(role_config_dir):
    parser = ConfigParser()
    with pytest.raises(Exception, match="not found"):
        parser.getStationRole("NOPE")


def test_validate_passive_station_without_operational_fields(role_config_dir):
    # Passive stations carry no router/receiver keys — must validate clean.
    parser = ConfigParser()
    result = parser.validateStationConfig("ZIMM")
    assert result["valid"] is True
    assert result["config"]["station_role"] == STATION_ROLE_PASSIVE
    assert result["config"]["is_reference_site"] is True
    assert result["config"]["is_in_iceland"] is False
    assert result["errors"] == []


def test_validate_active_station_defaults(role_config_dir):
    parser = ConfigParser()
    result = parser.validateStationConfig("ACTV")
    assert result["valid"] is True
    assert result["config"]["station_role"] == STATION_ROLE_ACTIVE
    assert result["config"]["is_reference_site"] is False  # default
    assert result["config"]["is_in_iceland"] is True  # default


def test_validate_flags_bad_role_and_bad_bool(role_config_dir):
    parser = ConfigParser()
    result = parser.validateStationConfig("TYPO")
    assert result["valid"] is False
    joined = " ".join(result["errors"])
    assert "Invalid station_role 'pasive'" in joined
    assert "is_reference_site" in joined


def test_getstationinfo_passes_schema_fields_through(role_config_dir):
    parser = ConfigParser()
    info = parser.getStationInfo("ZIMM")["station"]
    assert info["station_role"] == "passive"
    assert info["is_reference_site"] == "true"
    assert info["is_in_iceland"] == "false"


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        ("true", False, True),
        ("YES", False, True),
        ("1", False, True),
        ("on", False, True),
        ("false", True, False),
        ("No", True, False),
        ("0", True, False),
        ("off", True, False),
        (None, True, True),
        (None, False, False),
        ("", True, True),
        ("true # inline comment", False, True),
        (True, False, True),
        (False, True, False),
    ],
)
def test_parse_config_bool(value, default, expected):
    assert parse_config_bool(value, default) is expected


def test_parse_config_bool_rejects_garbage():
    with pytest.raises(ValueError):
        parse_config_bool("maybe")
