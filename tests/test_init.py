import os
import pytest

from gps_parser import ConfigParser


@pytest.fixture
def config_dir(tmp_path):
    # Create a temporary config directory with stations.cfg and postprocess.cfg
    config_dir = tmp_path / "gpsconfig"
    config_dir.mkdir()
    stations_cfg = config_dir / "stations.cfg"
    postprocess_cfg = config_dir / "postprocess.cfg"

    stations_cfg.write_text(
        "[Configs]\ndefault_station = TEST\n\n[STATION1]\nname = Station One\nlocation = Earth\n"
    )
    postprocess_cfg.write_text("[Configs]\noption1 = value1\noption2 = value2\n")
    return config_dir


def test_configparser_env_var(monkeypatch, config_dir):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    assert parser.config_path == str(config_dir)
    assert os.path.isfile(parser.dest_stations_config_path)
    assert os.path.isfile(parser.dest_postprocess_config_path)


def test_configparser_default_path(monkeypatch, tmp_path):
    # Simulate default path
    home = tmp_path
    config_path = home / ".config" / "gpsconfig"
    config_path.mkdir(parents=True)
    (config_path / "stations.cfg").write_text("[Configs]\n")
    (config_path / "postprocess.cfg").write_text("[Configs]\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GPS_CONFIG_PATH", raising=False)
    parser = ConfigParser()
    assert parser.config_path == str(config_path)


def test_missing_config_dir(monkeypatch, tmp_path):
    # Directory does not exist
    missing_dir = tmp_path / "doesnotexist"
    monkeypatch.setenv("GPS_CONFIG_PATH", str(missing_dir))
    with pytest.raises(Exception) as excinfo:
        ConfigParser()
    assert "does not exist" in str(excinfo.value)


def test_get_config(config_dir, monkeypatch):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    assert parser.get_config("STATION1", "name") == "Station One"


def test_get_stations_config_path(config_dir, monkeypatch):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    assert parser.get_stations_config_path().endswith("stations.cfg")


def test_get_postprocess_config_path(config_dir, monkeypatch):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    assert parser.get_postprocess_config_path().endswith("postprocess.cfg")


def test_getStationInfo_all(config_dir, monkeypatch):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    stations = parser.getStationInfo()
    assert "STATION1" in stations


def test_getStationInfo_specific(config_dir, monkeypatch):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    info = parser.getStationInfo("STATION1")
    assert info["station"]["name"] == "Station One"


def test_getStationInfo_not_found(config_dir, monkeypatch):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    with pytest.raises(Exception) as excinfo:
        parser.getStationInfo("DOESNOTEXIST")
    assert "not found" in str(excinfo.value)


def test_getPostprocessConfig_success(config_dir, monkeypatch):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    assert parser.getPostProcessConfig("option1") == "value1"


def test_getPostprocessConfig_not_found(config_dir, monkeypatch):
    monkeypatch.setenv("GPS_CONFIG_PATH", str(config_dir))
    parser = ConfigParser()
    with pytest.raises(Exception) as excinfo:
        parser.getPostProcessConfig("doesnotexist")
    assert "not found" in str(excinfo.value)
