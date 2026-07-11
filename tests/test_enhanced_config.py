"""
Test suite for gps_parser v0.4.0 enhanced configuration functionality.

Tests the Phase 1 implementation including:
- Timeout resolution logic validation
- FTP mode determination accuracy
- Session configuration retrieval
- System path resolution
- Default value configuration
- Configuration validation completeness
"""

import pytest
import tempfile
import os
from unittest.mock import patch
from gps_parser import ConfigParser


class TestEnhancedConfiguration:
    """Test enhanced configuration methods added in v0.4.0."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory with test configuration files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test stations.cfg
            stations_cfg = os.path.join(temp_dir, "stations.cfg")
            with open(stations_cfg, "w") as f:
                f.write("""# Test stations configuration

[TIMEOUT_CATEGORIES]
fixed_wired = 10,30,180,8192
mobile = 20,60,300,2048  
very_remote = 30,120,600,1024

[NETWORK_RULES]
ip_range_10_4 = active
ip_range_10_6 = passive
domain_default = auto

[SESSIONS]
15s_24hr = a,LOG1_15s_24hr,/DSK1/SSN/
1Hz_1hr = b,LOG2_1Hz_1hr,/DSK1/SSN/
status_1hr = b,LOG5_status_1hr,/DSK1/SSN/

[ELDC]
Station_NAME = Eldvörp
Station_ID = ELDC
router_ip = 10.6.1.90
receiver_type = PolaRX5
receiver_ftpport = 2160
timeout_category = extended_network
ftp_mode = passive

[TEST]
Station_NAME = Test Station
Station_ID = TEST
router_ip = 10.4.1.50
receiver_type = NetR9
receiver_ftpport = 2160
timeout_category = fixed_wired
connection_timeout = 15
inactivity_timeout = 45

[MOBILE]
Station_NAME = Mobile Station  
Station_ID = MOBILE
router_ip = 157.157.112.105
receiver_type = NetR9
receiver_ftpport = 2160
# No timeout_category - should default to mobile

[INVALID]
Station_NAME = Invalid Station
Station_ID = INVALID
# Missing required fields for validation testing
""")

            # Create test postprocess.cfg
            postprocess_cfg = os.path.join(temp_dir, "postprocess.cfg")
            with open(postprocess_cfg, "w") as f:
                f.write("""# Test postprocess configuration

[PATHS]
sbf2rin_path = /home/gpsops/bin/sbf2rin
teqc_path = /home/gpsops/bin/teqc
bin2asc_path = /opt/rxtools/bin/bin2asc
data_prepath = /data/
receiver_base_path = /DSK1/SSN/

[DEFAULTS]
default_days_back = 10
default_session = 15s_24hr
default_compression = .gz
default_end_offset_days = 1
health_extraction_pattern = *.sbf*
ftp_connection_retries = 3
ftp_transfer_timeout = 300

[Configs]
figDir = /home/bgo/gamit-times/figures/
totPath = /mnt/gpsdata/

