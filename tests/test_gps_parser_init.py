import os
import pytest

from src.gps_parser.__init__ import ConfigParser


@pytest.fixture
def temp_config_dir(tmp_path):
    # Create a temporary config directory with stations.cfg and postprocess.cfg
    config_dir = tmp_path / "gpsconfig"
    config_dir.mkdir()
    stations_cfg = config_dir / "stations.cfg"
    postprocess_cfg = config_dir / "postprocess.cfg"

    stations_cfg.write_text(
        "[Configs]\ndefault_station=ABC\n\n[ST001]\nname=Station1\nlocation=Earth\n"
    )
    postprocess_cfg.write_text("[Configs]\noption1=value1\noption2=value2\n")
    return config_dir


def test_configparser_reads_config(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    assert os.path.samefile(parser.config_path, temp_config_dir)
    assert os.path.isfile(parser.dest_stations_config_path)
    assert os.path.isfile(parser.dest_postprocess_config_path)


def test_get_config(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    value = parser.get_config("ST001", "name")
    assert value == "Station1"


def test_get_stations_config_path(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    assert parser.get_stations_config_path().endswith("stations.cfg")


def test_get_postprocess_config_path(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    assert parser.get_postprocess_config_path().endswith("postprocess.cfg")


def test_getStationInfo_all(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    stations = parser.getStationInfo()
    assert "ST001" in stations


def test_getStationInfo_specific(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    info = parser.getStationInfo("ST001")
    assert info["station"]["name"] == "Station1"
    assert info["station"]["location"] == "Earth"


def test_getStationInfo_not_found(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    with pytest.raises(Exception) as excinfo:
        parser.getStationInfo("ST999")
    assert "not found" in str(excinfo.value)


def test_getPostprocessConfig(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    value = parser.getPostProcessConfig("option1")
    assert value == "value1"


def test_getPostprocessConfig_not_found(monkeypatch, temp_config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(temp_config_dir))
    parser = ConfigParser()
    with pytest.raises(Exception) as excinfo:
        parser.getPostProcessConfig("doesnotexist")
    assert "not found" in str(excinfo.value)
