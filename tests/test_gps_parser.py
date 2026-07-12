"""
Test suite for gps_parser basic configuration functionality.

Tests basic configuration parser functionality including:
- Configuration file path resolution
- Station information retrieval
- Post-process configuration access
- Legacy configuration support
"""

import pytest
import tempfile
import os
from unittest.mock import patch
import gps_parser as cp


class TestBasicConfiguration:
    """Test basic configuration functionality."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory with test configuration files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create minimal test stations.cfg
            stations_cfg = os.path.join(temp_dir, "stations.cfg")
            with open(stations_cfg, "w") as f:
                f.write("""# Test stations configuration

[THEY]
Station_NAME = Þorvaldseyri
Station_ID = THEY
router_ip = 157.157.40.186
receiver_type = NetR9
receiver_ftpport = 8060

[ELDC]
Station_NAME = Eldvörp
Station_ID = ELDC
router_ip = 10.6.1.90
receiver_type = PolaRX5
receiver_ftpport = 2160
""")

            # Create minimal test postprocess.cfg
            postprocess_cfg = os.path.join(temp_dir, "postprocess.cfg")
            with open(postprocess_cfg, "w") as f:
                f.write("""# Test postprocess configuration

[FILES]
coordFile = station_coord.xyz
plateFile = station-plate
detrendFile = detrend_config.dat

[PATHS]
totPath = /mnt/gpsdata/
""")

            yield temp_dir

    @pytest.fixture
    def config_parser(self, temp_config_dir):
        """Create ConfigParser instance with test configuration."""
        with patch.dict("os.environ", {"GPS_CONFIG_PATH": temp_config_dir}):
            return cp.ConfigParser()

    def test_config_path_resolution(self, config_parser, temp_config_dir):
        """Test configuration file path resolution."""

        stations_path = config_parser.get_stations_config_path()
        postprocess_path = config_parser.get_postprocess_config_path()

        assert stations_path == os.path.join(temp_config_dir, "stations.cfg")
        assert postprocess_path == os.path.join(temp_config_dir, "postprocess.cfg")
        assert os.path.exists(stations_path)
        assert os.path.exists(postprocess_path)

    def test_basic_config_access(self, config_parser):
        """Test basic configuration option access."""

        # Test direct config access
        station_name = config_parser.get_config("THEY", "station_name")
        assert station_name == "Þorvaldseyri"

        router_ip = config_parser.get_config("ELDC", "router_ip")
        assert router_ip == "10.6.1.90"

        # Test FILES section access
        coordfile = config_parser.get_config("FILES", "coordFile")
        assert coordfile == "station_coord.xyz"

    def test_station_info_retrieval(self, config_parser):
        """Test station information retrieval functionality."""

        # Test specific station info
        they_info = config_parser.getStationInfo("THEY")
        assert "station" in they_info
        assert they_info["station"]["station_name"] == "Þorvaldseyri"
        assert they_info["station"]["router_ip"] == "157.157.40.186"
        assert they_info["station"]["receiver_type"] == "NetR9"

        # Test station list (no argument)
        station_list = config_parser.getStationInfo("")
        assert isinstance(station_list, list)
        assert "THEY" in station_list
        assert "ELDC" in station_list
        # Should not include non-station sections
        assert "FILES" not in station_list
        assert "PATHS" not in station_list

    def test_postprocess_config_access(self, config_parser, temp_config_dir):
        """Test post-process configuration file access."""

        # Test file path resolution
        coordfile_path = config_parser.getPostProcessConfig("coordFile")
        expected_path = os.path.join(temp_config_dir, "station_coord.xyz")
        assert coordfile_path == expected_path

        platefile_path = config_parser.getPostProcessConfig("plateFile")
        expected_path = os.path.join(temp_config_dir, "station-plate")
        assert platefile_path == expected_path

    def test_postprocess_dir_access(self, config_parser):
        """Test post-process directory path access."""

        # Test PATHS section access
        tot_path = config_parser.getPostProcessDir("totPath")
        assert tot_path == "/mnt/gpsdata/"

    def test_postprocess_dir_backward_compatibility(self):
        """Test backward compatibility with legacy [Configs] section."""
        import tempfile

        # Create a temporary directory for legacy config
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create stations.cfg (required by ConfigParser)
            stations_cfg = os.path.join(temp_dir, "stations.cfg")
            with open(stations_cfg, "w") as f:
                f.write("""# Minimal stations config
[TEST]
station_name = Test Station
""")

            # Create postprocess.cfg with legacy [Configs] section
            postprocess_cfg = os.path.join(temp_dir, "postprocess.cfg")
            with open(postprocess_cfg, "w") as f:
                f.write("""# Legacy postprocess configuration
[Configs]
totDir = /mnt/gpsdata/legacy/
preDir = /mnt/gpsdata/pre/
rapDir = /mnt/gpsdata/rap/
""")

            # Initialize parser with legacy config
            with patch.dict("os.environ", {"GPS_CONFIG_PATH": temp_dir}):
                legacy_parser = cp.ConfigParser()

                # Test that legacy [Configs] section still works
                tot_dir = legacy_parser.getPostProcessDir("totDir")
                assert tot_dir == "/mnt/gpsdata/legacy/"

                pre_dir = legacy_parser.getPostProcessDir("preDir")
                assert pre_dir == "/mnt/gpsdata/pre/"

    def test_missing_station_error(self, config_parser):
        """Test error handling for missing stations."""

        with pytest.raises(Exception, match="Station 'NONEXIST' not found"):
            config_parser.getStationInfo("NONEXIST")

    def test_missing_config_option_error(self, config_parser):
        """Test error handling for missing configuration options."""

        with pytest.raises(Exception, match="Option 'nonexistent' not found"):
            config_parser.getPostProcessConfig("nonexistent")

        with pytest.raises(Exception, match="Option 'nonexistent' not found"):
            config_parser.getPostProcessDir("nonexistent")

    def test_default_config_path(self):
        """Test default configuration path resolution."""

        # Test without GPS_CONFIG_PATH environment variable
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.path.isdir", return_value=False):
                with pytest.raises(Exception, match="does not exist"):
                    cp.ConfigParser()

    def test_case_sensitivity(self, config_parser):
        """Test case sensitivity handling for station IDs."""

        # Station IDs should be case-insensitive in retrieval
        config_parser.getStationInfo("THEY")
        config_parser.getStationInfo("they")  # Should work the same

        # The actual comparison depends on implementation -
        # if case-insensitive handling is implemented, they should be equal
        # For now, just test that lowercase doesn't crash
        try:
            config_parser.getStationInfo("they")
            # If this succeeds, case handling works
        except Exception as e:
            # If this fails, case sensitivity is strict
            assert "not found" in str(e)


def main():
    """Legacy main function for manual testing."""
    print("TEST gps_parser - Running basic functionality tests")

    try:
        config = cp.ConfigParser()

        print(f"Stations config path: {config.get_stations_config_path()}")
        print(f"Postprocess config path: {config.get_postprocess_config_path()}")

        # Test station info
        print(f"\nStation info for THEY: {config.getStationInfo('THEY')}")

        # Test postprocess config
        try:
            coordfile = config.getPostProcessConfig("coordFile")
            print(f"Coord file path: {coordfile}")
        except Exception as e:
            print(f"Could not get coordFile: {e}")

        print("\nBasic functionality test completed successfully")

    except Exception as e:
        print(f"Configuration test failed: {e}")


if __name__ == "__main__":
    main()