[FILES]
coordFile = station_coord.xyz
plateFile = station-plate
""")

            yield temp_dir

    @pytest.fixture
    def config_parser(self, temp_config_dir):
        """Create ConfigParser instance with test configuration."""
        with patch.dict("os.environ", {"GPS_CONFIG_PATH": temp_config_dir}):
            return ConfigParser()

    def test_station_timeout_resolution(self, config_parser):
        """Test timeout category assignment and value resolution."""

        # Test station with explicit timeout category
        timeout_config = config_parser.getStationTimeout("ELDC")
        # ELDC has timeout_category=extended_network, but no such category defined
        # Should fallback to mobile defaults
        assert timeout_config["connection_timeout"] == 20
        assert timeout_config["inactivity_timeout"] == 60
        assert timeout_config["progress_timeout"] == 300
        assert timeout_config["min_speed_threshold"] == 2048

        # Test station with fixed_wired category
        timeout_config = config_parser.getStationTimeout("TEST")
        # TEST has timeout_category=fixed_wired and some overrides
        assert timeout_config["connection_timeout"] == 15  # Override
        assert timeout_config["inactivity_timeout"] == 45  # Override
        assert timeout_config["progress_timeout"] == 180  # From category
        assert timeout_config["min_speed_threshold"] == 8192  # From category

        # Test station without timeout category (should default to mobile)
        timeout_config = config_parser.getStationTimeout("MOBILE")
        assert timeout_config["connection_timeout"] == 20
        assert timeout_config["inactivity_timeout"] == 60
        assert timeout_config["progress_timeout"] == 300
        assert timeout_config["min_speed_threshold"] == 2048

        # Test nonexistent station
        with pytest.raises(Exception, match="Station 'NONEXIST' not found"):
            config_parser.getStationTimeout("NONEXIST")

    def test_ftp_mode_determination(self, config_parser):
        """Test FTP mode rules for different IP ranges."""

        # Test explicit ftp_mode setting
        ftp_mode = config_parser.getStationFtpMode("ELDC", "10.6.1.90")
        assert ftp_mode == "passive"  # Explicitly set in station config

        # Test IP range 10.4.x.x (should be active)
        ftp_mode = config_parser.getStationFtpMode("TEST", "10.4.1.50")
        assert ftp_mode == "active"  # From NETWORK_RULES

        # Test IP range 10.6.x.x (should be passive)
        ftp_mode = config_parser.getStationFtpMode("MOBILE", "10.6.2.100")
        assert ftp_mode == "passive"  # From NETWORK_RULES

        # Test other IP (should be auto)
        ftp_mode = config_parser.getStationFtpMode("MOBILE", "157.157.112.105")
        assert ftp_mode == "auto"  # From NETWORK_RULES domain_default

        # Test nonexistent station
        with pytest.raises(Exception, match="Station 'NONEXIST' not found"):
            config_parser.getStationFtpMode("NONEXIST", "10.4.1.1")

    def test_session_config_retrieval(self, config_parser):
        """Test session mapping and path resolution."""

        # Test 15s_24hr session
        session_config = config_parser.getSessionConfig("15s_24hr")
        assert session_config["session_letter"] == "a"
        assert session_config["session_path"] == "LOG1_15s_24hr"
        assert session_config["receiver_path"] == "/DSK1/SSN/"

        # Test 1Hz_1hr session
        session_config = config_parser.getSessionConfig("1Hz_1hr")
        assert session_config["session_letter"] == "b"
        assert session_config["session_path"] == "LOG2_1Hz_1hr"
        assert session_config["receiver_path"] == "/DSK1/SSN/"

        # Test status_1hr session
        session_config = config_parser.getSessionConfig("status_1hr")
        assert session_config["session_letter"] == "b"
        assert session_config["session_path"] == "LOG5_status_1hr"
        assert session_config["receiver_path"] == "/DSK1/SSN/"

        # Test nonexistent session
        with pytest.raises(Exception, match="Session type 'nonexistent' not found"):
            config_parser.getSessionConfig("nonexistent")

    def test_system_path_resolution(self, config_parser):
        """Test tool path configuration and environment overrides."""

        # Test PATHS section values
        assert config_parser.getSystemPath("sbf2rin_path") == "/home/gpsops/bin/sbf2rin"
        assert config_parser.getSystemPath("bin2asc_path") == "/opt/rxtools/bin/bin2asc"
        assert config_parser.getSystemPath("data_prepath") == "/data/"

        # Test legacy Configs section fallback
        assert "/home/bgo/gamit-times/figures/" in config_parser.getSystemPath("figDir")
        assert "/mnt/gpsdata/" in config_parser.getSystemPath("totPath")

        # Test fallback defaults for missing paths
        # Remove bin2asc_path from config to test fallback
        with patch.object(config_parser.config, "has_option", return_value=False):
            default_path = config_parser.getSystemPath("bin2asc_path")
            assert default_path == "/opt/rxtools/bin/bin2asc"

        # Test nonexistent path
        with pytest.raises(Exception, match="System path 'nonexistent_path' not found"):
            config_parser.getSystemPath("nonexistent_path")

    def test_default_value_retrieval(self, config_parser):
        """Test default value configuration and type conversion."""

        # Test integer values
        assert config_parser.getDefaultValue("default_days_back") == 10
        assert config_parser.getDefaultValue("default_end_offset_days") == 1
        assert config_parser.getDefaultValue("ftp_connection_retries") == 3
        assert config_parser.getDefaultValue("ftp_transfer_timeout") == 300

        # Test string values
        assert config_parser.getDefaultValue("default_session") == "15s_24hr"
        assert config_parser.getDefaultValue("default_compression") == ".gz"
        assert config_parser.getDefaultValue("health_extraction_pattern") == "*.sbf*"

        # Test fallback defaults
        with patch.object(config_parser.config, "has_section", return_value=False):
            assert config_parser.getDefaultValue("default_days_back") == 10
            assert config_parser.getDefaultValue("default_session") == "15s_24hr"

        # Test nonexistent setting
        with pytest.raises(
            Exception, match="Default value 'nonexistent_setting' not found"
        ):
            config_parser.getDefaultValue("nonexistent_setting")

    def test_configuration_validation(self, config_parser):
        """Test configuration validation and error reporting."""

        # Test valid station configuration
        validation = config_parser.validateStationConfig("ELDC")
        assert validation["valid"] is True
        assert len(validation["errors"]) == 0
        assert "router_ip" in validation["config"]
        assert "receiver_ftpport" in validation["config"]
        assert "receiver_type" in validation["config"]

        # Test station with some missing optional fields
        validation = config_parser.validateStationConfig("MOBILE")
        assert validation["valid"] is True
        assert len(validation["warnings"]) > 0
        # Should warn about missing timeout_category, ftp_mode, etc.

        # Test invalid station (missing required fields)
        validation = config_parser.validateStationConfig("INVALID")
        assert validation["valid"] is False
        assert len(validation["errors"]) > 0
        # Should error on missing router_ip, receiver_ftpport, receiver_type

        # Test nonexistent station
        validation = config_parser.validateStationConfig("NONEXIST")
        assert validation["valid"] is False
        assert len(validation["errors"]) == 1
        assert "not found in stations.cfg" in validation["errors"][0]

    def test_timeout_fallback_behavior(self, config_parser):
        """Test timeout resolution when TIMEOUT_CATEGORIES section is missing."""

        # Mock missing TIMEOUT_CATEGORIES section
        with patch.object(config_parser.config, "has_section") as mock_has_section:

            def mock_section_check(section):
                if section == "TIMEOUT_CATEGORIES":
                    return False
                return config_parser.config.has_section(section)

            mock_has_section.side_effect = mock_section_check

            # Should use hardcoded defaults
            timeout_config = config_parser.getStationTimeout("ELDC")
            assert timeout_config["connection_timeout"] == 20  # mobile default
            assert timeout_config["inactivity_timeout"] == 60
            assert timeout_config["progress_timeout"] == 300
            assert timeout_config["min_speed_threshold"] == 2048

    def test_network_rules_fallback(self, config_parser):
        """Test FTP mode determination when NETWORK_RULES section is missing."""

        # Mock missing NETWORK_RULES section
        with patch.object(config_parser.config, "has_section") as mock_has_section:

            def mock_section_check(section):
                if section == "NETWORK_RULES":
                    return False
                return config_parser.config.has_section(section)

            mock_has_section.side_effect = mock_section_check

            # Should use hardcoded fallback logic
            assert config_parser.getStationFtpMode("TEST", "10.4.1.50") == "active"
            assert config_parser.getStationFtpMode("MOBILE", "10.6.2.100") == "passive"
            assert config_parser.getStationFtpMode("MOBILE", "157.157.1.1") == "auto"

    def test_session_config_fallback(self, config_parser):
        """Test session configuration when SESSIONS section is missing."""

        # Mock missing SESSIONS section
        with patch.object(config_parser.config, "has_section") as mock_has_section:

            def mock_section_check(section):
                if section == "SESSIONS":
                    return False
                return config_parser.config.has_section(section)

            mock_has_section.side_effect = mock_section_check

            # Should use hardcoded defaults
            session_config = config_parser.getSessionConfig("15s_24hr")
            assert session_config["session_letter"] == "a"
            assert session_config["session_path"] == "LOG1_15s_24hr"
            assert session_config["receiver_path"] == "/DSK1/SSN/"

            # Test unknown session type with missing section
            with pytest.raises(Exception, match="Unknown session type 'unknown'"):
                config_parser.getSessionConfig("unknown")

    def test_invalid_configurations(self, config_parser):
        """Test handling of invalid configuration values."""

        # Create a temporary config with invalid timeout format
        with tempfile.TemporaryDirectory() as temp_dir:
            stations_cfg = os.path.join(temp_dir, "stations.cfg")
            with open(stations_cfg, "w") as f:
                f.write("""
[TIMEOUT_CATEGORIES]
invalid_format = not,numeric,values,here

[BADSTATION]  
Station_NAME = Bad Station
timeout_category = invalid_format
""")

            # Mock the config to use our invalid config
            with patch.object(config_parser.config, "get") as mock_get:

                def mock_get_func(section, option, fallback=None):
                    if section == "TIMEOUT_CATEGORIES" and option == "invalid_format":
                        return "not,numeric,values,here"
                    elif section == "BADSTATION" and option == "timeout_category":
                        return "invalid_format"
                    return config_parser.config.get(section, option, fallback=fallback)

                mock_get.side_effect = mock_get_func

                with patch.object(
                    config_parser.config, "has_section", return_value=True
                ):
                    with patch.object(
                        config_parser.config, "has_option", return_value=True
                    ):
                        # Should raise exception for invalid timeout format
                        with pytest.raises(
                            Exception, match="Invalid timeout configuration"
                        ):
                            config_parser.getStationTimeout("BADSTATION")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
